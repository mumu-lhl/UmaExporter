import dearpygui.dearpygui as dpg


class NavigationMixin:
    def go_back(self, *args):
        if not self._has_navigable_history(self.history_back):
            return

        current_data = self._snapshot_asset_data(self.current_asset_data)
        if current_data:
            self.history_forward.append(current_data)

        prev_data = self._pop_navigable_entry(self.history_back)
        if not prev_data:
            self._update_nav_buttons()
            return

        self.is_navigating = True
        self.on_file_click(None, None, prev_data)
        self.is_navigating = False
        self._update_nav_buttons()

    def go_forward(self, *args):
        if not self._has_navigable_history(self.history_forward):
            return

        current_data = self._snapshot_asset_data(self.current_asset_data)
        if current_data:
            self.history_back.append(current_data)

        next_data = self._pop_navigable_entry(self.history_forward)
        if not next_data:
            self._update_nav_buttons()
            return

        self.is_navigating = True
        self.on_file_click(None, None, next_data)
        self.is_navigating = False
        self._update_nav_buttons()

    def _snapshot_asset_data(self, data):
        if not data:
            return None
        snapshot = data.copy()
        snapshot.pop("is_from_dep", None)
        return snapshot

    def _select_existing_result_item(self, asset_id):
        candidate_tags = (
            f"search_item_{asset_id}",
            f"scene_item_{asset_id}",
            f"prop_item_{asset_id}",
        )
        for tag in candidate_tags:
            if not dpg.does_item_exist(tag):
                continue
            try:
                dpg.set_value(tag, True)
                return tag
            except Exception:
                continue
        return None

    def _pop_navigable_entry(self, stack):
        current_id = self.current_asset_id
        while stack:
            item = stack.pop()
            if isinstance(item, dict) and item.get("id") != current_id:
                return item
        return None

    def _has_navigable_history(self, stack):
        current_id = self.current_asset_id
        return any(
            isinstance(item, dict) and item.get("id") != current_id for item in stack
        )

    def _update_nav_buttons(self):
        for prefix in self._detail_prefixes():
            dpg.configure_item(
                f"{prefix}nav_back_btn",
                enabled=self._has_navigable_history(self.history_back),
            )
            dpg.configure_item(
                f"{prefix}nav_forward_btn",
                enabled=self._has_navigable_history(self.history_forward),
            )
