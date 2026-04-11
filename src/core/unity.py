import os
import shutil
import subprocess
import tempfile
import json
from functools import lru_cache

import numpy as np

import UnityPy

from src.core.decryptor import decrypt_bundle, DEFAULT_KEY
from src.core.config import Config
from src.core.utils import is_nuitka

# Store original load_file to wrap it
_orig_load_file = UnityPy.Environment.load_file


def _custom_load_file(self, file, is_dependency=False, name=None):
    """Custom load_file for UnityPy that handles UMA decryption."""
    if isinstance(file, str):
        # Resolve path if it's relative
        phys_path = file
        if not os.path.exists(phys_path) and self.path:
            phys_path = os.path.join(self.path, file)

        if os.path.exists(phys_path):
            data_root = Config.get_data_root()
            if phys_path.startswith(data_root):
                # Try to get key for this file
                key = UnityLogic.get_key_for_path(phys_path)
                decrypted_data = UnityLogic._load_bundle_data(phys_path, bundle_key=key)
                if decrypted_data:
                    # Pass the decrypted bytes directly to original load_file
                    return _orig_load_file(
                        self,
                        decrypted_data,
                        is_dependency=is_dependency,
                        name=name or os.path.basename(file),
                    )
    return _orig_load_file(self, file, is_dependency=is_dependency, name=name)


# Apply monkey patch to the class
UnityPy.Environment.load_file = _custom_load_file
UnityPy.environment.Environment.load_file = _custom_load_file


