import os
import numpy as np
from PIL import Image


class ThumbnailService:
    def __init__(self, executor, queue_ui_task):
        self.executor = executor
        self._queue_ui_task = queue_ui_task

    def load_search_thumbnails_batch_async(self, tasks, apply_result):
        """Decode a thumbnail batch off-thread and queue its UI-owned result.

        ``apply_result`` must be a main-thread callback supplied by the UI
        feature.  This service deliberately has no Dear PyGui dependency.
        """

        def worker():
            results = []
            resample_filter = getattr(Image, "Resampling", Image).BILINEAR

            for path, img_id in tasks:
                try:
                    if not os.path.exists(path):
                        continue
                    img = Image.open(path).convert("RGBA")
                    img = img.resize((100, 100), resample_filter)
                    data = (np.array(img).flatten().astype(np.float32) / 255.0).tolist()
                    results.append((img_id, data))
                except Exception:
                    pass
            return results

        future = self.executor.submit(worker)

        def done(f):
            try:
                batch_results = f.result()
                if batch_results:
                    self._queue_ui_task(lambda: apply_result(batch_results))
            except Exception:
                pass

        future.add_done_callback(done)
