FROM python:3.12-slim
ENTRYPOINT []

RUN mkdir /app && chmod 777 /app
COPY requirements.txt /app
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY buildinglink_mqtt.py /app
WORKDIR "/app"

CMD ["python3", "buildinglink_mqtt.py"]
