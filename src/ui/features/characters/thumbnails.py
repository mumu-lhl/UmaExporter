"""Lazy character thumbnail loading, isolated from search result rendering."""

import os

import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.unity import UnityLogic


class CharacterThumbnailLoader:
    """Decode visible character cards in workers and bind them on the UI thread."""

    def __init__(self, app):
        self.app = app

    def process_visible(self, domain, batch_size):
        queue = self.app.lazy_thumb_queues.get(domain, [])
        if not queue:
            return False

        visible_indices = []
        for index, task in enumerate(queue):
            try:
                if dpg.is_item_visible(task["img_id"]):
                    visible_indices.append(index)
                    if len(visible_indices) == batch_size:
                        break
            except Exception:
                continue

        if not visible_indices:
            return False

        selected = set(visible_indices)
        tasks = [task for index, task in enumerate(queue) if index in selected]
        self.app.lazy_thumb_queues[domain] = [
            task for index, task in enumerate(queue) if index not in selected
        ]
        self._load_async(domain, tasks, self.app.thumbnail_request_ids.get(domain, 0))
        return True

    def _load_async(self, domain, tasks, request_id):
        def worker():
            import numpy as np
            from PIL import Image, ImageOps

            results = []
            resample_filter = getattr(Image, "Resampling", Image).BILINEAR
            for task in tasks:
                cache_path = task["cache_path"]
                if not os.path.exists(cache_path):
                    physical_path = os.path.join(
                        Config.get_data_root(), task["hash"][:2], task["hash"]
                    )
                    data, _, _ = UnityLogic.get_named_texture_data(
                        physical_path,
                        task["texture_name"],
                        bundle_key=task["key"],
                        max_size=task["size"],
                    )
                    if data is not None:
                        results.append((task["img_id"], data.tolist(), task["size"]))
                        self._schedule_cache_write(task)
                    continue

                try:
                    with Image.open(cache_path) as source:
                        image = ImageOps.contain(
                            source.convert("RGBA"),
                            (task["size"], task["size"]),
                            method=resample_filter,
                        )
                    canvas = Image.new(
                        "RGBA", (task["size"], task["size"]), (0, 0, 0, 0)
                    )
                    canvas.paste(
                        image,
                        (
                            (task["size"] - image.width) // 2,
                            (task["size"] - image.height) // 2,
                        ),
                        image,
                    )
                    data = (
                        np.array(canvas).flatten().astype(np.float32) / 255.0
                    ).tolist()
                    results.append((task["img_id"], data, task["size"]))
                except Exception:
                    continue
            return results

        future = self.app.executor.submit(worker)

        def done(completed):
            try:
                results = completed.result()
                if results:
                    self.app._queue_ui_task(
                        lambda: self._apply(domain, request_id, results)
                    )
            except Exception:
                pass

        future.add_done_callback(done)

    def _apply(self, domain, request_id, results):
        if request_id != self.app.thumbnail_request_ids.get(domain):
            return
        for image_tag, data, size in results:
            self.app.texture_registry.replace(domain, image_tag, data, size, size)

    def _schedule_cache_write(self, task):
        cache_name = task["cache_name"]
        pending = self.app.character_state.pending_cache_writes
        if cache_name in pending:
            return
        pending.add(cache_name)

        def worker():
            try:
                cache_path = task["cache_path"]
                if not os.path.exists(cache_path):
                    physical_path = os.path.join(
                        Config.get_data_root(), task["hash"][:2], task["hash"]
                    )
                    UnityLogic.export_named_texture_to_png(
                        physical_path,
                        task["texture_name"],
                        cache_path,
                        bundle_key=task["key"],
                    )
            finally:
                pending.discard(cache_name)

        self.app.executor.submit(worker)
