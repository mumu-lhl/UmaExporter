import shutil
import subprocess
import webbrowser

import dearpygui.dearpygui as dpg

from src.core.config import Config
from src.core.i18n import i18n
from src.services.thumbnail.manager import ThumbnailManager as thumb_manager


class SettingsController:
    NET9_DOWNLOAD_URL = "https://dotnet.microsoft.com/en-us/download/dotnet/9.0"

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

    def on_check_runtime(self, sender, app_data, user_data):
        dpg.set_value("settings_runtime_check_status", i18n("msg_runtime_checking"))
        dpg.configure_item(sender, enabled=False)
        self._render_runtime_check_results([])

        def run_check():
            result = self._check_dotnet9_runtime()

            def finalize():
                self._render_runtime_check_results([result])
                dpg.set_value(
                    "settings_runtime_check_status",
                    i18n("msg_runtime_check_done")
                    if result["ok"]
                    else i18n("msg_runtime_check_failed"),
                )
                dpg.configure_item(sender, enabled=True)

            self.app._queue_ui_task(finalize)

        self.app.executor.submit(run_check)

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
                        msg = i18n("msg_translations_updated_from").format(
                            used_source_name
                        )
                    else:
                        msg = i18n("msg_translations_updated")
                    dpg.set_value(
                        "settings_translation_status",
                        msg,
                    )
                    # Reload character list to show new names
                    self.app.character_controller.render_results()
                else:
                    dpg.set_value(
                        "settings_translation_status", i18n("msg_translations_failed")
                    )
                dpg.configure_item(sender, enabled=True)

            self.app._queue_ui_task(finalize)

        self.app.translation_service.download_translations(callback, source=source)

    def _check_dotnet9_runtime(self):
        label = i18n("label_runtime_check_net9")
        dotnet = shutil.which("dotnet")
        if not dotnet:
            return {
                "label": label,
                "ok": False,
                "status": i18n("runtime_status_missing"),
            }

        try:
            result = subprocess.run(
                [dotnet, "--list-runtimes"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as e:
            return {
                "label": label,
                "ok": False,
                "status": f"{i18n('runtime_status_error')}: {e}",
            }

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            detail = stderr if stderr else f"exit code {result.returncode}"
            return {
                "label": label,
                "ok": False,
                "status": f"{i18n('runtime_status_error')}: {detail}",
            }

        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            runtime_name, runtime_version = parts[0], parts[1]
            if runtime_name == "Microsoft.NETCore.App" and runtime_version.startswith(
                "9."
            ):
                return {
                    "label": label,
                    "ok": True,
                    "status": f"{i18n('runtime_status_found')} {runtime_version}",
                }

        return {
            "label": label,
            "ok": False,
            "status": i18n("runtime_status_not_found"),
        }

    def _render_runtime_check_results(self, results):
        if not dpg.does_item_exist("settings_runtime_check_list"):
            return

        dpg.delete_item("settings_runtime_check_list", children_only=True)

        if not results:
            with dpg.group(parent="settings_runtime_check_list"):
                dpg.add_text(i18n("msg_runtime_check_hint"))
            return

        for item in results:
            color = [46, 204, 113] if item["ok"] else [231, 76, 60]
            with dpg.group(horizontal=True, parent="settings_runtime_check_list"):
                dpg.add_text(item["label"], color=color)
                dpg.add_spacer(width=12)
                dpg.add_text(item["status"], color=color, wrap=360)

                if not item["ok"]:
                    dpg.add_spacer(width=12)
                    dpg.add_button(
                        label=i18n("btn_download_net9"),
                        callback=lambda: webbrowser.open(self.NET9_DOWNLOAD_URL),
                        small=True,
                    )
