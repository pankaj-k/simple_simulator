# BUG-03: system.tag.configure() with [default] basePath and nested path creates a ghost root-level tag instead of updating the existing tag

**Product:** Ignition 8.x — Tag configuration scripting API (`system.tag.configure`)  
**Severity:** Medium — causes tag namespace pollution; existing tags are silently left unchanged  
**Reproducibility:** 100%

---

## Summary

When `system.tag.configure()` is called with `"[default]"` as the `basePath` and a `"path"` field inside the tag config dict that points to a nested tag, the function does **not** navigate to the existing nested tag. Instead it silently creates a **new root-level tag** with the leaf name and stacks the configuration (e.g., alarms) onto that ghost tag. The real nested tag under `[default]Factory/Assembly/CNC_01/PartCount` is untouched. The function returns `[Good]`.

---

## Steps to Reproduce

```python
alarm_config = {
    "name":           "QualityBad",
    "mode":           "Bad Quality",
    "priority":       "High",
    "activePipeline": "MyProject/my-pipeline"
}

# WRONG — using [default] as basePath with a nested path field
result = system.tag.configure(
    "[default]",
    [{"path": "Factory/Assembly/CNC_01/PartCount", "alarms": [alarm_config]}],
    "m"
)
print("Result:", result)
# Prints: Result: [Good]

# Check the intended tag — alarm was NOT applied
intended = system.tag.getConfiguration("[default]Factory/Assembly/CNC_01/PartCount", False)
print("Intended tag alarms:", intended[0].get("alarms", "NONE"))
# Prints: NONE

# Check the root level — a ghost tag was created here
ghost = system.tag.getConfiguration("[default]PartCount", False)
print("Ghost tag alarms:", ghost[0].get("alarms", "NONE"))
# Prints: [{... the alarm ...}]
```

**Expected:** The call with `"path": "Factory/Assembly/CNC_01/PartCount"` should navigate to the existing tag at that path and merge the alarm config into it.  
**Actual:** A new tag named `PartCount` is created at the root of `[default]`. Running the script multiple times stacks duplicate alarms on the ghost tag (observed: 34 stacked alarms on a single ghost tag after multiple runs). The real tag at `[default]Factory/Assembly/CNC_01/PartCount` is untouched.

---

## The ghost tag accumulation problem

Running the wrong script twice or more stacks alarms on the ghost tag:
- Run 1: ghost tag `[default]PartCount` has 1 alarm
- Run 2: ghost tag `[default]PartCount` has 2 alarms
- Run 10: ghost tag `[default]PartCount` has 10 alarms (observed: 34 after many runs)

The ghost tag is not connected to the OPC UA server. It is a standalone memory tag at the root level. It is easy to miss in the tag browser if you are not looking for it.

**To remove the ghost tag:** right-click it in the tag browser → Delete. It is safe to delete — it is not the OPC UA tag.

---

## Correct pattern

`basePath` must be the **direct parent folder** of the tag, not `[default]`. Use `rfind("/")` to split the full path:

```python
full_path = "[default]Factory/Assembly/CNC_01/PartCount"
idx    = full_path.rfind("/")
parent = full_path[:idx]    # "[default]Factory/Assembly/CNC_01"
name   = full_path[idx+1:]  # "PartCount"

result = system.tag.configure(
    parent,                                   # ← parent folder, not [default]
    [{"name": name, "alarms": [alarm_config]}],  # ← "name", not "path"
    "m"
)
```

Note also: when using the direct parent as `basePath`, the key in the tag config dict is `"name"` (just the leaf name), not `"path"`. Using `"path"` with a nested string when the basePath is the parent folder may have unpredictable results.

---

## Impact

Anyone following the intuitive pattern of passing `"[default]"` as basePath and a full nested path in the config dict will silently fail to configure their target tags — while believing they succeeded (return value is `[Good]`). In a bulk-configuration scenario (46 tags), 46 ghost root-level tags are silently created and 46 real tags remain unconfigured.

---

## Environment

- Ignition version: 8.x (confirmed on 8.3.x)
- Scripting API: `system.tag.configure(basePath, tagConfigs, collisionPolicy)`

---

## Suggested Fix

1. If the `"path"` field in a tag config dict contains path separators (`/`) and `basePath` is `"[default]"`, the API should navigate to the existing tag at that full path rather than creating a new root-level tag.
2. If the navigation is intentionally not supported (i.e., basePath + leaf name is the only supported mode), the API should raise an error or warning when `"path"` contains a `/` — rather than creating an unintended new tag.
3. The SDK documentation for `system.tag.configure()` should include an explicit example showing that `basePath` must be the parent folder and that the config dict uses `"name"` (not `"path"`) for atomic tags in merge mode.
