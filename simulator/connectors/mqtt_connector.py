import asyncio
import json
import logging
import time
import paho.mqtt.client as mqtt
from simulator.factory.base import Device

logger = logging.getLogger(__name__)


class MqttConnector:
    def __init__(self, config: dict):
        self._config = config
        self._prefix = config.get("topic_prefix", "factory")
        self._qos = config.get("qos", 0)

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        if config.get("username"):
            self._client.username_pw_set(config["username"], config.get("password", ""))

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        logger.info("MQTT connected (rc=%s)", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("MQTT disconnected (rc=%s)", reason_code)

    def connect(self) -> None:
        self._client.connect(
            self._config.get("broker", "localhost"),
            self._config.get("port", 1883),
            keepalive=60,
        )
        self._client.loop_start()

    def publish(self, devices: list[Device]) -> None:
        ts = int(time.time() * 1000)
        for device in devices:
            payload = {
                "timestamp": ts,
                "area": device.area,
                "device": device.device_id,
                "tags": {
                    name: {"v": tag.value, "u": tag.unit, "q": tag.quality}
                    for name, tag in device.get_tags().items()
                },
            }
            topic = f"{self._prefix}/{device.area}/{device.device_id}"
            self._client.publish(topic, json.dumps(payload), qos=self._qos)

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    async def run(self, devices: list[Device], tick: float, fault_injector=None) -> None:
        self.connect()
        logger.info(
            "Plain MQTT publishing to %s:%s | prefix=%s | %d devices | tick=%.1fs%s",
            self._config.get("broker"),
            self._config.get("port"),
            self._prefix,
            len(devices),
            tick,
            " [FAULT INJECTION ON]" if fault_injector else "",
        )
        try:
            while True:
                for device in devices:
                    device.tick(tick)
                if fault_injector:
                    fault_injector.inject(tick)
                self.publish(devices)
                await asyncio.sleep(tick)
        finally:
            self.disconnect()
