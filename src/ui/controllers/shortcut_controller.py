import dearpygui.dearpygui as dpg


class ShortcutController:
    def __init__(self, app):
        self.app = app

    def setup_shortcuts(self):
        with dpg.handler_registry():
            dpg.add_key_press_handler(key=dpg.mvKey_F, callback=self._on_ctrl_f)
            dpg.add_key_press_handler(key=dpg.mvKey_Q, callback=self._on_ctrl_q)
            dpg.add_key_press_handler(key=dpg.mvKey_Up, callback=self._on_key_press)
            dpg.add_key_press_handler(key=dpg.mvKey_Down, callback=self._on_key_press)
            dpg.add_key_press_handler(key=dpg.mvKey_J, callback=self._on_key_press)
            dpg.add_key_press_handler(key=dpg.mvKey_K, callback=self._on_key_press)
            dpg.add_key_release_handler(key=dpg.mvKey_Up, callback=self._on_key_release)
            dpg.add_key_release_handler(
                key=dpg.mvKey_Down, callback=self._on_key_release
            )
            dpg.add_key_release_handler(key=dpg.mvKey_J, callback=self._on_key_release)
            dpg.add_key_release_handler(key=dpg.mvKey_K, callback=self._on_key_release)

    def _is_ctrl_pressed(self):
        return dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(
            dpg.mvKey_RControl
        )

    def _on_ctrl_f(self, sender, app_data, user_data, *args):
        if not self._is_ctrl_pressed():
            return

        active_tab = (
            dpg.get_value("main_tabs") if dpg.does_alias_exist("main_tabs") else None
        )
        active_tab_alias = ""
        try:
            if active_tab and not isinstance(active_tab, str):
                active_tab_alias = dpg.get_item_alias(active_tab) or ""
            elif isinstance(active_tab, str):
                active_tab_alias = active_tab
        except Exception:
            active_tab_alias = ""

        if active_tab_alias == "scene_tab" and dpg.does_item_exist(
            "scene_search_input"
        ):
            dpg.focus_item("scene_search_input")
        elif active_tab_alias == "prop_tab" and dpg.does_item_exist(
            "prop_search_input"
        ):
            dpg.focus_item("prop_search_input")
        elif active_tab_alias == "home_tab" and dpg.does_item_exist("search_input"):
            dpg.focus_item("search_input")
        elif active_tab_alias == "settings_tab" and dpg.does_item_exist(
            "settings_base_path"
        ):
            dpg.focus_item("settings_base_path")
        elif dpg.does_item_exist("search_input") and dpg.is_item_shown("search_input"):
            dpg.focus_item("search_input")
        elif dpg.does_item_exist("scene_search_input") and dpg.is_item_shown(
            "scene_search_input"
        ):
            dpg.focus_item("scene_search_input")
        elif dpg.does_item_exist("prop_search_input") and dpg.is_item_shown(
            "prop_search_input"
        ):
            dpg.focus_item("prop_search_input")
        elif dpg.does_item_exist("settings_base_path") and dpg.is_item_shown(
            "settings_base_path"
        ):
            dpg.focus_item("settings_base_path")

    def _on_ctrl_q(self, sender, app_data, user_data, *args):
        if self._is_ctrl_pressed():
            dpg.stop_dearpygui()

    def _on_key_press(self, sender, key_code, user_data, *args):
        # 1. Prevent keyboard navigation if an input field is focused
        for input_tag in [
            "search_input",
            "scene_search_input",
            "prop_search_input",
            "settings_base_path",
        ]:
            if dpg.does_item_exist(input_tag) and dpg.is_item_focused(input_tag):
                if key_code not in (dpg.mvKey_Up, dpg.mvKey_Down):
                    return

        # 2. Ensure we have a valid selection to start from
        if (
            not self.app.last_selected
            or not dpg.does_item_exist(self.app.last_selected)
            or not dpg.is_item_shown(self.app.last_selected)
        ):
            active_tab = dpg.get_value("main_tabs")
            parent = None
            if active_tab == "home_tab":
                parent = (
                    "search_results"
                    if dpg.is_item_shown("search_group")
                    else "browse_group"
                )
            elif active_tab == "scene_tab":
                parent = "scene_results_parent"
            elif active_tab == "prop_tab":
                parent = "prop_results_parent"

            if parent and dpg.does_item_exist(parent):
                children = dpg.get_item_children(parent, slot=1)
                for child in children:
                    if child in self.app.file_item_data:
                        self.app.last_selected = child
                        break

        if not self.app.last_selected or not dpg.does_item_exist(
            self.app.last_selected
        ):
            return

        # 3. Handle Navigation Mode (Equivalent to Drag Preview)
        self.app.drag_preview_active = True

        # 4. Find the container (parent) of the currently selected item
        parent = dpg.get_item_parent(self.app.last_selected)
        if not parent:
            return

        # 5. Get all siblings and filter for file selectables
        siblings = dpg.get_item_children(parent, slot=1)
        selectables = []
        for s in siblings:
            if s in self.app.file_item_data:
                selectables.append(s)
            else:
                alias = dpg.get_item_alias(s)
                if alias and alias in self.app.file_item_data:
                    selectables.append(alias)

        if not selectables:
            return

        # 6. Find current index and calculate new index
        current_idx = -1
        last_selected_alias = (
            dpg.get_item_alias(self.app.last_selected) or self.app.last_selected
        )
        for i, s in enumerate(selectables):
            s_alias = dpg.get_item_alias(s) or s
            if (
                s == self.app.last_selected
                or s_alias == self.app.last_selected
                or s == last_selected_alias
            ):
                current_idx = i
                break

        if current_idx == -1:
            return

        new_idx = current_idx
        if key_code in (dpg.mvKey_Up, dpg.mvKey_K):
            new_idx = max(0, current_idx - 1)
        elif key_code in (dpg.mvKey_Down, dpg.mvKey_J):
            new_idx = min(len(selectables) - 1, current_idx + 1)

        # 7. Trigger navigation
        if new_idx != current_idx:
            target_item = selectables[new_idx]
            target_data = self.app.file_item_data.get(target_item)
            if target_data:
                self.app.on_file_click(target_item, None, target_data)

                # 8. Find the scrollable container
                active_tab = dpg.get_value("main_tabs")
                scroll_container = None
                if active_tab == "home_tab":
                    scroll_container = (
                        "search_results"
                        if dpg.is_item_shown("search_group")
                        else "home_browse_scroll"
                    )
                elif active_tab == "scene_tab":
                    scroll_container = "scene_results_parent"
                elif active_tab == "prop_tab":
                    scroll_container = "prop_results_parent"

                if not scroll_container or not dpg.does_item_exist(scroll_container):
                    scroll_container = (
                        self.app.drag_controller._find_scroll_target_for_item(
                            target_item
                        )
                    )

                if scroll_container:
                    self._scroll_to_item(scroll_container, target_item)

    def _on_key_release(self, sender, key_code, user_data, *args):
        if key_code in (dpg.mvKey_Up, dpg.mvKey_Down, dpg.mvKey_J, dpg.mvKey_K):
            if not (
                dpg.is_key_down(dpg.mvKey_Up)
                or dpg.is_key_down(dpg.mvKey_Down)
                or dpg.is_key_down(dpg.mvKey_J)
                or dpg.is_key_down(dpg.mvKey_K)
            ):
                self.app.drag_preview_active = False
                if self.app.last_selected:
                    data = self.app.file_item_data.get(self.app.last_selected)
                    if data:
                        self.app.on_file_click(self.app.last_selected, None, data)

    def _scroll_to_item(self, container, item):
        if (
            not container
            or not item
            or not dpg.does_item_exist(container)
            or not dpg.does_item_exist(item)
        ):
            return

        try:
            dpg.focus_item(item)
        except Exception:
            pass

        try:
            item_min = dpg.get_item_rect_min(item)
            item_max = dpg.get_item_rect_max(item)
            cont_min = dpg.get_item_rect_min(container)
            cont_max = dpg.get_item_rect_max(container)

            if item_min[1] == 0 and item_max[1] == 0:
                return

            iy_min, iy_max = item_min[1], item_max[1]
            cy_min, cy_max = cont_min[1], cont_max[1]

            curr_scroll = dpg.get_y_scroll(container)
            max_scroll = dpg.get_y_scroll_max(container)

            margin = 40

            if iy_min < cy_min + margin:
                diff = (cy_min + margin) - iy_min
                dpg.set_y_scroll(container, max(0.0, curr_scroll - diff))
            elif iy_max > cy_max - margin:
                diff = iy_max - (cy_max - margin)
                dpg.set_y_scroll(container, min(max_scroll, curr_scroll + diff))
        except Exception:
            pass
