import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.ui.controllers import export_controller as export_module
from src.ui.controllers.preview_controller import PreviewController


class ExportControllerSelectionTests(unittest.TestCase):
    def test_export_selected_uses_implicitly_previewed_object(self):
        selected_data = (
            r"C:\asset_bundle",
            123,
            "Animator",
            "",
            "matching_object",
            7,
        )
        app = SimpleNamespace(
            last_unity_selected={"": None, "scene_": None, "prop_": None},
            last_unity_selection_data={
                "": selected_data,
                "scene_": None,
                "prop_": None,
            },
            current_asset_hash="ab0123",
            current_asset_id=None,
            current_asset_data={"key": 7},
        )
        controller = export_module.ExportController(app)

        with (
            patch.object(export_module, "dpg", Mock()) as dpg,
            patch.object(controller, "_set_export_status"),
            patch.object(controller, "_submit") as submit,
        ):
            dpg.get_value.return_value = "home_tab"
            dpg.does_item_exist.return_value = False

            controller.on_export_selected(
                None, {"file_path_name": r"C:\Export_Test"}
            )

        submit.assert_called_once_with(
            "",
            export_module.UnityLogic.export_single_unity_object,
            r"C:\asset_bundle",
            123,
            r"C:\Export_Test",
            "Animator",
            "matching_object",
            bundle_key=7,
        )

    def test_default_export_object_matches_selected_asset_name(self):
        app = SimpleNamespace(
            f3d_service=None,
            thumbnail_service=None,
            current_asset_data={"full_path": "folder/matching_object.prefab"},
        )
        controller = PreviewController(app)
        objects = [
            ("GameObject", "other", 1),
            ("Animator", "matching_object", 2),
        ]

        selected = controller._find_default_unity_object(objects)

        self.assertEqual(selected, ("Animator", "matching_object", 2))


if __name__ == "__main__":
    unittest.main()
