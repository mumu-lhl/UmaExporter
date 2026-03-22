import os
import shutil
import subprocess
import tempfile
from functools import lru_cache

import numpy as np

import UnityPy

from src.decryptor import decrypt_bundle, DEFAULT_KEY
from src.constants import Config
from src.utils import is_nuitka

# Store original load_file to wrap it
_orig_load_file = UnityPy.Environment.load_file


def _custom_load_file(self, file, is_dependency=False, name=None):
    """Custom load_file for UnityPy that handles UMA decryption."""
    if Config.DB_ENCRYPTED and isinstance(file, str):
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
        """Read bundle data and decrypt if necessary."""
        if not os.path.exists(physical_path):
            return None

        if Config.DB_ENCRYPTED:
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

                decrypted = decrypt_bundle(
                    data, region=Config.REGION, key=decryption_key
                )

                # Convert to bytes because bytearray is unhashable and causes UnityPy to fail in some Python versions
                return bytes(decrypted)
            except Exception as e:
                print(f"Error decrypting bundle {physical_path}: {e}")
                return None
        else:
            return physical_path

    @staticmethod
    @lru_cache(maxsize=8)
    def _load_env(physical_path, bundle_key=None):
        """Internal cached loader for Unity environments"""
        data = UnityLogic._load_bundle_data(physical_path, bundle_key=bundle_key)
        if data is None:
            raise FileNotFoundError(physical_path)
        return UnityPy.load(data)

    @staticmethod
    @lru_cache(maxsize=64)
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
    def export_unity_assets(physical_paths, export_dir, bundle_keys=None):
        """Optimized entry point for exporting Unity assets"""
        if not physical_paths:
            return

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
                return

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
        except Exception as e:
            print(f"Global export error: {e}")

    @staticmethod
    def batch_export_animators(export_configs, tmp_root):
        """
        High-performance batch export.
        export_configs: List of dicts { "physical_paths": [], "bundle_keys": [] }
        """
        staging_dir = os.path.join(tmp_root, "batch_staging")
        export_dir = os.path.join(tmp_root, "batch_output")
        os.makedirs(staging_dir, exist_ok=True)
        os.makedirs(export_dir, exist_ok=True)

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
        # _export_via_cli handles decryption and staging internally
        UnityLogic._export_via_cli(
            all_physical_paths, export_dir, mode="animator", bundle_keys=all_bundle_keys
        )

        return export_dir

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
                    if Config.DB_ENCRYPTED:
                        data = UnityLogic._load_bundle_data(p, bundle_key=key)
                        if data:
                            with open(target, "wb") as f:
                                f.write(data)
                    else:
                        # Link for speed
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
                    if Config.DB_ENCRYPTED:
                        data = UnityLogic._load_bundle_data(
                            p, bundle_key=key_map.get(p)
                        )
                        if data:
                            with open(target, "wb") as f:
                                f.write(data)
                    else:
                        # Link/Copy for unencrypted files
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
