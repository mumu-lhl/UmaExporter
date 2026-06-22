"""Structural regression tests for the Dear PyGui presentation boundary."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


def module_source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class UiArchitectureTests(unittest.TestCase):
    def test_thumbnail_worker_service_has_no_dearpygui_dependency(self):
        source = module_source("src/services/thumbnail/service.py")
        self.assertNotIn("dearpygui", source)
        self.assertIn("queue_ui_task", source)

    def test_character_feature_owns_its_controller_and_loader(self):
        controller = module_source("src/ui/features/characters/controller.py")
        thumbnails = module_source("src/ui/features/characters/thumbnails.py")
        self.assertIn("class CharacterController", controller)
        self.assertIn("class CharacterThumbnailLoader", thumbnails)
        self.assertIn("request_id != self.app.thumbnail_request_ids", controller)
        self.assertIn("request_id != self.app.thumbnail_request_ids", thumbnails)

    def test_search_controller_uses_character_feature_for_lazy_loading(self):
        source = module_source("src/ui/controllers/search_controller.py")
        self.assertIn("CharacterThumbnailLoader", source)
        self.assertIn("self.character_thumbnails.process_visible", source)
        self.assertNotIn("def _process_character_lazy_queue", source)
        self.assertNotIn("def _render_character_outfit_grid", source)

    def test_preview_controller_has_one_recursive_hash_helper(self):
        tree = ast.parse(module_source("src/ui/controllers/preview_controller.py"))
        methods = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(methods.count("_get_recursive_hashes"), 1)

    def test_preview_dependency_panel_is_a_feature_module(self):
        preview = module_source("src/ui/controllers/preview_controller.py")
        dependencies = module_source("src/ui/features/preview/dependencies.py")
        self.assertIn("DependencyPanelController", preview)
        self.assertIn("class DependencyPanelController", dependencies)
        self.assertNotIn("def _apply_dependency_result", preview)
        self.assertNotIn("def _fill_dependency_table", preview)

    def test_export_controller_has_one_generic_costume_helper(self):
        tree = ast.parse(
            module_source("src/ui/features/characters/export_controller.py")
        )
        methods = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(methods.count("_is_generic_costume"), 1)

    def test_character_export_has_a_dedicated_controller(self):
        app = module_source("src/ui/main_window.py")
        controller = module_source("src/ui/features/characters/export_controller.py")
        self.assertIn("CharacterExportController", app)
        self.assertIn("self.character_export_controller.on_character_export_selected", app)
        self.assertIn("class CharacterExportController", controller)
        self.assertNotIn("def on_export_selected", controller)
        self.assertNotIn("def on_export_all_objects", controller)


if __name__ == "__main__":
    unittest.main()
