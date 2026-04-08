import os
import dearpygui.dearpygui as dpg
import numpy as np
from PIL import Image


class ThumbnailService:
    def __init__(self, executor, controller):
        self.executor = executor
        self.controller = controller

    def load_search_thumbnails_batch_async(self, prefix, tasks):
        """Processes a batch of thumbnails in a single worker thread."""

        def worker():
            results = []
            resample_filter = getattr(Image, "Resampling", Image).BILINEAR

            for path, img_id in tasks:
                try:
                    if not os.path.exists(path):
                        continue
                    img = Image.open(path).convert("RGBA")
                    img = img.resize((100, 100), resample_filter)
                    data = np.array(img).flatten().astype(np.float32) / 255.0
                    results.append((img_id, data))
                except Exception:
                    pass
            return results

        future = self.executor.submit(worker)

        def done(f):
            try:
                batch_results = f.result()
                if batch_results:
                    self.controller._queue_ui_task(
                        lambda: self.apply_search_thumbnails_batch(
                            prefix, batch_results
                        )
                    )
            except Exception:
                pass

        future.add_done_callback(done)

    def apply_search_thumbnails_batch(self, prefix, batch_results):
        """Applies multiple textures and updates images in a single UI task."""
        with self.controller.texture_lock:
            for img_id, data in batch_results:
                if not dpg.does_item_exist(img_id):
                    continue

                tex_tag = dpg.generate_uuid()
                try:
                    dpg.add_static_texture(
                        width=100,
                        height=100,
                        default_value=data,
                        tag=tex_tag,
                        parent="main_texture_registry",
                    )
                    dpg.configure_item(img_id, texture_tag=tex_tag)
                    if prefix not in self.controller.search_thumbnail_textures:
                        self.controller.search_thumbnail_textures[prefix] = []
                    self.controller.search_thumbnail_textures[prefix].append(tex_tag)
                except Exception:
                    pass
