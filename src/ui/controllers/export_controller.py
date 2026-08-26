"""Export controller for generic scene and prop assets."""

import os

import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.i18n import i18n
from src.core.unity import UnityLogic


class ExportController:
    """Coordinate exports that are not tied to a selected character outfit."""

    def __init__(self, app):
        self.app = app

    def _get_active_prefix(self):
        active_tab = dpg.get_value("main_tabs")
        try:
            if active_tab and not isinstance(active_tab, str):
                active_tab = dpg.get_item_alias(active_tab) or ""
        except Exception:
            active_tab = ""

        prefix = {"scene_tab": "scene_", "prop_tab": "prop_"}.get(
            active_tab, ""
        )
        if prefix:
            return prefix

        # Dear PyGui may return 0/None for a tab bar on some Windows/RDP
        # backends. Infer the domain from the selected Unity object instead.
        for candidate in ("scene_", "prop_"):
            selected_tag = self.app.last_unity_selected.get(candidate)
            if selected_tag and dpg.does_item_exist(selected_tag):
                return candidate

        return ""

    def _set_export_status(self, prefix, message, color=None):
        tag = f"{prefix}ui_export_status"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, message)
            if color is not None:
                dpg.configure_item(tag, color=color)

    def _resolve_selected_item(self, preferred_prefix):
        """Return the live selected item without relying solely on the tab bar."""
        prefixes = [preferred_prefix]
        prefixes.extend(
            candidate
            for candidate in ("", "scene_", "prop_")
            if candidate not in prefixes
        )
        for candidate in prefixes:
            selected_tag = self.app.last_unity_selected.get(candidate)
            if selected_tag and dpg.does_item_exist(selected_tag):
                return candidate, selected_tag
        return preferred_prefix, None

    def _resolve_selection_data(self, preferred_prefix, selected_tag):
        if selected_tag and dpg.does_item_exist(selected_tag):
            return preferred_prefix, dpg.get_item_user_data(selected_tag)

        selections = getattr(self.app, "last_unity_selection_data", {})
        prefixes = [preferred_prefix]
        prefixes.extend(
            candidate
            for candidate in ("", "scene_", "prop_")
            if candidate not in prefixes
        )
        for candidate in prefixes:
            user_data = selections.get(candidate)
            if user_data and len(user_data) >= 2:
                return candidate, user_data
        return preferred_prefix, None

    def on_export_selected(self, sender, app_data):
        target_dir = app_data.get("file_path_name", "")
        if not target_dir:
            return
        prefix = self._get_active_prefix()
        prefix, selected_tag = self._resolve_selected_item(prefix)
        prefix, user_data = self._resolve_selection_data(prefix, selected_tag)
        self._set_export_status(prefix, i18n("msg_export_started"), [255, 255, 0])
        if not user_data:
            if self._submit_current_asset(prefix, target_dir):
                return
            self._set_export_status(prefix, i18n("msg_export_failed"), [255, 0, 0])
            return
        if not user_data or len(user_data) < 2:
            self._set_export_status(prefix, i18n("msg_export_failed"), [255, 0, 0])
            return

        phys_path, path_id = user_data[:2]
        object_type = user_data[2] if len(user_data) > 2 else None
        object_name = user_data[4] if len(user_data) > 4 else None
        bundle_key = user_data[5] if len(user_data) > 5 else None
        if object_type == "Animator" and self.app.current_asset_id:
            paths, bundle_keys = self._recursive_export_inputs(
                self.app.current_asset_id
            )
            if paths:
                self._submit(
                    prefix,
                    UnityLogic.export_animator_with_dependencies,
                    paths,
                    target_dir,
                    bundle_keys=bundle_keys,
                )
                return
        self._submit(
            prefix,
            UnityLogic.export_single_unity_object,
            phys_path,
            path_id,
            target_dir,
            object_type,
            object_name,
            bundle_key=bundle_key,
        )

    def on_export_all_objects(self, sender, app_data):
        target_dir = app_data.get("file_path_name", "")
        if not target_dir or not self.app.current_asset_hash:
            return
        prefix = self._get_active_prefix()
        self._set_export_status(prefix, i18n("msg_export_started"), [255, 255, 0])
        self._submit_current_asset(prefix, target_dir)

    def _submit_current_asset(self, prefix, target_dir):
        asset_hash = self.app.current_asset_hash
        if not asset_hash:
            return False
        paths, bundle_keys = self._recursive_export_inputs(self.app.current_asset_id)
        if not paths:
            paths = [os.path.join(Config.get_data_root(), asset_hash[:2], asset_hash)]
            key = (self.app.current_asset_data or {}).get("key")
            bundle_keys = [key] if key is not None else None
        self._submit(
            prefix,
            UnityLogic.export_unity_assets,
            paths,
            target_dir,
            bundle_keys=bundle_keys,
        )
        return True

    def _recursive_export_inputs(self, asset_id):
        if not asset_id or not self.app.db:
            return [], []
        paths, bundle_keys = [], []
        for asset_hash, key in self.app.preview_controller._get_recursive_hashes(
            asset_id
        ):
            path = os.path.join(Config.get_data_root(), asset_hash[:2], asset_hash)
            if os.path.exists(path):
                paths.append(path)
                bundle_keys.append(key)
        return paths, bundle_keys

    def _submit(self, prefix, operation, *args, **kwargs):
        future = self.app.executor.submit(operation, *args, **kwargs)

        def done(completed):
            try:
                result = completed.result()
                succeeded = bool(result)
            except Exception:
                import traceback

                traceback.print_exc()
                result = None
                succeeded = False
            self.app._queue_ui_task(
                lambda: self._set_export_status(
                    prefix,
                    i18n("msg_export_done") if succeeded else i18n("msg_export_failed"),
                    [0, 255, 0] if succeeded else [255, 0, 0],
                )
            )

        future.add_done_callback(done)
