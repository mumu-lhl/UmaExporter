import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import src.core.unity as unity_module
from src.core.unity import UnityLogic


class UnicodeExportPathTests(unittest.TestCase):
    def test_windows_system_drive_temp_is_absolute(self):
        attempted_dirs = []

        @contextlib.contextmanager
        def fake_temp_directory(prefix, dir=None):
            attempted_dirs.append(dir)
            if dir not in (r"C:\Temp", None):
                raise OSError(dir)
            yield r"C:\Temp\uma-cli-test"

        with (
            patch.object(unity_module.os, "name", "nt"),
            patch.dict(unity_module.os.environ, {"SystemDrive": "C:"}, clear=True),
            patch.object(
                unity_module.tempfile,
                "gettempdir",
                return_value=r"C:\Users\中文\AppData\Local\Temp",
            ),
            patch.object(UnityLogic, "_get_windows_short_path", return_value=None),
            patch.object(
                unity_module.Config,
                "get_bundle_dir",
                return_value=r"C:\Users\中文\UmaExporter",
            ),
            patch.object(
                unity_module.tempfile,
                "TemporaryDirectory",
                side_effect=fake_temp_directory,
            ),
        ):
            with UnityLogic._cli_temp_directory():
                pass

        self.assertIn(r"C:\Temp", attempted_dirs)

    def test_batch_thumbnail_cli_uses_ascii_staging_for_unicode_temp(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_path = root_path / "bundle"
            source_path.write_bytes(b"bundle")
            target_path = root_path / "中文批量缩略图"
            target_path.mkdir()
            captured = {}

            def fake_run(command):
                captured["command"] = command
                output_dir = Path(command[command.index("--output") + 1])
                output_file = output_dir / "FBX_Animator" / "logical" / "model.fbx"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_bytes(b"fbx")
                return SimpleNamespace(stdout="", stderr="")

            with (
                patch.object(UnityLogic, "_load_bundle_data", return_value=b"data"),
                patch.object(UnityLogic, "_run_cli_process", side_effect=fake_run),
                patch("src.core.unity.tempfile.gettempdir", return_value=root),
            ):
                results = UnityLogic.batch_export_to_fbx(
                    [
                        {
                            "hash": "asset-hash",
                            "paths": [str(source_path)],
                            "keys": [1],
                            "logical_name": "logical",
                        }
                    ],
                    str(target_path),
                )

            output_arg = captured["command"][
                captured["command"].index("--output") + 1
            ]
            expected_fbx = target_path / "FBX_Animator" / "logical" / "model.fbx"
            self.assertNotIn("中文", output_arg)
            self.assertEqual(results, [("asset-hash", str(expected_fbx))])
            self.assertTrue(expected_fbx.exists())

    def test_animator_preview_finds_fbx_after_cli_output_is_flattened(self):
        def fake_export(_paths, export_dir, **_kwargs):
            output_file = Path(export_dir) / "preview.fbx"
            output_file.write_bytes(b"fbx")
            return 1

        with patch.object(
            UnityLogic, "_export_via_cli", side_effect=fake_export
        ):
            preview_path = UnityLogic.save_animator_to_tmp(["bundle"])

        try:
            self.assertIsNotNone(preview_path)
            self.assertTrue(Path(preview_path).exists())
        finally:
            if preview_path:
                Path(preview_path).unlink(missing_ok=True)

    def test_pyinstaller_cli_context_restores_dll_directory(self):
        class FakeKernel32:
            def __init__(self):
                self.calls = []

            def GetDllDirectoryW(self, size, buffer):
                buffer.value = r"C:\PyInstaller"
                return len(buffer.value)

            def SetDllDirectoryW(self, path):
                self.calls.append(path)
                return 1

        kernel32 = FakeKernel32()
        fake_windll = SimpleNamespace(kernel32=kernel32)
        with (
            patch.object(unity_module.os, "name", "nt"),
            patch.object(UnityLogic, "_is_pyinstaller_runtime", return_value=True),
            patch.object(unity_module.ctypes, "windll", fake_windll, create=True),
        ):
            with UnityLogic._cli_process_context():
                pass

        self.assertEqual(kernel32.calls, [None, r"C:\PyInstaller"])

    def test_cli_process_uses_utf8_output_and_closes_frozen_app_handles(self):
        with patch(
            "src.core.unity.subprocess.run",
            return_value=SimpleNamespace(stdout="", stderr=""),
        ) as run:
            UnityLogic._run_cli_process(["AssetStudioModCLI", "--help"])

        options = run.call_args.kwargs
        self.assertEqual(options["encoding"], "utf-8")
        self.assertEqual(options["errors"], "replace")
        self.assertTrue(options["close_fds"])

    def test_cli_uses_ascii_staging_path_for_unicode_export_directory(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_path = root_path / "bundle"
            source_path.write_bytes(b"bundle")
            target_path = root_path / "中文导出"
            target_path.mkdir()

            cli_path = root_path / "as_cli" / "AssetStudioModCLI"
            cli_path.parent.mkdir()
            cli_path.write_bytes(b"")

            captured = {}

            def fake_run(command, **kwargs):
                captured["command"] = command
                output_dir = Path(command[command.index("--output") + 1])
                output_file = output_dir / "FBX_Animator" / "model.fbx"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_bytes(b"fbx")
                return SimpleNamespace(stdout="", stderr="")

            with (
                patch.object(UnityLogic, "_load_bundle_data", return_value=b"data"),
                patch("src.core.unity.subprocess.run", side_effect=fake_run),
                patch("src.core.unity.tempfile.gettempdir", return_value=root),
            ):
                exported = UnityLogic._export_via_cli(
                    [str(source_path)], str(target_path), mode="animator"
                )

            output_arg = captured["command"][captured["command"].index("--output") + 1]
            self.assertNotIn("中文", output_arg)
            self.assertEqual(exported, 1)
            self.assertTrue((target_path / "model.fbx").exists())


if __name__ == "__main__":
    unittest.main()
