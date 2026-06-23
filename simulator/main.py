"""
Factory Simulator — entry point.

Usage:
    python -m simulator.main opcua
    python -m simulator.main mqtt
    python -m simulator.main sparkplug
"""

import asyncio
import logging
import sys
from pathlib import Path

import yaml

from simulator.factory.assembly_line import create_assembly_line
from simulator.factory.energy_meter import create_energy_meters
from simulator.factory.packaging_line import create_packaging_lines
from simulator.factory.process_tank import create_process_tanks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# asyncua floods the console with INFO noise from its standard nodeset loader
# and WARNING noise about missing TLS certs. Only show actual errors from it.
logging.getLogger("asyncua").setLevel(logging.ERROR)
logger = logging.getLogger("factory_sim")

MODES = ("opcua", "mqtt", "sparkplug")


def load_config(path: str = "config/factory.yaml") -> dict:
    with open(Path(path)) as f:
        return yaml.safe_load(f)


def build_factory():
    return (
        create_assembly_line()
        + create_process_tanks()
        + create_energy_meters()
        + create_packaging_lines()
    )


async def run_opcua(config: dict, devices, tick: float) -> None:
    from simulator.connectors.opcua_server import OpcUaConnector
    await OpcUaConnector(config["opcua"]).run(devices, tick)


async def run_mqtt(config: dict, devices, tick: float) -> None:
    from simulator.connectors.mqtt_connector import MqttConnector
    await MqttConnector(config["mqtt"]).run(devices, tick)


async def run_sparkplug(config: dict, devices, tick: float) -> None:
    from simulator.connectors.sparkplug_connector import SparkplugConnector
    await SparkplugConnector(config["sparkplug"]).run(devices, tick)


_RUNNERS = {
    "opcua": run_opcua,
    "mqtt": run_mqtt,
    "sparkplug": run_sparkplug,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(f"Usage: python -m simulator.main [{' | '.join(MODES)}]")
        sys.exit(1)

    mode = sys.argv[1]
    config = load_config()
    tick = float(config.get("simulation", {}).get("tick_interval", 2.0))
    devices = build_factory()

    logger.info(
        "Starting factory simulator | mode=%-10s devices=%d  tick=%.1fs",
        mode, len(devices), tick,
    )
    for d in devices:
        logger.info("  %-12s  %s", d.area, d.device_id)

    try:
        asyncio.run(_RUNNERS[mode](config, devices, tick))
    except KeyboardInterrupt:
        logger.info("Simulator stopped.")


if __name__ == "__main__":
    main()
