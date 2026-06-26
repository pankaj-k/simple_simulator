# BUG-01: Editing any part of an Event Stream silently clears the Source tag path subscription

**Product:** Ignition 8.x — Event Streams module  
**Severity:** High — causes silent data loss in production pipelines  
**Reproducibility:** 100% — confirmed repeatedly across multiple streams

---

## Summary

Editing **any** part of a running Event Stream (Transform script, Error Handler, Kafka handler fields — anything) silently clears the Source block's tag path subscription on save. The stream continues to report "Event Stream running" with no errors, but `Events Received` drops to 0 and never recovers. No warning is shown. No log entry is written.

---

## Steps to Reproduce

1. Create an Event Stream with Source type **Tag Event**.
2. In the Source block, enter a tag path: `[default]Factory/Assembly/**`
3. Save and enable. Confirm events are flowing (Events Received counter increments).
4. Open the stream again and edit **only the Error Handler** script — no change to the Source block.
5. Save.

**Expected:** Events continue flowing. Source path is unchanged.  
**Actual:** `Events Received` drops to 0 immediately. Source block is blank.

---

## Confirming the cause

Create a second (test) Event Stream with the same tag path and no handler. If it starts receiving events within seconds, the infrastructure is fine — the silent path clear is confirmed as the only cause.

Also confirmed:
- Gateway restart does **not** fix it
- Disable → Enable on the stream does **not** fix it
- The only fix is re-entering the tag path in the Source block and saving

---

## Impact

Any edit to an Event Stream — including adding an Error Handler for the first time, or fixing a Transform bug — silently kills all data flow from that stream. Because the stream status remains green and no error is logged, a user can go hours or days without realizing the stream is delivering nothing to Kafka.

In this factory simulator project, this bug caused all four value streams (`assembly_stream`, `energy_stream`, `process_stream`, `packaging_stream`) to go dead simultaneously after each Error Handler was added. Each stream required a separate fix (re-enter source path) because the save applied per-stream.

---

## Environment

- Ignition version: 8.x (confirmed on 8.3.x)
- Event Streams module: installed from Inductive Automation module marketplace
- Kafka Connector module: installed
- OS: Windows 11

---

## Workaround

Before editing any Event Stream, note down the exact Source tag path(s). After saving any change, immediately click the Source block and verify the path is still present. If it is blank, re-enter it.

**Preventive check script for the Script Console:**

```python
# Run after any Event Stream edit to verify sources are still populated
# (No scripting API for Event Streams exists; this is a manual check reminder only)
# Check: Config → Event Streams → click each stream → click Source block → verify path is non-empty
```

---

## Suggested Fix

When saving any part of an Event Stream (Transform, Handler, Error Handler), the Source configuration should be read back from the current UI state before persisting, not re-serialized from an in-memory representation that may have lost the source path. Alternatively, the save operation should validate that a Tag Event source block still has a non-empty tag path and warn the user before saving if it is blank.

At minimum: if the Source block is blank after a save, show a warning: "Event Stream has no source — events will not be received."
