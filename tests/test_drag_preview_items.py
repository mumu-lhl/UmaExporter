import importlib.util
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "src/ui/controllers/drag_controller.py"
)
SPEC = importlib.util.spec_from_file_location("drag_controller_under_test", MODULE_PATH)
drag_module = importlib.util.module_from_spec(SPEC)
dearpygui_package = ModuleType("dearpygui")
dearpygui_module = ModuleType("dearpygui.dearpygui")
dearpygui_package.dearpygui = dearpygui_module
with patch.dict(
    "sys.modules",
    {
        "dearpygui": dearpygui_package,
        "dearpygui.dearpygui": dearpygui_module,
    },
):
    SPEC.loader.exec_module(drag_module)
DragController = drag_module.DragController


class DragPreviewItemTests(unittest.TestCase):
    def test_drag_selection_tints_thumbnail_image(self):
        app = SimpleNamespace(last_selected=None)
        controller = DragController(app)

        with patch.object(drag_module, "dpg", Mock()) as dpg:
            dpg.does_item_exist.return_value = True
            dpg.get_item_type.return_value = "mvAppItemType::mvImage"

            controller._select_drag_item(42)

        dpg.configure_item.assert_called_once_with(
            42, tint_color=[150, 200, 255, 255]
        )
        self.assertEqual(app.last_selected, 42)

    def test_home_tree_finds_child_outside_tree_header_without_global_scan(self):
        class NoFallbackItems(dict):
            def keys(self):
                return []

        app = SimpleNamespace(file_item_data=NoFallbackItems({3: {"id": 3}}))
        controller = DragController(app)

        with patch.object(drag_module, "dpg", Mock()) as dpg:
            dpg.get_mouse_pos.return_value = (50, 35)
            dpg.get_value.side_effect = lambda item: (
                "home_tab" if item == "main_tabs" else True
            )
            dpg.is_item_shown.side_effect = lambda item: item != "search_group"
            dpg.does_item_exist.return_value = True
            dpg.get_item_children.side_effect = lambda item, slot=1: {
                "home_browse_scroll": [2],
                2: [3],
                3: [],
            }.get(item, [])
            dpg.is_item_hovered.return_value = False
            dpg.get_item_type.side_effect = lambda item: {
                2: "mvAppItemType::mvTreeNode",
                3: "mvAppItemType::mvSelectable",
            }.get(item, "")
            dpg.get_item_rect_min.side_effect = lambda item: {
                2: (0, 10),
                3: (0, 30),
            }[item]
            dpg.get_item_rect_max.side_effect = lambda item: {
                2: (100, 20),
                3: (100, 40),
            }[item]

            found = controller._pick_file_item_under_mouse()

        self.assertEqual(found, 3, dpg.mock_calls)

    def test_prop_thumbnail_mode_hit_tests_visible_thumbnail_container(self):
        class NoFallbackItems(dict):
            def keys(self):
                return []

        app = SimpleNamespace(
            file_item_data=NoFallbackItems({7: {"id": 7}}),
            prop_view_mode="thumbnail",
        )
        controller = DragController(app)

        with patch.object(drag_module, "dpg", Mock()) as dpg:
            dpg.get_mouse_pos.return_value = (50, 50)
            dpg.get_value.return_value = "prop_tab"
            dpg.does_item_exist.return_value = True
            dpg.is_item_shown.return_value = True
            dpg.get_item_children.side_effect = lambda item, slot=1: {
                "prop_thumbnails_parent": [7],
                7: [],
            }.get(item, [])
            dpg.is_item_hovered.return_value = False
            dpg.get_item_type.return_value = "mvAppItemType::mvImage"
            dpg.get_item_rect_min.return_value = (0, 0)
            dpg.get_item_rect_max.return_value = (100, 100)

            found = controller._pick_file_item_under_mouse()

        self.assertEqual(found, 7, dpg.mock_calls)


if __name__ == "__main__":
    unittest.main()
