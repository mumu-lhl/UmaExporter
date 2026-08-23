import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import src.core.unity as unity_module
from src.core.unity import UnityLogic


class UnicodeExportPathTests(unittest.TestCase):
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
