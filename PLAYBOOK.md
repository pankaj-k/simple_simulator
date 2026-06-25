# Factory Simulator Playbook

A hands-on field guide to building an industrial IoT data pipeline from scratch — Python simulator → Ignition SCADA → Confluent Cloud Kafka. Each chapter is a milestone. Each chapter also records what broke and why, because that is where the learning is.

---

## Chapter 1: The Factory — What We Are Simulating

Before touching any infrastructure, it helps to know what the simulator actually models.

The factory has four areas and nine devices. They are not independent — faults in Assembly produce measurable downstream effects in Energy and Packaging, exactly as they would on a real plant floor.

### The four areas

| Area | Devices | What they model |
|------|---------|-----------------|
| **Assembly** | CNC_01, CNC_02, Robot_Arm_01 | CNC machining + robot arm with state machines |
| **Process** | Reactor_Tank_01, Reactor_Tank_02 | Chemical tanks with temperature/pressure/level |
| **Energy** | Main_Meter, Line_A_Meter, Line_B_Meter | Power meters observing the assembly machines |
| **Packaging** | Packaging_Line_01 | Conveyor line fed by the assembly machines |

### Assembly machines

Each machine runs a state machine:

```
RUNNING ──(0.2% chance/tick)──► FAULT ──(30s)──► IDLE ──(10s)──► RUNNING
   │                                                                   ▲
   └──(ToolWear ≥ 95%)──► IDLE (maintenance, wear resets to 0) ───────┘
```

Key tags: `State` (RUNNING/IDLE/FAULT), `PartCount`, `CycleTime_sec`, `ToolWear_pct`, `Alarm`.

### Energy meters

Energy meters observe the assembly machines and reflect their real load:

- **Main_Meter** — all 3 machines (total site load)
- **Line_A_Meter** — CNC_01 and CNC_02 only
- **Line_B_Meter** — Robot_Arm_01 only

Load formula: `30% base (lighting, HVAC, idle equipment) + 70% variable (machines running)`. When all machines fault, the meters drop to ~30% of rated power. When they recover, the meters rise again. This is visible in Kafka as a correlated dip in `factory.energy` events whenever `factory.assembly` shows a fault.

### Packaging line

The packaging line receives parts from the assembly machines. The key tag is `SupplyFactor_pct` — the percentage of assembly machines currently running (0–100%). When this hits zero, the packaging line is forced to stop regardless of its own state. Low supply also drives up the reject rate, which lowers OEE.

### The causal chain — what Kafka replay can reconstruct

```
T+00s  All machines RUNNING      SupplyFactor=100%  OEE≈75%   Main_Meter≈270kW
T+47s  CNC_01 → FAULT            SupplyFactor= 67%  OEE falls  Line_A_Meter drops
T+52s  CNC_02 → FAULT            SupplyFactor= 33%  OEE falls  reject rate rises
T+81s  Robot_Arm_01 wear at 95%  SupplyFactor=  0%  Line STOPS Main_Meter≈110kW
T+92s  CNC_01 recovers           SupplyFactor= 33%  Line restarts slowly
T+111s CNC_02 recovers           SupplyFactor= 67%  OEE climbs
T+121s Robot_Arm_01 back online  SupplyFactor=100%  OEE climbs Main_Meter≈270kW
```

A digital twin replaying Kafka offsets can answer "why did OEE drop at 14:32?" in seconds, because `SupplyFactor_pct` went to zero two seconds earlier, caused by `ToolWear_pct` crossing 95% on Robot_Arm_01.

---

## Chapter 2: Running the Simulator

### Installation

```bash
git clone <repo-url>
cd factory_simulator
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### Configuration

Everything is in `config/factory.yaml` — broker addresses, OPC UA endpoint, tick interval. No hardcoded connection strings anywhere in the source.

```yaml
simulation:
  tick_interval: 2.0     # seconds between updates

opcua:
  endpoint: "opc.tcp://0.0.0.0:4840/factory/"

mqtt:
  broker: "localhost"
  port: 1883

sparkplug:
  broker: "localhost"
  port: 1883
  group_id: "Factory_01"
  edge_node_id: "Edge_Node_01"
