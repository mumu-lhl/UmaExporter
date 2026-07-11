import time

import dearpygui.dearpygui as dpg


class DragController:
    def __init__(self, app):
        self.app = app

    def _on_mouse_move(self, *args):
        # Fallback initialization for middle-drag
        if dpg.is_mouse_button_down(dpg.mvMouseButton_Middle):
            if not self.app.middle_drag_active:
                self._on_middle_mouse_down()

        is_left_down = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)

        if not is_left_down:
            self.app.last_drag_preview_item = None
            self.app.pending_drag_preview = None
            self.app.last_tab_drag_switch_target = None
            return

        self._update_left_scrollbar_drag_state()

        # A scrollbar drag must remain a pure scrolling gesture even if the
        # pointer slips left over an item while the button is still held.
        if self.app.left_scrollbar_drag_active:
            return

        self._handle_tab_drag_switch()
        now = time.monotonic()
        if now - self.app.last_hover_scan_time < self.app.hover_scan_interval:
            return
        self.app.last_hover_scan_time = now

        hovered_item = self._pick_file_item_under_mouse()

        if not hovered_item:
            return

        if hovered_item == self.app.last_drag_preview_item:
            return

        file_data = self.app.file_item_data.get(hovered_item)
        if not file_data:
            return

        if self.app.current_asset_id == file_data.get("id"):
            self.app.last_drag_preview_item = hovered_item
            return

        self.app.last_drag_preview_item = hovered_item
        self._select_drag_item(hovered_item)
        if now - self.app.last_drag_preview_time < self.app.drag_preview_interval:
            self.app.pending_drag_preview = (hovered_item, file_data)
            return

        self._trigger_drag_preview(hovered_item, file_data)

    def _on_left_mouse_down(self, *args):
        if self.app.left_mouse_gesture_active:
            return
        self.app.left_mouse_gesture_active = True
        self.app.left_drag_preview_occurred = False
        # Do not classify the gesture from a synthetic scrollbar rectangle.
        # Selectable rows and the child-window scrollbar can overlap in DPG's
        # reported item rectangles, which caused ordinary row drags to be
        # locked out as scrollbar drags.  The gesture is promoted to a pure
        # scrollbar drag below only after the container actually scrolls.
        self.app.left_scrollbar_drag_active = False
        target = self._pick_scroll_target_under_mouse()
        self.app.left_scroll_candidate_target = target
        try:
            self.app.left_scroll_candidate_y = (
                dpg.get_y_scroll(target) if target else None
            )
        except Exception:
            self.app.left_scroll_candidate_y = None

    def _update_left_scrollbar_drag_state(self):
        if self.app.left_scrollbar_drag_active:
            return
        target = self.app.left_scroll_candidate_target
        start_y = self.app.left_scroll_candidate_y
        if not target or start_y is None or not dpg.does_item_exist(target):
            return
        try:
            if abs(dpg.get_y_scroll(target) - start_y) > 0.5:
                self.app.left_scrollbar_drag_active = True
                self.app.pending_drag_preview = None
        except Exception:
            pass

    def _trigger_drag_preview(self, item, file_data):
        now = time.monotonic()
        prev_nav_state = self.app.is_navigating
        prev_drag_state = self.app.drag_preview_active
        self.app.is_navigating = True
        self.app.drag_preview_active = True
        self.app.left_drag_preview_occurred = True
        try:
            self.app.on_file_click(item, None, file_data)
        finally:
            self.app.is_navigating = prev_nav_state
            self.app.drag_preview_active = prev_drag_state
            self.app.last_drag_preview_time = now

    def process_pending_drag_preview(self):
        if (
            not self.app.pending_drag_preview
            or self.app.left_scrollbar_drag_active
            or not dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
            or time.monotonic() - self.app.last_drag_preview_time
            < self.app.drag_preview_interval
        ):
            return

        item, file_data = self.app.pending_drag_preview
        self.app.pending_drag_preview = None
        if (
            dpg.does_item_exist(item)
            and self.app.current_asset_id != file_data.get("id")
        ):
            self._trigger_drag_preview(item, file_data)

    def _select_drag_item(self, item):
        previous = self.app.last_selected
        if previous == item:
            return
        try:
            if previous and dpg.does_item_exist(previous):
                previous_type = dpg.get_item_type(previous)
                if "mvSelectable" in previous_type:
                    dpg.set_value(previous, False)
                elif "mvImage" in previous_type:
                    dpg.configure_item(
                        previous, tint_color=[255, 255, 255, 255]
                    )
            if dpg.does_item_exist(item):
                item_type = dpg.get_item_type(item)
                if "mvSelectable" in item_type:
                    dpg.set_value(item, True)
                elif "mvImage" in item_type:
                    dpg.configure_item(item, tint_color=[150, 200, 255, 255])
                self.app.last_selected = item
        except Exception:
            pass

    def _on_middle_mouse_down(self, *args):
        if self.app.middle_drag_active:
            return

        target = self._pick_scroll_target_under_mouse()
        if not target:
            return

        self.app.middle_drag_active = True
        self.app.middle_drag_target = target
        self.app.middle_drag_start_mouse_y = dpg.get_mouse_pos(local=False)[1]
        try:
            self.app.middle_drag_start_scroll_y = dpg.get_y_scroll(target)
        except Exception:
            self.app.middle_drag_start_scroll_y = 0

    def _on_middle_mouse_drag(self, *args):
        if not self.app.middle_drag_active or not self.app.middle_drag_target:
            return

        # Guard against uninitialized start values if events arrive out of order
        mouse_y = dpg.get_mouse_pos(local=False)[1]
        if self.app.middle_drag_start_mouse_y is None:
            self.app.middle_drag_start_mouse_y = mouse_y
            try:
                self.app.middle_drag_start_scroll_y = dpg.get_y_scroll(
                    self.app.middle_drag_target
                )
            except Exception:
                self.app.middle_drag_start_scroll_y = 0
            return

        total_dy = mouse_y - self.app.middle_drag_start_mouse_y

        target = self.app.middle_drag_target
        if not dpg.does_item_exist(target) or not dpg.is_item_shown(target):
            return

        try:
            max_scroll = dpg.get_y_scroll_max(target)
            # UX rule: drag up => results move down, drag down => results move up.
            scroll_delta = -total_dy * self.app.middle_drag_speed
            new_scroll = max(
                0.0, min(max_scroll, self.app.middle_drag_start_scroll_y + scroll_delta)
            )
            dpg.set_y_scroll(target, new_scroll)
        except Exception:
            pass

    def _on_middle_mouse_release(self, *args):
        self.app.middle_drag_active = False
        self.app.middle_drag_target = None
        self.app.middle_drag_start_mouse_y = None
        self.app.middle_drag_start_scroll_y = None

    def _on_left_mouse_release(self, *args):
        self.app.left_mouse_gesture_active = False
        self.app.left_scroll_candidate_target = None
        self.app.left_scroll_candidate_y = None
        if self.app.left_scrollbar_drag_active:
            self.app.left_scrollbar_drag_active = False
            self.app.last_drag_preview_item = None
            self.app.pending_drag_preview = None
            self.app.last_tab_drag_switch_target = None
            self.app.left_drag_preview_occurred = False
            return

        self.app.left_scrollbar_drag_active = False
        if self.app.left_drag_preview_occurred:
            self._finalize_drag_preview_selection()
        self.app.left_drag_preview_occurred = False
        self.app.last_drag_preview_item = None
        self.app.pending_drag_preview = None
        self.app.last_tab_drag_switch_target = None

    def _finalize_drag_preview_selection(self):
        if not self.app.current_view_is_drag_preview or not self.app.current_asset_data:
            return

        # Prefer the last hovered drag target (possibly throttled) at mouse release.
        final_data = self.app.current_asset_data
        final_item = None
        if self.app.pending_drag_preview:
            pending_item, pending_data = self.app.pending_drag_preview
            if dpg.does_item_exist(pending_item) and pending_data:
                final_data = pending_data
                final_item = pending_item
        else:
            hovered_item = self._pick_file_item_under_mouse()
            hovered_data = (
                self.app.file_item_data.get(hovered_item) if hovered_item else None
            )
            if hovered_data:
                final_data = hovered_data
                final_item = hovered_item

        prev_nav_state = self.app.is_navigating
        self.app.is_navigating = True
        self.app.drag_preview_active = False
        try:
            sender_item = None
            if (
                final_item
                and dpg.does_item_exist(final_item)
                and self.app.file_item_data.get(final_item, {}).get("id")
                == final_data.get("id")
            ):
                sender_item = final_item
            self.app.on_file_click(sender_item, None, final_data)
        finally:
            self.app.is_navigating = prev_nav_state
            # self.app.drag_preview_active is intentionally left as False here
            # because the mouse release terminates the drag preview session.

    def _pick_scroll_target_under_mouse(self):
        mouse_pos = dpg.get_mouse_pos(local=False)

        # 1. Determine active tab tag robustly
        active_tab = dpg.get_value("main_tabs")
        if active_tab and not isinstance(active_tab, str):
            try:
                # DPG sometimes returns integer IDs even if aliases exist
                alias = dpg.get_item_alias(active_tab)
                if alias:
                    active_tab = alias
            except:
                pass

        if not active_tab and dpg.does_alias_exist("main_tabs"):
            # Fallback if value is None
            active_tab = "home_tab"  # Default

        # 2. Determine priority candidates based on the active tab and state
        candidates = []
        if active_tab == "home_tab":
            if dpg.is_item_shown("search_group"):
                candidates = ["search_results", "home_details_scroll"]
            else:
                candidates = ["home_browse_scroll", "home_details_scroll"]
        elif active_tab == "scene_tab":
            scene_container = (
                "scene_thumbnails_parent"
                if self.app.scene_view_mode == "thumbnail"
                else "scene_results_parent"
            )
            candidates = [scene_container, "scene_details_scroll"]
        elif active_tab == "prop_tab":
            prop_container = (
                "prop_thumbnails_parent"
                if self.app.prop_view_mode == "thumbnail"
                else "prop_results_parent"
            )
            candidates = [prop_container, "prop_details_scroll"]

        # 3. Precise rect-based hit testing
        for tag in candidates:
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
                try:
                    # Use a small buffer to ensure we're strictly inside
                    mi = dpg.get_item_rect_min(tag)
                    ma = dpg.get_item_rect_max(tag)
                    if (
                        mi[0] <= mouse_pos[0] <= ma[0]
                        and mi[1] <= mouse_pos[1] <= ma[1]
                    ):
                        return tag
                except Exception:
                    continue

        # 4. Fallback: If precise hit-test fails but we're in a known tab,
        # use the left-most visible container as the most likely target.
        if active_tab == "home_tab":
            if dpg.is_item_shown("search_group"):
                return "search_results"
            return "home_browse_scroll"
        elif active_tab == "scene_tab":
            return (
                "scene_thumbnails_parent"
                if self.app.scene_view_mode == "thumbnail"
                else "scene_results_parent"
            )
        elif active_tab == "prop_tab":
            return (
                "prop_thumbnails_parent"
                if self.app.prop_view_mode == "thumbnail"
                else "prop_results_parent"
            )

        return None

    def _handle_tab_drag_switch(self):
        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        target_tab = None
        for tab_tag in [
            "home_tab",
            "scene_tab",
            "prop_tab",
            "actions_tab",
            "settings_tab",
        ]:
            if not dpg.does_item_exist(tab_tag) or not dpg.is_item_shown(tab_tag):
                continue
            try:
                min_x, min_y = dpg.get_item_rect_min(tab_tag)
                max_x, max_y = dpg.get_item_rect_max(tab_tag)
                if min_x <= mouse_x <= max_x and min_y <= mouse_y <= max_y:
                    target_tab = tab_tag
                    break
            except Exception:
                continue

        if not target_tab:
            return
        if target_tab == self.app.last_tab_drag_switch_target:
            return
        if dpg.get_value("main_tabs") == target_tab:
            self.app.last_tab_drag_switch_target = target_tab
            return

        now = time.monotonic()
        if now - self.app.last_tab_drag_switch_time < self.app.tab_drag_switch_interval:
            return

        dpg.set_value("main_tabs", target_tab)
        self.app.last_tab_drag_switch_time = now
        self.app.last_tab_drag_switch_target = target_tab

    def _pick_file_item_under_mouse(self):
        mouse_pos = dpg.get_mouse_pos(local=False)
        mouse_x, mouse_y = mouse_pos

        # 1. Normalize active_tab
        active_tab = dpg.get_value("main_tabs")
        if active_tab and not isinstance(active_tab, str):
            try:
                alias = dpg.get_item_alias(active_tab)
                if alias:
                    active_tab = alias
            except:
                pass

        # 2. Determine the active container to narrow search scope
        container = None
        if active_tab == "home_tab":
            if dpg.is_item_shown("search_group"):
                container = "search_results"
            else:
                container = "home_browse_scroll"
        elif active_tab == "scene_tab":
            container = (
                "scene_thumbnails_parent"
                if self.app.scene_view_mode == "thumbnail"
                else "scene_results_parent"
            )
        elif active_tab == "prop_tab":
            container = (
                "prop_thumbnails_parent"
                if self.app.prop_view_mode == "thumbnail"
                else "prop_results_parent"
            )

        if not container or not dpg.does_item_exist(container):
            return None

        # 3. Optimized recursive hit-testing
        def find_item_recursive(parent):
            children = dpg.get_item_children(parent, slot=1)
            if not children:
                return None

            for child in reversed(children):
                if not dpg.is_item_shown(child):
                    continue

                # A tree node's item rectangle covers only its header, not
                # its expanded descendants. Recurse before the header rect
                # test so Home-page rows do not fall through to the global
                # O(N) file-item scan on every mouse movement.
                try:
                    child_type = dpg.get_item_type(child)
                except Exception:
                    child_type = ""
                if "mvTreeNode" in child_type and dpg.get_value(child):
                    result = find_item_recursive(child)
                    if result:
                        return result

                # Try direct hovered check (but might fail during drag)
                if dpg.is_item_hovered(child):
                    if child in self.app.file_item_data:
                        return child

                # Coordinate check
                try:
                    # Try rect_min/max first
                    mi = dpg.get_item_rect_min(child)
                    ma = dpg.get_item_rect_max(child)

                    if mi[0] <= mouse_x <= ma[0] and mi[1] <= mouse_y <= ma[1]:
                        if child in self.app.file_item_data:
                            return child

                        # If it's a container, recurse
                        if "mvChildWindow" in child_type or "mvGroup" in child_type:
                            res = find_item_recursive(child)
                            if res:
                                return res
                except:
                    # Fallback to get_item_state if rect_min fails
                    try:
                        state = dpg.get_item_state(child)
                        c_mi = state.get("rect_min", [0, 0])
                        c_ma = state.get("rect_max", [0, 0])
                        if (
                            c_mi[0] <= mouse_x <= c_ma[0]
                            and c_mi[1] <= mouse_y <= c_ma[1]
                        ):
                            if child in self.app.file_item_data:
                                return child
                            res = find_item_recursive(child)
                            if res:
                                return res
                    except:
                        continue
            return None

        # No logging during normal operation
        found = find_item_recursive(container)

        # BRUTE FORCE FALLBACK for items that might be outside the main hierarchy slot
        if not found:
            for item in list(self.app.file_item_data.keys()):
                if dpg.does_item_exist(item) and dpg.is_item_shown(item):
                    try:
                        mi = dpg.get_item_rect_min(item)
                        ma = dpg.get_item_rect_max(item)
                        if mi[0] <= mouse_x <= ma[0] and mi[1] <= mouse_y <= ma[1]:
                            return item
                    except:
                        continue

        return found

    def _find_scroll_target_for_item(self, item):
        current = item
        while current and dpg.does_item_exist(current):
            try:
                max_scroll = dpg.get_y_scroll_max(current)
                _ = dpg.get_y_scroll(current)
                if max_scroll > 0:
                    return current
            except Exception:
                pass
            try:
                parent = dpg.get_item_parent(current)
            except Exception:
                parent = None
            if not parent or parent == current:
                break
            current = parent
        return None
