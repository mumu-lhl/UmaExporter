import time

import numpy as np
from PIL import Image


class ThumbnailBatchResults(list):
    """Decoded items with worker-owned batch timing metadata."""

    def __init__(self, values=(), *, decode_seconds=None):
        super().__init__(values)
        self.decode_seconds = decode_seconds



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
            started_at = time.perf_counter()
            results = ThumbnailBatchResults()
            resample_filter = getattr(Image, "Resampling", Image).BILINEAR

            for path, img_id in tasks:
                try:
                    with Image.open(path) as image:
                        image = image.convert("RGBA")
                        image = image.resize((100, 100), resample_filter)
                        data = np.ascontiguousarray(
                            np.asarray(image, dtype=np.float32).reshape(-1)
                        )
                        data /= np.float32(255.0)
                    results.append((img_id, data))
                except Exception:
                    pass
            results.decode_seconds = time.perf_counter() - started_at
            return results

        future = self.executor.submit(worker)

        def done(f):
            try:
                batch_results = f.result()
            except Exception:
                batch_results = ThumbnailBatchResults()
            self._queue_ui_task(
                lambda results=batch_results: apply_result(results)
            )

        future.add_done_callback(done)
