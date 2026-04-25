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


def _parse_int_env(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer, got: {value!r}")


def load_config():
    """Load configuration from environment variables, falling back to config.py."""
    username = os.environ.get("BL_USERNAME")
    password = os.environ.get("BL_PASSWORD")
    mqtt_host = os.environ.get("MQTT_HOST")

    if username and password and mqtt_host:
        return {
            "username": username,
            "password": password,
            "broker": {
                "host": mqtt_host,
                "port": _parse_int_env("MQTT_PORT", 1883),
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
            "Configuration not found. Set BL_USERNAME, BL_PASSWORD, and MQTT_HOST "
            "environment variables, or create a config.py file based on config.example.py."
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
    r = s.post("https://www.buildinglink.com/v2/oidc-callback", data=form)


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

def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    cfg = load_config()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg["client_id"])
    client.on_connect = lambda c, u, f, rc, props: on_connect(c, u, f, rc, cfg)
    client.on_disconnect = on_disconnect
    client.connect(cfg["broker"]["host"])
    client.loop_start()

    with requests.Session() as session:
        load_page(session, cfg)

        packages = None

        while True:
            page = session.get("https://www.buildinglink.com/V2/Tenant/Deliveries/Deliveries.aspx")
            pkg_count = get_package_count(page)

            if pkg_count is not None:
                logging.info(f"{str(pkg_count)} package(s)")

                if packages != pkg_count:
                    packages = pkg_count
                    logging.info(f"Publishing: {packages} package(s) for pickup.")
                    publish_mqtt(client, {"packages": packages}, cfg)

            time.sleep(cfg["refresh_interval"])


if __name__ == "__main__":
    main()
