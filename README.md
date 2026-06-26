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

**2. Set the Change Triggers — and why Timestamp will ruin your day**

The Source stage has three checkboxes: **Value**, **Quality**, and **Timestamp**. All three are enabled by default.

| Trigger | What fires an event | Keep it? |
|---|---|---|
| **Value** | Any tag value changes | ✅ Yes — this is your actual data |
| **Quality** | Tag quality changes (Good → Bad, Bad → Good) | ⚠️ Maybe — useful for fault detection, but keep it separate (see below) |
| **Timestamp** | Every scan tick, regardless of whether anything changed | ❌ No — uncheck this immediately |

**Why Timestamp is a problem:** Ignition updates timestamps on every scan cycle even when the value is identical. With Timestamp checked, a 2-second tick interval and 30 tags generates ~900 Kafka messages per minute of pure clock-tick noise — same `value`, same `quality`, different timestamp. Your Kafka topic fills up, your Transform script runs 900 times a minute for nothing, and a downstream consumer has no way to tell a real change from a heartbeat.

**Recommendation: uncheck Timestamp, uncheck Quality, keep only Value.**

Once you do this, every event that reaches Kafka is implicitly a value-change event — no `trigger` field needed because it is always true.

**If you later need quality-change alerting** (e.g. detect a sensor going Bad): create a *separate* Event Stream — `factory-assembly-health-kafka` — with only Quality checked, routing to a `factory.alerts` topic. Keeping value-change data and quality-change events in separate streams makes each stream's purpose explicit and keeps your main data topics clean.

**3. Subscribe to tags using wildcards — not device folders**

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

**4. Enrich the payload in the Transform stage**

By default the Kafka message value is:
```json
{ "value": 419, "quality": "Good", "timestamp": 1782224819614 }
```

This is useless to a downstream consumer — there is no tag name, no device name, no area. A consumer reading `"value": 419` has no idea if that is PartCount, ToolWear, or something else entirely.

Fix this in the **Transform** stage (the currently-disabled stage in the pipeline). Click on Transform, enable it, and paste this script:

```python
def transform(event, state):
    # event.metadata.tagPath = "[default]Factory/Assembly/Robot_Arm_01/PartCount"
    parts = event.metadata.tagPath.split("/")
    #  [0]=[default]Factory  [1]=Assembly  [2]=Robot_Arm_01  [3]=PartCount

    if len(parts) < 4:
        return None  # drop malformed paths cleanly rather than sending bad data

    enriched = dict(event.data)          # copy existing value/quality/timestamp
    enriched["area"]       = parts[1]    # "Assembly"
    enriched["machine_id"] = parts[2]    # "Robot_Arm_01"
    enriched["tag"]        = parts[3]    # "PartCount"

    return system.util.jsonEncode(enriched)
```

`system.util.jsonEncode()` is the Ignition built-in that converts the Python dict to a JSON string. The Kafka handler sends that string as the message body bytes.

After the transform, the Kafka message becomes:
```json
{
  "area":       "Assembly",
  "machine_id": "Robot_Arm_01",
  "tag":        "PartCount",
  "value":      419,
  "quality":    "Good",
  "timestamp":  1782224819614
}
```

Every downstream consumer — TimescaleDB, S3, ClickHouse, a Python script — can now understand the message in isolation without parsing the key or knowing the topic structure.

> **Why enrich here and not downstream?** Fix data as early as possible in the pipeline. If you enrich in the consumer, every consumer independently does the same parsing. If the tag path format ever changes, you fix it in one place — the Transform script — and all consumers benefit automatically.

> **`dict(event.data)` vs hardcoding fields:** Using `dict(event.data)` copies whatever fields the encoder put in (`value`, `quality`, `timestamp`) and then adds the new ones on top. If Ignition ever adds a field to `event.data`, it carries through automatically without changing the script.

> **Returning `None` drops the event.** This is intentional for malformed paths. Sending incomplete data downstream is worse than sending nothing — a consumer that receives `{ "area": "Assembly", "machine_id": "CNC_01", "tag": "" }` will silently produce wrong results.

**5. Save and enable**

Click **Enabled** (top right). Check the pipeline counters — the number under **Handlers** should increment as tag changes flow through.

> **Expression bindings that work in the Kafka handler:** `{event.metadata.tagPath}` and `{event.data}` are the correct syntax. Expressions like `{tagPath}`, `{event.tagPath}`, `{event}`, or `{payload}` do NOT work — Ignition treats bare `{}` expressions as tag reads, not event bindings, and returns `Bad_NotFound`.

**6. Configure the Error Handler**

