import os
import re
import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.unity import UnityLogic
from src.core.i18n import i18n
from src.core.utils import normalize_outfit_id


class CharacterExportController:
    def __init__(self, app):
        self.app = app

    def _set_character_export_status(self, message, color=None):
        tag = "character_export_status"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, message)
            if color is not None:
                dpg.configure_item(tag, color=color)

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

        is_mini = False
        if dpg.does_item_exist("character_export_mini"):
            is_mini = bool(dpg.get_value("character_export_mini"))

        self._set_character_export_status(i18n("msg_export_started"), [255, 255, 0])

        future = self.app.executor.submit(
            self._export_character_animator_group,
            target_dir,
            chara_id,
            outfit_id,
            is_mini,
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

    def _build_character_export_targets(self, chara_id, outfit_id, is_mini=False):
        if not chara_id or not outfit_id:
            return []

        # Always fetch dress data first as it contains the authoritative body_type_sub
        dress_data = None
        if self.app.db and self.app.db.master_db:
            dress_data = self.app.db.master_db.get_dress_data(outfit_id)

        # Fallback values from string manipulation.  Short master dress IDs
        # (for example the common costume ``24``) are valid; they only lack
        # enough information for this fallback path.
        outfit_main, outfit_suffix_fallback = self._get_character_outfit_main_suffix(
            outfit_id
        )
        if not dress_data and (not outfit_main or not outfit_suffix_fallback):
            return []

        # Determine the authoritative suffix (body_type_sub from DB or fallback)
        if dress_data:
            asset_suffix = dress_data.get("body_type_sub", "00").zfill(2)
        else:
            asset_suffix = outfit_suffix_fallback

        # UmaViewer distinguishes common costumes by dress_data.chara_id,
        # not by the presentation dress ID.  The latter may be as short as
        # ``24`` and therefore cannot reliably encode a character ID.
        is_generic = (
            dress_data is not None
            and dress_data.get("chara_id") not in (None, str(chara_id))
        ) or (dress_data is None and self._is_generic_costume(chara_id, outfit_id))

        # Character-specific legacy assets commonly store subtype 01 under
        # the shared _00 bundle.  Generic costumes do not follow that rule:
        # e.g. dress 51 (bdy0017_00) and 52 (bdy0017_01) are distinct.
        if not is_generic and asset_suffix == "01":
            asset_suffix = "00"

        if is_mini:
            mini_body_main = (
                dress_data.get("body_type", "").zfill(4)
                if is_generic and dress_data
                else outfit_main
            )
            mini_head_suffix = "00" if is_generic else asset_suffix
            return [
                {
                    "label": "body",
                    "logical_path": f"3d/chara/mini/body/mbdy{mini_body_main}_{asset_suffix}/pfb_mbdy{mini_body_main}_{asset_suffix}",
                    "animator_name": f"pfb_mbdy{mini_body_main}_{asset_suffix}",
                    "texture_prefix": f"tex_mbdy{mini_body_main}_{asset_suffix}_",
                    "is_mini": True,
                    "allow_candidate_fallback": not is_generic,
                },
                {
                    "label": "head",
                    "logical_path": f"3d/chara/mini/head/mchr{chara_id}_{mini_head_suffix}/pfb_mchr{chara_id}_{mini_head_suffix}_hair",
                    "animator_name": f"pfb_mchr{chara_id}_{mini_head_suffix}_hair",
                    "texture_prefix": f"tex_mchr{chara_id}_{mini_head_suffix}_",
                    "is_mini": True,
                    "allow_candidate_fallback": not is_generic,
                },
            ]

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

        # UmaViewer uses the default character head for common body outfits;
        # only character-specific costumes select a matching head subtype.
        head_suffix = "00" if is_generic else asset_suffix

        return [
            {
                "label": "body",
                "logical_path": body_path,
                "animator_name": body_animator,
                "texture_prefix": body_texture_prefix,
                "texture_export_prefix": body_texture_export_prefix,
                "allow_candidate_fallback": not is_generic,
            },
            {
                "label": "head",
                "logical_path": f"3d/chara/head/chr{chara_id}_{head_suffix}/pfb_chr{chara_id}_{head_suffix}",
                "animator_name": f"pfb_chr{chara_id}_{head_suffix}",
                "allow_candidate_fallback": not is_generic,
            },
        ]

    def _resolve_character_tail_target(self, chara_id, outfit_id=None, is_mini=False):
        if not chara_id or not self.app.db:
            return None

        if is_mini:
            return self._resolve_character_mini_tail_target(chara_id)

        # UmaViewer first tries a character-and-costume-specific tail before
        # falling back to the shared tail with a character texture.
        _, outfit_suffix = self._get_character_outfit_main_suffix(outfit_id)
        if outfit_suffix:
            folder_name = f"tail{chara_id}_{outfit_suffix}"
            exclusive_path = f"3d/chara/tail/{folder_name}/pfb_{folder_name}"
            if self.app.db.get_asset_by_path(exclusive_path) is not None:
                return {
                    "label": "tail",
                    "logical_path": exclusive_path,
                    "animator_name": f"pfb_{folder_name}",
                    "texture_prefix": f"tex_{folder_name}_",
                }

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

    def _append_character_runtime_export_targets(
        self, export_configs, chara_id, is_mini=False
    ):
        """Include the runtime assets UmaViewer needs to assemble a character.

        The locator drives facial keys and the idle motion establishes the
        character animation rig.  They are optional in old game data, but
        when available they must be handed to AssetStudio with the model
        dependencies so the character export is complete.
        """
        if not self.app.db:
            return

        motion_path = (
            f"3d/motion/mini/event/body/chara/chr{chara_id}_00/"
            f"anm_min_eve_chr{chara_id}_00_idle01_loop"
            if is_mini
            else f"3d/motion/event/body/chara/chr{chara_id}_00/"
            f"anm_eve_chr{chara_id}_00_idle01_loop"
        )
        for logical_path in ("3d/animator/drivenkeylocator", motion_path):
            asset = self.app.db.get_asset_by_path(logical_path)
            if asset is None:
                continue
            paths, bundle_keys = self._get_recursive_export_inputs(asset.get("id"))
            if not paths:
                phys_path = os.path.join(
                    Config.get_data_root(), asset["hash"][:2], asset["hash"]
                )
                if not os.path.exists(phys_path):
                    continue
                paths, bundle_keys = [phys_path], [asset.get("key")]
            export_configs.append({"physical_paths": paths, "bundle_keys": bundle_keys})

    def _resolve_character_mini_tail_target(self, chara_id):
        if not chara_id or not self.app.db:
            return None

        for tail_id in ("0001", "0002"):
            for asset_prefix in ("mtail", "tail"):
                texture_name = f"tex_{asset_prefix}{tail_id}_00_{chara_id}_diff"
                texture_path = (
                    f"3d/chara/mini/tail/{asset_prefix}{tail_id}_00/"
                    f"textures/{texture_name}"
                )
                texture_asset = self.app.db.get_asset_by_path(texture_path)
                if texture_asset is None:
                    continue

                folder_name = f"{asset_prefix}{tail_id}_00"
                return {
                    "label": "tail",
                    "logical_path": f"3d/chara/mini/tail/{folder_name}/pfb_{folder_name}",
                    "animator_name": f"pfb_{folder_name}",
                    "texture_prefix": f"tex_{folder_name}_{chara_id}_",
                    "is_mini": True,
                }

        # Fallback for naming variations: infer the tail folder from any mini tail
        # texture that embeds the character id, then look for pfb_<folder> beside it.
        texture_assets = self.app.db.get_assets_by_prefix("3d/chara/mini/tail/")
        for texture_asset in texture_assets:
            full_path = texture_asset.get("full_path", "")
            if "/textures/" not in full_path:
                continue

            texture_name = full_path.rsplit("/", 1)[-1]
            chara_marker = f"_{chara_id}_"
            if chara_marker not in texture_name:
                continue

            base_dir = full_path.split("/textures/", 1)[0]
            folder_name = base_dir.rsplit("/", 1)[-1]
            animator_name = f"pfb_{folder_name}"
            model_path = f"{base_dir}/{animator_name}"
            if self.app.db.get_asset_by_path(model_path) is None:
                continue

            texture_prefix = texture_name.split(chara_marker, 1)[0] + chara_marker
            return {
                "label": "tail",
                "logical_path": model_path,
                "animator_name": animator_name,
                "texture_prefix": texture_prefix,
                "is_mini": True,
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

    def _matches_character_clothes_object(self, label, object_name, is_mini=False):
        if not object_name:
            return False

        if is_mini:
            object_name_lower = object_name.lower()
            if "cloth" in object_name_lower:
                return True
            return label == "body" and "skirt" in object_name_lower

        # Only export the specific clothes MonoBehaviour wrappers that mirror
        # the filenames we care about for body/head/tail exports.
        patterns = {
            "body": [
                r"^ast_bdy\d{4}_\d{2}_skirt\d{2}$",
                r"^pfb_bdy\d{4}_\d{2}_bust_cloth\d{2}$",
                r"^pfb_bdy\d{4}_\d{2}_cloth\d{2}$",
            ],
            "head": [r"^pfb_chr\d{4}_\d{2}_cloth\d{2}$"],
            "tail": [r"^pfb_tail\d{4}_\d{2}_cloth\d{2}$"],
        }

        return any(
            re.match(pattern, object_name) for pattern in patterns.get(label, [])
        )

    def _find_monobehaviour_by_name(self, physical_path, object_name, bundle_key=None):
        if not object_name:
            return None

        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            for asset in env.assets:
                for obj in asset.objects.values():
                    if obj.type.name != "MonoBehaviour":
                        continue
                    try:
                        data = obj.read()
                    except Exception:
                        continue

                    current_name = getattr(data, "m_Name", None)
                    if current_name == object_name:
                        return obj.path_id
            return None
        except Exception as e:
            print(f"Find monobehaviour error for {object_name}: {e}")
            return None

    def _find_monobehaviour_by_script_name(
        self, physical_path, script_name, bundle_key=None
    ):
        if not script_name:
            return None

        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            for asset in env.assets:
                for obj in asset.objects.values():
                    if obj.type.name != "MonoBehaviour":
                        continue
                    try:
                        data = obj.read()
                    except Exception:
                        continue

                    script_ptr = getattr(data, "m_Script", None)
                    if not script_ptr:
                        continue
                    try:
                        script_reader = script_ptr.deref()
                    except Exception:
                        script_reader = None
                    if not script_reader:
                        continue

                    try:
                        current_script_name = script_reader.peek_name()
                    except Exception:
                        current_script_name = None
                    if current_script_name == script_name:
                        return obj.path_id
            return None
        except Exception as e:
            print(f"Find monobehaviour by script error for {script_name}: {e}")
            return None

    def _export_character_clothes_monobehaviours(
        self, target_dir, asset, label, is_mini=False
    ):
        if not asset or not self.app.db:
            return 0

        base_dir = asset["full_path"].rsplit("/", 1)[0]
        clothes_prefix = f"{base_dir}/clothes/"
        clothes_assets = self.app.db.get_assets_by_prefix(clothes_prefix)
        exported_count = 0
        exported_names = set()

        for clothes_asset in clothes_assets:
            object_name = clothes_asset["full_path"].rsplit("/", 1)[-1]
            if object_name in exported_names:
                continue
            if not self._matches_character_clothes_object(
                label, object_name, is_mini=is_mini
            ):
                continue

            phys_path = os.path.join(
                Config.get_data_root(),
                clothes_asset["hash"][:2],
                clothes_asset["hash"],
            )
            if not os.path.exists(phys_path):
                continue

            if object_name.startswith("pfb_"):
                path_id = self._find_monobehaviour_by_script_name(
                    phys_path,
                    "CySpringDataContainer",
                    bundle_key=clothes_asset.get("key"),
                )
            else:
                path_id = self._find_monobehaviour_by_name(
                    phys_path,
                    object_name,
                    bundle_key=clothes_asset.get("key"),
                )
            if path_id is None:
                continue

            success = UnityLogic.export_single_unity_object(
                phys_path,
                path_id,
                target_dir,
                object_type="MonoBehaviour",
                object_name=object_name,
                bundle_key=clothes_asset.get("key"),
            )
            if success:
                exported_names.add(object_name)
                exported_count += 1

        return exported_count

    def _export_character_flare_monobehaviour(self, target_dir, asset, label):
        """Export the component flare MonoBehaviour beside body/head/tail exports.

        Character component flare bundles live under the component directory:
        - 3d/chara/body/bdyXXXX_YY/flares/ast_bdyXXXX_YY_flare
        - 3d/chara/head/chrXXXX_YY/flares/ast_chrXXXX_YY_flare
        - 3d/chara/tail/tailXXXX_YY/flares/ast_tailXXXX_YY_flare

        The MonoBehaviour to export has the same name as the flare bundle file.
        Missing flare bundles are treated as optional, matching clothes export behavior.
        """
        if not asset or not self.app.db:
            return 0

        expected_prefixes = {
            "body": "bdy",
            "head": "chr",
            "tail": "tail",
        }
        expected_prefix = expected_prefixes.get(label)
        if expected_prefix is None:
            return 0

        base_dir = asset["full_path"].rsplit("/", 1)[0]
        folder_name = base_dir.rsplit("/", 1)[-1]
        if not folder_name.startswith(expected_prefix):
            return 0

        object_name = f"ast_{folder_name}_flare"
        flare_path = f"{base_dir}/flares/{object_name}"
        flare_asset = self.app.db.get_asset_by_path(flare_path)
        if flare_asset is None:
            return 0

        flare_hash = flare_asset.get("hash")
        if not flare_hash:
            return 0

        phys_path = os.path.join(
            Config.get_data_root(),
            flare_hash[:2],
            flare_hash,
        )
        if not os.path.exists(phys_path):
            return 0

        path_id = UnityLogic.find_monobehaviour_by_name(
            phys_path,
            object_name,
            bundle_key=flare_asset.get("key"),
        )
        if path_id is None:
            return 0

        success = UnityLogic.export_single_unity_object(
            phys_path,
            path_id,
            target_dir,
            object_type="MonoBehaviour",
            object_name=object_name,
            bundle_key=flare_asset.get("key"),
        )
        return 1 if success else 0

    def _export_character_animator_group(
        self, target_dir, chara_id, outfit_id, is_mini=False
    ):
        targets = self._build_character_export_targets(
            chara_id, outfit_id, is_mini=is_mini
        )
        tail_target = self._resolve_character_tail_target(
            chara_id, outfit_id, is_mini=is_mini
        )
        if tail_target is not None:
            targets.append(tail_target)
        if not targets or not self.app.db:
            return False

        export_configs = []
        texture_exports = 0

        for target in targets:
            asset = self.app.db.get_asset_by_path(target["logical_path"])
            animator_name = target["animator_name"]

            if asset is None and target.get("allow_candidate_fallback", False):
                candidates = self.app.db.find_character_component_candidates(
                    target["label"], chara_id, outfit_id, is_mini=is_mini
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
            texture_exports += self._export_character_clothes_monobehaviours(
                target_dir,
                asset,
                target["label"],
                is_mini=is_mini,
            )
            if not is_mini:
                texture_exports += self._export_character_flare_monobehaviour(
                    target_dir,
                    asset,
                    target["label"],
                )

            if target["label"] == "head" and not is_mini:
                texture_exports += self._export_head_facial_target(
                    target_dir, phys_path, asset, target
                )

        self._append_character_runtime_export_targets(
            export_configs, chara_id, is_mini=is_mini
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
