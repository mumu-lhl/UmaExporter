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

    @staticmethod
    def _item_alias(item):
        try:
            return dpg.get_item_alias(item) or item
        except Exception:
            return item

    def _active_tab_alias(self):
        raw_tab = dpg.get_value("main_tabs")
        return self._item_alias(raw_tab)

    def _search_navigation_context(self):
        active_tab = self._active_tab_alias()
        if active_tab == "home_tab":
            if dpg.does_item_exist("search_group") and dpg.is_item_shown(
                "search_group"
            ):
                return "", "search_results"
            return None
        if active_tab == "scene_tab":
            container = (
                "scene_thumbnails_parent"
                if self.app.scene_view_mode == "thumbnail"
                else "scene_results_parent"
            )
            return "scene_", container
        if active_tab == "prop_tab":
            container = (
                "prop_thumbnails_parent"
                if self.app.prop_view_mode == "thumbnail"
                else "prop_results_parent"
            )
            return "prop_", container
        return None

    def _stable_search_tags(self, prefix):
        return [
            tag
            for tag in self.app.search_item_tags[prefix]
            if dpg.does_item_exist(tag) and tag in self.app.file_item_data
        ]

    def _legacy_sibling_tags(self, selected):
        parent = dpg.get_item_parent(selected)
        if not parent:
            return []
        tags = []
        for item in dpg.get_item_children(parent, slot=1):
            alias = self._item_alias(item)
            if item in self.app.file_item_data:
                tags.append(item)
            elif alias in self.app.file_item_data:
                tags.append(alias)
        return tags

    def _on_key_press(self, sender, key_code, user_data, *args):
        for input_tag in (
            "search_input",
            "scene_search_input",
            "prop_search_input",
            "settings_base_path",
        ):
            if dpg.does_item_exist(input_tag) and dpg.is_item_focused(input_tag):
                if key_code not in (dpg.mvKey_Up, dpg.mvKey_Down):
                    return

        search_context = self._search_navigation_context()
        if search_context:
            prefix, scroll_container = search_context
            selectables = self._stable_search_tags(prefix)
            if not selectables:
                return
            selected = self._item_alias(self.app.last_selected)
            if selected not in selectables:
                selected = selectables[0]
                self.app.last_selected = selected
        else:
            scroll_container = None
            selected = self._item_alias(self.app.last_selected)
            if (
                not selected
                or not dpg.does_item_exist(selected)
                or not dpg.is_item_shown(selected)
            ):
                if self._active_tab_alias() != "home_tab":
                    return
                browse_items = [
                    self._item_alias(item)
                    for item in dpg.get_item_children("browse_group", slot=1)
                ]
                browse_items = [
                    item
                    for item in browse_items
                    if item in self.app.file_item_data
                    and dpg.does_item_exist(item)
                ]
                if not browse_items:
                    return
                selected = browse_items[0]
                self.app.last_selected = selected
                scroll_container = "home_browse_scroll"
            selectables = self._legacy_sibling_tags(selected)
            if not selectables:
                return

        try:
            current_idx = selectables.index(selected)
        except ValueError:
            return

        self.app.drag_preview_active = True
        new_idx = current_idx
        if key_code in (dpg.mvKey_Up, dpg.mvKey_K):
            new_idx = max(0, current_idx - 1)
        elif key_code in (dpg.mvKey_Down, dpg.mvKey_J):
            new_idx = min(len(selectables) - 1, current_idx + 1)

        if new_idx == current_idx:
            return

        target_item = selectables[new_idx]
        target_data = self.app.file_item_data.get(target_item)
        if not target_data:
            return
        self.app.on_file_click(target_item, None, target_data)

        if not scroll_container or not dpg.does_item_exist(scroll_container):
            scroll_container = self.app.drag_controller._find_scroll_target_for_item(
                target_item
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