The Error Handler is the last stage in the pipeline (the dashed circle after Handlers). By default it is empty — errors are silently swallowed, and you will have no idea why data stops flowing.

The default code is:
```python
def onError(event, state):
```

Replace it with:
```python
def onError(event, state):
    logger = system.util.getLogger("factory.stream")

    try:
        tag = event.metadata.tagPath
    except:
        tag = "unknown"

    try:
        error = str(event.error)
    except:
        try:
            error = str(event.cause)
        except:
            error = "unknown error"

    logger.error("Pipeline error | tag=%s | error=%s" % (tag, error))
```

Errors are then visible in **Config → Logs** — filter by logger name `factory.stream`.

Notes on the `try/except` blocks:
- `event.metadata.tagPath` might not be populated if the error happened before the event was enriched (e.g. a Confluent connection failure)
- `event.error` vs `event.cause` — Ignition's exact property name is not confirmed in the docs; this tries both so at least one works
- Once an error fires, check the log to see which property name was actually available and tighten the script

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

### Step 5 — Monitor quality changes (why Event Streams falls short, and what to use instead)

Tag quality changes silently — a sensor can go `Bad` and keep publishing its last-known value indefinitely. Nothing in the value-change stream tells you this has happened because the value itself didn't change. You need a dedicated quality monitoring path to catch it.

