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

### 4. Left-Button Drag Preview For File List
- Detect hovered file row in `_on_mouse_move` using rectangle hit-test.
- If left button is down, preview the row under cursor.
- Keep throttled preview responsive:
  - Store newest target in `pending_drag_preview` while inside interval.
  - On every mouse-move tick, if interval has elapsed, flush `pending_drag_preview` immediately.
- On left release, call `_finalize_drag_preview_selection` to exit preview mode and load full asset metadata.

### 5. Middle-Button Drag Scroll
- Map mouse Y-delta to container scroll Y.
- Mapping: `drag up => scroll moves list down`, `drag down => scroll moves list up`.

## Crash Prevention Checklist

1. Ensure no `executor.submit(...)` targets call `dpg.*`.
2. Ensure `drag_preview_active` is explicitly set to `False` before final `on_file_click` to trigger full data loading.
3. Always check `dpg.does_item_exist(tag)` before `delete_item` or `configure_item`.
4. Run syntax check after modification:
```bash
python -m py_compile src/ui/main_window.py
```

## Resource Scope
Procedural guidance for Dear PyGui stability. Applicable to any project using DPG for data-heavy browsing.