```

### The three protocol modes

```bash
python -m simulator.main opcua        # OPC UA server on port 4840
python -m simulator.main mqtt         # JSON publisher to MQTT broker
python -m simulator.main sparkplug    # Sparkplug B publisher to MQTT broker
```

Start the simulator first, then connect Ignition to it. The OPC UA mode needs no broker — just Python and Ignition.

### Protocol comparison

| | OPC UA | Plain MQTT | Sparkplug B |
|--|--------|------------|-------------|
| Transport | TCP | MQTT | MQTT |
| Payload | Binary | JSON | Protobuf binary |
| Ignition module | None (built-in) | MQTT Engine | MQTT Engine (Cirrus Link) |
| Auto tag creation | Yes (browse) | Manual | Yes (from DBIRTH) |
| Best for | First step | Learning the data | Production pattern |

### Test mode

```bash
python -m simulator.main opcua --test
```

Enables the `FaultInjector`. Each tick, after all device updates, it randomly sets `tag.quality` to `"Bad"` (60% probability) or `"Uncertain"` (40%) on individual tags — ~0.1% chance per tag per 2-second tick. Each affected tag recovers after a random duration between 2 and 120 seconds. Console output:

```
22:51:03 WARNING  Quality FAULT      CNC_01                ToolWear_pct                   (47s)
22:51:50 INFO     Quality RECOVERED  CNC_01                ToolWear_pct
```

The OPC UA connector translates quality to OPC UA status codes:
- `Bad` → `BadDeviceFailure` — Ignition shows the tag as `Bad_DeviceFailure`
- `Uncertain` → `UncertainLastUsableValue` — Ignition shows the tag as `Uncertain`
- `Good` → no status code set (default Good quality)

The test mode exists so you can exercise your quality alarm pipeline without waiting for a real sensor to fail.

---

## Chapter 3: Connecting Ignition over OPC UA

With the simulator running in OPC UA mode, the tag tree is immediately visible from Ignition.

### Creating the OPC UA connection

1. **Config → OPC UA → Connections → Add Connection**
2. Endpoint URL: `opc.tcp://<your-PC-IP>:4840/factory/`
3. Leave Security Policy as None for local development
4. Save and Connect — status should turn green

### Browsing tags

In the Designer tag browser, expand the OPC UA connection. The tag tree mirrors the factory structure:

```
[FactorySimulator]
└── Factory
    ├── Assembly
    │   ├── CNC_01
    │   │   ├── State          (String)
    │   │   ├── PartCount      (Int)
    │   │   ├── CycleTime_sec  (Float)
    │   │   ├── ToolWear_pct   (Float)
    │   │   └── Alarm          (Bool)
    │   ├── CNC_02             ...
    │   └── Robot_Arm_01       ...
    ├── Process ...
    ├── Energy  ...
    └── Packaging ...
```

Drag any tag onto a Vision or Perspective component to see it updating live.

### What to observe

- `State` flips between RUNNING, IDLE, and FAULT roughly every few minutes
- `ToolWear_pct` climbs steadily and resets to 0 when it hits 95%
- `ActivePower_kW` on the energy meters drops whenever assembly machines fault
- `OEE_pct` on the packaging line drops when `SupplyFactor_pct` falls

With `--test` mode: watch individual tags go `Bad_DeviceFailure` in the quality column and recover automatically. This is the quality signal you will route to Kafka in later chapters.

### Known startup noise

The asyncua library logs INFO messages about "parent node does not exist" at startup — these are normal, it is loading its built-in OPC UA standard nodesets. They are suppressed in `main.py` by setting the asyncua logger to ERROR level.

---

## Chapter 4: Streaming Tag Values to Confluent Cloud Kafka

This chapter wires Ignition → Confluent so every tag value change flows into Kafka in near real-time.

### Required Ignition modules

Two modules are needed beyond the standard Ignition install. Install via **Config → Modules → Install or Upgrade a Module**:

1. **Event Streams module** — must be installed first
2. **Kafka Connector module** — depends on Event Streams

### Step 1 — Store the Confluent API secret safely

Rather than pasting the secret as plaintext:

1. **Config → Security → Secret Providers → Internal provider**
2. Add secret: name `confluent-kafka-secret`, value = your Confluent API secret key

### Step 2 — Create the Kafka connection

**Config → Kafka Connector → Connections → Add Connection**

| Field | Value |
|-------|-------|
| Name | `confluent-kafka` |
| Bootstrap Servers | `pkc-xxxxx.us-east-1.aws.confluent.cloud:9092` |
| Security Protocol | `SASL_SSL` |
| SASL Mechanism | `PLAIN` |
| SASL Username | your Confluent API key |
| SASL Password | `{secrets:confluent-kafka-secret}` |

