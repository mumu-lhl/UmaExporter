"""Dependency-table loading and rendering for the asset preview feature."""

import dearpygui.dearpygui as dpg

from src.core.i18n import i18n


class DependencyPanelController:
    """Loads dependency tables asynchronously and applies only current results."""

    def __init__(self, app):
        self.app = app

    def load_dependencies(self, asset_id, request_id):
        self._load(
            asset_id,
            request_id,
            cache=self.app.cached_deps,
            fetch=self.app.db.get_dependencies if self.app.db else None,
            parent_suffix="ui_dep_parent",
            empty_message=i18n("msg_no_deps"),
        )

    def load_reverse_dependencies(self, asset_id, request_id):
        self._load(
            asset_id,
            request_id,
            cache=self.app.cached_rev_deps,
            fetch=self.app.db.get_reverse_dependencies if self.app.db else None,
            parent_suffix="ui_rev_dep_parent",
            empty_message=i18n("msg_no_rev_deps"),
        )

    def _load(self, asset_id, request_id, cache, fetch, parent_suffix, empty_message):
        if fetch is None:
            return
        cached = cache.get(asset_id)
        if cached is not None:
            self.app._queue_ui_task(
                lambda: self._apply(asset_id, request_id, cached, parent_suffix, empty_message)
            )
            return

        future = self.app.executor.submit(fetch, asset_id)

        def done(completed):
            try:
                data = completed.result()
            except Exception:
                data = []
            cache[asset_id] = data
            self.app._queue_ui_task(
                lambda: self._apply(asset_id, request_id, data, parent_suffix, empty_message)
            )

        future.add_done_callback(done)

    def _apply(self, asset_id, request_id, data, parent_suffix, empty_message):
        if request_id != self.app.selection_request_id:
            return
        if not self.app._is_still_selected(asset_id):
            return
        for prefix in self._detail_prefixes():
            self._fill_table(f"{prefix}{parent_suffix}", data, empty_message)

    @staticmethod
    def _detail_prefixes():
        prefixes = [""]
        if dpg.does_alias_exist("scene_ui_path"):
            prefixes.append("scene_")
        if dpg.does_alias_exist("prop_ui_path"):
            prefixes.append("prop_")
        return prefixes

    def _fill_table(self, parent, data, empty_message):
        dpg.delete_item(parent, children_only=True)
        if not data:
            dpg.add_text(empty_message, parent=parent)
            return
        with dpg.table(
            header_row=True,
            resizable=True,
            parent=parent,
            policy=dpg.mvTable_SizingStretchProp,
        ):
            dpg.add_table_column(label="Type", width_fixed=True)
            dpg.add_table_column(label="Asset Path")
            for name, data_type, asset_id, size, asset_hash, key in data:
                with dpg.table_row() as row:
                    dpg.add_text(f"Type {data_type}")
                    self.app._add_file_selectable(
                        name,
                        {
                            "id": asset_id,
                            "size": size,
                            "hash": asset_hash,
                            "full_path": name,
                            "key": key,
                            "is_from_dep": True,
                        },
                        row,
                    )
