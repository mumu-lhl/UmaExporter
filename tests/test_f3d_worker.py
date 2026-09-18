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

    def test_viewer_worker_exits_on_empty_stdin(self):
        fake_interactor = SimpleNamespace(
            remove_binding=lambda *a: None,
            add_binding=lambda *a, **kw: None,
            start=lambda *a: None,
            stop=lambda: None,
            trigger_command=lambda *a: None,
        )
        fake_window = SimpleNamespace(
            set_window_name=lambda *a: None,
            camera=SimpleNamespace(
                reset_to_bounds=lambda: None,
                position=(0, 0, 1),
                focal_point=(0, 0, 0),
            ),
            render=lambda: None,
        )
        fake_eng = SimpleNamespace(
            scene=SimpleNamespace(clear=lambda: None, add=lambda *a: None),
            window=fake_window,
            interactor=fake_interactor,
            options=SimpleNamespace(update=lambda *a: None),
        )
        fake_f3d = SimpleNamespace(
            Engine=SimpleNamespace(create=lambda: fake_eng),
            InteractionBind=lambda *a: object(),
        )

        with (
            patch.dict(sys.modules, {"f3d": fake_f3d}),
            patch("src.services.f3d.worker.sys.stdin", io.StringIO("")),
        ):
            # Should exit immediately without hanging
            launch_f3d_viewer_stdin()

    def test_service_notifies_on_loaded_callback(self):
        service = F3dService()
        callback_results = []

        def on_loaded(success, count):
            callback_results.append((success, count))

        fake_stdin = io.StringIO()
        fake_process = SimpleNamespace(
            stdin=fake_stdin,
            poll=lambda: None,
        )
        service.f3d_process = fake_process

        service.load_mesh("/path/to/model.fbx", on_loaded=on_loaded)
        self.assertEqual(fake_stdin.getvalue(), "/path/to/model.fbx\n")

        # Simulate worker emitting F3D_SCENE_LOADED
        service._notify_loaded(True, 2)
        self.assertEqual(callback_results, [(True, 2)])


if __name__ == "__main__":
    unittest.main()

