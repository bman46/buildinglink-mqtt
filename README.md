# buildinglink-mqtt

An MQTT-based Home Assistant integration to retrieve information about packages waiting in the mail room from your BuildingLink web portal.

The integration periodically polls the BuildingLink website, counts the number of packages waiting for pickup, and publishes that count to an MQTT broker. It also publishes an [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) config message so that Home Assistant automatically creates a sensor entity.

## Prerequisites

- A [BuildingLink](https://www.buildinglink.com) account with access to the Deliveries section
- An MQTT broker reachable from where you run the container (e.g. [Mosquitto](https://mosquitto.org/))
- Home Assistant with the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) configured (optional, but required for auto-discovery)

## Configuration

Copy `config.example.py` to `config.py` and fill in your values:

```bash
cp config.example.py config.py
```

| Key | Description |
|-----|-------------|
| `username` | Your BuildingLink login username |
| `password` | Your BuildingLink login password |
| `broker.host` | IP address or hostname of your MQTT broker |
| `broker.port` | MQTT broker port (default: `1883`) |
| `client_id` | MQTT client identifier (any unique string) |
| `discovery_prefix` | Home Assistant MQTT discovery prefix (default: `homeassistant`) |
| `refresh_interval` | Polling interval in seconds (default: `300`) |

## Running

### With Python

Install the required dependencies and run the script directly:

```bash
pip install -r requirements.txt
python3 buildinglink_mqtt.py
```

### With Docker

Build the image locally:

```bash
docker build -t buildinglink-mqtt .
```

Run the container, mounting your `config.py` into the image:

```bash
docker run -d \
  --name buildinglink-mqtt \
  --restart unless-stopped \
  -v "$(pwd)/config.py:/app/config.py:ro" \
  buildinglink-mqtt
```

#### Using the pre-built image from GitHub Container Registry

```bash
docker run -d \
  --name buildinglink-mqtt \
  --restart unless-stopped \
  -v "$(pwd)/config.py:/app/config.py:ro" \
  ghcr.io/bman46/buildinglink-mqtt:latest
```

### With Docker Compose

Create a `docker-compose.yml` alongside your `config.py`:

```yaml
services:
  buildinglink-mqtt:
    image: ghcr.io/bman46/buildinglink-mqtt:latest
    restart: unless-stopped
    volumes:
      - ./config.py:/app/config.py:ro
```

Then start it:

```bash
docker compose up -d
```

## Home Assistant

Once the integration is running and connected to the same MQTT broker as Home Assistant, a new sensor will be automatically discovered:

- **Entity**: `sensor.buildinglink_packages`
- **Unit**: `package(s)`
- **Icon**: `mdi:package-variant`

You can use this sensor in dashboards, automations, or notifications. For example, to send a notification when a new package arrives:

```yaml
automation:
  - alias: "Notify on new package"
    trigger:
      - platform: state
        entity_id: sensor.buildinglink_packages
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state | int > trigger.from_state.state | int }}"
    action:
      - service: notify.mobile_app
        data:
          message: "You have {{ states('sensor.buildinglink_packages') }} package(s) waiting for pickup."
```

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file.