### Step 3 — Create four Kafka topics in Confluent

One topic per area. Confluent does not auto-create topics — create them before configuring Ignition.

| Topic | Partitions |
|-------|------------|
| `factory.assembly` | 4 |
| `factory.process` | 3 |
| `factory.energy` | 4 |
| `factory.packaging` | 3 |

Set retention to 7 days (`604800000` ms). Skip the data contract / schema step — get data flowing first, then define the schema from real messages.

### Step 4 — Create four Event Streams

**Config → Event Streams → Add Event Stream** — one per area.

**Source:** Tag Event. Subscribe to:

```
[default]Factory/Assembly/**
[default]Factory/Process/**
[default]Factory/Energy/**
[default]Factory/Packaging/**
```

The `**` wildcard fires one event per leaf tag per change. This is important — subscribing to a folder without `**` fires one event for the entire folder with no tag name in the payload.

**Change Triggers — uncheck Timestamp immediately.**

| Trigger | Keep? | Why |
|---------|-------|-----|
| Value | ✅ Yes | actual data changes |
| Quality | ❌ No (for value streams) | handled separately in Chapter 6 |
| Timestamp | ❌ No | fires every scan tick even with no change — pure noise |

With a 2-second tick and 46 tags, leaving Timestamp checked generates ~1,380 events per minute of pure clock-tick noise.

**Kafka handler fields:**

| Field | Expression |
|-------|-----------|
| Connector | `confluent-kafka` |
| Topic | `'factory.assembly'` ← **single quotes required** |
| Key | `{event.metadata.tagPath}` |
| Value | `{event.data}` |

The single quotes matter: Ignition's handler fields use expression language, not plain strings. Without quotes, `factory.assembly` is evaluated as an expression looking for a variable named `factory` — it returns null, and every message is silently dropped.

### Step 5 — Enrich the payload in the Transform stage

The default `{event.data}` value is `{ "value": 419, "quality": "Good", "timestamp": 1782224819614 }`. The tag name, device, and area are missing. Fix this in the Transform:

```python
def transform(event, state):
    # event.metadata.tagPath = "[default]Factory/Assembly/Robot_Arm_01/PartCount"
    parts = event.metadata.tagPath.split("/")
    #  [0]=[default]Factory  [1]=Assembly  [2]=Robot_Arm_01  [3]=PartCount

    if len(parts) < 4:
        return None   # drop malformed paths — bad data is worse than no data

    enriched = dict(event.data)
    enriched["area"]       = parts[1]   # "Assembly" / "Energy" / "Process" / "Packaging"
    enriched["machine_id"] = parts[2]   # device name
    enriched["tag"]        = parts[3]   # tag name
    return system.util.jsonEncode(enriched)
```

> **This same script works for all four value streams without modification.** `parts[1]` resolves to the area name for whichever stream is running — `"Assembly"`, `"Energy"`, `"Process"`, or `"Packaging"`. Paste it identically into the Transform of all four Event Streams.

Result in Kafka:
```json
{
  "value": 419,
  "quality": "Good",
  "timestamp": 1782224819614,
  "area": "Assembly",
  "machine_id": "Robot_Arm_01",
  "tag": "PartCount"
}
```

### Step 6 — Add an Error Handler

Without this, errors disappear silently. Add to the Error Handler stage:

```python
def onError(event, state):
    logger = system.util.getLogger("factory.stream")
    for item in event:
        logger.error("Stream error: " + str(item))
```

Note: `event` in `onError` is a **list**, not a single object. Calling `event.stage` throws `AttributeError`. Iterate it.

---

## Chapter 5: Fault Injection and OPC UA Quality

The simulator's `--test` flag enables the `FaultInjector`, which simulates what a real PLC does when a sensor fails: it sets the tag's quality to non-Good rather than publishing a wrong value.

### What the FaultInjector does

Located in `simulator/factory/fault_injector.py`. Each tick, after all device updates:

- Scans every tag on every device
- 0.1% chance per tag per tick of triggering a fault
- Sets `tag.quality` to `"Bad"` (60%) or `"Uncertain"` (40%)
- Records a recovery timer between 2 and 120 seconds
- On recovery, sets `tag.quality` back to `"Good"`

### How the OPC UA connector translates quality

The asyncua `DataValue` object carries both a value and a status code. The connector writes them together:

