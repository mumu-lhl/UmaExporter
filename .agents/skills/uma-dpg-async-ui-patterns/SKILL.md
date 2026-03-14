---
name: uma-dpg-async-ui-patterns
description: Guidelines for high-performance asynchronous UI updates in Dear PyGui. Use when handling large data (textures, database results) to prevent main-thread blocking, flickering, or state race conditions.
---

# Uma DPG Async UI Patterns & State Safety

## Overview

Dear PyGui (DPG) is highly sensitive to main-thread blocking, especially when converting large Python objects (like lists of 4M+ floats for textures). This skill provides patterns to off-load processing to background threads while maintaining UI stability and state consistency.

## Core Rules

1. **Calculations in Workers**: All data conversions (`np.ravel()`, `tolist()`, `PIL.Image.resize`) MUST happen inside the `ThreadPoolExecutor` worker. The main thread should only receive the final "ready-to-consume" list or value.
2. **Request ID Fencing**: Every asynchronous UI request (thumbnail, texture load, search) must increment a `request_id` for its specific domain (e.g., `self.app.thumbnail_request_ids[prefix]`).
3. **Validation at Callback**: UI callbacks MUST verify that the `request_id` still matches the current application state before modifying any `dpg` items.
4. **Atomic Texture Registry Updates**: Always follow the "Add-Widget-Then-Delete-Old-Texture" pattern to prevent white flashes or crashes caused by missing resources.

## Patterns To Reuse

### 1. The "Off-Main-Thread" Data Pipeline
- **Problem**: `dpg.add_static_texture` is fast, but passing a 4MB Python list to it causes a "hitch" while DPG parses the list.
- **Solution**:
    1. Worker: Extract texture -> Resize (`BILINEAR`) -> `data.astype(np.float32) / 255.0` -> **`.tolist()`**.
    2. Callback: `self.app._queue_ui_task(lambda: self._apply(data_list))`
    3. UI Task: `dpg.add_static_texture(default_value=data_list, ...)`

### 2. Request ID Fencing (The Guard Pattern)
- **Implementation**:
    ```python
    # 1. Trigger
    self.app.thumbnail_request_ids[prefix] += 1
    req_id = self.app.thumbnail_request_ids[prefix]
    self.app.executor.submit(worker, req_id)

    # 2. Callback (Main Thread)
    def apply_result(req_id, data):
        if req_id != self.app.thumbnail_request_ids.get(prefix):
            return # Request is stale, user already clicked something else
        # Proceed with UI update...
    ```

### 3. Safe State Inspection
- **Rule**: When checking if an asset is "still selected" in a callback, always check the **global application state** (usually `self.app.current_asset_hash` or `self.app.current_asset_id`) rather than local controller attributes.
- **Verification**: Use `hasattr(self.app, 'attr')` to ensure the core state exists before comparison.

### 4. Texture Lifecycle Management
To avoid memory leaks in the `texture_registry` and visual flickering:
1. Generate unique tag for new texture: `f"tex_{int(time.time()*1000)}"`.
2. Add new texture to registry.
3. Update `dpg.add_image` or `dpg.configure_item` with the new tag.
4. Call a cleanup helper (e.g., `_clear_previous_texture`) to delete the **old** tag from the registry.

## Performance Checklist

- [ ] Are all `tolist()` or `ravel()` calls inside the worker thread?
- [ ] Is `BILINEAR` resampling used for transient previews?
- [ ] Does the callback verify a domain-specific `request_id`?
- [ ] Is the `texture_lock` (if applicable) held for the minimum time possible?
- [ ] Are old textures explicitly deleted from the registry to prevent VRAM growth?

## Resource Scope
Architecture for maintainable async UI logic in Python-based Dear PyGui applications.
