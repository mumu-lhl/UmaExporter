---
name: uma-dpg-scene-auto-preview-debug
description: Fix and debug Scene-page Animator auto-preview issues in Uma Viewer Dear PyGui UI. Use when Scene file click should auto-preview first Animator but does not trigger, triggers inconsistently, or is blocked by async/UI state races.
---

# Uma Dpg Scene Auto Preview Debug

## Scope

Use this skill for `src/ui/main_window.py` when:
- Scene file click should auto-preview an `Animator`.
- Auto-preview works for some files but not others.
- Behavior differs between manual click and auto-trigger.

## Required Behavior

1. In Scene context, if at least one `Animator` exists, auto-preview the first found `Animator`.
2. Do not require "only one Animator".
3. Reuse the same preview path as manual Animator click (`on_unity_obj_click` -> `on_animator_preview_click`).

## Common Failure Modes

1. **Scene context detection is wrong**  
Do not rely only on `dpg.get_value("main_tabs") == "scene_tab"` because tab value may be numeric item id.
Prefer:
- `sender` tag prefix check (`scene_item_...`) OR
- resolve alias from numeric id (`dpg.get_item_alias(active_tab)`).

2. **Async stale results overwrite or skip**  
Use request version checks (`selection_request_id`) before applying async Unity object results.

3. **Animator row not rendered in table**  
If Unity object list UI is truncated (for example first 200 rows), auto-preview must still run.
If selectable tag does not exist, call `on_unity_obj_click(sender=None, ...)` and ensure handler supports `sender=None`.

4. **Trigger blocked by drag-preview mode**  
Scene auto Animator preview should run for normal click, not drag-preview.

## Implementation Pattern

1. Arm scene auto-preview request at file click with:
- `asset_id`
- `request_id`

2. In Unity objects async result callback:
- verify `request_id` matches current.
- verify selected asset is unchanged.
- find first `Animator`.
- call `on_unity_obj_click` with:
  - real selectable tag if exists; otherwise `None`.
  - user_data `(phys_path, path_id, "Animator", "scene_")`.

3. In `on_unity_obj_click`, guard sender operations:
- Toggle branch should require `sender` truthy.
- Selection write (`dpg.set_value(sender, True)`) should run only if sender exists.

## Minimal Debug Logs

When debugging, add logs with one prefix (for example `[AUTO_PREVIEW]`):
- file click: asset id, tab raw value, sender, drag flag, request id.
- scene request armed/skipped.
- unity async result: request ids, object count, stale reason.
- animator detection: count, first path_id, sender_exists.
- dispatch confirmation.
- animator preview click entry.

Remove or reduce logs after fix confirmation.

## Validation Checklist

1. Scene click on files with Animator always auto-previews first Animator.
2. Scene click on files without Animator does not auto-preview.
3. Manual Animator click still works.
4. Back/Forward navigation does not break auto-preview logic.
5. Compile check:

```bash
python3 -m compileall -q src
```