**Why you want this in Kafka:**
- One `factory.quality` topic for all areas — alerting is cross-area by nature
- Volume is low (sensors don't go Bad constantly) — no need for per-area topics
- Consumers are different: value data feeds analytics; quality events feed an alerting system (Slack, PagerDuty, anomaly detector)
- 7-day retention recommended — longer than value topics so you can correlate a bad sensor with past anomalies

**The natural instinct: use Event Streams with Quality trigger — and why it doesn't work**

The first thing you'll try is creating an Event Stream with the Quality change trigger checked and `**` wildcards — the same pattern that works perfectly for value changes. It does not work. Here is exactly what happens and why.

With **Value** trigger, `**` fires one event **per leaf tag** that changes:
```
event.metadata.tagPath = [default]Factory/Assembly/CNC_01/ToolWear_pct   ← 4 segments ✅
```

With **Quality** trigger, `**` fires one event **per subscribed folder root**:
```
event.metadata.tagPath = [default]Factory/Assembly   ← 2 segments ❌
```

The path only has 2 segments when split by `/`. The Transform script drops it (`len(parts) < 4 → return None`). Nothing reaches Kafka. Even if you remove the guard, the payload carries no device name and no tag name — just `{ "value": 2, "quality": "Good", "timestamp": ... }` where `value: 2` is Ignition's internal folder quality code, not a sensor reading.

**Why can't you get the tag name?**

Ignition fires quality rollup events at the folder level when any child tag's quality changes. It does not fire one event per affected tag — it fires one event per subscription root. So with `[default]Factory/Assembly/**` as the source, one Quality event covers the entire Assembly area. The specific tag that went Bad is not in `event.metadata.tagPath` and is not in `event.data`. It is simply not available in the Event Streams quality event payload.

**What about subscribing per device?**

You might try replacing the area wildcards with one line per device:
```
[default]Factory/Assembly/CNC_01/**
[default]Factory/Assembly/CNC_02/**
...
```

Based on the same rollup behaviour, quality events fire at `[default]Factory/Assembly/CNC_01` (3 segments). You gain the device name but still lose the tag name. And you've gone from 4 wildcard lines to 9 device lines — any new device added to the simulator requires a matching change in Ignition.

**What about subscribing per tag (no wildcards)?**

Subscribing to each individual tag path gives 4-segment paths and therefore the exact tag name. But that means listing ~40 paths explicitly for this factory, and every new tag added to the simulator requires an Ignition config change. Fragile and not maintainable.

**Event Streams source types available**

The Ignition Event Stream source dropdown offers: Event Listener, Kafka, MQTT, Sparkplug, Tag Event. There is no Alarm Event source. Tag Event with Quality trigger is the only tag-quality path in Event Streams, and it has the folder-rollup limitation above.

**The right approach: Ignition Alarms → Kafka**

Ignition Alarms are designed for exactly this. Configure a quality alarm on each tag (built-in alarm type, triggers when quality transitions to non-Good). Alarms know the exact tag path, the device, the transition time, the previous quality state, and whether the alarm is acknowledged. They survive Ignition restarts and are written to a persistent alarm journal.

Tag quality has exactly three values: **Good**, **Uncertain**, **Bad**. Configure one alarm per quality state (excluding Good) so each transition is captured with the right priority.

**Configuring alarms on all tags automatically**

Rather than clicking each tag individually, run this once in **Tools → Script Console** to add a `QualityBad` alarm to every atomic tag under Factory. The `"m"` (merge) mode is idempotent — safe to run repeatedly without creating duplicates.

> **Critical:** `basePath` in `system.tag.configure()` must be the **parent folder** of each tag, not `[default]`. Passing `"[default]"` as the base with a nested path in the config dict does not navigate to the existing tag — it silently creates a ghost root-level tag with the same name and stacks alarms onto that instead. The correct pattern splits each full path into parent + name with `rfind("/")`.

```python
alarm_config = {
    "name": "QualityBad",
    "mode": "Bad Quality",          # ← space required; "BadQuality" silently does nothing
    "priority": "High",
    "activePipeline": "FactorySimulator_OPC_UA/factory-quality-pipeline"
    # ↑ field is "activePipeline", not "pipeline". Format: "ProjectName/PipelineName"
}

def collect_atomic_tags(path, results):
    for tag in system.tag.browse(path).getResults():
        tag_type = str(tag["tagType"])
        full_path = str(tag["fullPath"])
        if tag_type == "AtomicTag":
            results.append(full_path)
        elif tag_type in ("Folder", "UdtInstance"):
            collect_atomic_tags(full_path, results)

all_tags = []
collect_atomic_tags("[default]Factory", all_tags)
print("Found", len(all_tags), "tags")

count, errors = 0, []
for full_path in all_tags:
    idx    = full_path.rfind("/")
    parent = full_path[:idx]        # "[default]Factory/Assembly/CNC_01"
    name   = full_path[idx+1:]      # "PartCount"
    result = system.tag.configure(parent, [{"name": name, "alarms": [alarm_config]}], "m")
    if result and str(result[0]) == "Good":
        count += 1
    else:
        errors.append((full_path, result))

print("Configured:", count, "tags")
if errors:
    print("Errors:", errors)
```

Verify one tag after running:
```python
check = system.tag.getConfiguration("[default]Factory/Assembly/CNC_01/PartCount", False)
print(check[0].get("alarms", "NONE"))
# Expected: [{u'activePipeline': u'...', u'priority': High, u'mode': Bad Quality, u'name': u'QualityBad'}]
```

> **If `getConfiguration` shows a root-level `PartCount` tag with many alarms stacked on it:** that is a ghost tag created by a previous run of the wrong script. Delete it from the tag browser (right-click → Delete). It is not an OPC UA tag. The correct script above will not create it.

**Keeping alarms up to date as new devices are added**

The script above only covers tags that exist at the moment you run it. When you add a new device to the simulator and restart it, new tags appear with no alarms. Fix this with a **Gateway Scheduled Script** that runs automatically every 5 minutes and only touches tags that are missing the alarm.

In Ignition Designer: **Tools → Gateway Scripts → Scheduled → Add Script**

| Setting | Value |
|---|---|
| Name | `alarm-auto-configure` |
| Schedule (CRON Minutes field) | `*/5` — leave Hours, Days, Months, Weekdays as `*` |

```python
alarm_config = {
    "name": "QualityBad",
    "mode": "Bad Quality",
    "priority": "High",
    "activePipeline": "FactorySimulator_OPC_UA/factory-quality-pipeline"
}

def collect_atomic_tags(path, results):
    for tag in system.tag.browse(path).getResults():
        tag_type = str(tag["tagType"])
        full_path = str(tag["fullPath"])
        if tag_type == "AtomicTag":
            results.append(full_path)
        elif tag_type in ("Folder", "UdtInstance"):
            collect_atomic_tags(full_path, results)

all_tags = []
collect_atomic_tags("[default]Factory", all_tags)

for full_path in all_tags:
    check = system.tag.getConfiguration(full_path, False)
    if check and not check[0].get("alarms"):          # skip tags that already have alarms
        idx    = full_path.rfind("/")
        parent = full_path[:idx]
        name   = full_path[idx+1:]
        system.tag.configure(parent, [{"name": name, "alarms": [alarm_config]}], "m")
        system.util.getLogger("AlarmProvisioner").info("Added QualityBad alarm to " + full_path)
```

Save (Ctrl+S) and **Publish** (Ctrl+Shift+P) — it won't run until published. The `if not check[0].get("alarms")` guard means it skips tags that already have the alarm, so running every 5 minutes is cheap and harmless. New tags from new simulator devices get their alarm within 5 minutes of appearing.

Getting alarms into Kafka requires one of two paths. **Check which is available in your install first.**

**Confirmed path — Event Stream Source block in the Alarm Notification Pipeline**

Ignition's Alarm Notification Pipeline has a native **Event Stream Source** block (visible in the Pipeline Blocks toolbar in the Designer, alongside Notification, Script, Delay etc.). This block feeds alarm event data directly into an Event Stream that uses an **Event Listener** source — no scripting required in the pipeline itself.

The full chain:

```
Alarm fires
  → Alarm Notification Pipeline
      → Event Stream Source block ──→ factory-alarm-listener (Event Listener source)
                                              → Transform script
                                                  → Kafka Handler → factory.quality
```

**1. Create the Event Stream**

Go to **Config → Event Streams → Add Event Stream**. Name it `factory-alarm-listener`. Set the source type to **Event Listener**. Add a Kafka handler pointing at `factory.quality`. Enable the Transform stage (see script below).

**2. Configure the Alarm Notification Pipeline**

In the Designer, open (or create) an Alarm Notification Pipeline. Drag the **Event Stream Source** block from the Pipeline Blocks toolbar onto the canvas. Connect it after START. In the block's properties panel, set the **Event Stream** dropdown to `factory-alarm-listener`.

The alarm event data passed to the Event Stream is an **AlarmEventObject** — it carries the tag source path, alarm state, priority, active time, clear time, and any custom alarm properties. This is the object that arrives as `event.data` in the Transform script.

**3. What the alarm event data actually looks like**

The event that arrives in the Transform is a `PyEventPayload` object. `event.data` is a Java-backed dict you can convert with `dict(event.data)`. A real alarm event from this simulator looks like:

```python
{
    'eventId':           '68afc44e-254a-4487-96bc-0257c251f146',
    'eventFlags':        0,
    'source':            'prov:default:/tag:Factory/Packaging/Packaging_Line_01/ConveyorSpeed_m_min:/alm:QualityBad',
    'displayPath':       '',
    'eventType':         2,
    'priority':          3,
    'eventTypeReadable': 'Active, Unacknowledged',
    'priorityReadable':  'High',
    'eventTime':         'Fri Jun 26 00:10:41 AEST 2026'
}
```

The key field is `source`. It follows the format:

```
prov:{provider}:/tag:{tag_path}:/alm:{alarm_name}
```

So `source.split("/tag:")[1].split(":/alm:")[0]` extracts `Factory/Packaging/Packaging_Line_01/ConveyorSpeed_m_min`.

**4. Transform script for alarm events**

```python
def transform(event, state):
    logger     = system.util.getLogger("alarm-transform")
    try:
        data       = dict(event.data)
        raw_source = str(data.get("source", ""))

        # Parse: prov:default:/tag:Factory/Assembly/CNC_01/PartCount:/alm:QualityBad
        tag_path = raw_source.split("/tag:")[1].split(":/alm:")[0] if "/tag:" in raw_source else raw_source
        alarm    = raw_source.split(":/alm:")[1]                   if ":/alm:" in raw_source else ""
        parts    = tag_path.split("/")   # ['Factory', 'Assembly', 'CNC_01', 'PartCount']

        result = {
            "metadata": {"tagPath": tag_path},
            "data": {
                "tag_path":   tag_path,
                "area":       parts[1] if len(parts) > 1 else "",
                "device":     parts[2] if len(parts) > 2 else "",
                "tag":        parts[3] if len(parts) > 3 else "",
                "alarm":      alarm,
                "state":      str(data.get("eventTypeReadable", "")),
                "priority":   str(data.get("priorityReadable", "")),
                "event_time": str(data.get("eventTime", "")),
                "event_id":   str(data.get("eventId", ""))
            }
        }
        logger.info("OUTPUT: " + str(result))
        return result
    except Exception as e:
        logger.error("Transform FAILED: " + str(e))
        return None
```

> **Transform function signature is `(event, state)`, not `(event, logger)`.** The second parameter is a persistent state dict, not a logger. Log via `system.util.getLogger("name")` inside the function body.

> **Why wrap in try/except:** without it, any exception in the Transform is swallowed silently — the event counter increments but nothing reaches Kafka and there is no error in the logs.

**5. Kafka handler configuration for `factory-alarm-listener`**

| Field | Value | Notes |
|---|---|---|
| Connector | `confluent-kafka` | same connection as the other streams |
| Topic | `'factory.quality'` | **single quotes required** — Ignition expression language; without quotes `factory.quality` is evaluated as an expression looking for variable `factory`, returns null, silently drops every message |
| Key | *(leave blank)* | null key → Kafka distributes round-robin. `{event.metadata.tagPath}` and `{event.data.tag_path}` both fail — Ignition's expression engine cannot navigate nested Python dicts via dot notation after Transform returns a Python dict. The `tag_path` is inside the value payload anyway. |
| Value | `{event.data}` | the `data` field from the Transform result dict |

The resulting Kafka message in Confluent:

```json
{
  "metadata": { "tagPath": "Factory/Assembly/CNC_01/PartCount" },
  "data": {
    "tag_path":   "Factory/Assembly/CNC_01/PartCount",
    "area":       "Assembly",
    "device":     "CNC_01",
    "tag":        "PartCount",
    "alarm":      "QualityBad",
    "state":      "Active, Unacknowledged",
    "priority":   "High",
    "event_time": "Fri Jun 26 00:10:37 AEST 2026",
    "event_id":   "fdfd711d-a711-42ea-afa2-587e62ae65d7"
  }
}
```

The `metadata.tagPath` is redundant with `data.tag_path` — both are there because `{event.data}` returns the entire dict the Transform returned (not just the inner `data` key). Downstream consumers should read from `data`.

> **Ignition expression engine limitation:** After a Transform returns a Python dict, the handler expressions `{event.X}` and `{event.X.Y}` only work if the key `X` maps to a Java-accessible property. `{event.data}` works (accesses the `"data"` key of the top-level dict). `{event.data.tag_path}` fails ("Missing element") — the expression engine cannot recursively traverse nested Python dicts. This is why the Key is left blank rather than using `{event.data.tag_path}`.

**A quality alarm message in `factory.quality` looks like:**

```json
{
  "tag_path":   "Factory/Assembly/CNC_01/ToolWear_pct",
  "area":       "Assembly",
  "device":     "CNC_01",
  "tag":        "ToolWear_pct",
  "alarm":      "QualityBad",
  "state":      "Active, Unacknowledged",
  "priority":   "High",
  "event_time": "Fri Jun 26 00:10:37 AEST 2026",
  "event_id":   "fdfd711d-a711-42ea-afa2-587e62ae65d7"
}
```

This tells a downstream consumer exactly which tag went Bad, when, and what state the alarm is in — everything the Event Streams Quality trigger approach cannot deliver.

**6. Error Handler**

Add an error handler so failures are logged rather than silently swallowed:

```python
def onError(event, state):
    logger = system.util.getLogger("alarm-error")
    logger.error("Error count: " + str(len(event)))
    for item in event:
        logger.error("Error item: " + str(item))
```

> **`event` in `onError` is a list**, not a single object. Accessing `event.stage` or `event.cause` throws `AttributeError: 'list' object has no attribute 'stage'`. Iterate over it.

Check **Config → Logs** and filter by logger name `alarm-error` to see failures.

> **`system.kafka` does not exist.** The Kafka Connector module (as of Ignition 8.3) does not expose a scripting namespace. Running `print(dir(system.kafka))` in the Script Console throws `AttributeError`. The Event Stream Source block approach above is the only supported path for routing alarm events to Kafka.

> **Summary of all streams and topics:**
>
> | Source | Ignition config | Kafka topic | Per-tag? |
> |---|---|---|---|
> | `factory-assembly-kafka` Event Stream | Tag Event / Value | `factory.assembly` | ✅ |
> | `factory-process-kafka` Event Stream | Tag Event / Value | `factory.process` | ✅ |
> | `factory-energy-kafka` Event Stream | Tag Event / Value | `factory.energy` | ✅ |
> | `factory-packaging-kafka` Event Stream | Tag Event / Value | `factory.packaging` | ✅ |
> | Alarm Notification Pipeline | Script → Kafka or Event Listener | `factory.quality` | ✅ |
> | ~~`tag_quality_stream` Event Stream~~ | ~~Tag Event / Quality~~ | ~~`factory.quality`~~ | ❌ folder-level only |

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

**Event Stream shows "Events Received: 0" after editing any part of the stream**
Editing any part of an Event Stream in Ignition — including just the error handler script — silently clears the Source tag path subscription on save. The stream reports "Event Stream running" and shows no errors, but receives nothing. Gateway restart and Disable → Enable do not fix it.

Symptoms:
- `Events Received: 0` in the Status panel
- OPC UA connection is green, tag values are actively changing in the tag browser
- Other streams that were not edited continue working normally

Fix: click the **Source** block of the affected stream, re-enter the tag path (e.g. `[default]Factory/Assembly/**`), and save. Events will start flowing immediately.

To confirm the issue is the tag path and not the infrastructure, create a fresh test stream with the same tag path and no handler — if it receives events, the existing stream's source path was cleared.

**Safest way to edit an Event Stream without losing the tag path subscription:** note down the tag path before making any changes. After saving, immediately check the Source block to confirm the path is still there.