class UnityLogic:
    _key_provider = None

    @staticmethod
    def set_key_provider(provider):
        UnityLogic._key_provider = provider

    @staticmethod
    def clear_runtime_caches():
        UnityLogic._load_env.cache_clear()
        UnityLogic.get_unity_assets.cache_clear()

    @staticmethod
    def get_key_for_path(physical_path):
        if UnityLogic._key_provider:
            # Extract hash from path (it's the filename)
            f_hash = os.path.basename(physical_path)
            return UnityLogic._key_provider(f_hash)
        return None

    @staticmethod
    def _sanitize_export_name(name):
        if not name:
            return None
        sanitized = str(name).strip()
        if not sanitized:
            return None
        for ch in '<>:"/\\|?*':
            sanitized = sanitized.replace(ch, "_")
        return sanitized.rstrip(". ") or None

    @staticmethod
    def _load_bundle_data(physical_path, bundle_key=None):
        """Read bundle data and decrypt."""
        if not os.path.exists(physical_path):
            return None

        try:
            # Use provided key if available, else fallback to default
            decryption_key = DEFAULT_KEY
            if bundle_key is not None and str(bundle_key).strip() != "":
                try:
                    decryption_key = int(bundle_key)
                except ValueError, TypeError:
                    pass

            with open(physical_path, "rb") as f:
                data = bytearray(f.read())

            decrypted = decrypt_bundle(data, region=Config.REGION, key=decryption_key)

            # Convert to bytes because bytearray is unhashable and causes UnityPy to fail in some Python versions
            return bytes(decrypted)
        except Exception as e:
            print(f"Error decrypting bundle {physical_path}: {e}")
            return None

    @staticmethod
    @lru_cache(maxsize=2)
    def _load_env(physical_path, bundle_key=None):
        """Internal cached loader for Unity environments"""
        data = UnityLogic._load_bundle_data(physical_path, bundle_key=bundle_key)
        if data is None:
            raise FileNotFoundError(physical_path)
        return UnityPy.load(data)

    @staticmethod
    @lru_cache(maxsize=16)
    def get_unity_assets(physical_path, bundle_key=None):
        """Analyze Unity AssetBundle and return object list"""
        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)

            assets_info = []
            for obj in env.objects:
                # ... rest of the loop remains same ...
                if obj.type.name in [
                    "AssetBundle",
                    "PreloadData",
                    "Transform",
                    "MeshFilter",
                ]:
                    continue

                try:
                    data = obj.parse_as_object()
                    name = getattr(data, "m_Name", "Unnamed")

                    if (
                        obj.type.name
                        in [
                            "Renderer",
                            "MeshRenderer",
                            "SkinnedMeshRenderer",
                            "Animator",
                        ]
                        and data.m_GameObject
                    ):
                        game_obj_reader = data.m_GameObject.deref()
                        name = game_obj_reader.peek_name()

                    assets_info.append((obj.type.name, name, obj.path_id))
                except:
                    assets_info.append((obj.type.name, "Unparsable", obj.path_id))

            assets_info.sort(key=lambda x: (x[0], x[1]))
            return tuple(assets_info)
        except FileNotFoundError:
            print(f"Asset file not found (likely not downloaded): {physical_path}")
            return ()
        except Exception as e:
            print(f"Error getting unity assets for {physical_path}: {e}")
            import traceback

            traceback.print_exc()
            return ()

    @staticmethod
    def save_mesh_to_tmp(physical_path, path_id, bundle_key=None):
        """Extract Unity Mesh and save to a temporary .obj file (For Preview Only)"""
        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            target_obj = None
            for asset in env.assets:
                if path_id in asset.objects:
                    target_obj = asset.objects[path_id]
                    break

            if not target_obj or target_obj.type.name != "Mesh":
                return None

            data = target_obj.parse_as_object()
            if not hasattr(data, "export"):
                return None

            mesh_data = data.export()
            tmp_file = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
            tmp_file.write(
                mesh_data.encode("utf-8") if isinstance(mesh_data, str) else mesh_data
            )
            tmp_file.close()
            return tmp_file.name
        except:
            return None

    @staticmethod
    def save_animator_to_tmp(
        physical_paths, object_name=None, bundle_keys=None, logical_file_name=None
    ):
        """Export Animator to FBX in a temporary folder using CLI (For Preview)"""
        tmp_export_dir = tempfile.mkdtemp()
        try:
            UnityLogic._export_via_cli(
                physical_paths, tmp_export_dir, mode="animator", bundle_keys=bundle_keys
            )

            # AssetStudioModCLI Animator mode structure: FBX_Animator/{logical_file_name}/{object_name}.fbx
            animator_dir = os.path.join(tmp_export_dir, "FBX_Animator")

            # 1. Direct addressing (Efficient)
            if logical_file_name and object_name:
                sanitized_obj = UnityLogic._sanitize_export_name(object_name)
                # Try with logical_file_name as provided (might be basename already)
                direct_path = os.path.join(
                    animator_dir, logical_file_name, f"{sanitized_obj}.fbx"
                )
                if os.path.exists(direct_path):
                    return direct_path

                # Try with basename of logical_file_name
                base_logical = os.path.basename(logical_file_name)
                direct_path = os.path.join(
                    animator_dir, base_logical, f"{sanitized_obj}.fbx"
                )
                if os.path.exists(direct_path):
                    return direct_path

            # 2. Fallback: Scoped os.walk search (Efficient and Robust)
            fbx_files = []
            sanitized_obj_lower = (
                UnityLogic._sanitize_export_name(object_name).lower()
                if object_name
                else None
            )

            for root, _, files in os.walk(animator_dir):
                for f in files:
                    if f.lower().endswith(".fbx"):
                        full_path = os.path.join(root, f)
                        # If we find a filename match, return immediately
                        if sanitized_obj_lower and sanitized_obj_lower in f.lower():
                            return full_path
                        fbx_files.append(full_path)

            if fbx_files:
                return fbx_files[0]

            return None
        except Exception as e:
            print(f"Animator preview error: {e}")
            return None

    @staticmethod
    def get_texture_data(physical_path, path_id, bundle_key=None, max_dim=None):
        """Extract Unity texture and convert to raw RGBA float32 for DPG."""
        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            target_obj = None
            for asset in env.assets:
                if path_id in asset.objects:
                    target_obj = asset.objects[path_id]
                    break

            if not target_obj:
                return None, 0, 0

            data = target_obj.read()
            if not hasattr(data, "image"):
                return None, 0, 0

            img = data.image.convert("RGBA")

            # Optional resizing for preview performance
            if max_dim:
                w, h = img.size
                if w > max_dim or h > max_dim:
                    if w > h:
                        new_w = max_dim
                        new_h = int(h * (max_dim / w))
                    else:
                        new_h = max_dim
                        new_w = int(w * (max_dim / h))
                    from PIL import Image

                    # Use BILINEAR for speed in preview mode
                    img = img.resize((new_w, new_h), resample=Image.BILINEAR)

            width, height = img.size
            # Convert to float32 early in background
            data_np = np.array(img, dtype=np.float32)
            data_np /= 255.0
            return data_np.ravel(), width, height
        except Exception as e:
            import traceback

            traceback.print_exc()
            raise e

    @staticmethod
    def export_named_texture_to_png(
        physical_path, texture_name, output_path, bundle_key=None
    ):
        """Export a Texture2D whose m_Name matches the file name to a PNG cache."""
        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            for asset in env.assets:
                for obj in asset.objects.values():
                    if obj.type.name != "Texture2D":
                        continue
                    try:
                        data = obj.read()
                    except Exception:
                        continue

                    if getattr(data, "m_Name", None) != texture_name:
                        continue
                    if not hasattr(data, "image"):
                        continue

                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    data.image.save(output_path)
                    return output_path
            return None
        except Exception as e:
            print(f"Named texture export error for {texture_name}: {e}")
            return None

    @staticmethod
    def get_named_texture_data(
        physical_path, texture_name, bundle_key=None, max_size=None
    ):
        """Extract a named Texture2D and return RGBA float data for immediate UI display."""
        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            for asset in env.assets:
                for obj in asset.objects.values():
                    if obj.type.name != "Texture2D":
                        continue
                    try:
                        data = obj.read()
                    except Exception:
                        continue

                    if getattr(data, "m_Name", None) != texture_name:
                        continue
                    if not hasattr(data, "image"):
                        continue

                    img = data.image.convert("RGBA")
                    if max_size:
                        from PIL import Image, ImageOps

                        resample_filter = getattr(Image, "Resampling", Image).BILINEAR
                        img = ImageOps.contain(
                            img, (max_size, max_size), method=resample_filter
                        )
                        canvas = Image.new("RGBA", (max_size, max_size), (0, 0, 0, 0))
                        paste_x = (max_size - img.width) // 2
                        paste_y = (max_size - img.height) // 2
                        canvas.paste(img, (paste_x, paste_y), img)
                        img = canvas

                    width, height = img.size
                    data_np = np.array(img, dtype=np.float32)
                    data_np /= 255.0
                    return data_np.ravel(), width, height
            return None, 0, 0
        except Exception as e:
            print(f"Named texture load error for {texture_name}: {e}")
            return None, 0, 0

    @staticmethod
    def find_named_animator(physical_path, animator_name, bundle_key=None):
        """Find an Animator by m_Name within a bundle."""
        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            animator_candidates = []
            for asset in env.assets:
                for obj in asset.objects.values():
                    if obj.type.name != "Animator":
                        continue
                    try:
                        data = obj.parse_as_object()
                    except Exception:
                        continue

                    current_name = getattr(data, "m_Name", None)
                    game_object_name = None
                    game_object = getattr(data, "m_GameObject", None)
                    if game_object:
                        try:
                            game_object_name = game_object.deref().peek_name()
                        except Exception:
                            game_object_name = None

                    animator_candidates.append(
                        {
                            "path_id": obj.path_id,
                            "m_name": current_name,
                            "game_object_name": game_object_name,
                        }
                    )

                    if (
                        current_name == animator_name
                        or game_object_name == animator_name
                    ):
                        return obj.path_id

            if len(animator_candidates) == 1:
                return animator_candidates[0]["path_id"]
            return None
        except Exception as e:
            print(f"Find animator error for {animator_name}: {e}")
            return None

    @staticmethod
    def find_monobehaviour_by_name(physical_path, monobehaviour_name, bundle_key=None):
        """Find a MonoBehaviour by m_Name within a bundle."""
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
                    if current_name == monobehaviour_name:
                        return obj.path_id
            return None
        except Exception as e:
            print(f"Find monobehaviour error for {monobehaviour_name}: {e}")
            return None

    @staticmethod
    def get_monobehaviour_preview(physical_path, path_id, bundle_key=None):
        """Build a readable MonoBehaviour preview using its m_Script reference."""
        try:
            env = UnityLogic._load_env(physical_path, bundle_key=bundle_key)
            target_obj = None
            for asset in env.assets:
                if path_id in asset.objects:
                    target_obj = asset.objects[path_id]
                    break

            if not target_obj or target_obj.type.name != "MonoBehaviour":
                return None

            parsed = target_obj.read()
            lines = ["Type: MonoBehaviour"]

            mono_name = getattr(parsed, "m_Name", None)
            if mono_name:
                lines.append(f"Name: {mono_name}")

            script_ptr = getattr(parsed, "m_Script", None)
            script_reader = None
            if script_ptr:
                try:
                    script_reader = script_ptr.deref()
                except Exception:
                    script_reader = None

            if script_reader:
                lines.append("")
                lines.append("[m_Script]")

                script_name = None
                try:
                    script_name = script_reader.peek_name()
                except Exception:
                    script_name = None
                if script_name:
                    lines.append(f"Name: {script_name}")

                script_tree = None
                try:
                    script_tree = script_reader.read_typetree(wrap=False)
                except Exception:
                    script_tree = None

                if isinstance(script_tree, dict):
                    for label, key in (
                        ("Class", "m_ClassName"),
                        ("Namespace", "m_Namespace"),
                        ("Assembly", "m_AssemblyName"),
                    ):
                        value = script_tree.get(key)
                        if value not in (None, ""):
                            lines.append(f"{label}: {value}")

                    script_body = (
                        script_tree.get("m_Script")
                        or script_tree.get("m_Text")
                        or script_tree.get("m_Source")
                    )
                    if script_body not in (None, ""):
                        lines.append("")
                        lines.append("[Script Content]")
                        lines.append(str(script_body))
                else:
                    lines.append("Unable to read MonoScript typetree.")
            else:
                lines.append("")
                lines.append("m_Script: <missing or unresolved>")

            behaviour_tree = None
            try:
                behaviour_tree = target_obj.read_typetree(wrap=False)
            except Exception:
                behaviour_tree = None

            if behaviour_tree:
                lines.append("")
                lines.append("[MonoBehaviour Data]")
                lines.append(
                    json.dumps(
                        behaviour_tree,
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    )
                )

            return "\n".join(lines)
        except Exception as e:
            print(f"MonoBehaviour preview error: {e}")
            return None

    @staticmethod
    def export_unity_assets(physical_paths, export_dir, bundle_keys=None):
        """Optimized entry point for exporting Unity assets"""
        if not physical_paths:
            return 0

        try:
            # Map paths to keys for easier retrieval
            key_map = {}
            if isinstance(bundle_keys, dict):
                key_map = bundle_keys
            elif isinstance(bundle_keys, (list, tuple)):
                for i, p in enumerate(physical_paths):
                    if i < len(bundle_keys):
                        key_map[p] = bundle_keys[i]

            # For multi-path load, we need to handle decryption for each
            loaded_data = []
            for p in physical_paths:
                data = UnityLogic._load_bundle_data(p, bundle_key=key_map.get(p))
                if data is not None:
                    loaded_data.append(data)

            if not loaded_data:
                return 0

            env = UnityPy.load(*loaded_data)
            os.makedirs(export_dir, exist_ok=True)
            count = 0

            # Check for Animator objects to use specialized CLI export
            has_animator = False
            for asset in env.assets:
                for obj in asset.objects.values():
                    if obj.type.name == "Animator":
                        has_animator = True
                        break
                if has_animator:
                    break

            if has_animator:
                print("Animator detected, using AssetStudioModCLI for export...")
                cli_count = UnityLogic._export_via_cli(
                    physical_paths, export_dir, mode="animator", bundle_keys=bundle_keys
                )
                count += cli_count

            # We always check for other assets too, but maybe avoid Mesh if we already did FBX
            for asset in env.assets:
                for obj in asset.objects.values():
                    if obj.type.name in ["AssetBundle", "PreloadData"]:
                        continue

                    try:
                        data = obj.parse_as_object()
                        name = getattr(data, "m_Name", f"Unnamed_{obj.path_id}")

                        if obj.type.name in ["Texture2D", "Sprite"] and hasattr(
                            data, "image"
                        ):
                            UnityLogic._save_asset(
                                export_dir, obj.type.name, f"{name}.png", data.image
                            )
                            count += 1
                        elif obj.type.name == "TextAsset" and hasattr(data, "m_Script"):
                            UnityLogic._save_asset(
                                export_dir, "TextAsset", f"{name}.txt", data.m_Script
                            )
                            count += 1
                        elif obj.type.name == "Mesh" and hasattr(data, "export"):
                            # Simple OBJ export for static meshes in non-animator bundles
                            UnityLogic._save_asset(
                                export_dir, "Mesh", f"{name}.obj", data.export()
                            )
                            count += 1
                        elif obj.type.name == "AudioClip" and hasattr(data, "samples"):
                            for sample in data.samples:
                                UnityLogic._save_asset(
                                    export_dir, "AudioClip", f"{name}.wav", sample
                                )
                    except:
                        continue
            print(f"Export completed. Total {count} items saved to {export_dir}")
            return count
        except Exception as e:
            print(f"Global export error: {e}")
            return 0

    @staticmethod
    def export_single_unity_object(
        physical_path,
        path_id,
        export_dir,
        object_type=None,
        object_name=None,
        bundle_key=None,
    ):
        """Export a single Unity object by path_id from one bundle."""
        if not physical_path or path_id is None or not export_dir:
            return False

        try:
            data = UnityLogic._load_bundle_data(physical_path, bundle_key=bundle_key)
            if data is None:
                return

            env = UnityPy.load(data)
            os.makedirs(export_dir, exist_ok=True)

            for asset in env.assets:
                if path_id not in asset.objects:
                    continue

                obj = asset.objects[path_id]
                try:
                    parsed = obj.parse_as_object()
                except Exception:
                    parsed = None

                name = object_name
                if not name and parsed is not None:
                    name = getattr(parsed, "m_Name", None)
                if not name:
                    name = f"Unnamed_{path_id}"

                safe_name = (
                    UnityLogic._sanitize_export_name(name) or f"Unnamed_{path_id}"
                )
                obj_type = object_type or obj.type.name

                if obj_type == "Animator":
                    UnityLogic.export_animator_with_dependencies(
                        [physical_path],
                        export_dir,
                        bundle_keys={physical_path: bundle_key},
                    )
                    return True

                if (
                    obj_type in ["Texture2D", "Sprite"]
                    and parsed is not None
                    and hasattr(parsed, "image")
                ):
                    UnityLogic._save_asset(
                        export_dir, obj_type, f"{safe_name}.png", parsed.image
                    )
                    return True
                if (
                    obj_type == "TextAsset"
                    and parsed is not None
                    and hasattr(parsed, "m_Script")
                ):
                    UnityLogic._save_asset(
                        export_dir, "TextAsset", f"{safe_name}.txt", parsed.m_Script
                    )
                    return True
                if (
                    obj_type == "Mesh"
                    and parsed is not None
                    and hasattr(parsed, "export")
                ):
                    UnityLogic._save_asset(
                        export_dir, "Mesh", f"{safe_name}.obj", parsed.export()
                    )
                    return True
                if (
                    obj_type == "AudioClip"
                    and parsed is not None
                    and hasattr(parsed, "samples")
                ):
                    for idx, sample in enumerate(parsed.samples):
                        suffix = f"_{idx}" if len(parsed.samples) > 1 else ""
                        UnityLogic._save_asset(
                            export_dir,
                            "AudioClip",
                            f"{safe_name}{suffix}.wav",
                            sample,
                        )
                    return True
                if obj_type == "MonoBehaviour" and parsed is not None:
                    # Export MonoBehaviour data as JSON directly to export_dir
                    try:
                        import json

                        type_tree = obj.read_typetree(wrap=False)
                        json_data = json.dumps(
                            type_tree, indent=2, ensure_ascii=False, default=str
                        )
                        save_path = os.path.join(export_dir, f"{safe_name}.json")
                        with open(save_path, "w", encoding="utf-8") as f:
                            f.write(json_data)
                        return True
                    except Exception as e:
                        print(f"MonoBehaviour export error: {e}")
                        return False
                return False
        except Exception as e:
            print(f"Single export error: {e}")
            return False

    @staticmethod
    def export_animator_with_dependencies(physical_paths, export_dir, bundle_keys=None):
        """Export animator(s) with AssetStudioModCLI using provided dependency paths."""
        if not physical_paths:
            return 0
        try:
            return UnityLogic._export_via_cli(
                physical_paths, export_dir, mode="animator", bundle_keys=bundle_keys
            )
        except Exception as e:
            print(f"Animator export error: {e}")
            return 0

    @staticmethod
    def batch_export_animators(export_configs, tmp_root):
        """
        High-performance batch export.
        export_configs: List of dicts { "physical_paths": [], "bundle_keys": [] }
        """
        os.makedirs(tmp_root, exist_ok=True)

        all_physical_paths = []
        all_bundle_keys = {}

        # 1. Collect all paths and keys
        for cfg in export_configs:
            paths = cfg.get("physical_paths", [])
            keys = cfg.get("bundle_keys", [])
            for i, p in enumerate(paths):
                if p not in all_physical_paths:
                    all_physical_paths.append(p)
                    if i < len(keys):
                        all_bundle_keys[p] = keys[i]

        # 2. Run CLI on the collected paths
        # _export_via_cli handles decryption and staging internally.
        # Export to a temporary directory first, then flatten all files into tmp_root.
        with tempfile.TemporaryDirectory() as export_dir:
            UnityLogic._export_via_cli(
                all_physical_paths,
                export_dir,
                mode="animator",
                bundle_keys=all_bundle_keys,
            )

            exported_files = 0
            for root, _, files in os.walk(export_dir):
                for file_name in files:
                    source_path = os.path.join(root, file_name)
                    target_path = os.path.join(tmp_root, file_name)

                    if os.path.exists(target_path):
                        base, ext = os.path.splitext(file_name)
                        counter = 1
                        while True:
                            candidate = os.path.join(tmp_root, f"{base}_{counter}{ext}")
                            if not os.path.exists(candidate):
                                target_path = candidate
                                break
                            counter += 1

                    shutil.move(source_path, target_path)
                    exported_files += 1

        return exported_files

    @staticmethod
    def batch_export_to_fbx(batch_configs, export_dir):
        """
        Efficiently exports multiple animators at once with parallel staging.
        """
        results = []
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as staging_dir:
            # 1. Collect all unique paths to prepare
            all_unique_tasks = {}  # Map path -> (key, target_filename)
            for cfg in batch_configs:
                paths = cfg.get("paths", [])
                keys = cfg.get("keys", [])
                for i, p in enumerate(paths):
                    if os.path.exists(p) and p not in all_unique_tasks:
                        all_unique_tasks[p] = (
                            keys[i] if i < len(keys) else None,
                            os.path.basename(p),
                        )

            # 2. Parallel Staging (Decryption + I/O)
            # 16 workers is usually a good balance for disk/CPU overlap
            def stage_file(path_info):
                p, info = path_info
                key, filename = info
                target = os.path.join(staging_dir, filename)
                try:
                    success = False
                    # All data is now encrypted, so we must decrypt before staging
                    data = UnityLogic._load_bundle_data(p, bundle_key=key)
                    if data:
                        with open(target, "wb") as f:
                            f.write(data)
                        success = True

                    if not success:
                        # Fallback for unexpected cases or decryption failure
                        try:
                            if hasattr(os, "symlink"):
                                os.symlink(p, target)
                            else:
                                os.link(p, target)
                        except:
                            shutil.copy2(p, target)
                    return True
                except Exception as e:
                    print(f"Failed to stage {p}: {e}")
                    return False

            with ThreadPoolExecutor(max_workers=16) as executor:
                list(executor.map(stage_file, all_unique_tasks.items()))

            # 3. Run CLI ONCE on the staging directory
            UnityLogic._run_as_cli(staging_dir, export_dir, mode="animator")

            # 3. Match exported FBX files back to assets
            # AS CLI structure: {export_dir}/FBX_Animator/{logical_name}/{animator_name}.fbx
            # Since we don't know animator_name here easily without parsing,
            # we'll look for files in subfolders that match the logical_name.

            animator_base = os.path.join(export_dir, "FBX_Animator")
            if not os.path.exists(animator_base):
                return results

            for cfg in batch_configs:
                asset_hash = cfg["hash"]
                logical_name = cfg.get("logical_name")
                if not logical_name:
                    continue

                # Look in {animator_base}/{logical_name}/
                search_dir = os.path.join(animator_base, logical_name)
                if os.path.exists(search_dir):
                    for f in os.listdir(search_dir):
                        if f.lower().endswith(".fbx"):
                            results.append((asset_hash, os.path.join(search_dir, f)))
                            break  # Take first one for thumbnail
                else:
                    # Fallback search if logical name mapping failed
                    # This is slower but robust
                    found = False
                    for root, dirs, files in os.walk(animator_base):
                        if logical_name in root:
                            for f in files:
                                if f.lower().endswith(".fbx"):
                                    results.append((asset_hash, os.path.join(root, f)))
                                    found = True
                                    break
                        if found:
                            break

        return results

    @staticmethod
    def _run_as_cli(input_path, output_dir, mode="animator"):
        cli_name = "AssetStudioModCLI"
        if os.name == "nt":
            cli_name += ".exe"

        cli_path = os.path.join(Config.get_bundle_dir(), "as_cli", cli_name)
        if not os.path.exists(cli_path):
            cli_path = os.path.abspath(os.path.join("as_cli", cli_name))

        if not os.path.exists(cli_path):
            return 0

        if os.name != "nt":
            try:
                os.chmod(cli_path, 0o755)
            except:
                pass

        cmd = [
            cli_path,
            input_path,
            "--mode",
            mode,
            "--output",
            output_dir,
            "--fbx-animation",
            "auto",
        ]

        # Prepare creationflags for Windows to hide terminal window
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            if is_nuitka():
                env = os.environ.copy()
                env["NUITKA_SELF_EXECUTION"] = "0"
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                    creationflags=creationflags,
                )
            else:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    creationflags=creationflags,
                )
            return True
        except Exception as e:
            print(f"AS CLI Error: {e}")
            return False

    @staticmethod
    def _export_via_cli(physical_paths, export_dir, mode="animator", bundle_keys=None):
        """Export assets using AssetStudioModCLI in a temporary directory"""
        if isinstance(physical_paths, str) and os.path.isdir(physical_paths):
            # If a directory is passed, collect all files in it
            unique_paths = []
            for root, _, files in os.walk(physical_paths):
                for f in files:
                    unique_paths.append(os.path.join(root, f))
        else:
            # Deduplicate paths to avoid duplicate link attempts
            unique_paths = list(dict.fromkeys(physical_paths))

        exported_count = 0

        # Map paths to keys for easier retrieval
        key_map = {}
        if isinstance(bundle_keys, dict):
            key_map = bundle_keys
        elif isinstance(bundle_keys, (list, tuple)):
            for i, p in enumerate(physical_paths):
                if i < len(bundle_keys):
                    key_map[p] = bundle_keys[i]

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Decrypt and save all files to temporary directory
            for p in unique_paths:
                if not os.path.exists(p):
                    continue
                target = os.path.join(tmp_dir, os.path.basename(p))

                # Skip if already exists
                if os.path.exists(target):
                    continue

                try:
                    success = False
                    # All data is now encrypted, so we must decrypt first
                    data = UnityLogic._load_bundle_data(p, bundle_key=key_map.get(p))
                    if data:
                        with open(target, "wb") as f:
                            f.write(data)
                        success = True

                    if not success:
                        # Link/Copy for unencrypted files or decryption failure
                        if hasattr(os, "symlink"):
                            os.symlink(p, target)
                        else:
                            os.link(p, target)
                except Exception:
                    # Fallback to copy if linking/decryption fails
                    try:
                        shutil.copy2(p, target)
                    except shutil.SameFileError:
                        pass
                    except Exception as e2:
                        print(f"Warning: Failed to prepare {p}: {e2}")

            cli_name = "AssetStudioModCLI"
            if os.name == "nt":
                cli_name += ".exe"

            # Use bundle root to find as_cli
            cli_path = os.path.join(Config.get_bundle_dir(), "as_cli", cli_name)
            if not os.path.exists(cli_path):
                # Fallback to CWD for development
                cli_path = os.path.abspath(os.path.join("as_cli", cli_name))

            if not os.path.exists(cli_path):
                print(f"Error: AssetStudioModCLI not found at {cli_path}")
                return 0

            # Ensure executable on Unix-like systems
            if os.name != "nt":
                try:
                    os.chmod(cli_path, 0o755)
                except:
                    pass

            cmd = [
                cli_path,
                tmp_dir,
                "--mode",
                mode,
                "--output",
                export_dir,
                "--fbx-animation",
                "auto",  # Fix: value is required
            ]

            try:
                print(f"Running CLI command: {' '.join(cmd)}")
                # Scan BEFORE to compare
                pre_files = set()
                for root, _, files in os.walk(export_dir):
                    for f in files:
                        pre_files.add(os.path.join(root, f))

                # Prepare creationflags for Windows to hide terminal window
                creationflags = 0
                if os.name == "nt":
                    creationflags = subprocess.CREATE_NO_WINDOW

                # Disable Nuitka self-execution mechanism for subprocess calls
                if is_nuitka():
                    env = os.environ.copy()
                    env["NUITKA_SELF_EXECUTION"] = "0"
                    result = subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        text=True,
                        env=env,
                        creationflags=creationflags,
                    )
                else:
                    result = subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        text=True,
                        creationflags=creationflags,
                    )

                # Scan AFTER to count new files
                for root, dirs, files in os.walk(export_dir):
                    for f in files:
                        p = os.path.join(root, f)
                        if p not in pre_files:
                            exported_count += 1

                if exported_count == 0:
                    print("CLI finished but no new files were created. Output:")
                    print(result.stdout)

            except subprocess.CalledProcessError as e:
                print(f"AssetStudioModCLI failed with error: {e.stderr}")
            except Exception as e:
                print(f"Failed to run AssetStudioModCLI: {e}")

        return exported_count

    @staticmethod
    def _save_asset(base_dir, type_name, filename, content):
        target_dir = os.path.join(base_dir, type_name)
        os.makedirs(target_dir, exist_ok=True)
        save_path = os.path.join(target_dir, filename)

        if hasattr(content, "save"):
            content.save(save_path)
        else:
            mode = "w" if isinstance(content, str) else "wb"
            encoding = "utf-8" if isinstance(content, str) else None
            with open(save_path, mode, encoding=encoding) as f:
                f.write(content)