```python
_QUALITY_STATUS = {
    "Uncertain": ua.StatusCodes.UncertainLastUsableValue,
    "Bad":       ua.StatusCodes.BadDeviceFailure,
}

dv = ua.DataValue(ua.Variant(tag.value, vtype))
if tag.quality in _QUALITY_STATUS:
    dv.StatusCode = ua.StatusCode(_QUALITY_STATUS[tag.quality])
await var_node.write_value(dv)
```

Note: the attribute is `StatusCode` (no underscore). Setting `StatusCode_` raises `AttributeError`. The correct name was confirmed via `dir(ua.DataValue())`.

### What you see in Ignition

With `--test` running, the Ignition tag browser shows individual tags flickering between `Good`, `Bad_DeviceFailure`, and `Uncertain_LastUsableValue` quality states. The value itself is unchanged — this is exactly how a real failed sensor behaves.

---

## Chapter 6: Quality Monitoring — The Wrong Way First

Quality changes silently — a sensor goes Bad but keeps publishing its last-known value. The value-change stream in Chapter 4 does not catch this. The natural instinct is to add a Quality trigger to the existing Event Streams.

### The attempt

Create an Event Stream with the Quality change trigger checked and `[default]Factory/Assembly/**` as the source. Looks right. Doesn't work.

### What actually fires

With **Value** trigger, `**` fires one event **per leaf tag**:
```
event.metadata.tagPath = [default]Factory/Assembly/CNC_01/ToolWear_pct   ← 4 path segments ✅
```

With **Quality** trigger, `**` fires one event **per subscription root folder**:
```
event.metadata.tagPath = [default]Factory/Assembly   ← 2 path segments ❌
```

The path has only 2 segments. The Transform's `len(parts) < 4` guard drops it. Even if you remove the guard, the payload is `{ "value": 2, "quality": "Good", "timestamp": ... }` — the `value: 2` is Ignition's internal folder quality rollup code, not a sensor reading. There is no device name, no tag name.

### Why this happens

Ignition fires quality events at the **folder level** — one event for the entire subscription root, not one per affected tag. The specific tag that went Bad is not available in `event.data` or `event.metadata.tagPath`. It is simply not there.

### Alternatives explored and why they fail

| Approach | Result |
|----------|--------|
| Subscribe per device (`[default]Factory/Assembly/CNC_01/**`) | Quality fires at `CNC_01` level — gain device name, still lose tag name |
| Subscribe per tag (no wildcards) | Works but requires listing ~46 paths explicitly — not maintainable |
| Event Streams Quality trigger with `**` | Folder-level only — unusable |

There is no "Alarm Event" source type in the Event Streams source dropdown. The right answer is Ignition Alarms.

---

## Chapter 7: Quality Alarms — The Right Architecture

Ignition Alarms are designed for exactly this use case. Configure a quality alarm on each tag and it will:
- Know the exact tag path
- Know the transition time
- Know whether the alarm is acknowledged
- Survive Ignition restarts (written to the alarm journal)
- Route through an Alarm Notification Pipeline

### The architecture

```
Simulator --test
    → OPC UA tag goes Bad quality
        → QualityBad alarm activates on that tag
            → factory-quality-pipeline (Alarm Notification Pipeline)
                → Event Stream Source block
                    → factory-alarm-listener (Event Listener source Event Stream)
                        → Transform script
                            → Kafka Handler
                                → factory.quality topic
```

### Creating the alarm notification pipeline

In the Designer: **Alarming → Alarm Notification Pipelines → New Pipeline**. Name it `factory-quality-pipeline`.

Drag an **Event Stream Source** block from the pipeline blocks toolbar onto the canvas. Connect it to START. In the block properties, set the Event Stream dropdown to `factory-alarm-listener`.

No further blocks needed — the pipeline's job is to route alarm events into the Event Stream. The Event Stream handles the Kafka delivery.

### Creating the factory-alarm-listener Event Stream

**Config → Event Streams → Add Event Stream**

- Name: `factory-alarm-listener`
- Source type: **Event Listener** (not Tag Event)
- The Event Listener listens for events published by the alarm notification pipeline's Event Stream Source block

Enable the Transform stage and add the Kafka handler (details in Chapter 9).

---

## Chapter 8: Configuring Alarms on Every Tag

The pipeline from Chapter 7 needs each tag to have a `QualityBad` alarm that references `factory-quality-pipeline`. With 46 tags, clicking each one individually in the Designer is not realistic.

