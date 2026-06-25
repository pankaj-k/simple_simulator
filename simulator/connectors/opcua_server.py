import asyncio
import logging
from asyncua import Server, ua
from simulator.factory.base import Device

logger = logging.getLogger(__name__)

_VARIANT_TYPE = {
    "float": ua.VariantType.Double,
    "int": ua.VariantType.Int64,
    "bool": ua.VariantType.Boolean,
    "string": ua.VariantType.String,
}

_QUALITY_STATUS = {
    "Uncertain": ua.StatusCodes.UncertainLastUsableValue,
    "Bad":       ua.StatusCodes.BadDeviceFailure,
}


class OpcUaConnector:
    def __init__(self, config: dict):
        self._config = config

    async def run(self, devices: list[Device], tick: float, fault_injector=None) -> None:
        server = Server()
        await server.init()
        server.set_endpoint(self._config.get("endpoint", "opc.tcp://0.0.0.0:4840/factory/"))

        uri = self._config.get("namespace", "urn:factory:simulator")
        idx = await server.register_namespace(uri)

        node_map: dict[tuple, object] = {}

        factory_node = await server.nodes.objects.add_object(idx, "Factory")

        areas: dict[str, list[Device]] = {}
        for d in devices:
            areas.setdefault(d.area, []).append(d)

        for area_name, area_devices in areas.items():
            area_node = await factory_node.add_object(idx, area_name)
            for device in area_devices:
                device_node = await area_node.add_object(idx, device.device_id)
                for tag_name, tag in device.get_tags().items():
                    vtype = _VARIANT_TYPE.get(tag.datatype, ua.VariantType.Double)
                    var_node = await device_node.add_variable(
                        idx, tag_name, tag.value, varianttype=vtype
                    )
                    await var_node.set_writable()
                    node_map[(device.device_id, tag_name)] = (var_node, vtype)

        async with server:
            logger.info(
                "OPC UA server listening on %s | %d devices | tick=%.1fs%s",
                self._config.get("endpoint"),
                len(devices),
                tick,
                " [FAULT INJECTION ON]" if fault_injector else "",
            )
            while True:
                for device in devices:
                    device.tick(tick)
                if fault_injector:
                    fault_injector.inject(tick)

                for device in devices:
                    for tag_name, tag in device.get_tags().items():
                        entry = node_map.get((device.device_id, tag_name))
                        if entry:
                            var_node, vtype = entry
                            dv = ua.DataValue(ua.Variant(tag.value, vtype))
                            if tag.quality in _QUALITY_STATUS:
                                dv.StatusCode = ua.StatusCode(_QUALITY_STATUS[tag.quality])
                            await var_node.write_value(dv)

                await asyncio.sleep(tick)
