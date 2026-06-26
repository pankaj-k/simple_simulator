# Factory Simulator

A Python simulator that mimics a mixed industrial factory and streams live sensor data to [Ignition SCADA](https://inductiveautomation.com/) over three different protocols. Use it to learn how OPC UA, MQTT, and Sparkplug B each expose the same factory data differently — without needing real hardware.

---

## What it simulates

The factory has four areas. Devices are not independent — they are causally linked so that faults in one area produce measurable effects in others, exactly as they would on a real factory floor.

| Area | Devices | Key tags |
|------|---------|----------|
| **Assembly** | CNC_01, CNC_02, Robot_Arm_01 | State (RUNNING/IDLE/FAULT), PartCount, CycleTime_sec, ToolWear_pct, Alarm |
| **Process** | Reactor_Tank_01, Reactor_Tank_02 | Temperature_C, Pressure_bar, Level_pct, FlowRate_L_min, HeaterOn |
| **Energy** | Main_Meter, Line_A_Meter, Line_B_Meter | ActivePower_kW, EnergyTotal_kWh, PowerFactor, Voltage_V, Current_A |
| **Packaging** | Packaging_Line_01 | Running, ConveyorSpeed_m_min, Throughput_units_hr, RejectCount, OEE_pct, SupplyFactor_pct |

### How each device behaves

**Assembly machines (CNC_01, CNC_02, Robot_Arm_01)**

Each machine runs a state machine:

```
RUNNING ──(0.2% chance/tick)──► FAULT ──(30s)──► IDLE ──(10s)──► RUNNING
   │                                                                   ▲
   └──(ToolWear reaches 95%)──► IDLE (maintenance, wear resets to 0) ─┘
```

- Parts are only produced while RUNNING. PartCount increments each completed cycle (~45s).
- ToolWear accumulates 0.1–0.3% per part. At 95% the machine idles for maintenance.
- A FAULT sets `Alarm = True` for its duration.

**Process tanks (Reactor_Tank_01, Reactor_Tank_02)**

- Temperature and pressure follow a sinusoidal pattern with Gaussian noise — realistic sensor variation without a flat line.
- Level drains continuously via flow rate and auto-refills when it drops below 20%.
- The heater (`HeaterOn`) cuts in when temperature falls below setpoint.
- Process tanks are independent of Assembly — they represent a separate part of the plant.

**Energy meters**

Energy meters observe the assembly machines and reflect their actual load:

| Meter | Observes | Behaviour |
|---|---|---|
| Main_Meter | All 3 machines | Total site load — drops when any machines go down |
| Line_A_Meter | CNC_01, CNC_02 | CNC line load — tracks CNC states |
| Line_B_Meter | Robot_Arm_01 | Robot cell load — tracks robot state |

Load formula: `30% base (lighting, HVAC) + 70% variable (machines running)`. When all machines are faulted or idle, meters drop to ~30% of rated power.

**Packaging line**

The packaging line depends on parts supplied by the assembly machines:

- `SupplyFactor_pct` = percentage of assembly machines currently running (0–100%)
- At 0% supply (all machines down) → line is **forced to stop**, regardless of its own state
- Reduced supply → higher reject rate (incomplete/rushed parts arriving) → **OEE drops**
- Recovery probability scales with supply — the line restarts more slowly when parts are scarce

### The causal chain Kafka replay can reconstruct

This is what makes the simulator useful for digital twin work. A sequence of events in the Kafka topics tells a complete story:

```
T+00s  All machines RUNNING      SupplyFactor=100%  OEE≈75%   Main_Meter≈270kW
T+47s  CNC_01 → FAULT            SupplyFactor= 67%  OEE falls  Line_A_Meter drops
T+52s  CNC_02 → FAULT            SupplyFactor= 33%  OEE falls  reject rate rises
T+81s  Robot_Arm_01 ToolWear 95% SupplyFactor=  0%  Line STOPS Main_Meter≈110kW
T+92s  CNC_01 recovers           SupplyFactor= 33%  Line can restart
T+111s CNC_02 recovers           SupplyFactor= 67%  OEE climbs
T+121s Robot_Arm_01 back online  SupplyFactor=100%  OEE climbs Main_Meter≈270kW
```

A digital twin replaying these Kafka offsets can answer: "why did OEE drop at 14:32?" — because `SupplyFactor_pct` went to zero two seconds earlier, caused by `ToolWear_pct` crossing 95% on Robot_Arm_01 at 14:31:39.

---

## Prerequisites

| Tool | Why | Where to get it |
|------|-----|-----------------|
| Python 3.11+ | Runs the simulator | [python.org](https://www.python.org/downloads/) |
| Ignition 8.x | SCADA server you're connecting to | [inductiveautomation.com](https://inductiveautomation.com/downloads/) |
| MQTT broker | Required for `mqtt` and `sparkplug` modes | [Mosquitto](https://mosquitto.org/) locally, or your Cirrus Link broker |
| Cirrus Link MQTT Engine module | Required for `sparkplug` mode in Ignition | Cirrus Link Solutions |

For the `opcua` mode you only need Python and Ignition — no broker required.

---

## Installation

```bash
# 1. Clone the repo (or download the zip)
git clone <repo-url>
cd simple_simulator

# 2. Create a virtual environment (keeps packages isolated)
python -m venv .venv

# 3. Activate it
#    Windows:
.venv\Scripts\activate
#    Mac/Linux:
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

---

## Configuration

Open [config/factory.yaml](config/factory.yaml) and update the addresses to match your setup:

```yaml
simulation:
  tick_interval: 2.0      # how often (seconds) the simulator sends an update

opcua:
  endpoint: "opc.tcp://0.0.0.0:4840/factory/"   # leave as-is; Ignition connects to this

mqtt:
  broker: "localhost"     # change to your MQTT broker IP
  port: 1883

sparkplug:
  broker: "localhost"     # change to your Cirrus Link / Mosquitto broker IP
  port: 1883
  group_id: "Factory_01"
  edge_node_id: "Edge_Node_01"
```

---

## Running the simulator

Pick the protocol you want to learn. Run the simulator first, then connect Ignition to it.

Add `--test` to any mode to enable fault injection — tags randomly go `Bad` and recover, so you can test your quality alarm pipeline without waiting for a real sensor failure:

```bash
python -m simulator.main opcua --test
```

Console output in test mode:
```
22:51:03 WARNING  simulator.factory.fault_injector: Quality FAULT      CNC_01                ToolWear_pct                   (47s)
22:51:50 INFO     simulator.factory.fault_injector: Quality RECOVERED  CNC_01                ToolWear_pct
```

### Mode 1 — OPC UA

The simulator becomes an OPC UA **server**. Ignition's built-in OPC UA driver connects as a client.

```bash
python -m simulator.main opcua
```

**Connect Ignition:**
1. Go to **Config → OPC UA → Connections → Add Connection**
2. Endpoint URL: `opc.tcp://<your-PC-IP>:4840/factory/`
3. Browse the tag tree: `Factory → Assembly → CNC_01 → State`

---

### Mode 2 — Plain MQTT (JSON)

The simulator publishes JSON payloads to your MQTT broker. Ignition's MQTT Engine or Distributor module receives them.

```bash
python -m simulator.main mqtt
```

Topic pattern: `factory/<Area>/<Device>`

Example payload on topic `factory/Assembly/CNC_01`:
```json
{
  "timestamp": 1719000000000,
  "area": "Assembly",
  "device": "CNC_01",
  "tags": {
    "State":        { "v": "RUNNING", "u": "" },
    "PartCount":    { "v": 142,       "u": "parts" },
    "CycleTime_sec":{ "v": 44.8,      "u": "s" },
    "ToolWear_pct": { "v": 23.1,      "u": "%" },
    "Alarm":        { "v": false,     "u": "" }
  }
}
```

You can inspect messages with any MQTT client (e.g. [MQTT Explorer](https://mqtt-explorer.com/)).

---

### Mode 3 — Sparkplug B

The simulator publishes Sparkplug B encoded messages. This is what Cirrus Link's **MQTT Engine** module in Ignition was designed for — it auto-creates tags from the birth certificates.

```bash
python -m simulator.main sparkplug
```

Topic pattern: `spBv1.0/Factory_01/{NBIRTH,DBIRTH,DDATA,NDEATH}/Edge_Node_01[/<Device>]`

**Connect Ignition (MQTT Engine):**
1. Configure MQTT Engine to point at your broker
2. It will auto-discover the edge node and create tag folders automatically
3. Tags appear under `[MQTT Engine] Factory_01/Edge_Node_01/<Device>/`

> **Why no protobuf package needed?** The encoder ([sparkplug_encoder.py](simulator/connectors/sparkplug_encoder.py)) writes the binary wire format directly using Python's `struct` module. Ignition decodes it identically to messages from a real Cirrus Link MQTT Transmission module.

---

## Understanding the three protocols

```
                        ┌─────────────────────────────┐
                        │     Factory Simulator        │
                        │  (same 9 devices, same data) │
                        └──────┬──────────┬────────────┘
                               │          │            │
                         OPC UA│    MQTT  │  Sparkplug │
                          Server│  Publish │  B Publish │
                               │          │            │
                    ┌──────────▼──┐  ┌────▼────┐  ┌───▼──────────┐
                    │ Ignition    │  │  MQTT   │  │  MQTT broker  │
                    │ OPC-UA      │  │ broker  │  │  + MQTT Engine│
                    │ driver      │  │         │  │  module       │
                    └─────────────┘  └─────────┘  └──────────────-┘
```

| | OPC UA | Plain MQTT | Sparkplug B |
|--|--------|------------|-------------|
| Transport | TCP (built-in) | MQTT | MQTT |
| Payload | Binary (OPC UA binary) | JSON (human-readable) | Protobuf binary |
| Ignition module needed | None (built-in) | MQTT Engine or custom | MQTT Engine (Cirrus Link) |
| Auto tag creation | Yes (via browse) | Manual | Yes (from DBIRTH) |
| Best for learning | First step — simplest | Understanding the data | Production pattern |

---

## Project layout

```
factory_simulator/
├── config/
│   └── factory.yaml          ← all connection settings
├── simulator/
│   ├── main.py               ← entry point, mode selector
│   ├── factory/              ← simulation logic (protocol-agnostic)
│   │   ├── base.py           ← Device and Tag base classes
│   │   ├── assembly_line.py  ← state machine: RUNNING / IDLE / FAULT
│   │   ├── process_tank.py   ← sinusoidal temp/pressure with noise
│   │   ├── energy_meter.py   ← power demand with Ohm's law
│   │   └── packaging_line.py ← OEE calculation, random stoppages
│   └── connectors/           ← protocol adapters
│       ├── opcua_server.py   ← asyncua OPC UA server
│       ├── mqtt_connector.py ← paho-mqtt JSON publisher
│       ├── sparkplug_encoder.py  ← hand-written protobuf encoder
│       └── sparkplug_connector.py ← birth/death lifecycle manager
└── requirements.txt
```

---