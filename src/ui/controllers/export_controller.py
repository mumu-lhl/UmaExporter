import os
import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.unity import UnityLogic
from src.core.i18n import i18n
from src.core.utils import normalize_outfit_id


class ExportController:
    def __init__(self, app):
        self.app = app

    def _get_active_prefix(self):
        active_tab = dpg.get_value("main_tabs")
        try:
            if active_tab and not isinstance(active_tab, str):
                active_tab = dpg.get_item_alias(active_tab) or ""
        except Exception:
            active_tab = ""
        if active_tab == "scene_tab":
            return "scene_"
        if active_tab == "prop_tab":
            return "prop_"
        return ""

    def _set_export_status(self, prefix, message, color=None):
        tag = f"{prefix}ui_export_status"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, message)
            if color is not None:
                dpg.configure_item(tag, color=color)

    def _set_character_export_status(self, message, color=None):
        tag = "character_export_status"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, message)
            if color is not None:
                dpg.configure_item(tag, color=color)

    def on_export_selected(self, sender, app_data):
        target_dir = app_data.get("file_path_name", "")
        if not target_dir:
            return

        prefix = self._get_active_prefix()
        self._set_export_status(prefix, i18n("msg_export_started"), [255, 255, 0])

        selected_tag = self.app.last_unity_selected.get(prefix, None)
        if not selected_tag or not dpg.does_item_exist(selected_tag):
            print("No Unity object selected for export.")
            self._set_export_status(prefix, i18n("msg_export_failed"), [255, 0, 0])
            return

        user_data = dpg.get_item_user_data(selected_tag)
        if not user_data or len(user_data) < 2:
            print("Invalid Unity object selection data.")
            self._set_export_status(prefix, i18n("msg_export_failed"), [255, 0, 0])
            return

        phys_path = user_data[0]
        path_id = user_data[1]
        u_type = user_data[2] if len(user_data) > 2 else None
        object_name = user_data[4] if len(user_data) > 4 else None
        bundle_key = user_data[5] if len(user_data) > 5 else None

        if u_type == "Animator" and self.app.current_asset_id:
            results = self.app.preview_controller._get_recursive_hashes(
                self.app.current_asset_id
            )
            paths = []
            bundle_keys = []
            for h, k in results:
                p = os.path.join(Config.get_data_root(), h[:2], h)
                if os.path.exists(p):
                    paths.append(p)
                    bundle_keys.append(k)

            if paths:
                future = self.app.executor.submit(
                    UnityLogic.export_animator_with_dependencies,
                    paths,
                    target_dir,
                    bundle_keys=bundle_keys,
                )
                future.add_done_callback(
                    lambda f: self.app._queue_ui_task(
                        lambda: self._set_export_status(
                            prefix,
                            i18n("msg_export_done")
                            if (f.exception() is None and (f.result() or 0) > 0)
                            else i18n("msg_export_failed"),
                            [0, 255, 0]
                            if (f.exception() is None and (f.result() or 0) > 0)
                            else [255, 0, 0],
                        )
                    )
                )
                return

        future = self.app.executor.submit(
            UnityLogic.export_single_unity_object,
            phys_path,
            path_id,
            target_dir,
            u_type,
            object_name,
            bundle_key=bundle_key,
        )
        future.add_done_callback(
            lambda f: self.app._queue_ui_task(
                lambda: self._set_export_status(
                    prefix,
                    i18n("msg_export_done")
                    if (f.exception() is None and bool(f.result()))
                    else i18n("msg_export_failed"),
                    [0, 255, 0]
                    if (f.exception() is None and bool(f.result()))
                    else [255, 0, 0],
                )
            )
        )

    def on_export_all_objects(self, sender, app_data):
        target_dir = app_data.get("file_path_name", "")
        if not target_dir or not self.app.current_asset_hash:
            return

        prefix = self._get_active_prefix()
        self._set_export_status(prefix, i18n("msg_export_started"), [255, 255, 0])

        # Get recursive dependencies to ensure all required assets are decrypted/passed
        export_paths, export_bundle_keys = self._get_recursive_export_inputs(
            self.app.current_asset_id
        )

        if not export_paths:
            # Fallback to single asset if no dependencies found or recursive search failed
            phys_path = os.path.join(
                Config.get_data_root(),
                self.app.current_asset_hash[:2],
                self.app.current_asset_hash,
            )
            export_paths = [phys_path]
            bundle_key = None
            if self.app.current_asset_data:
                bundle_key = self.app.current_asset_data.get("key")
            export_bundle_keys = [bundle_key] if bundle_key is not None else None

        future = self.app.executor.submit(
            UnityLogic.export_unity_assets,
            export_paths,
            target_dir,
            bundle_keys=export_bundle_keys,
        )
        future.add_done_callback(
            lambda f: self.app._queue_ui_task(
                lambda: self._set_export_status(
                    prefix,
                    i18n("msg_export_done")
                    if (f.exception() is None and (f.result() or 0) > 0)
                    else i18n("msg_export_failed"),
                    [0, 255, 0]
                    if (f.exception() is None and (f.result() or 0) > 0)
                    else [255, 0, 0],
                )
            )
        )

    def on_character_export_selected(self, sender, app_data):
        target_dir = app_data.get("file_path_name", "")
        if not target_dir:
            return

        selected_outfit = self.app.current_character_outfit
        if not selected_outfit:
            self._set_character_export_status(
                i18n("msg_select_outfit"), [255, 120, 120]
            )
            return

        chara_id = selected_outfit.get("chara_id")
        outfit_id = selected_outfit.get("outfit_id")
        if not chara_id or not outfit_id:
            self._set_character_export_status(i18n("msg_export_failed"), [255, 0, 0])
            return

        self._set_character_export_status(i18n("msg_export_started"), [255, 255, 0])

        future = self.app.executor.submit(
            self._export_character_animator_group,
            target_dir,
            chara_id,
            outfit_id,
        )

        future.add_done_callback(
            lambda f: self.app._queue_ui_task(
                lambda: self._set_character_export_status(
                    i18n("msg_export_done")
                    if (f.exception() is None and bool(f.result()))
                    else i18n("msg_character_export_missing")
                    if f.exception() is None
                    else i18n("msg_export_failed"),
                    [0, 255, 0]
                    if (f.exception() is None and bool(f.result()))
                    else [255, 0, 0],
                )
            )
        )

    def _get_character_outfit_main_suffix(self, outfit_id):
        outfit_id = normalize_outfit_id(outfit_id)
        if not outfit_id or len(outfit_id) < 6:
            return None, None

        outfit_main = outfit_id[:4]
        outfit_suffix = outfit_id[-2:]
        if outfit_suffix == "01":
            outfit_suffix = "00"

        return outfit_main, outfit_suffix

    def _is_generic_costume(self, chara_id, outfit_id):
        """
        Check if the outfit is a generic/universal costume.
        A generic costume is when the 6-digit outfit_id doesn't start with the 4-digit chara_id.
        """
        outfit_id = normalize_outfit_id(outfit_id)
        if not chara_id or not outfit_id or len(outfit_id) < 4:
            return False
        return outfit_id[:4] != chara_id

    def _build_character_export_targets(self, chara_id, outfit_id):
        if not chara_id or not outfit_id:
            return []

        # Always fetch dress data first as it contains the authoritative body_type_sub
        dress_data = None
        if self.app.db and self.app.db.master_db:
            dress_data = self.app.db.master_db.get_dress_data(outfit_id)

        # Fallback values from string manipulation
        outfit_main, outfit_suffix_fallback = self._get_character_outfit_main_suffix(
            outfit_id
        )
        if not outfit_main or not outfit_suffix_fallback:
            return []

        # Determine the authoritative suffix (body_type_sub from DB or fallback)
        if dress_data:
            asset_suffix = dress_data.get("body_type_sub", "00").zfill(2)
        else:
            asset_suffix = outfit_suffix_fallback

        if asset_suffix == "01":
            asset_suffix = "00"

        is_generic = self._is_generic_costume(chara_id, outfit_id)

        if is_generic:
            # Generic costume: construct compound costume ID and build special body path
            chara_data = None
            if self.app.db and self.app.db.master_db:
                chara_data = self.app.db.master_db.get_chara_data(chara_id)

            if dress_data and chara_data:
                body_type = dress_data.get("body_type", outfit_main)
                body_type = body_type.zfill(4)

                body_type_sub = asset_suffix
                body_setting = dress_data.get("body_setting", "00")
                body_setting = body_setting.zfill(2)

                height = chara_data.get("height", "00")
                shape = chara_data.get("shape", "00")
                bust = chara_data.get("bust", "00")
                skin = chara_data.get("skin", "00")
                socks = chara_data.get("socks", "00")

                costume_id_compound = f"{body_type}_{body_type_sub}_{body_setting}_{height}_{shape}_{bust}"
                costume_id_short = f"{body_type}_{body_type_sub}"
                costume_id_long = f"{body_type}_{body_type_sub}_{body_setting}"

                body_path = (
                    f"3d/chara/body/bdy{costume_id_short}/pfb_bdy{costume_id_compound}"
                )
                body_animator = f"pfb_bdy{costume_id_compound}"

                if body_type == "0001":
                    body_texture_prefix = (
                        f"tex_bdy{costume_id_short}_00_{skin}_{bust}_0{socks}_"
                    )
                elif body_type == "0003":
                    body_texture_prefix = f"tex_bdy{costume_id_short}_00_{skin}_{bust}_"
                elif body_type == "0006":
                    body_texture_prefix = f"tex_bdy{costume_id_long}_{skin}_{bust}_00_"
                else:
                    body_texture_prefix = f"tex_bdy{costume_id_long}_{skin}_{bust}_"

                body_texture_export_prefix = f"tex_bdy{chara_id}_00_"
            else:
                body_path = f"3d/chara/body/bdy{outfit_main}_{asset_suffix}/pfb_bdy{outfit_main}_{asset_suffix}"
                body_animator = f"pfb_bdy{outfit_main}_{asset_suffix}"
                body_texture_prefix = f"tex_bdy{outfit_main}_{asset_suffix}_"
                body_texture_export_prefix = None
        else:
            body_path = f"3d/chara/body/bdy{outfit_main}_{asset_suffix}/pfb_bdy{outfit_main}_{asset_suffix}"
            body_animator = f"pfb_bdy{outfit_main}_{asset_suffix}"
            body_texture_prefix = f"tex_bdy{outfit_main}_{asset_suffix}_"
            body_texture_export_prefix = None

        return [
            {
                "label": "body",
                "logical_path": body_path,
                "animator_name": body_animator,
                "texture_prefix": body_texture_prefix,
                "texture_export_prefix": body_texture_export_prefix,
            },
            {
                "label": "head",
                "logical_path": f"3d/chara/head/chr{chara_id}_{asset_suffix}/pfb_chr{chara_id}_{asset_suffix}",
                "animator_name": f"pfb_chr{chara_id}_{asset_suffix}",
            },
        ]

    def _resolve_character_tail_target(self, chara_id):
        if not chara_id or not self.app.db:
            return None

        for tail_id in ("0001", "0002"):
            texture_name = f"tex_tail{tail_id}_00_{chara_id}_diff"
            texture_path = f"3d/chara/tail/tail{tail_id}_00/textures/{texture_name}"
            texture_asset = self.app.db.get_asset_by_path(texture_path)
            if texture_asset is None:
                continue

            return {
                "label": "tail",
                "logical_path": f"3d/chara/tail/tail{tail_id}_00/pfb_tail{tail_id}_00",
                "animator_name": f"pfb_tail{tail_id}_00",
                "texture_prefix": f"tex_tail{tail_id}_00_{chara_id}_",
            }

        return None

    def _get_recursive_export_inputs(self, asset_id):
        if not asset_id or not self.app.db:
            return [], []

        results = self.app.preview_controller._get_recursive_hashes(asset_id)
        paths = []
        bundle_keys = []

        for asset_hash, bundle_key in results:
            phys_path = os.path.join(Config.get_data_root(), asset_hash[:2], asset_hash)
            if not os.path.exists(phys_path):
                continue
            paths.append(phys_path)
            bundle_keys.append(bundle_key)

        return paths, bundle_keys

    def _build_character_texture_output_path(self, target_dir, label, texture_name):
        safe_name = UnityLogic._sanitize_export_name(texture_name) or "texture"
        file_name = f"{safe_name}.png"
        output_path = os.path.join(target_dir, file_name)

        if not os.path.exists(output_path):
            return output_path

        base, ext = os.path.splitext(file_name)
        counter = 1
        while True:
            candidate = os.path.join(target_dir, f"{base}_{counter}{ext}")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _export_character_component_textures(
        self,
        target_dir,
        label,
        asset,
        texture_prefix_filter=None,
        texture_export_prefix=None,
    ):
        if not asset or not self.app.db:
            return 0

        base_dir = asset["full_path"].rsplit("/", 1)[0]
        texture_prefix = f"{base_dir}/textures/"
        texture_assets = self.app.db.get_assets_by_prefix(texture_prefix)
        exported_count = 0

        for texture_asset in texture_assets:
            texture_name = texture_asset["full_path"].rsplit("/", 1)[-1]
            texture_hash = texture_asset.get("hash")
            if not texture_name or not texture_hash:
                continue
            if texture_prefix_filter and not texture_name.startswith(
                texture_prefix_filter
            ):
                continue

            export_texture_name = texture_name
            if texture_prefix_filter and texture_export_prefix:
                if texture_name.startswith(texture_prefix_filter):
                    suffix = texture_name[len(texture_prefix_filter) :]
                    export_texture_name = f"{texture_export_prefix}{suffix}"

            phys_path = os.path.join(
                Config.get_data_root(),
                texture_hash[:2],
                texture_hash,
            )
            if not os.path.exists(phys_path):
                continue

            output_path = self._build_character_texture_output_path(
                target_dir, label, export_texture_name
            )
            exported = UnityLogic.export_named_texture_to_png(
                phys_path,
                texture_name,
                output_path,
                bundle_key=texture_asset.get("key"),
            )
            if exported:
                exported_count += 1

        return exported_count

    def _export_character_animator_group(self, target_dir, chara_id, outfit_id):
        targets = self._build_character_export_targets(chara_id, outfit_id)
        tail_target = self._resolve_character_tail_target(chara_id)
        if tail_target is not None:
            targets.append(tail_target)
        if not targets or not self.app.db:
            return False

        export_configs = []
        texture_exports = 0

        for target in targets:
            asset = self.app.db.get_asset_by_path(target["logical_path"])
            animator_name = target["animator_name"]

            if asset is None and target["label"] != "tail":
                candidates = self.app.db.find_character_component_candidates(
                    target["label"], chara_id, outfit_id
                )
                if candidates:
                    asset = candidates[0]
                    animator_name = asset["full_path"].rsplit("/", 1)[-1]

            if asset is None:
                return False

            phys_path = os.path.join(
                Config.get_data_root(),
                asset["hash"][:2],
                asset["hash"],
            )
            if (
                UnityLogic.find_named_animator(
                    phys_path,
                    animator_name,
                    bundle_key=asset.get("key"),
                )
                is None
            ):
                return False

            export_paths, export_bundle_keys = self._get_recursive_export_inputs(
                asset.get("id")
            )
            if not export_paths:
                export_paths = [phys_path]
                export_bundle_keys = [asset.get("key")]

            export_configs.append(
                {
                    "physical_paths": export_paths,
                    "bundle_keys": export_bundle_keys,
                }
            )
            texture_exports += self._export_character_component_textures(
                target_dir,
                target["label"],
                asset,
                texture_prefix_filter=target.get("texture_prefix"),
                texture_export_prefix=target.get("texture_export_prefix"),
            )

            if target["label"] == "head":
                texture_exports += self._export_head_facial_target(
                    target_dir, phys_path, asset, target
                )

        if not export_configs:
            return False

        exported_count = UnityLogic.batch_export_animators(export_configs, target_dir)
        return (exported_count + texture_exports) > 0

    def _export_head_facial_target(self, target_dir, phys_path, asset, target):
        """Export the facial MonoBehaviour from the head asset file.
        Tries both ast_*_facial_target and ast_*_facial naming conventions.
        Includes fallback logic to _00 suffix if specific one is not found.
        """
        try:
            logical_path = target.get("logical_path", "")
            path_parts = logical_path.rsplit("/", 1)
            if len(path_parts) < 2:
                return 0

            folder_path = path_parts[0]
            folder_name = folder_path.split("/")[-1]
            # folder_name is like chr1234_05

            # List of possible object names to try
            possible_names = [
                f"ast_{folder_name}_facial_target",
                f"ast_{folder_name}_facial",
            ]

            # Add fallback names with _00 suffix
            if "_" in folder_name:
                base_folder_name = folder_name.rsplit("_", 1)[0] + "_00"
                if base_folder_name != folder_name:
                    possible_names.append(f"ast_{base_folder_name}_facial_target")
                    possible_names.append(f"ast_{base_folder_name}_facial")

            found_name = None
            path_id = None
            for name in possible_names:
                path_id = UnityLogic.find_monobehaviour_by_name(
                    phys_path, name, bundle_key=asset.get("key")
                )
                if path_id is not None:
                    found_name = name
                    break

            if path_id is None:
                return 0

            export_dir = target_dir
            os.makedirs(export_dir, exist_ok=True)

            success = UnityLogic.export_single_unity_object(
                phys_path,
                path_id,
                export_dir,
                object_type="MonoBehaviour",
                object_name=found_name,
                bundle_key=asset.get("key"),
            )

            return 1 if success else 0
        except Exception as e:
            print(f"Failed to export facial data: {e}")
            return 0
