import os

import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.database import UmaDatabase
from src.core.i18n import i18n
from src.core.unity import UnityLogic


class DatabaseService:
    """Manages database lifecycle: initialization, loading, and state reset."""

    def __init__(self, app):
        self.app = app

    def start_db_load(self):
        """Asynchronously initialize the database and load its index."""
        if self.app.is_db_loading:
            return

        db_path = Config.get_db_path()
        if not Config.BASE_PATH or not os.path.exists(db_path):
            self.app.db = None
            self.app.tree_data = {}
            self.app._queue_ui_task(lambda: dpg.set_value("main_tabs", "settings_tab"))
            return

        def run_db_load():
            try:
                self.app.is_db_loading = True
                self.app._queue_ui_task(lambda: dpg.show_item("loading_modal"))

                db = UmaDatabase(
                    Config.get_db_path(),
                    translation_service=self.app.translation_service,
                )
                UnityLogic.set_key_provider(db.get_key_by_hash)
                tree_data = db.load_index()

                def finalize():
                    self.app.db = db
                    self.app.is_db_loading = False
                    dpg.hide_item("loading_modal")
                    self._on_database_ready(tree_data)

                self.app._queue_ui_task(finalize)

            except Exception as e:
                print(f"Failed to load database: {e}")

                def on_error(err=str(e)):
                    dpg.hide_item("loading_modal")
                    dpg.set_value("settings_status_msg", err)
                    dpg.set_value("main_tabs", "settings_tab")

                self.app._queue_ui_task(on_error)
                self.app.is_db_loading = False

        self.app.executor.submit(run_db_load)

    def _on_database_ready(self, tree_data):
        """Called when database has been successfully loaded."""
        self.app.tree_data = tree_data

        if dpg.does_item_exist("browse_group"):
            dpg.delete_item("browse_group", children_only=True)
            self.app.browser_controller.render_browser_tree_items("browse_group")
        if dpg.does_item_exist("search_results"):
            dpg.delete_item("search_results", children_only=True)
        if dpg.does_item_exist("search_group"):
            dpg.configure_item("search_group", show=False)
        if dpg.does_item_exist("browse_group"):
            dpg.configure_item("browse_group", show=True)
        if dpg.does_alias_exist("main_tabs"):
            dpg.set_value("main_tabs", "home_tab")

        dpg.set_value(
            "settings_status_msg",
            i18n("msg_db_ready") + f" ({self.app.db.db_path})",
        )

        self.app.search_controller.render_scene_results()
        self.app.search_controller.render_prop_results()
        self.app.search_controller.render_character_results()

    def reset_database_state(self):
        """Reset all database-related state and clear UI."""
        if self.app.db:
            try:
                self.app.db.close()
            except Exception:
                pass

        self.app.db = None
        self.app.tree_data = {}
        self.app.node_map = {}
        self.app.cached_recursive_hashes = {}
        self.app.cached_deps = {}
        self.app.cached_rev_deps = {}
        UnityLogic.clear_runtime_caches()

        # Clear UI containers
        self._clear_ui_containers()

        # Reset character-related state
        self._reset_character_state()

    def _clear_ui_containers(self):
        """Delete all database-populated UI containers."""
        containers_to_clear = [
            "browse_group",
            "search_results",
            "scene_results_parent",
            "scene_thumbnails_parent",
            "prop_results_parent",
            "prop_thumbnails_parent",
            "character_list_scroll",
            "character_outfits_content",
        ]
        for tag in containers_to_clear:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag, children_only=True)

    def _reset_character_state(self):
        """Reset character-related UI state."""
        self.app.character_entries = []
        self.app.current_character_id = None
        self.app.last_selected_character_logo = None
        self.app.character_cache_pending.clear()
        self.app.last_selected_character_outfit = None
        self.app.current_character_outfit = None
        self.app.thumbnail_items["character_outfits"] = []
        self.app.lazy_thumb_queues["character_icons"] = []
        self.app.lazy_thumb_queues["character_outfits"] = []
