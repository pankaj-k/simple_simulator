# CLAUDE.md — Factory Simulator

## What this project is

A Python factory simulator that publishes live sensor data from a mixed discrete/process/energy/packaging factory to Ignition SCADA over three switchable protocols: OPC UA, plain MQTT (JSON), and Sparkplug B. The goal is hands-on learning — run it against a real Ignition instance and see how each protocol behaves differently.

Target stack: Ignition 8.x desktop + Cirrus Link MQTT Engine module + AWS MSK (Kafka) downstream.

## Architecture

The factory model is **protocol-agnostic**. All three connectors read the same `Device.get_tags() -> dict[str, Tag]` interface.

```
simulator/
├── factory/        ← simulation logic only, no I/O
│   ├── base.py     ← Device (ABC) + Tag dataclass
│   ├── assembly_line.py
│   ├── process_tank.py
│   ├── energy_meter.py
│   └── packaging_line.py
└── connectors/     ← protocol adapters; each has a .run(devices, tick) coroutine
    ├── opcua_server.py
    ├── mqtt_connector.py
    ├── sparkplug_encoder.py   ← zero-dependency protobuf encoder
    └── sparkplug_connector.py
```

Entry point: `python -m simulator.main [opcua|mqtt|sparkplug] [--test]`
Config: `config/factory.yaml`

## Key conventions

- Every device subclasses `Device` from `simulator/factory/base.py`. Required method: `tick(elapsed: float)`.
- Tags are written via `self._set(name, value, unit="", datatype="float")`. Valid datatypes: `float`, `int`, `bool`, `string`.
- `Tag` has a `quality: str` field (`"Good"` by default). Only `FaultInjector` writes `"Bad"` to it — devices never touch quality directly.
- Connectors read `device.get_tags()` — they never reach into device internals.
- All connectors expose `async def run(devices, tick, fault_injector=None)` so `main.py` calls them uniformly with `asyncio.run()`.

## Test mode (fault injection)

`python -m simulator.main opcua --test` enables `FaultInjector` (`simulator/factory/fault_injector.py`).

Each tick, after all `device.tick()` calls, `fault_injector.inject(elapsed)` runs. It randomly sets `tag.quality = "Bad"` on individual tags (~0.2% chance per tag per 2s tick) and recovers them after 30–120 seconds. The connector then writes the appropriate quality status to the protocol:

- **OPC UA**: sets `dv.StatusCode = ua.StatusCode(ua.StatusCodes.BadDeviceFailure)` on the `DataValue` — Ignition sees the tag go `Bad_DeviceFailure`. Note: the attribute is `StatusCode` not `StatusCode_` — confirmed by `dir(ua.DataValue())`
- **MQTT**: adds `"q": "Bad"` field to the tag object in the JSON payload
- **Sparkplug B**: `tag.quality` is set but not yet encoded in the binary payload (Sparkplug quality encoding not implemented)

Fault events are logged at WARNING; recoveries at INFO. Look for `Quality FAULT` and `Quality RECOVERED` lines in the console.

## OPC UA connector — known gotcha

When creating OPC UA variable nodes with `asyncua`, always pass the raw Python value plus `varianttype=` separately:

```python
# CORRECT
var_node = await device_node.add_variable(idx, tag_name, tag.value, varianttype=vtype)

# WRONG — wrapping in DataValue before add_variable registers the node as
# ExtensionObject (type 23); subsequent writes with the real type raise BadTypeMismatch
var_node = await device_node.add_variable(idx, tag_name, ua.DataValue(ua.Variant(tag.value, vtype)))
```

The "parent node does not exist" INFO lines at startup are normal — asyncua logs these while loading its built-in OPC UA standard nodesets. They are not errors. The asyncua logger is set to ERROR level in `main.py` to suppress this noise.

## Sparkplug B encoder

`simulator/connectors/sparkplug_encoder.py` hand-writes protobuf wire format using `struct`. No `protobuf` package dependency. It handles the Payload + Metric structure from the Sparkplug B 3.0 spec. If you need to add a new datatype, add it to the `DataType` class and extend the if/elif in `_encode_metric`.

## Adding a new device type

1. Create `simulator/factory/<new_area>.py`, subclass `Device`, implement `tick()`.
2. Write a `create_<new_area>()` factory function returning `list[Device]`.
3. Import and call it in `simulator/main.py` inside `build_factory()`.
Nothing else changes — all three connectors pick it up automatically.

## Adding a new connector / protocol

1. Create `simulator/connectors/<protocol>_connector.py`.
2. Implement `async def run(devices: list[Device], tick: float, fault_injector=None) -> None`. Call `fault_injector.inject(tick)` after device ticks if not None.
3. Add an entry to `_RUNNERS` dict in `simulator/main.py`.

## Dependencies

| Package | Used for |
|---------|----------|
| `asyncua` | OPC UA server (Mode 1) |
| `paho-mqtt >= 2.0` | MQTT transport for Mode 2 and 3 |
| `pyyaml` | Config loading |

No protobuf package required. The Sparkplug B encoder is self-contained.

## Simulation behaviour

- **Assembly machines**: state machine RUNNING → FAULT (random 0.2% chance/tick) → IDLE (30s) → RUNNING. Tool wear accumulates; at 95% it triggers a maintenance idle.
- **Process tanks**: sinusoidal temperature + pressure with Gaussian noise. Level drains via flow rate, refills when below 20%.
- **Energy meters**: base load + sine wave demand variation. kWh accumulates continuously.
- **Packaging line**: random micro-stoppages (0.1% chance/tick, 5% recovery/tick). OEE = availability × performance × quality.

## Config file

`config/factory.yaml` — broker addresses, OPC UA endpoint, tick interval. No hardcoded connection strings anywhere in the source.