### The natural approach — and why it creates ghost tags

The obvious script:
```python
system.tag.configure("[default]", [{"path": "Factory/Assembly/CNC_01/PartCount", "alarms": [...]}], "m")
```

This silently creates a **root-level tag named `PartCount`** and stacks alarms on it. The real `[default]Factory/Assembly/CNC_01/PartCount` is untouched. With 3 machines each having a `PartCount` tag and multiple script runs, you end up with a root-level `PartCount` ghost tag with 34 alarms stacked on it.

If this happened: right-click the root-level ghost tag in the tag browser → Delete. It is not an OPC UA tag.

### Why it happens

`system.tag.configure("[default]", ...)` treats `[default]` as the base path. The `path` field in the config dict is then interpreted relative to that base — but it does not navigate to an existing nested tag. It creates a new tag at the given path under `[default]`.

### The correct pattern

`basePath` must be the **parent folder** of the tag, not `[default]`. Use `rfind("/")` to split:

```python
full_path = "[default]Factory/Assembly/CNC_01/PartCount"
idx    = full_path.rfind("/")
parent = full_path[:idx]    # "[default]Factory/Assembly/CNC_01"
name   = full_path[idx+1:]  # "PartCount"
system.tag.configure(parent, [{"name": name, "alarms": [alarm_config]}], "m")
```

### Other gotchas discovered

| Wrong | Correct | Effect of wrong value |
|-------|---------|----------------------|
| `"mode": "BadQuality"` | `"mode": "Bad Quality"` | silently does nothing — alarm not created |
| `"pipeline": "..."` | `"activePipeline": "..."` | field name wrong — alarm not routed to pipeline |
| project name omitted | `"ProjectName/PipelineName"` | pipeline not found |

And: `configure()` returning `[Good]` does not mean the alarm was applied. Always verify:
```python
check = system.tag.getConfiguration("[default]Factory/Assembly/CNC_01/PartCount", False)
print(check[0].get("alarms", "NONE"))
```

### Test the approach on one tag first

Before running the script on all 46 tags, verify the approach works on a single known tag:

```python
alarm_config = {
    "name": "QualityBad",
    "mode": "Bad Quality",
    "priority": "High",
    "activePipeline": "FactorySimulator_OPC_UA/factory-quality-pipeline"
}

result = system.tag.configure(
    "[default]Factory/Assembly/CNC_01",
    [{"name": "PartCount", "alarms": [alarm_config]}],
    "m"
)
print("Result:", result)
# Expected: [Good]

check = system.tag.getConfiguration("[default]Factory/Assembly/CNC_01/PartCount", False)
print("Alarm:", check[0].get("alarms", "NONE"))
# Expected: [{u'activePipeline': u'...', u'mode': Bad Quality, u'name': u'QualityBad', ...}]
```

If the alarm shows up — proceed to the bulk script. If it shows `NONE` despite `[Good]` result — check the field names (mode, activePipeline) and verify the pipeline name prefix matches your Ignition project name exactly.

### The working bulk alarm script

Run once in **Tools → Script Console**:

```python
alarm_config = {
    "name": "QualityBad",
    "mode": "Bad Quality",
    "priority": "High",
    "activePipeline": "FactorySimulator_OPC_UA/factory-quality-pipeline"
}

def collect_atomic_tags(path, results):
    for tag in system.tag.browse(path).getResults():
        tag_type  = str(tag["tagType"])
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
    parent = full_path[:idx]
    name   = full_path[idx+1:]
    result = system.tag.configure(parent, [{"name": name, "alarms": [alarm_config]}], "m")
    if result and str(result[0]) == "Good":
        count += 1
    else:
        errors.append((full_path, result))

print("Configured:", count, "tags")
if errors:
    print("Errors:", errors)
```

Expected output: `Found 46 tags` / `Configured: 46 tags`.

### Gateway Scheduled Script — auto-provision new tags

New devices added to the simulator get new tags with no alarms. A scheduled script handles this automatically.

**Designer → Tools → Gateway Scripts → Scheduled → Add Script**

| Field | Value |
|-------|-------|
| Name | `alarm-auto-configure` |
| CRON Minutes | `*/5` |

