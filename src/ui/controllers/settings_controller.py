import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.services.thumbnail.manager import ThumbnailManager as thumb_manager
from src.core.i18n import i18n


class SettingsController:
    def __init__(self, app):
        self.app = app

    def on_settings_dir_selected(self, sender, app_data):
        selected_path = app_data["file_path_name"]
        dpg.set_value("settings_base_path", selected_path)

    def apply_settings(self, sender, app_data, user_data):
        base_path = dpg.get_value("settings_base_path")
        region = dpg.get_value("settings_region")
        lang = dpg.get_value("settings_language")

        region_map = {
            i18n("region_jp"): "jp",
            i18n("region_global"): "global",
        }
        Config.update_config(base_path, region_map.get(region, "jp"), lang)
        self.app._reset_database_state()
        dpg.set_value("settings_status_msg", i18n("msg_loading"))
        self.app.database_service.start_db_load()

    def on_clear_thumbnail_cache(self, sender, app_data, user_data):
        try:
            thumb_manager.clear_all()
            dpg.set_value("settings_status_msg", i18n("msg_clear_cache_success"))
        except Exception as e:
            dpg.set_value("settings_status_msg", f"Failed to clear cache: {e}")

    def on_update_translations(self, sender, app_data, user_data):
        dpg.set_value("settings_translation_status", i18n("msg_updating_translations"))
        dpg.configure_item(sender, enabled=False)

        source_val = dpg.get_value("settings_translation_source")
        source_map = {
            i18n("source_auto"): "auto",
            i18n("source_github"): "github",
            i18n("source_yingqwq"): "yingqwq",
            i18n("source_leadrdrk"): "leadrdrk",
        }
        source = source_map.get(source_val, "auto")

        def callback(success, used_source_name=None):
            def finalize():
                if success:
                    if used_source_name:
                        msg = i18n("msg_translations_updated_from").format(used_source_name)
                    else:
                        msg = i18n("msg_translations_updated")
                    dpg.set_value(
                        "settings_translation_status",
                        msg,
                    )
                    # Reload character list to show new names
                    self.app.search_controller.render_character_results()
                else:
                    dpg.set_value(
                        "settings_translation_status", i18n("msg_translations_failed")
                    )
                dpg.configure_item(sender, enabled=True)

            self.app._queue_ui_task(finalize)

        self.app.translation_service.download_translations(callback, source=source)

