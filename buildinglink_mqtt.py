#!/usr/bin/env python3

import json
import logging
import lxml.html
import os
import re
import requests
import time

import paho.mqtt.client as mqtt

PACKAGES_TABLE_ID = "ctl00_ContentPlaceHolder1_GridDeliveries_ctl00"
PACKAGES_XPATH = f"//table[@id='{PACKAGES_TABLE_ID}']/tbody/tr"
EVENT_LOG_URL_DEFAULT = "https://eventlog-us1.buildinglink.com/event-log/resident"


def _parse_int_env(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer, got: {value!r}")


def _read_secret(env_var):
    """Read a value from a file path given by {env_var}_FILE, or fall back to {env_var}.

    This supports Docker secrets, which are mounted as files under /run/secrets/.
    """
    file_path = os.environ.get(f"{env_var}_FILE")
    if file_path:
        try:
            with open(file_path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError as e:
            logging.debug("Could not read secret file for %s (%s): %s", env_var, file_path, e)
            raise RuntimeError(f"Could not read secret file for {env_var}: {e.strerror}") from e
    return os.environ.get(env_var)


def load_config():
    """Load configuration from environment variables, falling back to config.py.

    Sensitive values (BL_USERNAME, BL_PASSWORD) can also be provided via Docker
    secrets by setting BL_USERNAME_FILE / BL_PASSWORD_FILE to the secret file path.
    """
    username = _read_secret("BL_USERNAME")
    password = _read_secret("BL_PASSWORD")
    mqtt_host = os.environ.get("MQTT_HOST")
    mqtt_username = _read_secret("MQTT_USERNAME")
    mqtt_password = _read_secret("MQTT_PASSWORD")

    if username and password and mqtt_host:
        return {
            "username": username,
            "password": password,
            "broker": {
                "host": mqtt_host,
                "port": _parse_int_env("MQTT_PORT", 1883),
                "username": mqtt_username,
                "password": mqtt_password,
            },
            "client_id": os.environ.get("MQTT_CLIENT_ID", "buildinglink_mqtt"),
            "discovery_prefix": os.environ.get("MQTT_DISCOVERY_PREFIX", "homeassistant"),
            "refresh_interval": _parse_int_env("BL_REFRESH_INTERVAL", 300),
        }

    try:
        import config
        return config.CONFIG
    except ImportError:
        raise RuntimeError(
            "Configuration not found. Set BL_USERNAME (or BL_USERNAME_FILE), "
            "BL_PASSWORD (or BL_PASSWORD_FILE), and MQTT_HOST environment variables, "
            "or create a config.py file based on config.example.py."
        )


def mqtt_base_topic(cfg):
    return f"{cfg['discovery_prefix']}/sensor/buildinglink"

def mqtt_discovery_topic(cfg):
    return f"{cfg['discovery_prefix']}/sensor/buildinglink_packages/config"

def publish_mqtt(client, data, cfg):
    client.publish(f"{mqtt_base_topic(cfg)}/state", json.dumps(data), retain=True)

def on_connect(client, userdata, connect_flags, reason_code, cfg):
    logging.info("Connected to the MQTT broker. rc=" + str(reason_code))

    client.publish(mqtt_discovery_topic(cfg), json.dumps({
        "name": "BuildingLink Packages",
        "unique_id": "buildinglink_packages",
        "state_topic": f"{mqtt_base_topic(cfg)}/state",
        "icon": "mdi:package-variant",
        "unit_of_measurement": "package(s)",
        "value_template": "{{ value_json.packages | int }}"
    }), retain=True)

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    logging.info("Disconnected from the MQTT broker. rc=" + str(reason_code))


def get_hidden_inputs(text):
    html = lxml.html.fromstring(text)
    hidden_inputs = html.xpath(r'//form//input[@type="hidden"]')
    form = {x.attrib["name"]: x.attrib["value"] for x in hidden_inputs}
    return form

def load_page(s, cfg):
    r = s.get( "https://www.buildinglink.com/v2/global/login/login.aspx")

    # Find the redirect URL located in the <script>.
    content = r.content
    url = content[content.find(b'https://auth'):content.rfind(b'";')]

    r = s.get(url)

    form = get_hidden_inputs(r.text)
    form['Username'] = cfg["username"]
    form['Password'] = cfg["password"]
    r = s.post(r.url, data=form)

    form = get_hidden_inputs(r.text)
    r = s.post("https://www.buildinglink.com/v2/oidc-callback", data=form)


def get_package_count(page):
    trs = lxml.html.fromstring(page.text).xpath(PACKAGES_XPATH)
    rows = len(trs)

    if rows == 0:
        logging.debug("No package rows found; treating as 0 packages")
        return 0
    elif rows == 1 and "rgNoRecords" in trs[0].get("class"):
        logging.debug(f"rgNoRecords found; 0 packages")
        return 0
    else:
        return rows


def _extract_event_log_url(text):
    match = re.search(r"https://eventlog-[^\"']+/event-log/resident", text)
    if match:
        return match.group(0)
    return EVENT_LOG_URL_DEFAULT


def _extract_bearer_token(text):
    token_patterns = [
        r'"access[_-]?token"\s*:\s*"([^"]+)"',
        r"'access[_-]?token'\s*:\s*'([^']+)'",
        r'"token"\s*:\s*"([^"]+)"',
        r"'token'\s*:\s*'([^']+)'",
        r"Bearer\s+([A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)",
        r"([A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)",
    ]

    for pattern in token_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def get_package_count_from_event_log(session, page):
    event_log_url = _extract_event_log_url(page.text)
    token = _extract_bearer_token(page.text)
    headers = {}

    if token:
        headers["Authorization"] = "Bearer " + token
    else:
        logging.debug("No bearer token found in Vue page; trying event-log request with session cookies only")

    response = session.get(event_log_url, headers=headers)
    response.raise_for_status()

    data = response.json()
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        events = data.get("events")
        if isinstance(events, list):
            return len(events)

    logging.debug("Unexpected event-log payload type: %s", type(data).__name__)
    return 0

def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    cfg = load_config()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg["client_id"])
    client.on_connect = lambda c, u, f, rc, props: on_connect(c, u, f, rc, cfg)
    client.on_disconnect = on_disconnect
    broker_cfg = cfg["broker"]
    broker_username = broker_cfg.get("username")
    if broker_username:
        client.username_pw_set(broker_username, broker_cfg.get("password"))
    client.connect(broker_cfg["host"], broker_cfg.get("port", 1883))
    client.loop_start()

    with requests.Session() as session:
        load_page(session, cfg)

        packages = None

        while True:
            page = session.get("https://www.buildinglink.com/V2/Tenant/Deliveries/Deliveries.aspx")
            pkg_count = get_package_count(page)

            if pkg_count == 0 and "VueAppWrapper.aspx" in page.url:
                try:
                    pkg_count = get_package_count_from_event_log(session, page)
                except requests.RequestException as e:
                    logging.warning("Could not fetch packages from event-log API: %s", e)
                except ValueError as e:
                    logging.warning("Could not parse event-log API response: %s", e)

            if pkg_count is not None:
                logging.info(f"{str(pkg_count)} package(s)")

                if packages != pkg_count:
                    packages = pkg_count
                    logging.info(f"Publishing: {packages} package(s) for pickup.")
                    publish_mqtt(client, {"packages": packages}, cfg)

            time.sleep(cfg["refresh_interval"])


if __name__ == "__main__":
    main()
