import os
import shutil
import subprocess
import webbrowser

import dearpygui.dearpygui as dpg
import requests

from src.core.config import Config
from src.core.i18n import i18n
from src.core.version import VERSION
from src.services.thumbnail.manager import ThumbnailManager as thumb_manager


class SettingsController:
    NET9_DOWNLOAD_URL = "https://dotnet.microsoft.com/en-us/download/dotnet/9.0"
    REPOSITORY_URL = "https://github.com/mumu-lhl/UmaExporter"
    GITHUB_LATEST_RELEASE_URL = (
        "https://api.github.com/repos/mumu-lhl/UmaExporter/releases/latest"
    )
    GITHUB_TAGS_URL = "https://api.github.com/repos/mumu-lhl/UmaExporter/tags"

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
            i18n("region_tw"): "tw",
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

    def on_check_updates(self, sender, app_data, user_data):
        dpg.set_value("settings_update_status", i18n("msg_update_checking"))
        if dpg.does_item_exist("settings_update_link"):
            dpg.configure_item("settings_update_link", show=False)
        dpg.configure_item(sender, enabled=False)

        def run_check():
            result = self._check_latest_version()

            def finalize():
                dpg.set_value("settings_update_status", result["message"])
                update_url = result.get("url")
                if dpg.does_item_exist("settings_update_link"):
                    if update_url:
                        dpg.configure_item(
                            "settings_update_link",
                            show=True,
                            callback=lambda: webbrowser.open(update_url),
                        )
                    else:
                        dpg.configure_item("settings_update_link", show=False)
                dpg.configure_item(sender, enabled=True)

            self.app._queue_ui_task(finalize)

        self.app.executor.submit(run_check)

    def _check_latest_version(self):
        try:
            latest_version, release_url = self._fetch_latest_version()
        except Exception as e:
            return {
                "ok": False,
                "message": f"{i18n('msg_update_check_failed')}: {e}",
            }

        current_version = VERSION
        comparison = self._compare_versions(latest_version, current_version)
        if comparison > 0:
            return {
                "ok": True,
                "message": i18n("msg_update_available").format(
                    current_version, latest_version, release_url
                ),
                "url": release_url,
            }

        return {
            "ok": True,
            "message": i18n("msg_update_latest").format(
                current_version, latest_version
            ),
        }

    def _fetch_latest_version(self):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "UmaExporter",
        }
        try:
            response = requests.get(
                self.GITHUB_LATEST_RELEASE_URL,
                headers=headers,
                timeout=10,
            )
            if response.status_code != 404:
                response.raise_for_status()
                data = response.json()
                version = data.get("tag_name") or data.get("name")
                if version:
                    return version, data.get("html_url") or self.REPOSITORY_URL
        except requests.HTTPError:
            raise
        except requests.RequestException:
            pass

        response = requests.get(self.GITHUB_TAGS_URL, headers=headers, timeout=10)
        response.raise_for_status()
        tags = response.json()
        if not tags:
            raise RuntimeError(i18n("msg_update_no_remote_version"))
        latest_tag = max(
            tags,
            key=lambda tag: self._normalize_version(tag.get("name", "")),
        )
        version = latest_tag.get("name")
        if not version:
            raise RuntimeError(i18n("msg_update_no_remote_version"))
        return version, f"{self.REPOSITORY_URL}/releases/tag/{version}"

    @staticmethod
    def _normalize_version(version):
        version = (version or "").strip()
        if version.startswith(("v", "V")):
            version = version[1:]
        if "-" in version:
            version = version.split("-", 1)[0]
        parts = []
        for part in version.split("."):
            digits = ""
            for char in part:
                if not char.isdigit():
                    break
                digits += char
            parts.append(int(digits) if digits else 0)
        while parts and parts[-1] == 0:
            parts.pop()
        return parts

    @classmethod
    def _compare_versions(cls, left, right):
        left_parts = cls._normalize_version(left)
        right_parts = cls._normalize_version(right)
        max_len = max(len(left_parts), len(right_parts))
        left_parts.extend([0] * (max_len - len(left_parts)))
        right_parts.extend([0] * (max_len - len(right_parts)))
        if left_parts > right_parts:
            return 1
        if left_parts < right_parts:
            return -1
        return 0

    def on_check_runtime(self, sender, app_data, user_data):
        dpg.set_value("settings_runtime_check_status", i18n("msg_runtime_checking"))
        dpg.configure_item(sender, enabled=False)
        self._render_runtime_check_results([])
        base_path = dpg.get_value("settings_base_path")

        def run_check():
            results = [
                self._check_data_root(base_path),
                self._check_dotnet9_runtime(),
            ]

            def finalize():
                self._render_runtime_check_results(results)
                dpg.set_value(
                    "settings_runtime_check_status",
                    i18n("msg_runtime_check_done")
                    if all(result["ok"] for result in results)
                    else i18n("msg_runtime_check_failed"),
                )
                dpg.configure_item(sender, enabled=True)

            self.app._queue_ui_task(finalize)

        self.app.executor.submit(run_check)

    def _check_data_root(self, base_path):
        label = i18n("label_runtime_check_data_root")
        path = (base_path or "").strip()
        if not path:
            return {
                "label": label,
                "ok": False,
                "status": i18n("runtime_status_path_empty"),
            }

        normalized_path = os.path.normpath(path)
        if os.path.basename(normalized_path) != "Persistent":
            return {
                "label": label,
                "ok": False,
                "status": i18n("runtime_status_data_root_not_persistent"),
            }

        if not os.path.isdir(normalized_path):
            return {
                "label": label,
                "ok": False,
                "status": i18n("runtime_status_data_root_not_directory"),
            }

        return {
            "label": label,
            "ok": True,
            "status": i18n("runtime_status_data_root_ok"),
        }

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
                "action": "download_net9",
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
                "action": "download_net9",
            }

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            detail = stderr if stderr else f"exit code {result.returncode}"
            return {
                "label": label,
                "ok": False,
                "status": f"{i18n('runtime_status_error')}: {detail}",
                "action": "download_net9",
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
            "action": "download_net9",
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

                if not item["ok"] and item.get("action") == "download_net9":
                    dpg.add_spacer(width=12)
                    dpg.add_button(
                        label=i18n("btn_download_net9"),
                        callback=lambda: webbrowser.open(self.NET9_DOWNLOAD_URL),
                        small=True,
                    )
