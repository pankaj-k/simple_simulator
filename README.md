# Factory Simulator

A Python simulator that mimics a mixed industrial factory and streams live sensor data to [Ignition SCADA](https://inductiveautomation.com/) over three different protocols. Use it to learn how OPC UA, MQTT, and Sparkplug B each expose the same factory data differently — without needing real hardware.

---

## What it simulates

The factory has four areas, each running continuously with realistic noise and fault injection:

| Area | Devices | Key tags |
|------|---------|----------|
| **Assembly** | CNC_01, CNC_02, Robot_Arm_01 | State (RUNNING/IDLE/FAULT), PartCount, CycleTime, ToolWear % |
| **Process** | Reactor_Tank_01, Reactor_Tank_02 | Temperature °C, Pressure bar, Level %, FlowRate L/min, HeaterOn |
| **Energy** | Main_Meter, Line_A_Meter, Line_B_Meter | ActivePower kW, EnergyTotal kWh, PowerFactor, Voltage V, Current A |
| **Packaging** | Packaging_Line_01 | Running, ConveyorSpeed m/min, Throughput units/hr, RejectCount, OEE % |

Faults happen automatically — machines break down, the packaging line stops, tanks drain and refill. You'll see these as state changes in Ignition just as you would from real hardware.

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
cd factory_simulator

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

## Forwarding data to Confluent Cloud Kafka

This section covers wiring Ignition to Confluent Cloud so tag data flows from Ignition into Kafka. The simulator produces the data; Ignition is the bridge to Kafka.

### Prerequisites

Two extra Ignition modules are required — neither is bundled with a standard Ignition install. Install them via **Config → Modules → Install or Upgrade a Module**:

1. **Event Streams module** — must be installed and active first (the Kafka Connector depends on it)
2. **Kafka Connector module** — provides the connection UI and producer/consumer pipeline

Both are `.modl` files available from Inductive Automation's module marketplace.

### Step 1 — Store your Confluent API secret safely

Rather than pasting the API secret as plaintext in the connection form, store it in Ignition's secret provider so it can be referenced by name.

1. Go to **Config → Security → Secret Providers**
2. Select the built-in **Internal** provider (or create one)
3. Add a new secret — name it `confluent-kafka-secret`, value = your Confluent API secret key
4. Save

### Step 2 — Create the Kafka connection

1. Go to **Config → Kafka Connector → Connections → Add Connection**
2. Fill in the fields:

| Field | Value |
|-------|-------|
| Name | `confluent-kafka` |
| Bootstrap Servers | `pkc-oxqxx9.us-east-1.aws.confluent.cloud:9092` |
| Security Protocol | `SASL_SSL` |
| SASL Mechanism | `PLAIN` |
| SASL Username | your Confluent API key (the short alphanumeric key, not the secret) |
| SASL Password | reference your secret provider: `{secrets:confluent-kafka-secret}` |
| SSL / TLS properties | leave blank — Confluent Cloud uses publicly trusted certificates already in the Java truststore |

3. Click **Save and Connect** — the status indicator should turn green

### Step 3 — Create the four Kafka topics in Confluent Cloud

One topic per factory area. Do this in the Confluent Cloud UI before touching Ignition.

1. Log in to [confluent.cloud](https://confluent.cloud) → select your cluster
2. Go to **Topics → Add Topic** and create each of the following:

| Topic name | Partitions | Reason for count |
|---|---|---|
| `factory.assembly` | 4 | 3 devices (CNC_01, CNC_02, Robot_Arm_01) + 1 headroom |
| `factory.process` | 3 | 2 devices (Reactor_Tank_01, Reactor_Tank_02) + 1 headroom |
| `factory.energy` | 4 | 3 devices (Main_Meter, Line_A_Meter, Line_B_Meter) + 1 headroom |
| `factory.packaging` | 3 | 1 device (Packaging_Line_01) + 2 headroom |

3. For each topic, work through the creation form as follows:

**Partitions** — use the counts in the table above. 6 is also fine if you want a consistent number across all topics — it gives extra headroom and divides evenly by 2 and 3, which helps if you later run multiple consumer instances.

**Retention** — turn **off** the "Enable infinite retention" toggle. Click **Show advanced settings** and set `retention.ms` to one of:

| Scenario | Value |
|---|---|
| Just learning / experimenting | `86400000` (1 day) |
| Want to replay a week | `604800000` (7 days) |

Infinite retention accumulates storage costs on Confluent Cloud — avoid it for a learning setup.

**Data contract (schema)** — after the topic is created, Confluent will offer to add a data contract (Avro / Protobuf / JSON Schema). **Click Skip.**

Reason: you don't yet know the exact JSON structure that Ignition's JsonObject encoder will produce. If you define a schema now and the real messages don't match it, Confluent rejects every message Ignition sends. The right order is: get data flowing first → inspect real messages in the Confluent topic browser → come back and define a JSON Schema from the actual payload shape.

4. Click **Create** → repeat for all four topics.

> Headroom matters because Kafka does not let you reduce partition count later — you can only increase it. Adding a new device after the fact is painless if a spare partition already exists.

### Step 4 — Create four Event Streams in Ignition

One Event Stream per area, each with a Kafka handler pointing to its topic. The Kafka Connector does not have its own producer UI — routing is configured here on the Event Stream side.

```
Tag value changes → Event Stream (sources = tag paths) → Kafka Handler → Confluent topic
```

Repeat the following for each area:

**1. Go to Config → Event Streams → Add Event Stream**

| Event Stream name | Tag Path (one line) | Kafka topic |
|---|---|---|
| `factory-assembly-kafka` | `[default]Factory/Assembly/**` | `factory.assembly` |
| `factory-process-kafka` | `[default]Factory/Process/**` | `factory.process` |
| `factory-energy-kafka` | `[default]Factory/Energy/**` | `factory.energy` |
| `factory-packaging-kafka` | `[default]Factory/Packaging/**` | `factory.packaging` |

**2. Subscribe to tags using wildcards — not device folders**

Ignition Event Streams supports wildcards in tag paths (added in 8.3.4). Use them — they're far cleaner than listing every tag individually, and new devices or tags are picked up automatically without changing the event stream config.

**Wildcard operators:**

| Operator | Matches | Example |
|---|---|---|
| `*` | Any characters within a **single** path segment | `[default]Factory/Assembly/*` → every tag directly inside Assembly |
| `**` | Any number of intermediate folders (recursive) | `[default]Factory/Assembly/**` → every tag at any depth below Assembly |
| `?` | Exactly one character | `[default]CNC_?` → CNC_1, CNC_2 but not CNC_10 |
| `??`, `???` | Fixed character count | `[default]Tag??` → Tag10, Tag42 but not Tag1 |

Operators can be combined: `[default]Factory/**/CNC_*` matches any tag whose path contains a folder at any depth followed by a name starting with `CNC_`.

**Use `**` for each area — one line per event stream:**

```
[default]Factory/Assembly/**
```

This single line subscribes to every tag at every depth below Assembly:
- `[default]Factory/Assembly/CNC_01/State`
- `[default]Factory/Assembly/CNC_01/PartCount`
- `[default]Factory/Assembly/CNC_02/ToolWear_pct`
- … and any tags added in future without any config change

> **Why not subscribe to the device folder directly?**
> Subscribing to `[default]Factory/Assembly/CNC_01` (no wildcard, no `**`) produces events where the value payload has no tag name — consumers see `{ "value": 2, "quality": "Good", "timestamp": ... }` and have no idea if `2` is PartCount, ToolWear, or something else. The wildcard subscription fires a separate event per tag change, each with the full tag path in `{event.metadata.tagPath}`, so consumers know exactly what changed.

**3. Configure the Kafka handler fields**

| Field | Expression | Notes |
|---|---|---|
| Connector | `confluent-kafka` | select from dropdown |
| Topic | `'factory.assembly'` | static string in single quotes |
| Key | `{event.metadata.tagPath}` | full tag path, e.g. `[default]Factory/Assembly/CNC_01/State` — Kafka hashes this to pick a partition, all tags from the same device land in the same partition |
| Value | `{event.data}` | JSON object with `value`, `quality`, `timestamp` |
| Partition | *(leave blank)* | auto-assigned from Key hash |
| Timestamp | *(leave blank)* | Kafka stamps on arrival |

The resulting Kafka message looks like:

```
Key:   [default]Factory/Assembly/CNC_01/State
Value: { "value": "RUNNING", "quality": "Good", "timestamp": 1782218920495 }
```

The key carries the full tag path so consumers know both the device (`CNC_01`) and the tag (`State`). All tags from `CNC_01` hash to the same partition, preserving per-device ordering.

**4. Save and enable**

Click **Enabled** (top right). Check the pipeline counters — the number under **Handlers** should increment as tag changes flow through.

> **Expression bindings that work in the Kafka handler:** `{event.metadata.tagPath}` and `{event.data}` are the correct syntax. Expressions like `{tagPath}`, `{event.tagPath}`, `{event}`, or `{payload}` do NOT work — Ignition treats bare `{}` expressions as tag reads, not event bindings, and returns `Bad_NotFound`.

> **Per-tag vs per-device partition routing — understand the tradeoff:**
>
> With `{event.metadata.tagPath}` as the Key, the full tag path including tag name is used:
> ```
> [default]Factory/Assembly/CNC_02/State        → hashes to partition 3
> [default]Factory/Assembly/CNC_02/PartCount    → hashes to partition 1
> [default]Factory/Assembly/CNC_02/ToolWear_pct → hashes to partition 5
> ```
> Different tags from the same device can land in different partitions. Kafka hashes each unique key consistently — so `ToolWear_pct` always goes to the same partition — but the three tags above are in three different partitions.
>
> | Consumer need | Per-tag key (current setup) | Per-device key |
> |---|---|---|
> | History of one specific tag | ✅ ordered | ✅ ordered |
> | All CNC_02 changes in strict arrival order | ❌ split across partitions | ✅ single partition |
> | Time-series analytics per tag | ✅ fine | ✅ fine |
> | Fault correlation (State + PartCount together in order) | ⚠️ multi-partition read needed | ✅ single partition |
>
> **For learning and tag-level analytics, per-tag keying is fine.** If you later need strict per-device ordering, change the Key expression to extract only the device segment from the path — for example `split({event.metadata.tagPath}, "/")[2]` to extract `CNC_02` — so all tags from the same device share one key and land in one partition.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'asyncua'`**
Run `pip install -r requirements.txt` inside your activated virtual environment.

**OPC UA: Ignition can't connect**
Make sure your firewall allows inbound TCP on port 4840. On Windows: Control Panel → Windows Defender Firewall → Allow an app → add Python.

**MQTT: no messages arriving**
Check your broker is running (`mosquitto` or similar). Confirm the broker address in `config/factory.yaml` matches. Use MQTT Explorer to verify the simulator is publishing.

**Sparkplug B: tags not appearing in Ignition**
Ensure the MQTT Engine module is licensed and configured with the correct broker. The group ID and edge node ID in `factory.yaml` must match what MQTT Engine is scanning for.
