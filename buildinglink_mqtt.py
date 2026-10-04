#!/usr/bin/env python3

import json
import logging
import lxml.html
import os
import requests
import time

import paho.mqtt.client as mqtt

PACKAGES_TABLE_ID = "ctl00_ContentPlaceHolder1_GridDeliveries_ctl00"
PACKAGES_XPATH = f"//table[@id='{PACKAGES_TABLE_ID}']/tbody/tr"
EVENTLOG_URL = "https://eventlog-us1.buildinglink.com/event-log/resident"
EVENTLOG_API_KEY = "hylwvvmjdgc45mt9kab1agriyvuh0nig9qx8djmu"
EVENTLOG_ACCEPT = "application/json;odata.metadata=minimal;odata.streaming=true"


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

def publish_mqtt(client, data, cfg):
    client.publish(f"{mqtt_base_topic(cfg)}/state", json.dumps(data), retain=True)

def on_connect(client, userdata, connect_flags, reason_code, cfg):
    logging.info("Connected to the MQTT broker. rc=" + str(reason_code))

    base = mqtt_base_topic(cfg)
    client.publish(f"{base}-packages/config", json.dumps({
        "name": "BuildingLink Packages",
        "unique_id": "buildinglink_packages",
        "state_topic": f"{base}/state",
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
    access_token = form.get("access_token")
    r = s.post("https://www.buildinglink.com/v2/oidc-callback", data=form)
    return access_token


def get_package_count(page):
    trs = lxml.html.fromstring(page.text).xpath(PACKAGES_XPATH)
    rows = len(trs)

    if rows == 0:
        logging.warning(f"No package rows found at all")
        return None
    elif rows == 1 and "rgNoRecords" in trs[0].get("class"):
        logging.debug(f"rgNoRecords found; 0 packages")
        return 0
    else:
        return rows


def get_package_count_from_eventlog(s, access_token):
    if not access_token:
        logging.warning("No access token available for event-log fallback")
        return None

    response = s.get(
        EVENTLOG_URL,
        headers={
            "Authorization": "Bearer " + access_token,
            "x-api-key": EVENTLOG_API_KEY,
            "Accept": EVENTLOG_ACCEPT,
            "Origin": "https://www.buildinglink.com",
            "Referer": "https://www.buildinglink.com/",
        },
    )

    if response.status_code == 401:
        return None

    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, list):
        return len(payload)

    if isinstance(payload, dict):
        for key in ("openDeliveries", "items", "data", "results", "events"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)

    logging.warning("Unexpected event-log payload shape: %s", type(payload).__name__)
    return None

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
        access_token = load_page(session, cfg)

        packages = None

        while True:
            page = session.get("https://www.buildinglink.com/V2/Tenant/Deliveries/Deliveries.aspx")
            pkg_count = get_package_count(page)

            if pkg_count is None:
                try:
                    pkg_count = get_package_count_from_eventlog(session, access_token)
                    if pkg_count is None:
                        access_token = load_page(session, cfg)
                        pkg_count = get_package_count_from_eventlog(session, access_token)
                except requests.RequestException as e:
                    logging.warning(f"Event-log fallback failed: {e}")

            if pkg_count is not None:
                logging.info(f"{str(pkg_count)} package(s)")

                if packages != pkg_count:
                    packages = pkg_count
                    logging.info(f"Publishing: {packages} package(s) for pickup.")
                    publish_mqtt(client, {"packages": packages}, cfg)

            time.sleep(cfg["refresh_interval"])


if __name__ == "__main__":
    main()
