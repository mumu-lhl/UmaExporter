import os
import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor

import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.unity import UnityLogic
from src.core.i18n import i18n
from src.services.f3d.worker import generate_thumbnail
from src.services.thumbnail.manager import ThumbnailManager as thumb_manager


class BatchController:
    def __init__(self, app):
        self.app = app

    def on_stop_batch_click(self, sender, app_data, user_data):
        self.app.batch_stop_event.set()
        dpg.set_value("batch_status_msg", i18n("msg_batch_stopped"))
        dpg.configure_item("btn_stop_batch", enabled=False)

    def on_batch_cat_all_change(self, sender, app_data, user_data):
        is_all = dpg.get_value("batch_cat_all")
        if is_all:
            dpg.set_value("batch_cat_scene", True)
            dpg.set_value("batch_cat_prop", True)
            dpg.configure_item("batch_cat_scene", enabled=False)
            dpg.configure_item("batch_cat_prop", enabled=False)
        else:
            dpg.set_value("batch_cat_scene", False)
            dpg.set_value("batch_cat_prop", False)
            dpg.configure_item("batch_cat_scene", enabled=True)
            dpg.configure_item("batch_cat_prop", enabled=True)

        dpg.bind_item_theme("batch_cat_scene", "checkbox_state_theme")
        dpg.bind_item_theme("batch_cat_prop", "checkbox_state_theme")

    def on_start_batch_click(self, sender, app_data, user_data):
        if self.app.is_batch_running:
            return

        if not self.app.db:
            dpg.set_value("batch_status_msg", i18n("label_db_not_ready"))
            return

        cats = []
        if dpg.get_value("batch_cat_all"):
            cats.append("all")
        else:
            if dpg.get_value("batch_cat_scene"):
                cats.append("scene")
            if dpg.get_value("batch_cat_prop"):
                cats.append("prop")

        if not cats:
            dpg.set_value("batch_status_msg", "Please select at least one category.")
            return

        batch_size = dpg.get_value("batch_size")

        self.app.is_batch_running = True
        self.app.batch_stop_event.clear()
        dpg.configure_item("btn_start_batch", enabled=False)
        dpg.configure_item("btn_stop_batch", enabled=True)
        dpg.configure_item("batch_progress_bar", show=True, default_value=0.0)
        dpg.set_value("batch_progress_bar", 0.0)
        dpg.configure_item("batch_progress_text", show=True)
        dpg.set_value("batch_status_msg", "Scanning for assets...")

        self.app.executor.submit(self._run_batch_worker, cats, batch_size)

    def _run_batch_worker(self, cats, batch_size):
        try:
            raw_assets = self.app.db.get_all_animator_assets(cats)
            force_overwrite = dpg.get_value("batch_force_overwrite")

            existing_thumbnails = set()
            if not force_overwrite:
                thumb_dir = Config.get_thumbnail_dir()
                if os.path.exists(thumb_dir):
                    # Cache filenames (without .png) for quick lookup
                    existing_thumbnails = {
                        f[:-4] for f in os.listdir(thumb_dir) if f.endswith(".png")
                    }

            to_process = []
            for i_id, name, size, f_hash, key_val in raw_assets:
                if self.app.batch_stop_event.is_set():
                    break
                if force_overwrite or (f_hash not in existing_thumbnails):
                    to_process.append((i_id, name, f_hash))

            total_to_process = len(to_process)
            if total_to_process == 0:
                self.app._queue_ui_task(
                    lambda: self._finalize_batch(i18n("msg_batch_finished"))
                )
                return

            self.app._queue_ui_task(
                lambda: dpg.set_value(
                    "batch_status_msg",
                    f"Found {total_to_process} assets needing thumbnails.",
                )
            )

            processed_count = 0
            user_chunk_size = dpg.get_value("batch_size")
            chunk_size = user_chunk_size if user_chunk_size > 0 else 32

            chunks = [
                to_process[i : i + chunk_size]
                for i in range(0, total_to_process, chunk_size)
            ]
            progress_lock = threading.Lock()

            def process_one_chunk(chunk_data):
                nonlocal processed_count
                if self.app.batch_stop_event.is_set():
                    return

                batch_configs = []
                for asset_id, name, asset_hash in chunk_data:
                    deps = self.app.preview_controller._get_recursive_hashes(asset_id)
                    paths = []
                    keys = []
                    for h, k in deps:
                        p = os.path.join(Config.get_data_root(), h[:2], h)
                        if os.path.exists(p):
                            paths.append(p)
                            keys.append(k)

                    batch_configs.append(
                        {
                            "id": asset_id,
                            "hash": asset_hash,
                            "paths": paths,
                            "keys": keys,
                            "logical_name": os.path.basename(name),
                        }
                    )

                staging_base = (
                    "/dev/shm"
                    if os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK)
                    else None
                )

                with tempfile.TemporaryDirectory(dir=staging_base) as chunk_export_dir:
                    exported_results = UnityLogic.batch_export_to_fbx(
                        batch_configs, chunk_export_dir
                    )

                    batch_engine = None
                    try:
                        import f3d

                        batch_engine = f3d.Engine.create(offscreen=True)
                    except:
                        pass

                    for asset_hash, fbx_path in exported_results:
                        if self.app.batch_stop_event.is_set():
                            break

                        output_filename = f"{asset_hash}.png"
                        output_path = os.path.join(
                            Config.get_thumbnail_dir(), output_filename
                        )

                        if generate_thumbnail(
                            fbx_path, output_path, engine=batch_engine
                        ):
                            thumb_manager.set_thumbnail(asset_hash, output_path)

                    batch_engine = None

                with progress_lock:
                    processed_count += len(chunk_data)
                    progress = processed_count / total_to_process
                    self.app._queue_ui_task(
                        lambda p=progress, c=processed_count, t=total_to_process: (
                            self._update_batch_progress(p, c, t)
                        )
                    )

            with ThreadPoolExecutor(max_workers=2) as chunk_pool:
                chunk_pool.map(process_one_chunk, chunks)

            self.app._queue_ui_task(
                lambda: self._finalize_batch(
                    i18n("msg_batch_finished")
                    if not self.app.batch_stop_event.is_set()
                    else i18n("msg_batch_stopped")
                )
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            err_msg = str(e)
            print(f"Batch worker fatal error: {err_msg}")
            self.app._queue_ui_task(
                lambda msg=err_msg: self._finalize_batch(f"Fatal Error: {msg}")
            )

    def _update_batch_progress(self, progress, count, total):
        dpg.set_value("batch_progress_bar", progress)
        dpg.set_value(
            "batch_progress_text", f"{i18n('label_progress')} {count} / {total}"
        )

    def _finalize_batch(self, message):
        self.app.is_batch_running = False
        dpg.set_value("batch_status_msg", message)
        dpg.configure_item("btn_start_batch", enabled=True)
        dpg.configure_item("btn_stop_batch", enabled=False)
        if hasattr(self.app, "current_asset_id") and self.app.current_asset_id:
            for prefix in self.app.preview_controller._detail_prefixes():
                self.app.preview_controller._check_and_display_thumbnail(
                    prefix, self.app.current_asset_hash
                )
                self.app.preview_controller._update_thumbnail_button(
                    prefix, self.app.current_asset_id
                )
