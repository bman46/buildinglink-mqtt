CONFIG = {
    # BuildingLink credentials
    "username": "your_buildinglink_username",
    "password": "your_buildinglink_password",

    # MQTT settings
    "broker": {
        "host": "192.168.1.100",   # IP or hostname of your MQTT broker
        "port": 1883,               # Default MQTT port
    },
    "client_id": "buildinglink_mqtt",

    # Home Assistant MQTT discovery prefix (usually "homeassistant")
    "discovery_prefix": "homeassistant",

    # How often (in seconds) to poll BuildingLink for package updates
    "refresh_interval": 300,
}
