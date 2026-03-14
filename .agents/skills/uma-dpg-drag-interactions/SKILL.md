---
name: uma-dpg-drag-interactions
description: Stabilize and implement drag-heavy and high-frequency Dear PyGui interactions in Uma Viewer. Use when implementing or fixing drag-preview, texture flicker, keyboard navigation with auto-scroll, or high-speed list hit-testing.
---

# Uma Dpg Drag Interactions & UI Optimization

## Overview

Implement robust drag and high-frequency UI interactions for `src/ui/main_window.py` without breaking stability or causing visual jitter. 
Prioritize predictable hit-testing, low flicker, and smooth automated scrolling in Dear PyGui (DPG).

## Core Rules

1. **Main Thread Only**: Keep all `dpg.*` UI mutations on the main thread.
2. **Surgical Updates**: Avoid `delete_item(..., children_only=True)` on common containers during high-frequency updates. Instead, use stable `tag` IDs for critical UI elements (like image headers or loading text) and only replace the dynamic content.
3. **Texture Registry Safety**: Always `add_static_texture` new textures before deleting old ones to prevent "white flash" during rapid switching.
4. **Hit-Testing Performance**: For large lists, scan items in **reverse** order and perform fast-path coordinate checks before expensive `is_item_visible` calls.
5. **Keyboard as Drag**: Treat keyboard navigation (j/k, arrows) like a "drag preview":
    - **Press/Hold**: Enter `drag_preview_active` mode (lightweight rendering).
    - **Release**: Finalize selection (load full details/dependencies).

## Patterns To Reuse

### 1. Zero-Flicker Texture Preview
- Use a persistent `image_container_tag` for the preview area.
- Perform expensive conversions (e.g., `tolist()`, `np.ravel()`) in a **background thread**.
- In `_apply_texture_preview_result`:
    1. Check `request_id` and `asset_id` to ensure response is still valid.
    2. Add the new texture to the registry.
    3. If an old `image_tag` exists, delete it surgically.
    4. Add the new `dpg.add_image` using a fixed `image_tag`.
    5. **Only then** delete the old texture from the registry.

### 2. Sibling-Based Keyboard Navigation
- When a file is selected (`last_selected`), navigate using its siblings.
- Filter siblings using `self.file_item_data` to ensure we only jump between valid file entries.
- Use `dpg.get_item_parent(self.last_selected)` to find the container dynamically, supporting both tree nodes and flat search lists.

### 3. Automated Follow-Scroll
- Since DPG/ImGui doesn't always auto-scroll to focused items in nested layouts:
- First, try `dpg.focus_item(item)` as a native hint to the engine.
- Second, perform manual calculation in `_scroll_to_item`:
    - Compare `get_item_rect_min/max(item)` with `get_item_rect_min/max(container)`.
    - Apply a buffer (e.g., 40px) to ensure the item isn't partially cut off.
    - Use `dpg.set_y_scroll(container, ...)` with the calculated delta.

### 4. Robust Drag Preview (Left-Button)
- **ID Normalization**: Always convert `dpg.get_value("tabs")` (which might be an `int`) to a `str` tag alias using `dpg.get_item_alias`.
- **Throttled Hit-Test**:
    - Use a recursive search for nested containers.
    - **Brute-Force Fallback**: If recursive search fails (often due to slot mismatches), iterate through `file_item_data` keys and check `dpg.get_item_rect_min/max`.
- **Balanced Rendering**: Skip heavy UI updates (like full dependency tables or 3D scene loads) during `drag_preview_active` mode. Only update high-impact labels and textures.

### 5. Middle-Button Drag Scroll
- Map mouse Y-delta to container scroll Y.
- Mapping: `drag up => scroll moves list down`, `drag down => scroll moves list up`.

## Crash Prevention Checklist

1. **Async Safety**: Ensure no `executor.submit(...)` targets call `dpg.*`.
2. **Mode Cleanup**: Ensure `drag_preview_active` is explicitly set to `False` before final `on_file_click` to trigger full data loading.
3. **Existence Check**: Always check `dpg.does_item_exist(tag)` before `delete_item` or `configure_item`.
4. **Resampling**: Use `BILINEAR` for fast previews and `LANCZOS` only for final exports to keep the UI responsive.
5. Run syntax check after modification:
```bash
python -m py_compile src/ui/main_window.py
```

## Resource Scope
Procedural guidance for Dear PyGui stability. Applicable to any project using DPG for data-heavy browsing.
