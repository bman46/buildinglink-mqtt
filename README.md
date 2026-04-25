# buildinglink-mqtt

An MQTT-based Home Assistant integration to retrieve information about packages waiting in the mail room from your BuildingLink web portal.

The integration periodically polls the BuildingLink website, counts the number of packages waiting for pickup, and publishes that count to an MQTT broker. It also publishes an [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) config message so that Home Assistant automatically creates a sensor entity.

## Prerequisites

- A [BuildingLink](https://www.buildinglink.com) account with access to the Deliveries section
- An MQTT broker reachable from where you run the container (e.g. [Mosquitto](https://mosquitto.org/))
- Home Assistant with the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) configured (optional, but required for auto-discovery)

## Configuration

All configuration is supplied via environment variables. For local Python runs, you can alternatively copy `config.example.py` to `config.py` and fill in your values (environment variables take precedence when set).

| Environment Variable | config.py key | Description | Default |
|---|---|---|---|
| `BL_USERNAME` | `username` | BuildingLink login username | *(required)* |
| `BL_USERNAME_FILE` | — | Path to a file containing the BuildingLink username (e.g. a Docker secret) | — |
| `BL_PASSWORD` | `password` | BuildingLink login password | *(required)* |
| `BL_PASSWORD_FILE` | — | Path to a file containing the BuildingLink password (e.g. a Docker secret) | — |
| `MQTT_HOST` | `broker.host` | IP address or hostname of your MQTT broker | *(required)* |
| `MQTT_PORT` | `broker.port` | MQTT broker port | `1883` |
| `MQTT_CLIENT_ID` | `client_id` | MQTT client identifier | `buildinglink_mqtt` |
| `MQTT_DISCOVERY_PREFIX` | `discovery_prefix` | Home Assistant MQTT discovery prefix | `homeassistant` |
| `BL_REFRESH_INTERVAL` | `refresh_interval` | Polling interval in seconds | `300` |

> **Tip:** When both `BL_USERNAME_FILE` and `BL_USERNAME` are set, the file value takes precedence.

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

Run the container, passing configuration as environment variables:

```bash
docker run -d \
  --name buildinglink-mqtt \
  --restart unless-stopped \
  -e BL_USERNAME=your_username \
  -e BL_PASSWORD=your_password \
  -e MQTT_HOST=192.168.1.100 \
  buildinglink-mqtt
```

#### Using the pre-built image from GitHub Container Registry

```bash
docker run -d \
  --name buildinglink-mqtt \
  --restart unless-stopped \
  -e BL_USERNAME=your_username \
  -e BL_PASSWORD=your_password \
  -e MQTT_HOST=192.168.1.100 \
  ghcr.io/bman46/buildinglink-mqtt:latest
```

### With Docker Compose

```yaml
services:
  buildinglink-mqtt:
    image: ghcr.io/bman46/buildinglink-mqtt:latest
    restart: unless-stopped
    environment:
      BL_USERNAME: your_username
      BL_PASSWORD: your_password
      MQTT_HOST: 192.168.1.100
      # MQTT_PORT: 1883
      # MQTT_CLIENT_ID: buildinglink_mqtt
      # MQTT_DISCOVERY_PREFIX: homeassistant
      # BL_REFRESH_INTERVAL: 300
```

You can also keep credentials in a separate `.env` file (not committed to source control):

```bash
# .env
BL_USERNAME=your_username
BL_PASSWORD=your_password
MQTT_HOST=192.168.1.100
```

```yaml
services:
  buildinglink-mqtt:
    image: ghcr.io/bman46/buildinglink-mqtt:latest
    restart: unless-stopped
    env_file: .env
```

### With Docker Secrets (Docker Swarm)

For production deployments, credentials can be stored as [Docker secrets](https://docs.docker.com/engine/swarm/secrets/) instead of plain-text environment variables. Secrets are mounted as files under `/run/secrets/` and referenced via `BL_USERNAME_FILE` / `BL_PASSWORD_FILE`:

Create the secrets:

```bash
echo "your_buildinglink_username" | docker secret create bl_username -
echo "your_buildinglink_password" | docker secret create bl_password -
```

Deploy as a Swarm service:

```bash
docker service create \
  --name buildinglink-mqtt \
  --secret bl_username \
  --secret bl_password \
  -e BL_USERNAME_FILE=/run/secrets/bl_username \
  -e BL_PASSWORD_FILE=/run/secrets/bl_password \
  -e MQTT_HOST=192.168.1.100 \
  ghcr.io/bman46/buildinglink-mqtt:latest
```

Or with a Docker Compose Swarm stack (`docker stack deploy`):

```yaml
services:
  buildinglink-mqtt:
    image: ghcr.io/bman46/buildinglink-mqtt:latest
    environment:
      BL_USERNAME_FILE: /run/secrets/bl_username
      BL_PASSWORD_FILE: /run/secrets/bl_password
      MQTT_HOST: 192.168.1.100
    secrets:
      - bl_username
      - bl_password

secrets:
  bl_username:
    external: true
  bl_password:
    external: true
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
