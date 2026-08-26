import errno
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.f3d.service import F3dService
from src.services.f3d.worker import launch_f3d_viewer_stdin


class InvalidOutputStream:
    def write(self, _value):
        raise OSError(errno.EINVAL, "Invalid argument")

    def flush(self):
        raise OSError(errno.EINVAL, "Invalid argument")


class F3dWorkerTests(unittest.TestCase):
    def test_thumbnail_rendering_is_isolated_from_gui_process(self):
        root = Path(__file__).resolve().parents[1]
        preview = (root / "src/ui/controllers/preview_controller.py").read_text()
        batch = (root / "src/ui/controllers/batch_controller.py").read_text()

        self.assertIn("F3dThumbnailWorker", preview)
        self.assertIn("F3dThumbnailWorker", batch)
        self.assertNotIn("generate_thumbnail(", preview)
        self.assertNotIn("generate_thumbnail(", batch)

    def test_viewer_pipe_uses_utf8_for_unicode_preview_paths(self):
        fake_process = SimpleNamespace(stdout=object(), stderr=object())

        with (
            patch(
                "src.services.f3d.service.subprocess.Popen",
                return_value=fake_process,
            ) as popen,
            patch("src.services.f3d.service.threading.Thread"),
            patch("src.services.f3d.service.sys.frozen", True, create=True),
        ):
            F3dService().ensure_f3d_viewer()

        options = popen.call_args.kwargs
        self.assertEqual(options["encoding"], "utf-8")
        self.assertEqual(options["errors"], "strict")

    def test_worker_exit_does_not_crash_when_windowed_stdout_is_invalid(self):
        fake_f3d = SimpleNamespace(
            Engine=SimpleNamespace(create=lambda: (_ for _ in ()).throw(RuntimeError()))
        )

        with (
            patch.dict(sys.modules, {"f3d": fake_f3d}),
            patch("src.services.f3d.worker.sys.stdin", io.StringIO("")),
            patch("src.services.f3d.worker.sys.stdout", InvalidOutputStream()),
        ):
            launch_f3d_viewer_stdin()


if __name__ == "__main__":
    unittest.main()
