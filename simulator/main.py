"""
Factory Simulator — entry point.

Usage:
    python -m simulator.main opcua
    python -m simulator.main mqtt
    python -m simulator.main sparkplug
    python -m simulator.main opcua --test    # fault injection: tags go Bad and recover
"""

import argparse
import asyncio
import logging
from pathlib import Path

import yaml

from simulator.factory.assembly_line import create_assembly_line
from simulator.factory.energy_meter import create_energy_meters
from simulator.factory.fault_injector import FaultInjector
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


async def run_opcua(config: dict, devices, tick: float, fault_injector=None) -> None:
    from simulator.connectors.opcua_server import OpcUaConnector
    await OpcUaConnector(config["opcua"]).run(devices, tick, fault_injector)


async def run_mqtt(config: dict, devices, tick: float, fault_injector=None) -> None:
    from simulator.connectors.mqtt_connector import MqttConnector
    await MqttConnector(config["mqtt"]).run(devices, tick, fault_injector)


async def run_sparkplug(config: dict, devices, tick: float, fault_injector=None) -> None:
    from simulator.connectors.sparkplug_connector import SparkplugConnector
    await SparkplugConnector(config["sparkplug"]).run(devices, tick, fault_injector)


_RUNNERS = {
    "opcua": run_opcua,
    "mqtt": run_mqtt,
    "sparkplug": run_sparkplug,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Factory Simulator")
    parser.add_argument("mode", choices=MODES, help="Protocol mode")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Enable fault injection: tags randomly go Bad and recover, for testing alarm pipelines",
    )
    args = parser.parse_args()

    config = load_config()
    tick = float(config.get("simulation", {}).get("tick_interval", 2.0))
    devices = build_factory()

    fault_injector = FaultInjector(devices) if args.test else None

    logger.info(
        "Starting factory simulator | mode=%-10s devices=%d  tick=%.1fs  test=%s",
        args.mode, len(devices), tick, args.test,
    )
    for d in devices:
        logger.info("  %-12s  %s", d.area, d.device_id)

    try:
        asyncio.run(_RUNNERS[args.mode](config, devices, tick, fault_injector))
    except KeyboardInterrupt:
        logger.info("Simulator stopped.")


if __name__ == "__main__":
    main()
