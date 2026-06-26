# BUG-02: system.tag.configure() returns [Good] when alarm config fields are invalid, without applying the alarm

**Product:** Ignition 8.x — Tag configuration scripting API (`system.tag.configure`)  
**Severity:** Medium — silent failure; developer gets false success signal  
**Reproducibility:** 100%

---

## Summary

`system.tag.configure()` in merge (`"m"`) mode returns `[Good]` when the alarm configuration dict contains unrecognized or incorrectly named fields. The alarm is not created, not updated, and not applied to the tag. There is no error, no warning, and no indication in the return value that the alarm config was ignored.

---

## Steps to Reproduce

Run the following in the Script Console:

```python
# WRONG field names
alarm_config_wrong = {
    "name":     "QualityBad",
    "mode":     "BadQuality",       # wrong — missing space
    "priority": "High",
    "pipeline": "MyProject/my-pipeline"  # wrong field name — should be "activePipeline"
}

result = system.tag.configure(
    "[default]Factory/Assembly/CNC_01",
    [{"name": "PartCount", "alarms": [alarm_config_wrong]}],
    "m"
)
print("Result:", result)
# Prints: Result: [Good]

# Verify the alarm was NOT applied:
check = system.tag.getConfiguration("[default]Factory/Assembly/CNC_01/PartCount", False)
print("Alarms:", check[0].get("alarms", "NONE"))
# Prints: Alarms: NONE
```

**Expected:** `configure()` should return an error status, or raise an exception, or at minimum return a warning that the alarm config contained unknown fields.  
**Actual:** Returns `[Good]`. `getConfiguration()` shows no alarm was applied.

---

## Field names that are affected

| Wrong field name | Correct field name | Effect if wrong |
|------------------|--------------------|-----------------|
| `"mode": "BadQuality"` | `"mode": "Bad Quality"` (space required) | alarm silently not created |
| `"pipeline": "..."` | `"activePipeline": "..."` | alarm not routed to pipeline |

Both mistakes return `[Good]` with no indication of failure.

---

## Impact

A developer running a bulk alarm configuration script across 46+ tags gets output like:

```
Configured: 46 tags
```

...and reasonably concludes all alarms were applied. In fact, none were. The pipeline never fires when a tag quality goes Bad, quality events never reach Kafka, and alerts never trigger. The failure mode is silent and the false-success return value actively misleads.

In this factory simulator project, this cost significant debugging time — specifically because the success return value (`[Good]`) made us look at the pipeline, the Event Stream, and the Kafka connector rather than the alarm config itself.

---

## Correct alarm configuration (for reference)

```python
alarm_config = {
    "name":           "QualityBad",
    "mode":           "Bad Quality",         # space is required
    "priority":       "High",
    "activePipeline": "ProjectName/PipelineName"  # "activePipeline", not "pipeline"
}
```

Verify after every configure() call:
```python
check = system.tag.getConfiguration(full_path, False)
assert check[0].get("alarms"), "Alarm was not applied despite [Good] result"
```

---

## Environment

- Ignition version: 8.x (confirmed on 8.3.x)
- Scripting API: `system.tag.configure(basePath, tagConfigs, collisionPolicy)`

---

## Suggested Fix

1. Validate alarm config field names against the known schema before applying. Unknown fields should produce a warning in the return value (e.g., `[Good (warnings: unknown alarm field 'pipeline')]`).
2. The `"mode"` field value should either be validated against the allowed values list (`"Bad Quality"`, `"AboveSetpoint"`, etc.) at configure time, or the API should document clearly that the string must match the UI label exactly including spaces.
3. At minimum, document in the SDK reference that `[Good]` does not guarantee the alarm was applied — and recommend always verifying with `getConfiguration()`.
