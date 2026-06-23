import asyncio
import logging
import time
import paho.mqtt.client as mqtt
from simulator.factory.base import Device
from .sparkplug_encoder import DataType, build_payload, tag_to_metric

logger = logging.getLogger(__name__)


class SparkplugConnector:
    """
    Publishes to spBv1.0/<group>/{NBIRTH,DBIRTH,DDATA,NDEATH}/<node>[/<device>]

    Birth/death lifecycle:
      NBIRTH  — published on (re)connect before any DBIRTH
      DBIRTH  — one per device on (re)connect
      DDATA   — every tick for each device
      NDEATH  — MQTT will message (auto-sent by broker on disconnect)
    """

    def __init__(self, config: dict):
        self._config = config
        self._group = config.get("group_id", "Factory_01")
        self._node = config.get("edge_node_id", "Edge_Node_01")
        self._qos = config.get("qos", 0)
        self._seq = 0
        self._bd_seq = 0
        self._devices: list[Device] = []

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        if config.get("username"):
            self._client.username_pw_set(config["username"], config.get("password", ""))

        ndeath = build_payload([("bdSeq", DataType.Int64, 0)], seq=0)
        self._client.will_set(
            f"spBv1.0/{self._group}/NDEATH/{self._node}",
            ndeath, qos=1, retain=False,
        )

    # ------------------------------------------------------------------
    # Sequence helpers
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        logger.info("Sparkplug B connected (rc=%s) — publishing birth certificates", reason_code)
        self._seq = 0
        self._publish_nbirth()
        for device in self._devices:
            self._publish_dbirth(device)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("Sparkplug B disconnected (rc=%s)", reason_code)

    # ------------------------------------------------------------------
    # Birth / death publishers
    # ------------------------------------------------------------------

    def _publish_nbirth(self) -> None:
        metrics = [
            ("bdSeq", DataType.Int64, self._bd_seq),
            ("Node Control/Reboot", DataType.Boolean, False),
        ]
        topic = f"spBv1.0/{self._group}/NBIRTH/{self._node}"
        self._client.publish(topic, build_payload(metrics, self._next_seq()), qos=self._qos)
        self._bd_seq = (self._bd_seq + 1) % 256

    def _publish_dbirth(self, device: Device) -> None:
        metrics = [tag_to_metric(n, t) for n, t in device.get_tags().items()]
        topic = f"spBv1.0/{self._group}/DBIRTH/{self._node}/{device.device_id}"
        self._client.publish(topic, build_payload(metrics, self._next_seq()), qos=self._qos)
        logger.debug("DBIRTH %s/%s (%d metrics)", device.area, device.device_id, len(metrics))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self, devices: list[Device]) -> None:
        self._devices = devices
        self._client.connect(
            self._config.get("broker", "localhost"),
            self._config.get("port", 1883),
            keepalive=60,
        )
        self._client.loop_start()

    def publish(self, devices: list[Device]) -> None:
        for device in devices:
            metrics = [tag_to_metric(n, t) for n, t in device.get_tags().items()]
            topic = f"spBv1.0/{self._group}/DDATA/{self._node}/{device.device_id}"
            self._client.publish(topic, build_payload(metrics, self._next_seq()), qos=self._qos)

    def disconnect(self) -> None:
        ndeath = build_payload([("bdSeq", DataType.Int64, self._bd_seq)], seq=0)
        self._client.publish(
            f"spBv1.0/{self._group}/NDEATH/{self._node}", ndeath, qos=1
        )
        time.sleep(0.15)
        self._client.loop_stop()
        self._client.disconnect()

    async def run(self, devices: list[Device], tick: float) -> None:
        self.connect(devices)
        logger.info(
            "Sparkplug B publishing to %s:%s | group=%s node=%s | %d devices | tick=%.1fs",
            self._config.get("broker"),
            self._config.get("port"),
            self._group,
            self._node,
            len(devices),
            tick,
        )
        try:
            while True:
                for device in devices:
                    device.tick(tick)
                self.publish(devices)
                await asyncio.sleep(tick)
        finally:
            self.disconnect()