```python
alarm_config = {
    "name": "QualityBad",
    "mode": "Bad Quality",
    "priority": "High",
    "activePipeline": "FactorySimulator_OPC_UA/factory-quality-pipeline"
}

def collect_atomic_tags(path, results):
    for tag in system.tag.browse(path).getResults():
        tag_type  = str(tag["tagType"])
        full_path = str(tag["fullPath"])
        if tag_type == "AtomicTag":
            results.append(full_path)
        elif tag_type in ("Folder", "UdtInstance"):
            collect_atomic_tags(full_path, results)

all_tags = []
collect_atomic_tags("[default]Factory", all_tags)

for full_path in all_tags:
    check = system.tag.getConfiguration(full_path, False)
    if check and not check[0].get("alarms"):
        idx    = full_path.rfind("/")
        parent = full_path[:idx]
        name   = full_path[idx+1:]
        system.tag.configure(parent, [{"name": name, "alarms": [alarm_config]}], "m")
        system.util.getLogger("AlarmProvisioner").info("Added QualityBad alarm to " + full_path)
```

Publish with Ctrl+Shift+P. New tags get their alarm within 5 minutes of appearing.

---

## Chapter 9: Wiring the Alarm Pipeline to Kafka

With alarms configured and the pipeline in place, this chapter covers getting alarm events from Ignition into the `factory.quality` Kafka topic. This is where the most debugging time was spent.

### What arrives in the Transform

The `factory-alarm-listener` Transform receives a `PyEventPayload` Java object. Calling `dict(event.data)` converts the alarm event to a Python dict. A real event looks like:

```python
{
    'eventId':           '68afc44e-254a-4487-96bc-0257c251f146',
    'eventFlags':        0,
    'source':            'prov:default:/tag:Factory/Packaging/Packaging_Line_01/ConveyorSpeed_m_min:/alm:QualityBad',
    'displayPath':       '',
    'eventType':         2,
    'eventTypeReadable': 'Active, Unacknowledged',
    'priority':          3,
    'priorityReadable':  'High',
    'eventTime':         'Fri Jun 26 00:10:41 AEST 2026'
}
```

The `source` field follows the format `prov:{provider}:/tag:{tag_path}:/alm:{alarm_name}`. Parse it with:

```python
raw_source = str(data.get("source", ""))
tag_path   = raw_source.split("/tag:")[1].split(":/alm:")[0]
alarm_name = raw_source.split(":/alm:")[1]
```

### The working Transform script

```python
def transform(event, state):
    logger = system.util.getLogger("alarm-transform")
    try:
        data       = dict(event.data)
        raw_source = str(data.get("source", ""))

        tag_path = raw_source.split("/tag:")[1].split(":/alm:")[0] if "/tag:" in raw_source else raw_source
        alarm    = raw_source.split(":/alm:")[1]                   if ":/alm:" in raw_source else ""
        parts    = tag_path.split("/")   # ['Factory', 'Assembly', 'CNC_01', 'PartCount']

        return {
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
    except Exception as e:
        logger.error("Transform FAILED: " + str(e))
        return None
```

### Kafka handler configuration

| Field | Value | Notes |
|-------|-------|-------|
| Connector | `confluent-kafka` | same as other streams |
| Topic | `'factory.quality'` | single quotes required — see below |
| Key | *(leave blank)* | null key, round-robin partitioning |
| Value | `{event.data}` | the data field of the Transform result |

### Kafka handler gotchas — where hours were lost

**1. Topic expression syntax.** The Topic field is an **expression**, not a plain string. `factory.quality` (no quotes) is evaluated as "look up property `quality` on variable `factory`" — returns null — every message is silently dropped with no error. `'factory.quality'` (single-quoted string literal) is correct.

Compare with the working assembly_stream Kafka handler — it shows `'factory.assembly'` with single quotes. This is the pattern.

**2. Key expression failures.** Ignition's expression engine cannot navigate nested Python dicts via dot notation. After the Transform returns a Python dict, the handler expressions behave as follows:

| Expression | Result |
|-----------|--------|
| `{event.data}` | ✅ returns the `data` field of the Transform result |
| `{event.metadata.tagPath}` | ❌ `Missing element` error — dot notation fails on nested Python dicts |
| `{event.data.tag_path}` | ❌ same error |
| `'factory-alarm'` (static string) | ✅ works |
| *(blank)* | ✅ null key, Kafka distributes round-robin |

The `tag_path` is inside the value payload, so consumers can still identify the tag. Blank key is the correct choice here.

**3. `{event.data}` returns the entire Transform output dict.** In the handler context, `event` is the PyEventPayload wrapping whatever the Transform returned. `event.data` is the **full dict** the Transform returned — which is `{"metadata": {...}, "data": {...}}`. The Kafka message value therefore contains both the `metadata` and `data` keys. Downstream consumers should read from the `data` key.

**4. Kafka handler counting attempts, not confirmed deliveries.** The pipeline counter (e.g. "39") counts attempts sent to the Kafka handler, not messages confirmed received by Confluent. If the topic does not exist or the expression evaluates to null, all 39 are silently dropped. Always verify in the Confluent topic browser.

### Debugging the pipeline

**Add a Transform debug log:**

```python
def transform(event, state):
    logger = system.util.getLogger("alarm-transform")
    data = dict(event.data)
    logger.info("INPUT: " + str(data))
    # ... rest of transform ...
    logger.info("OUTPUT: " + str(result))
    return result
```

Check logs in **Config → Logs**, filter by `alarm-transform`. If you see OUTPUT lines but no Confluent messages, the bug is in the Kafka handler (topic expression, connector, or Key/Value fields). If you see no OUTPUT lines, the bug is upstream of the Transform (pipeline not firing, Event Listener source not connected).

**Add the Error Handler:**

```python
def onError(event, state):
    logger = system.util.getLogger("alarm-error")
    logger.error("Error count: " + str(len(event)))
    for item in event:
        logger.error("Error: " + str(item))
```

The error from a bad Topic expression looks like:
```
IllegalArgumentException: EventStreamExpression unable to extract String for 'key'
quality='Error_ExpressionEval("Missing element. path='event.metadata.tagPath'")'
```

The error from a bad Key expression looks like exactly the same thing with the failing path name.

### The working Confluent message

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

### What `system.kafka` is and why it does not exist

During early investigation, `print(dir(system.kafka))` was run in the Script Console expecting to find a Kafka producer API. It throws `AttributeError: 'com.inductiveautomation...' object has no attribute 'kafka'`. The Kafka Connector module does not expose a scripting namespace. The Event Stream Source block is the only supported path.

---

## Chapter 10: Reading the Story in Kafka

With all five streams flowing, the Kafka topics tell the complete factory story.

### The five streams

| Stream | Ignition source | Kafka topic | Partition key |
|--------|-----------------|-------------|---------------|
| assembly_stream | Tag Event / Value | `factory.assembly` | tag path |
| energy_stream | Tag Event / Value | `factory.energy` | tag path |
| packaging_stream | Tag Event / Value | `factory.packaging` | tag path |
| process_stream | Tag Event / Value | `factory.process` | tag path |
| factory-alarm-listener | Event Listener (alarm pipeline) | `factory.quality` | null (round-robin) |

### Correlating across topics

The joining signal is `SupplyFactor_pct` in `factory.packaging`. When this drops:

1. Find the timestamp in `factory.packaging` where `tag=SupplyFactor_pct` starts falling
2. Look in `factory.assembly` at the same timestamp — find which machine's `State` changed to FAULT or IDLE
3. Look in `factory.energy` — the corresponding meter's `ActivePower_kW` should show the same dip
4. Look in `factory.quality` — if the fault was preceded by a Bad quality alarm, the fault was a sensor/quality failure, not a mechanical one

This is the digital twin replay loop: given an OEE anomaly, trace back through Kafka to find the root cause device and whether the alarm pipeline caught it before the OEE impact was visible.

### Retention strategy

| Topic | Recommended retention | Reason |
|-------|-----------------------|--------|
| `factory.assembly` | 7 days | high volume, rolling window is enough |
| `factory.energy` | 7 days | same |
| `factory.process` | 7 days | same |
| `factory.packaging` | 7 days | same |
| `factory.quality` | 30 days | low volume, longer history useful for correlating recurring faults |

### What to build next

- A **Flink or Kafka Streams job** that joins `factory.quality` events with `factory.assembly` state changes within a 30-second window — outputs a "fault with preceding quality degradation" event
- A **TimescaleDB sink** for time-series queries: "show me CNC_01 ToolWear_pct and Main_Meter ActivePower_kW on the same axis for the last 24 hours"
- A **Grafana dashboard** consuming from TimescaleDB showing OEE, SupplyFactor, and quality alarm count side by side
- A **Python consumer** that subscribes to `factory.quality` and posts to Slack when a High priority alarm has been active for more than 5 minutes without acknowledgement
