import webbrowser
import subprocess
import os
import threading
import time
import platform
import sys
import tempfile
import numpy as np
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

import dearpygui.dearpygui as dpg

from src.constants import Config
from src.database import UmaDatabase
from src.thumbnail_manager import ThumbnailManager as thumb_manager
from src.unity_logic import UnityLogic
from src.ui.controllers import DragMixin, NavigationMixin, PreviewMixin
from src.ui.i18n import i18n
from src.ui.f3d_worker import generate_thumbnail


class UmaExporterApp(DragMixin, NavigationMixin, PreviewMixin):
    def __init__(self):
        Config.load()

        # Database and Tree data will be loaded asynchronously in run()
        self.db = None
        self.tree_data = {}
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.is_db_loading = False

        self.node_map = {}
        self.last_selected = None
        self.last_unity_selected = {"": None, "scene_": None, "prop_": None}
        self.batch_stop_event = threading.Event()
        self.is_batch_running = False
        self.current_asset_id = None
        self.current_asset_data = None
        self.current_asset_hash = None
        self.texture_lock = threading.Lock()
        self.preview_texture_tags = {"": None, "scene_": None, "prop_": None}
        self.thumbnail_texture_tags = {"": None, "scene_": None, "prop_": None}
        self.file_item_data = {}
        self.last_drag_preview_item = None
        self.drag_preview_active = False
        self.drag_preview_interval = 0.02
        self.last_drag_preview_time = 0.0
        self.pending_drag_preview = None
        self.current_view_is_drag_preview = False
        self.middle_drag_start_mouse_y = None
        self.middle_drag_start_scroll_y = None
        self.middle_drag_target = None
        self.middle_drag_active = False
        self.middle_drag_speed = 1.8
        self.last_tab_drag_switch_time = 0.0
        self.tab_drag_switch_interval = 0.06
        self.last_tab_drag_switch_target = None
        self.scene_auto_preview_request = None
        self.prop_auto_preview_request = None
        self.last_hover_scan_time = 0.0
        self.hover_scan_interval = 0.015

        self.selection_request_id = 0
        self.texture_request_ids = {"": 0, "scene_": 0, "prop_": 0}
        self.thumbnail_request_ids = {"": 0, "scene_": 0, "prop_": 0}
        self.ui_tasks = Queue()
        self.max_ui_tasks_per_frame = 32
        self.cached_deps = {}
        self.cached_rev_deps = {}
        self.cached_recursive_hashes = {}

        # F3D singleton process management
        self.f3d_process = None
        self.f3d_lock = threading.Lock()

        # Navigation history
        self.history_back = []
        self.history_forward = []
        self.is_navigating = False

        # View modes for scene and prop pages
        self.scene_view_mode = "list"
        self.prop_view_mode = "list"
        self.search_thumbnail_textures = {"scene_": [], "prop_": []}
        self.thumbnail_items = {"scene_": [], "prop_": []}
        self.thumbnail_columns = {"scene_": 0, "prop_": 0}
        # Separated queues for much faster scanning
        self.lazy_thumb_queues = {"scene_": [], "prop_": []}
        self.last_lazy_scan_time = 0.0
        self.lazy_scan_interval = 0.05

    def _setup_fonts(self):
        font_paths = []
        is_chinese = Config.get_effective_language() == "Chinese"
        system = platform.system()

        if system == "Windows":
            windir = os.environ.get("WINDIR", "C:/Windows")
            fonts_dir = os.path.join(windir, "Fonts")
            if is_chinese:
                font_paths.append(os.path.join(fonts_dir, "msyh.ttc"))
                font_paths.append(os.path.join(fonts_dir, "simsun.ttc"))
            font_paths.append(os.path.join(fonts_dir, "segoeui.ttf"))
        elif system == "Darwin":  # macOS
            if is_chinese:
                font_paths.append("/System/Library/Fonts/PingFang.ttc")
            font_paths.append("/System/Library/Fonts/Helvetica.ttc")
        elif system == "Linux":
            if is_chinese:
                font_paths.append("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
                font_paths.append(
                    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
                )
                font_paths.append(
                    "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc"
                )  # RHEL
            font_paths.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
            font_paths.append("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf")

        actual_font = ""
        for p in font_paths:
            if os.path.exists(p):
                actual_font = p
                break

        if actual_font:
            # Delete old font registry if it exists to ensure clean bind
            if dpg.does_item_exist("main_font_registry"):
                dpg.delete_item("main_font_registry")

            # Chinese fonts often look smaller at the same pixel size, so we bump it up
            font_size = 20 if is_chinese else 16
            with dpg.font_registry(tag="main_font_registry"):
                with dpg.font(actual_font, font_size) as default_font:
                    dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)

                    if is_chinese:
                        dpg.add_font_range_hint(dpg.mvFontRangeHint_Chinese_Full)
                        # Explicitly add common CJK range to ensure visibility
                        dpg.add_font_range(0x4E00, 0x9FFF)

                    dpg.bind_font(default_font)

    def _load_database_async(self):
        """Asynchronously initialize the database and load its index."""
        db_path = Config.get_db_path()
        if not Config.BASE_PATH or not os.path.exists(db_path):
            self._queue_ui_task(lambda: dpg.set_value("main_tabs", "settings_tab"))
            return

        def run_db_load():
            try:
                # 1. Start loading logic
                self.is_db_loading = True
                self._queue_ui_task(lambda: dpg.show_item("loading_modal"))

                # 2. Heavy IO: Initialize DB and load index
                db = UmaDatabase(Config.get_db_path())
                UnityLogic.set_key_provider(db.get_key_by_hash)
                tree_data = db.load_index()

                # 3. Finalize
                def finalize():
                    self.db = db
                    self.tree_data = tree_data
                    self.is_db_loading = False
                    dpg.hide_item("loading_modal")

                    # 4. Trigger initial renders now that DB is ready
                    self.executor.submit(
                        self._render_browser_tree_items, "browse_group"
                    )
                    self.executor.submit(self._render_scene_results, "")
                    self.executor.submit(self._render_prop_results, "")

                self._queue_ui_task(finalize)

            except Exception as e:
                print(f"Failed to load database: {e}")
                self._queue_ui_task(lambda: dpg.hide_item("loading_modal"))
                self.is_db_loading = False

        self.executor.submit(run_db_load)

    def run(self):
        dpg.create_context()
        self._setup_fonts()
        dpg.add_texture_registry(tag="main_texture_registry")

        # Create a placeholder texture for image buttons (matched to 100x100)
        # Using a solid gray (0.5) to indicate loading state visually
        # 100 * 100 * 4 = 40,000 values
        with self.texture_lock:
            placeholder_data = [0.5] * 40000
            dpg.add_static_texture(
                width=100,
                height=100,
                default_value=placeholder_data,
                tag="thumb_placeholder",
                parent="main_texture_registry",
            )

        # Create themes before layout
        with dpg.theme(tag="button_state_theme"):
            with dpg.theme_component(dpg.mvButton, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Text, [128, 128, 128])
                dpg.add_theme_color(dpg.mvThemeCol_Button, [45, 45, 48])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [45, 45, 48])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [45, 45, 48])
                dpg.add_theme_style(
                    dpg.mvStyleVar_Alpha, 0.5, category=dpg.mvThemeCat_Core
                )

        with dpg.theme(tag="checkbox_state_theme"):
            with dpg.theme_component(dpg.mvCheckbox, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Text, [128, 128, 128])
                dpg.add_theme_color(dpg.mvThemeCol_CheckMark, [80, 80, 80])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, [50, 50, 50])
                dpg.add_theme_style(
                    dpg.mvStyleVar_Alpha, 0.5, category=dpg.mvThemeCat_Core
                )

        self._create_file_dialog()
        self._create_main_layout()

        # Add a simple loading modal
        with dpg.window(
            label="Loading...",
            modal=True,
            show=False,
            tag="loading_modal",
            no_title_bar=True,
            pos=(500, 350),
            width=200,
            height=100,
        ):
            dpg.add_text("Parsing Database...")
            dpg.add_loading_indicator(style=1)

        self._setup_shortcuts()

        dpg.create_viewport(title="Uma Musume Exporter", width=1200, height=800)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        self._update_nav_buttons()

        self._load_database_async()

        dpg.set_primary_window("PrimaryWindow", True)
        try:
            while dpg.is_dearpygui_running():
                self._drain_ui_tasks()
                self._process_lazy_thumbnails()
                dpg.render_dearpygui_frame()
        finally:
            if self.f3d_process and self.f3d_process.poll() is None:
                try:
                    self.f3d_process.stdin.write("STOP\n")
                    self.f3d_process.stdin.flush()
                    self.f3d_process.wait(timeout=1)
                except:
                    self.f3d_process.terminate()

            self.executor.shutdown(wait=False, cancel_futures=True)

            dpg.destroy_context()
            if self.db:
                self.db.close()

    def _queue_ui_task(self, task):
        self.ui_tasks.put(task)

    def _drain_ui_tasks(self):
        for _ in range(self.max_ui_tasks_per_frame):
            try:
                task = self.ui_tasks.get_nowait()
            except Empty:
                return
            try:
                task()
            except Exception as e:
                print(f"UI task error: {e}")

    def _setup_shortcuts(self):
        with dpg.handler_registry():
            dpg.add_key_press_handler(key=dpg.mvKey_F, callback=self._on_ctrl_f)
            dpg.add_key_press_handler(key=dpg.mvKey_Q, callback=self._on_ctrl_q)
            dpg.add_key_press_handler(key=dpg.mvKey_Up, callback=self._on_key_press)
            dpg.add_key_press_handler(key=dpg.mvKey_Down, callback=self._on_key_press)
            dpg.add_key_press_handler(key=dpg.mvKey_J, callback=self._on_key_press)
            dpg.add_key_press_handler(key=dpg.mvKey_K, callback=self._on_key_press)
            dpg.add_key_release_handler(key=dpg.mvKey_Up, callback=self._on_key_release)
            dpg.add_key_release_handler(
                key=dpg.mvKey_Down, callback=self._on_key_release
            )
            dpg.add_key_release_handler(key=dpg.mvKey_J, callback=self._on_key_release)
            dpg.add_key_release_handler(key=dpg.mvKey_K, callback=self._on_key_release)
            dpg.add_mouse_move_handler(callback=self._on_mouse_move)
            dpg.add_mouse_down_handler(
                button=dpg.mvMouseButton_Middle, callback=self._on_middle_mouse_down
            )
            dpg.add_mouse_drag_handler(
                button=dpg.mvMouseButton_Middle, callback=self._on_middle_mouse_drag
            )
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Middle, callback=self._on_middle_mouse_release
            )
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Left, callback=self._on_left_mouse_release
            )

    def _is_ctrl_pressed(self):
        return dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(
            dpg.mvKey_RControl
        )

    def _on_ctrl_f(self, sender, app_data, user_data, *args):
        if not self._is_ctrl_pressed():
            return

        active_tab = (
            dpg.get_value("main_tabs") if dpg.does_alias_exist("main_tabs") else None
        )
        active_tab_alias = ""
        try:
            if active_tab and not isinstance(active_tab, str):
                active_tab_alias = dpg.get_item_alias(active_tab) or ""
            elif isinstance(active_tab, str):
                active_tab_alias = active_tab
        except Exception:
            active_tab_alias = ""

        # Focus by active tab first; fallback to visible fields only.
        if active_tab_alias == "scene_tab" and dpg.does_item_exist(
            "scene_search_input"
        ):
            dpg.focus_item("scene_search_input")
        elif active_tab_alias == "prop_tab" and dpg.does_item_exist(
            "prop_search_input"
        ):
            dpg.focus_item("prop_search_input")
        elif active_tab_alias == "home_tab" and dpg.does_item_exist("search_input"):
            dpg.focus_item("search_input")
        elif active_tab_alias == "settings_tab" and dpg.does_item_exist(
            "settings_base_path"
        ):
            dpg.focus_item("settings_base_path")
        elif dpg.does_item_exist("search_input") and dpg.is_item_shown("search_input"):
            dpg.focus_item("search_input")
        elif dpg.does_item_exist("scene_search_input") and dpg.is_item_shown(
            "scene_search_input"
        ):
            dpg.focus_item("scene_search_input")
        elif dpg.does_item_exist("prop_search_input") and dpg.is_item_shown(
            "prop_search_input"
        ):
            dpg.focus_item("prop_search_input")
        elif dpg.does_item_exist("settings_base_path") and dpg.is_item_shown(
            "settings_base_path"
        ):
            dpg.focus_item("settings_base_path")

    def _on_ctrl_q(self, sender, app_data, user_data, *args):
        if self._is_ctrl_pressed():
            dpg.stop_dearpygui()

    def _on_key_press(self, sender, key_code, user_data, *args):
        # 1. Prevent keyboard navigation if an input field is focused (except for Up/Down)
        for input_tag in [
            "search_input",
            "scene_search_input",
            "prop_search_input",
            "settings_base_path",
        ]:
            if dpg.does_item_exist(input_tag) and dpg.is_item_focused(input_tag):
                if key_code not in (dpg.mvKey_Up, dpg.mvKey_Down):
                    return

        # 2. Ensure we have a valid selection to start from
        # If no valid selection exists, try to find the first visible selectable in the active container
        if (
            not self.last_selected
            or not dpg.does_item_exist(self.last_selected)
            or not dpg.is_item_shown(self.last_selected)
        ):
            active_tab = dpg.get_value("main_tabs")
            parent = None
            if active_tab == "home_tab":
                parent = (
                    "search_results"
                    if dpg.is_item_shown("search_group")
                    else "browse_group"
                )
            elif active_tab == "scene_tab":
                parent = "scene_results_parent"
            elif active_tab == "prop_tab":
                parent = "prop_results_parent"

            if parent and dpg.does_item_exist(parent):
                children = dpg.get_item_children(parent, slot=1)
                for child in children:
                    if child in self.file_item_data:
                        self.last_selected = child
                        break

        if not self.last_selected or not dpg.does_item_exist(self.last_selected):
            return

        # 3. Handle Navigation Mode (Equivalent to Drag Preview)
        self.drag_preview_active = True

        # 4. Find the container (parent) of the currently selected item
        parent = dpg.get_item_parent(self.last_selected)
        if not parent:
            return

        # 5. Get all siblings and filter for file selectables
        siblings = dpg.get_item_children(parent, slot=1)
        # Robust normalization: Ensure we match regardless of whether DPG returns ints or tags
        selectables = []
        for s in siblings:
            if s in self.file_item_data:
                selectables.append(s)
            else:
                alias = dpg.get_item_alias(s)
                if alias and alias in self.file_item_data:
                    selectables.append(alias)

        if not selectables:
            return

        # 6. Find current index and calculate new index
        # We also normalize self.last_selected comparison
        current_idx = -1
        last_selected_alias = (
            dpg.get_item_alias(self.last_selected) or self.last_selected
        )
        for i, s in enumerate(selectables):
            s_alias = dpg.get_item_alias(s) or s
            if (
                s == self.last_selected
                or s_alias == self.last_selected
                or s == last_selected_alias
            ):
                current_idx = i
                break

        if current_idx == -1:
            return

        new_idx = current_idx
        if key_code in (dpg.mvKey_Up, dpg.mvKey_K):
            new_idx = max(0, current_idx - 1)
        elif key_code in (dpg.mvKey_Down, dpg.mvKey_J):
            new_idx = min(len(selectables) - 1, current_idx + 1)
        # 7. Trigger navigation
        if new_idx != current_idx:
            target_item = selectables[new_idx]
            target_data = self.file_item_data.get(target_item)
            if target_data:
                self.on_file_click(target_item, None, target_data)

                # 8. Find the scrollable container
                # First, check explicit known containers based on tab
                active_tab = dpg.get_value("main_tabs")
                scroll_container = None
                if active_tab == "home_tab":
                    scroll_container = (
                        "search_results"
                        if dpg.is_item_shown("search_group")
                        else "home_browse_scroll"
                    )
                elif active_tab == "scene_tab":
                    scroll_container = "scene_results_parent"
                elif active_tab == "prop_tab":
                    scroll_container = "prop_results_parent"

                # Fallback to generic search if explicit one is not found
                if not scroll_container or not dpg.does_item_exist(scroll_container):
                    scroll_container = self._find_scroll_target_for_item(target_item)

                if scroll_container:
                    self._scroll_to_item(scroll_container, target_item)

    def _on_key_release(self, sender, key_code, user_data, *args):
        # Finalize selection when navigation keys are released
        if key_code in (dpg.mvKey_Up, dpg.mvKey_Down, dpg.mvKey_J, dpg.mvKey_K):
            # Only finalize if no other navigation keys are held
            if not (
                dpg.is_key_down(dpg.mvKey_Up)
                or dpg.is_key_down(dpg.mvKey_Down)
                or dpg.is_key_down(dpg.mvKey_J)
                or dpg.is_key_down(dpg.mvKey_K)
            ):
                self.drag_preview_active = False
                if self.last_selected:
                    data = self.file_item_data.get(self.last_selected)
                    if data:
                        # Full load on release
                        self.on_file_click(self.last_selected, None, data)

    def _scroll_to_item(self, container, item):
        if (
            not container
            or not item
            or not dpg.does_item_exist(container)
            or not dpg.does_item_exist(item)
        ):
            return

        # 1. Try built-in focus (most reliable way to trigger ImGui's internal scroll-to-item)
        try:
            dpg.focus_item(item)
        except:
            pass

        # 2. Manual scroll logic as a robust fallback
        try:
            # Get item and container screen positions
            item_min = dpg.get_item_rect_min(item)
            item_max = dpg.get_item_rect_max(item)
            cont_min = dpg.get_item_rect_min(container)
            cont_max = dpg.get_item_rect_max(container)

            if item_min[1] == 0 and item_max[1] == 0:
                return  # Item might not be rendered yet

            iy_min, iy_max = item_min[1], item_max[1]
            cy_min, cy_max = cont_min[1], cont_max[1]

            curr_scroll = dpg.get_y_scroll(container)
            max_scroll = dpg.get_y_scroll_max(container)

            # Margin for visibility
            margin = 40

            if iy_min < cy_min + margin:
                # Off-screen top
                diff = (cy_min + margin) - iy_min
                dpg.set_y_scroll(container, max(0.0, curr_scroll - diff))
            elif iy_max > cy_max - margin:
                # Off-screen bottom
                diff = iy_max - (cy_max - margin)
                dpg.set_y_scroll(container, min(max_scroll, curr_scroll + diff))
        except:
            pass

    def _show_about(self, *args):
        if dpg.does_item_exist("about_window"):
            dpg.show_item("about_window")
            dpg.focus_item("about_window")
            return

        with dpg.window(
            label=i18n("menu_about"),
            tag="about_window",
            width=450,
            height=200,
            pos=[300, 300],
            no_collapse=True,
        ):
            dpg.add_text("Uma Musume Exporter", color=[0, 255, 255])
            dpg.add_spacer(height=10)
            dpg.add_text(f"{i18n('label_author')}Mumulhl (沐沐13号)")
            dpg.add_text(f"{i18n('label_license')}GPL-3.0")
            dpg.add_spacer(height=10)

            dpg.add_text("GitHub: ")
            dpg.add_button(
                label="https://github.com/mumu-lhl/UmaExporter",
                callback=lambda: webbrowser.open(
                    "https://github.com/mumu-lhl/UmaExporter"
                ),
                small=True,
            )

    def _create_file_dialog(self):
        with dpg.file_dialog(
            directory_selector=True,
            show=False,
            callback=self.on_export_selected,
            id="export_dialog",
            width=600,
            height=400,
        ):
            dpg.add_file_extension(".*")

        with dpg.file_dialog(
            directory_selector=True,
            show=False,
            callback=self.on_settings_dir_selected,
            id="settings_dir_dialog",
            width=600,
            height=400,
        ):
            dpg.add_file_extension(".*")

    def _create_main_layout(self):
        # Create a theme for disabled buttons
        if not dpg.does_alias_exist("disabled_btn_theme"):
            with dpg.theme(tag="disabled_btn_theme"):
                with dpg.theme_component(dpg.mvButton, enabled_state=False):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, [128, 128, 128])
                    dpg.add_theme_color(dpg.mvThemeCol_Button, [40, 40, 40])
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [40, 40, 40])
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [40, 40, 40])

        if not dpg.does_item_exist("PrimaryWindow"):
            dpg.add_window(tag="PrimaryWindow")

        dpg.delete_item("PrimaryWindow", children_only=True)
        # We use dpg.set_item_label or similar if we wanted, but we just want to fill it.
        # To use 'with' on an existing item without re-adding it, we use the parent parameter
        # or just push it. But in DPG, 'with window' always tries to add if not careful.
        # Actually, if we want to add to an existing window, we just don't use the tag in the constructor
        # if we are already inside the window context, OR we specify the parent.
        # The cleanest way to RE-USE a window with 'with' is not to use 'with dpg.window' again.

        # Use a group as a temporary container to hold everything, then reparent if needed,
        # OR simply add items directly specifying parent.

        with dpg.menu_bar(parent="PrimaryWindow"):
            with dpg.menu(label=i18n("menu_file")):
                dpg.add_menu_item(
                    label=i18n("tab_settings"),
                    callback=lambda: dpg.set_value("main_tabs", "settings_tab"),
                )
                dpg.add_menu_item(
                    label=i18n("menu_exit"), callback=lambda: dpg.stop_dearpygui()
                )
            with dpg.menu(label=i18n("menu_help")):
                dpg.add_menu_item(label=i18n("menu_about"), callback=self._show_about)

        with dpg.tab_bar(tag="main_tabs", parent="PrimaryWindow"):
            with dpg.tab(label=i18n("tab_home"), tag="home_tab"):
                with dpg.group(horizontal=True):
                    # Left Column: Browser/Search (Fixed Search Bar)
                    with dpg.child_window(width=500, border=True, resizable_x=True):
                        self._build_search_bar(
                            "search_input",
                            self.on_search,
                            self.clear_search,
                            scroll_targets=["home_browse_scroll", "search_results"],
                        )
                        dpg.add_separator()

                        # Content area that scrolls
                        with dpg.child_window(tag="home_browse_scroll", border=False):
                            self._build_browser_tree()

                    # Right Column: Details
                    with dpg.child_window(
                        tag="home_details_scroll", width=-1, border=True
                    ):
                        self._build_details_panel()

            with dpg.tab(label=i18n("tab_scene"), tag="scene_tab"):
                with dpg.group(horizontal=True):
                    # Left Column: Scene Browser/Search
                    with dpg.child_window(width=500, border=True, resizable_x=True):
                        self._build_search_bar(
                            "scene_search_input",
                            self.on_scene_search,
                            self.clear_scene_search,
                            scroll_targets=["scene_results_parent"],
                        )
                        with dpg.group(horizontal=True):
                            dpg.add_radio_button(
                                items=[
                                    i18n("label_view_list"),
                                    i18n("label_view_thumbnail"),
                                ],
                                default_value=i18n("label_view_list"),
                                horizontal=True,
                                callback=self._on_view_mode_change,
                                user_data="scene_",
                            )
                        dpg.add_separator()
                        with dpg.child_window(tag="scene_results_parent", border=False):
                            pass
                        with dpg.child_window(
                            tag="scene_thumbnails_parent", border=False, show=False
                        ):
                            pass

                    # Right Column: Details (same structure as Home)
                    with dpg.child_window(
                        tag="scene_details_scroll", width=-1, border=True
                    ):
                        self._build_details_panel(prefix="scene_")

            with dpg.tab(label=i18n("tab_prop"), tag="prop_tab"):
                with dpg.group(horizontal=True):
                    # Left Column: Prop Browser/Search
                    with dpg.child_window(width=500, border=True, resizable_x=True):
                        self._build_search_bar(
                            "prop_search_input",
                            self.on_prop_search,
                            self.clear_prop_search,
                            scroll_targets=["prop_results_parent"],
                        )
                        with dpg.group(horizontal=True):
                            dpg.add_radio_button(
                                items=[
                                    i18n("label_view_list"),
                                    i18n("label_view_thumbnail"),
                                ],
                                default_value=i18n("label_view_list"),
                                horizontal=True,
                                callback=self._on_view_mode_change,
                                user_data="prop_",
                            )
                        dpg.add_separator()
                        with dpg.child_window(tag="prop_results_parent", border=False):
                            pass
                        with dpg.child_window(
                            tag="prop_thumbnails_parent", border=False, show=False
                        ):
                            pass

                    # Right Column: Details
                    with dpg.child_window(
                        tag="prop_details_scroll", width=-1, border=True
                    ):
                        self._build_details_panel(prefix="prop_")

            with dpg.tab(label=i18n("tab_actions"), tag="actions_tab"):
                with dpg.group(indent=20):
                    dpg.add_spacer(height=10)
                    dpg.add_text(i18n("label_batch_thumb"), color=[0, 255, 0])
                    dpg.add_separator()
                    dpg.add_spacer(height=10)

                    dpg.add_text(i18n("label_select_cats"))
                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(
                            label=i18n("label_cat_all"),
                            tag="batch_cat_all",
                            default_value=True,
                            callback=self._on_batch_cat_all_change,
                        )
                        dpg.add_checkbox(
                            label=i18n("label_cat_scene"),
                            tag="batch_cat_scene",
                            default_value=True,
                            enabled=False,
                        )
                        dpg.bind_item_theme("batch_cat_scene", "checkbox_state_theme")
                        dpg.add_checkbox(
                            label=i18n("label_cat_prop"),
                            tag="batch_cat_prop",
                            default_value=True,
                            enabled=False,
                        )
                        dpg.bind_item_theme("batch_cat_prop", "checkbox_state_theme")

                    dpg.add_spacer(height=10)
                    dpg.add_text(i18n("label_batch_size"))
                    dpg.add_input_int(
                        tag="batch_size",
                        default_value=0,
                        min_value=0,
                        width=200,
                        callback=lambda s, a: dpg.set_value(s, max(0, a)),
                    )

                    dpg.add_spacer(height=5)
                    dpg.add_checkbox(
                        label=i18n("label_force_overwrite"),
                        tag="batch_force_overwrite",
                        default_value=False,
                    )

                    dpg.add_spacer(height=20)
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label=i18n("btn_start_batch"),
                            tag="btn_start_batch",
                            callback=self.on_start_batch_click,
                            width=150,
                        )
                        dpg.bind_item_theme("btn_start_batch", "button_state_theme")
                        dpg.add_button(
                            label=i18n("btn_stop_batch"),
                            tag="btn_stop_batch",
                            callback=self.on_stop_batch_click,
                            width=100,
                            enabled=False,
                        )
                        dpg.bind_item_theme("btn_stop_batch", "button_state_theme")

                    dpg.add_spacer(height=20)
                    dpg.add_text(
                        i18n("label_progress"), tag="batch_progress_text", show=False
                    )
                    dpg.add_progress_bar(tag="batch_progress_bar", width=-1, show=False)
                    dpg.add_text("", tag="batch_status_msg", wrap=600)

            with dpg.tab(label=i18n("tab_settings"), tag="settings_tab"):
                with dpg.group(indent=20):
                    dpg.add_spacer(height=10)
                    dpg.add_text(i18n("label_settings"), color=[0, 255, 0])
                    dpg.add_separator()
                    dpg.add_spacer(height=10)

                    dpg.add_text(i18n("label_data_root"))
                    with dpg.group(horizontal=True):
                        dpg.add_input_text(
                            tag="settings_base_path",
                            default_value=Config.BASE_PATH,
                            width=-100,
                        )
                        dpg.add_button(
                            label=i18n("btn_browse"),
                            callback=lambda: dpg.show_item("settings_dir_dialog"),
                        )

                    dpg.add_spacer(height=10)
                    dpg.add_text(i18n("label_region"))
                    region_options = {
                        i18n("region_jp"): "jp",
                        i18n("region_global"): "global",
                    }
                    reverse_region_map = {v: k for k, v in region_options.items()}
                    dpg.add_combo(
                        items=list(region_options.keys()),
                        default_value=reverse_region_map.get(
                            Config.REGION, i18n("region_jp")
                        ),
                        tag="settings_region",
                        width=200,
                    )

                    dpg.add_spacer(height=10)
                    dpg.add_text(i18n("label_language"))
                    dpg.add_combo(
                        items=["Auto", "English", "Chinese"],
                        tag="settings_language",
                        default_value=Config.LANGUAGE,
                        width=200,
                    )

                    dpg.add_spacer(height=20)
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label=i18n("btn_apply"),
                            width=200,
                            callback=self.apply_settings,
                        )
                        dpg.add_button(
                            label=i18n("btn_clear_cache"),
                            width=200,
                            callback=self.on_clear_thumbnail_cache,
                        )
                        dpg.add_text("", tag="settings_status_msg")

                    dpg.add_text(
                        i18n("label_restart_note"),
                        color=[150, 150, 150],
                    )
        # Bind the disabled theme
        dpg.bind_item_theme("nav_back_btn", "disabled_btn_theme")
        dpg.bind_item_theme("nav_forward_btn", "disabled_btn_theme")
        if dpg.does_alias_exist("scene_nav_back_btn"):
            dpg.bind_item_theme("scene_nav_back_btn", "disabled_btn_theme")
        if dpg.does_alias_exist("scene_nav_forward_btn"):
            dpg.bind_item_theme("scene_nav_forward_btn", "disabled_btn_theme")
        if dpg.does_alias_exist("prop_nav_back_btn"):
            dpg.bind_item_theme("prop_nav_back_btn", "disabled_btn_theme")
        if dpg.does_alias_exist("prop_nav_forward_btn"):
            dpg.bind_item_theme("prop_nav_forward_btn", "disabled_btn_theme")

        # Ensure navigation buttons start in the correct state
        self._update_nav_buttons()

    def _build_search_bar(
        self, tag, search_callback, clear_callback, scroll_targets=None
    ):
        def scroll_to_top():
            if not scroll_targets:
                return
            for target in scroll_targets:
                if dpg.does_item_exist(target):
                    try:
                        dpg.set_y_scroll(target, 0)
                    except:
                        pass

        # Use a table to allow the input to stretch while buttons take only needed space
        with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column()  # Input field (stretchy)
            dpg.add_table_column(width_fixed=True)  # Search button
            dpg.add_table_column(width_fixed=True)  # Clear button
            if scroll_targets:
                dpg.add_table_column(width_fixed=True)  # Top button

            with dpg.table_row():
                dpg.add_input_text(
                    hint=i18n("search_hint"),
                    tag=tag,
                    width=-1,
                    on_enter=True,
                    callback=search_callback,
                )

                # Search Button
                search_btn = dpg.add_button(
                    label=i18n("btn_search"), callback=search_callback
                )
                with dpg.tooltip(search_btn):
                    dpg.add_text(i18n("tooltip_search"))

                # Clear Button
                clear_btn = dpg.add_button(
                    label=i18n("btn_clear"), callback=clear_callback
                )
                with dpg.tooltip(clear_btn):
                    dpg.add_text(i18n("tooltip_clear"))

                # Top Button
                if scroll_targets:
                    top_btn = dpg.add_button(
                        label=i18n("btn_top"), callback=scroll_to_top
                    )
                    with dpg.tooltip(top_btn):
                        dpg.add_text(i18n("tooltip_top"))
                # Apply theme if available, otherwise use inline styling via item colors (simpler for DPG)
                # But since DPG themes are preferred for consistency, I will use a simple color style.

    def _build_browser_tree(self):
        with dpg.group(tag="browse_group"):
            pass

        with dpg.group(tag="search_group", show=False):
            dpg.add_text(i18n("search_results"), color=[0, 255, 255])
            with dpg.child_window(tag="search_results", border=False):
                pass

    def _render_browser_tree_items(self, parent):
        self._queue_ui_task(
            lambda: dpg.add_text(
                i18n("dir_browser"), color=[255, 200, 0], parent=parent
            )
        )

        # Sort root items: directories first, then files
        root_items = sorted(
            self.tree_data.items(),
            key=lambda x: (
                isinstance(x[1], dict) and x[1].get("_is_file", False),
                x[0],
            ),
        )

        for name, content in root_items:
            self.render_node(name, content, parent)

    def _build_details_panel(self, prefix=""):
        nav_back_tag = f"{prefix}nav_back_btn"
        nav_forward_tag = f"{prefix}nav_forward_btn"
        path_tag = f"{prefix}ui_path"
        details_group_tag = f"{prefix}details_group"
        hash_tag = f"{prefix}ui_hash"
        size_tag = f"{prefix}ui_size"
        phys_tag = f"{prefix}ui_phys"
        thumbnail_container_tag = f"{prefix}ui_thumbnail_container"
        unity_parent_tag = f"{prefix}ui_unity_parent"
        unity_image_container_tag = f"{prefix}ui_unity_image_container"
        dep_parent_tag = f"{prefix}ui_dep_parent"
        rev_dep_parent_tag = f"{prefix}ui_rev_dep_parent"
        dep_section_tag = f"{prefix}ui_dep_section"
        rev_dep_section_tag = f"{prefix}ui_rev_dep_section"

        with dpg.group(horizontal=True):
            dpg.add_button(
                label=i18n("btn_back"),
                callback=self.go_back,
                tag=nav_back_tag,
                enabled=False,
            )
            dpg.add_button(
                label=i18n("btn_forward"),
                callback=self.go_forward,
                tag=nav_forward_tag,
                enabled=False,
            )
            dpg.add_text(i18n("label_asset_props"), color=[0, 255, 0])

        dpg.add_separator()
        dpg.add_text(i18n("label_select_file"), tag=path_tag, wrap=650)

        with dpg.group(tag=details_group_tag, show=False):
            with dpg.group(horizontal=True):
                dpg.add_text(i18n("prop_storage_hash"))
                dpg.add_input_text(tag=hash_tag, readonly=True, width=-1)
            dpg.add_text("", tag=size_tag)
            dpg.add_text("", tag=phys_tag, color=[120, 150, 255])
            dpg.add_spacer(height=10)

            # Thumbnail container
            with dpg.group(tag=thumbnail_container_tag, show=False):
                dpg.add_text(i18n("label_thumbnail"), color=[0, 255, 255])
                dpg.add_group(tag=f"{prefix}ui_thumbnail_actions_parent")
                dpg.add_group(tag=f"{prefix}ui_thumbnail_image_parent")

            dpg.add_spacer(height=5)
            dpg.add_button(
                label=i18n("btn_export"),
                width=200,
                callback=lambda: dpg.show_item("export_dialog"),
            )

            dpg.add_spacer(height=20)
            with dpg.group(tag=f"{prefix}ui_unity_section"):
                dpg.add_text(i18n("label_unity_objs"), color=[0, 255, 255])
                dpg.add_separator()
                with dpg.child_window(height=250, border=True, tag=unity_parent_tag):
                    pass

            with dpg.group(tag=unity_image_container_tag, show=False):
                pass

            with dpg.group(tag=dep_section_tag):
                dpg.add_spacer(height=20)
                dpg.add_text(i18n("label_ext_deps"), color=[255, 255, 0])
                dpg.add_separator()
                with dpg.child_window(height=200, border=True, tag=dep_parent_tag):
                    pass

            with dpg.group(tag=rev_dep_section_tag):
                dpg.add_spacer(height=20)
                dpg.add_text(i18n("label_used_by"), color=[255, 100, 100])
                dpg.add_separator()
                with dpg.child_window(height=200, border=True, tag=rev_dep_parent_tag):
                    pass

    def render_node(self, name, content, parent):
        if isinstance(content, dict) and content.get("_is_file"):

            def add_f_item():
                self._add_file_selectable(
                    label=f"[F] {name}",
                    user_data=content,
                    parent=parent,
                )

            self._queue_ui_task(add_f_item)
        else:

            def add_d_node():
                node = dpg.add_tree_node(
                    label=f"[D] {name}",
                    parent=parent,
                    selectable=False,
                    span_full_width=True,
                )
                self.node_map[node] = content
                dpg.add_text("Click to load content...", parent=node)

                # Bind handler inside the main-thread task
                with dpg.item_handler_registry() as handler:
                    dpg.add_item_clicked_handler(callback=self.on_tree_click)
                dpg.bind_item_handler_registry(node, handler)

            self._queue_ui_task(add_d_node)

    def on_tree_click(self, sender, app_data, user_data, *args):
        node = app_data[1]
        if node not in self.node_map:
            return
        children = dpg.get_item_children(node, slot=1)
        found_loading_text = False
        for child in children:
            if dpg.get_item_type(child) == "mvAppItemType::mvText":
                dpg.delete_item(child)
                found_loading_text = True
                break

        if not found_loading_text:
            return

        content = self.node_map.pop(node)
        dirs, files = [], []
        if "_file_entry" in content:
            files.append(("[F] (Asset Root)", content["_file_entry"]))
        for sub_name, sub_content in content.items():
            if sub_name == "_file_entry":
                continue
            if isinstance(sub_content, dict) and "_is_file" in sub_content:
                files.append((f"[F] {sub_name}", sub_content))
            else:
                dirs.append((sub_name, sub_content))

        for sub_name, sub_content in sorted(dirs):
            self.render_node(sub_name, sub_content, node)
        for label, sub_content in sorted(files):

            def add_sub_file(l=label, c=sub_content, p=node):
                self._add_file_selectable(
                    label=l,
                    user_data=c,
                    parent=p,
                )

            self._queue_ui_task(add_sub_file)

    def _add_file_selectable(
        self, label, user_data, parent=None, tag=None, span_columns=False
    ):
        if parent is not None and not dpg.does_item_exist(parent):
            return None
        safe_label = label if isinstance(label, str) else str(label)
        if "\x00" in safe_label:
            safe_label = safe_label.replace("\x00", "")
        if not safe_label:
            safe_label = "(unnamed)"
        kwargs = {
            "label": safe_label,
            "callback": self.on_file_click,
            "user_data": user_data,
        }
        if parent is not None:
            kwargs["parent"] = parent
        if tag is not None:
            kwargs["tag"] = tag
        if span_columns:
            kwargs["span_columns"] = True
        try:
            item = dpg.add_selectable(**kwargs)
        except Exception:
            return None
        self.file_item_data[item] = user_data
        return item

    def on_file_click(self, sender, app_data, user_data, *args):
        for input_tag in ["search_input", "scene_search_input", "prop_search_input"]:
            if dpg.does_item_exist(input_tag) and dpg.is_item_focused(input_tag):
                if sender and dpg.does_item_exist(sender):
                    dpg.focus_item(sender)
                elif dpg.does_alias_exist("main_tabs"):
                    dpg.focus_item("main_tabs")
                break

        is_drag_preview = self.drag_preview_active
        self.current_view_is_drag_preview = is_drag_preview
        self._set_dependency_sections_visible(not is_drag_preview)
        self.selection_request_id += 1
        request_id = self.selection_request_id
        active_tab = (
            dpg.get_value("main_tabs") if dpg.does_alias_exist("main_tabs") else None
        )
        sender_tag = sender if isinstance(sender, str) else ""
        active_tab_alias = ""
        try:
            if active_tab and not isinstance(active_tab, str):
                active_tab_alias = dpg.get_item_alias(active_tab) or ""
            elif isinstance(active_tab, str):
                active_tab_alias = active_tab
        except Exception:
            active_tab_alias = ""
        is_scene_click_context = sender_tag.startswith("scene_item_") or (
            active_tab_alias == "scene_tab"
        )
        is_prop_click_context = sender_tag.startswith("prop_item_") or (
            active_tab_alias == "prop_tab"
        )
        if is_scene_click_context and not is_drag_preview:
            self.scene_auto_preview_request = {
                "asset_id": user_data["id"],
                "request_id": request_id,
            }
        else:
            self.scene_auto_preview_request = None

        if is_prop_click_context and not is_drag_preview:
            self.prop_auto_preview_request = {
                "asset_id": user_data["id"],
                "request_id": request_id,
            }
        else:
            self.prop_auto_preview_request = None

        if not self.is_navigating:
            current_data = self.current_asset_data
            if current_data and current_data["id"] != user_data["id"]:
                self.history_back.append(self._snapshot_asset_data(current_data))
                self.history_forward.clear()

        self.last_unity_selected = {"": None, "scene_": None, "prop_": None}
        self.current_asset_id = user_data["id"]
        self.current_asset_data = user_data

        self._update_nav_buttons()

        # Handle visual selection state
        if self.last_selected and dpg.does_item_exist(self.last_selected):
            try:
                # Reset previous: if it was a selectable
                if (
                    dpg.get_item_type(self.last_selected)
                    == "mvAppItemType::mvSelectable"
                ):
                    dpg.set_value(self.last_selected, False)
                # Reset previous: if it was a thumbnail image
                elif dpg.get_item_type(self.last_selected) == "mvAppItemType::mvImage":
                    dpg.configure_item(
                        self.last_selected, tint_color=[255, 255, 255, 255]
                    )
            except Exception:
                pass

        if sender:
            # Apply selection to new item
            if dpg.get_item_type(sender) == "mvAppItemType::mvSelectable":
                dpg.set_value(sender, True)
            elif dpg.get_item_type(sender) == "mvAppItemType::mvImage":
                # Light blue tint for selected thumbnail
                dpg.configure_item(sender, tint_color=[150, 200, 255, 255])

            self.last_selected = sender
        else:
            self.last_selected = self._select_existing_result_item(user_data["id"])
            # If the fallback found an item, apply the selection color if it's an image
            if (
                self.last_selected
                and dpg.get_item_type(self.last_selected) == "mvAppItemType::mvImage"
            ):
                dpg.configure_item(self.last_selected, tint_color=[150, 200, 255, 255])

        for prefix in self._detail_prefixes():
            self._update_asset_properties_panel(prefix, user_data)
            if not is_drag_preview:
                dpg.configure_item(f"{prefix}ui_unity_image_container", show=False)
                dpg.delete_item(f"{prefix}ui_unity_image_container", children_only=True)

        h = user_data["hash"]
        self.current_asset_hash = h

        self._reset_detail_containers(is_drag_preview=is_drag_preview)

        phys_path = os.path.join(Config.get_data_root(), h[:2], h)
        asset_id = user_data["id"]
        bundle_key = user_data.get("key")

        if is_drag_preview:
            # Performance optimization: During drag-previews on scene and prop pages,
            # we skip UnityPy file parsing entirely and only show the thumbnail.
            # We check both the context flags and self.is_navigating to be sure it's a transient view.
            if is_scene_click_context or is_prop_click_context:
                prefix = "scene_" if is_scene_click_context else "prop_"
                self._check_and_display_thumbnail(prefix, h)
                return

            self._preview_drag_texture_async(
                phys_path, asset_id, request_id, bundle_key=bundle_key
            )
            return

        self._load_unity_async(phys_path, asset_id, request_id, bundle_key=bundle_key)
        self._load_deps_async(asset_id, request_id)
        self._load_rev_deps_async(asset_id, request_id)

    def _ensure_f3d_viewer(self):
        """Ensure the f3d viewer process is running via subprocess"""
        with self.f3d_lock:
            if self.f3d_process is None or self.f3d_process.poll() is not None:
                # Get the path to the current executable (works for Nuitka, PyInstaller, and raw Python)
                executable = sys.executable

                args = [executable]
                # If running from source, main.py is the second argument
                if not (getattr(sys, "frozen", False) or "__compiled__" in globals()):
                    # We assume main.py is in the current directory or executable path
                    main_py = os.path.abspath(sys.argv[0])
                    args = [executable, main_py]

                args.append("--f3d-viewer")

                self.f3d_process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,  # Line buffered
                    # On Windows, hide the console window
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )

                # Thread to pipe stdout and stderr to the main terminal
                def log_pipe(pipe, label):
                    try:
                        for line in iter(pipe.readline, ""):
                            if line:
                                print(f"{label}: {line.strip()}", flush=True)
                        pipe.close()
                    except:
                        pass

                threading.Thread(
                    target=log_pipe,
                    args=(self.f3d_process.stdout, "[F3D-OUT]"),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=log_pipe,
                    args=(self.f3d_process.stderr, "[F3D-ERR]"),
                    daemon=True,
                ).start()

    def on_search(self, sender, app_data, user_data, *args):
        if not self.db:
            return
        query = dpg.get_value("search_input").strip()
        if not query:
            self.clear_search()
            return

        def run_search():
            self._queue_ui_task(lambda: dpg.configure_item("browse_group", show=False))
            self._queue_ui_task(lambda: dpg.configure_item("search_group", show=True))
            self._queue_ui_task(
                lambda: dpg.delete_item("search_results", children_only=True)
            )

            rows = self.db.search_assets(query)
            if not rows:
                self._queue_ui_task(
                    lambda: dpg.add_text(
                        i18n("label_no_assets"), parent="search_results"
                    )
                )
            else:
                first_item = None
                for i_id, name, size, f_hash, key_val in rows:
                    u_data = {
                        "id": i_id,
                        "full_path": name,
                        "size": size,
                        "hash": f_hash,
                        "key": key_val,
                    }

                    def add_item(
                        label=os.path.basename(name),
                        tag=f"search_item_{i_id}",
                        data=u_data,
                    ):
                        self._add_file_selectable(
                            label=label,
                            tag=tag,
                            user_data=data,
                            parent="search_results",
                            span_columns=True,
                        )

                    self._queue_ui_task(add_item)
                    if first_item is None:
                        first_item = (f"search_item_{i_id}", u_data)

                if first_item:
                    self._queue_ui_task(
                        lambda f=first_item: self.on_file_click(f[0], None, f[1])
                    )

        self.executor.submit(run_search)

    def on_scene_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("scene_search_input").strip()
        self.executor.submit(self._render_scene_results, query)

    def _scene_display_name(self, full_path):
        return os.path.basename(full_path)

    def clear_search(self, *args):
        dpg.set_value("search_input", "")
        dpg.configure_item("browse_group", show=True)
        dpg.configure_item("search_group", show=False)

    def clear_scene_search(self, *args):
        dpg.set_value("scene_search_input", "")
        self._render_scene_results("")

    def on_prop_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("prop_search_input").strip()
        self.executor.submit(self._render_prop_results, query)

    def _on_view_mode_change(self, sender, app_data, user_data):
        prefix = user_data  # "scene_" or "prop_"
        new_mode = "thumbnail" if app_data == i18n("label_view_thumbnail") else "list"

        if prefix == "scene_":
            self.scene_view_mode = new_mode
            query = dpg.get_value("scene_search_input").strip()
            self.executor.submit(self._render_scene_results, query)
        else:
            self.prop_view_mode = new_mode
            query = dpg.get_value("prop_search_input").strip()
            self.executor.submit(self._render_prop_results, query)

    def _clear_search_thumbnails(self, prefix):
        with self.texture_lock:
            for tag in self.search_thumbnail_textures.get(prefix, []):
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            self.search_thumbnail_textures[prefix] = []

    def _render_scene_results(self, query=""):
        view_mode = self.scene_view_mode
        list_container = "scene_results_parent"
        thumb_container = "scene_thumbnails_parent"

        self._queue_ui_task(
            lambda: dpg.configure_item(list_container, show=(view_mode == "list"))
        )
        self._queue_ui_task(
            lambda: dpg.configure_item(thumb_container, show=(view_mode == "thumbnail"))
        )
        self._queue_ui_task(lambda: dpg.delete_item(list_container, children_only=True))
        self._queue_ui_task(
            lambda: dpg.delete_item(thumb_container, children_only=True)
        )
        self._clear_search_thumbnails("scene_")
        self.lazy_thumb_queues["scene_"] = []

        if not self.db:
            self._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_db_not_ready"),
                    parent=list_container,
                    color=[200, 120, 120],
                )
            )
            return

        rows = self.db.search_scenes(query)
        if not rows:
            target = list_container if view_mode == "list" else thumb_container
            self._queue_ui_task(
                lambda: dpg.add_text(i18n("label_no_scenes"), parent=target)
            )
            return

        first_item = None

        if view_mode == "list":
            for i_id, name, size, f_hash, key_val in rows:
                u_data = {
                    "id": i_id,
                    "full_path": name,
                    "size": size,
                    "hash": f_hash,
                    "key": key_val,
                }
                display_name = self._scene_display_name(name)

                def add_scene_item(
                    label=display_name, tag=f"scene_item_{i_id}", data=u_data
                ):
                    self._add_file_selectable(
                        label=label,
                        tag=tag,
                        user_data=data,
                        parent=list_container,
                        span_columns=True,
                    )

                self._queue_ui_task(add_scene_item)
                if first_item is None:
                    first_item = (f"scene_item_{i_id}", u_data)
        else:
            # Thumbnail mode
            items_with_thumb = []
            for i_id, name, size, f_hash, key_val in rows:
                if thumb_manager.get_thumbnail(f_hash):
                    items_with_thumb.append((i_id, name, size, f_hash, key_val))

            if not items_with_thumb:
                self.thumbnail_items["scene_"] = []
                self._queue_ui_task(
                    lambda: dpg.add_text(
                        i18n("label_no_scenes"), parent=thumb_container
                    )
                )
            else:
                self._render_thumbnail_grid("scene_", items_with_thumb, thumb_container)
                # In thumb mode, we don't necessarily auto-click the first one as it might be jarring
                # during a search unless explicitly requested.

        if first_item and query and view_mode == "list":
            self._queue_ui_task(
                lambda f=first_item: self.on_file_click(f[0], None, f[1])
            )

    def _render_prop_results(self, query=""):
        view_mode = self.prop_view_mode
        list_container = "prop_results_parent"
        thumb_container = "prop_thumbnails_parent"

        self._queue_ui_task(
            lambda: dpg.configure_item(list_container, show=(view_mode == "list"))
        )
        self._queue_ui_task(
            lambda: dpg.configure_item(thumb_container, show=(view_mode == "thumbnail"))
        )
        self._queue_ui_task(lambda: dpg.delete_item(list_container, children_only=True))
        self._queue_ui_task(
            lambda: dpg.delete_item(thumb_container, children_only=True)
        )
        self._clear_search_thumbnails("prop_")
        self.lazy_thumb_queues["prop_"] = []

        if not self.db:
            self._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_db_not_ready"),
                    parent=list_container,
                    color=[200, 120, 120],
                )
            )
            return

        rows = self.db.search_props(query)
        if not rows:
            target = list_container if view_mode == "list" else thumb_container
            self._queue_ui_task(
                lambda: dpg.add_text(
                    i18n("label_no_props"),
                    parent=target,
                )
            )
            return

        if view_mode == "list":
            first_item = None
            for i_id, name, size, f_hash, key_val in rows:
                u_data = {
                    "id": i_id,
                    "full_path": name,
                    "size": size,
                    "hash": f_hash,
                    "key": key_val,
                }

                def add_prop_item(
                    label=os.path.basename(name), tag=f"prop_item_{i_id}", data=u_data
                ):
                    self._add_file_selectable(
                        label=label,
                        tag=tag,
                        user_data=data,
                        parent=list_container,
                        span_columns=True,
                    )

                self._queue_ui_task(add_prop_item)
                if first_item is None:
                    first_item = (f"prop_item_{i_id}", u_data)

            if first_item and query:
                self._queue_ui_task(
                    lambda f=first_item: self.on_file_click(f[0], None, f[1])
                )
        else:
            # Thumbnail mode
            items_with_thumb = []
            for i_id, name, size, f_hash, key_val in rows:
                if thumb_manager.get_thumbnail(f_hash):
                    items_with_thumb.append((i_id, name, size, f_hash, key_val))

            if not items_with_thumb:
                self.thumbnail_items["prop_"] = []
                self._queue_ui_task(
                    lambda: dpg.add_text(i18n("label_no_props"), parent=thumb_container)
                )
            else:
                self._render_thumbnail_grid("prop_", items_with_thumb, thumb_container)

    def _render_thumbnail_grid(self, prefix, items, parent):
        self.thumbnail_items[prefix] = items

        try:
            width = dpg.get_item_rect_size(parent)[0]
            if width <= 0:
                width = 500
        except Exception:
            width = 500

        columns = max(1, int(width / 115))
        self.thumbnail_columns[prefix] = columns

        def build_grid():
            if not dpg.does_item_exist(parent):
                return

            dpg.delete_item(parent, children_only=True)
            self._clear_search_thumbnails(prefix)
            self.lazy_thumb_queues[prefix] = []

            with dpg.table(
                header_row=False, parent=parent, policy=dpg.mvTable_SizingStretchProp
            ):
                for _ in range(columns):
                    dpg.add_table_column()

                for i in range(0, len(items), columns):
                    with dpg.table_row():
                        for j in range(columns):
                            idx = i + j
                            if idx < len(items):
                                i_id, name, size, f_hash, key_val = items[idx]
                                with dpg.group() as cell_group:
                                    u_data = {
                                        "id": i_id,
                                        "full_path": name,
                                        "size": size,
                                        "hash": f_hash,
                                        "key": key_val,
                                    }

                                    img_id = dpg.add_image(
                                        "thumb_placeholder",
                                        width=100,
                                        height=100,
                                    )

                                    with dpg.item_handler_registry() as handler:
                                        dpg.add_item_clicked_handler(
                                            callback=lambda s, a, u: self.on_file_click(
                                                a[1], a, u
                                            ),
                                            user_data=u_data,
                                        )
                                    dpg.bind_item_handler_registry(img_id, handler)

                                    with dpg.tooltip(img_id):
                                        dpg.add_text(os.path.basename(name))

                                    thumb_path = thumb_manager.get_thumbnail(f_hash)
                                    if thumb_path:
                                        abs_path = os.path.abspath(thumb_path)
                                        # Include parent tag for buffered coordinate checking
                                        self.lazy_thumb_queues[prefix].append(
                                            (abs_path, img_id, parent)
                                        )
                            else:
                                dpg.add_spacer()

        self._queue_ui_task(build_grid)

    def _process_lazy_thumbnails(self):
        """Proximity-Buffered Lazy Loading: Uses visibility as anchor to load a range of items."""
        now = time.time()
        if now - self.last_lazy_scan_time < self.lazy_scan_interval:
            return
        self.last_lazy_scan_time = now

        raw_tab = dpg.get_value("main_tabs")
        active_tab = (
            dpg.get_item_alias(raw_tab) if isinstance(raw_tab, int) else raw_tab
        )
        tab_to_prefix = {"scene_tab": "scene_", "prop_tab": "prop_"}
        active_prefix = tab_to_prefix.get(active_tab)

        if active_prefix:
            view_mode = (
                self.scene_view_mode
                if active_prefix == "scene_"
                else self.prop_view_mode
            )
            if view_mode == "thumbnail":
                container = f"{active_prefix}thumbnails_parent"
                if dpg.does_item_exist(container):
                    width = dpg.get_item_rect_size(container)[0]
                    expected_columns = max(1, int(width / 115))
                    if expected_columns != self.thumbnail_columns.get(active_prefix, 0):
                        items = self.thumbnail_items.get(active_prefix, [])
                        if items:
                            self._render_thumbnail_grid(active_prefix, items, container)
                            return

        if not active_prefix or not self.lazy_thumb_queues[active_prefix]:
            return

        queue = self.lazy_thumb_queues[active_prefix]

        # 1. Find the first visible item to use as an anchor
        first_visible_idx = -1
        # Check every few items to speed up scanning of large lists
        for i in range(0, len(queue), 4):
            try:
                if dpg.is_item_visible(queue[i][1]):
                    first_visible_idx = i
                    break
            except:
                continue

        # 2. Determine the batch to load based on the anchor
        if first_visible_idx == -1:
            # Check the very first one as a final fallback
            try:
                if dpg.is_item_visible(queue[0][1]):
                    first_visible_idx = 0
            except:
                pass

        to_load_batch = []
        remaining = []

        if first_visible_idx == -1:
            # If NOTHING is visible yet (can happen during initial render or fast scroll),
            # just eager-load the first few items to provide immediate feedback.
            to_load_batch = queue[:24]
            remaining = queue[24:]
        else:
            # Load a window around the visible anchor: 12 above, 48 below
            start = max(0, first_visible_idx - 12)
            end = min(len(queue), first_visible_idx + 48)

            to_load_batch = queue[start:end]
            # Keep items outside this window in the queue
            remaining = queue[:start] + queue[end:]

        self.lazy_thumb_queues[active_prefix] = remaining

        if to_load_batch:
            # Extract (path, img_id) for the worker
            tasks = [(t[0], t[1]) for t in to_load_batch]
            self._load_search_thumbnails_batch_async(active_prefix, tasks)

    def _load_search_thumbnails_batch_async(self, prefix, tasks):
        """Processes a batch of thumbnails in a single worker thread."""

        def worker():
            results = []
            resample_filter = getattr(Image, "Resampling", Image).BILINEAR

            for path, img_id in tasks:
                try:
                    if not os.path.exists(path):
                        continue
                    img = Image.open(path).convert("RGBA")
                    img = img.resize((100, 100), resample_filter)
                    data = np.array(img).flatten().astype(np.float32) / 255.0
                    results.append((img_id, data.tolist()))
                except Exception:
                    pass
            return results

        future = self.executor.submit(worker)

        def done(f):
            try:
                batch_results = f.result()
                if batch_results:
                    self._queue_ui_task(
                        lambda: self._apply_search_thumbnails_batch(
                            prefix, batch_results
                        )
                    )
            except Exception:
                pass

        future.add_done_callback(done)

    def _apply_search_thumbnails_batch(self, prefix, batch_results):
        """Applies multiple textures and updates images in a single UI task."""
        with self.texture_lock:
            for img_id, data in batch_results:
                if not dpg.does_item_exist(img_id):
                    continue

                tex_tag = dpg.generate_uuid()
                try:
                    dpg.add_static_texture(
                        width=100,
                        height=100,
                        default_value=data,
                        tag=tex_tag,
                        parent="main_texture_registry",
                    )
                    dpg.configure_item(img_id, texture_tag=tex_tag)
                    self.search_thumbnail_textures[prefix].append(tex_tag)
                except Exception:
                    pass

    def clear_prop_search(self, *args):
        dpg.set_value("prop_search_input", "")
        self.executor.submit(self._render_prop_results, "")

    def on_export_selected(self, sender, app_data, user_data, *args):
        target_dir = app_data.get("file_path_name", "")
        if not target_dir or not self.last_selected or not self.db:
            return

        user_data = dpg.get_item_user_data(self.last_selected)
        asset_id = user_data["id"]

        # Fetch ALL recursive dependencies for Animator/Mesh completeness
        results = self._get_recursive_hashes(asset_id)
        paths = []
        bundle_keys = []
        for h, k in results:
            p = os.path.join(Config.get_data_root(), h[:2], h)
            if os.path.exists(p):
                paths.append(p)
                bundle_keys.append(k)

        self.executor.submit(
            UnityLogic.export_unity_assets, paths, target_dir, bundle_keys=bundle_keys
        )

    def on_settings_dir_selected(self, sender, app_data, user_data, *args):
        new_path = app_data.get("file_path_name", "")
        if new_path:
            dpg.set_value("settings_base_path", new_path)

    def apply_settings(self, sender, app_data, user_data, *args):
        new_path = dpg.get_value("settings_base_path").strip()
        new_lang = dpg.get_value("settings_language")

        region_options = {i18n("region_jp"): "jp", i18n("region_global"): "global"}
        new_region_label = dpg.get_value("settings_region")
        new_region = region_options.get(new_region_label, "jp")

        path_valid = Config.is_valid_path(new_path)
        if new_path and not path_valid:
            print(f"Warning: Invalid data root path {new_path}")

        active_tab = dpg.get_value("main_tabs")
        active_tab_alias = ""
        if active_tab:
            try:
                active_tab_alias = dpg.get_item_alias(active_tab) or active_tab
            except:
                pass

        path_changed = Config.BASE_PATH != new_path
        lang_changed = Config.LANGUAGE != new_lang
        region_changed = Config.REGION != new_region

        Config.set_base_path(new_path)
        Config.LANGUAGE = new_lang
        Config.REGION = new_region
        Config.save()

        self._setup_fonts()

        if (path_changed or region_changed) and path_valid:
            print(
                f"Re-initializing database for path: {new_path}, region: {new_region}"
            )
            if self.db:
                self.db.close()
            try:
                self.db = UmaDatabase(Config.get_db_path())
                UnityLogic.set_key_provider(self.db.get_key_by_hash)
                self.cached_deps.clear()
                self.cached_rev_deps.clear()
                self.cached_recursive_hashes.clear()
                self.node_map.clear()
                self.tree_data = self.db.load_index()

                # Re-render UI components that depend on the database
                self.executor.submit(self._render_browser_tree_items, "browse_group")
                self.executor.submit(self._render_scene_results, "")
                self.executor.submit(self._render_prop_results, "")
            except Exception as e:
                print(f"Failed to initialize database: {e}")
                self.db = None
                self.tree_data = {}

        self._create_main_layout()
        self._update_nav_buttons()

        if active_tab_alias and dpg.does_item_exist(active_tab_alias):
            dpg.set_value("main_tabs", active_tab_alias)

        if path_changed and path_valid:
            self.clear_search()
            self.clear_scene_search()
            self.clear_prop_search()

        status_tag = "settings_status_msg"
        if dpg.does_item_exist(status_tag):
            msg = i18n("msg_settings_applied")
            if new_path and not path_valid:
                msg += f" ({i18n('label_data_root')} {i18n('error_invalid')})"

            dpg.set_value(status_tag, msg)
            dpg.configure_item(
                status_tag,
                color=[255, 255, 0] if (new_path and not path_valid) else [0, 255, 0],
            )

            def clear_msg():
                if dpg.does_item_exist(status_tag):
                    dpg.set_value(status_tag, "")

            threading.Timer(3.0, clear_msg).start()

    def on_clear_thumbnail_cache(self, sender, app_data, user_data, *args):
        """Clears all generated thumbnails and resets the UI display."""
        thumb_manager.clear_all()
        dpg.set_value("settings_status_msg", i18n("msg_cache_cleared"))

        # Reset thumbnails in current detail views
        for prefix in self._detail_prefixes():
            thumbnail_container = f"{prefix}ui_thumbnail_container"
            image_parent = f"{prefix}ui_thumbnail_image_parent"
            actions_parent = f"{prefix}ui_thumbnail_actions_parent"

            if dpg.does_item_exist(thumbnail_container):
                dpg.configure_item(thumbnail_container, show=False)
            if dpg.does_item_exist(image_parent):
                dpg.delete_item(image_parent, children_only=True)
            if dpg.does_item_exist(actions_parent):
                dpg.delete_item(actions_parent, children_only=True)

    def on_stop_batch_click(self, sender, app_data, user_data):
        self.batch_stop_event.set()
        dpg.set_value("batch_status_msg", i18n("msg_batch_stopped"))
        dpg.configure_item("btn_stop_batch", enabled=False)

    def _on_batch_cat_all_change(self, sender, app_data, user_data):
        is_all = dpg.get_value("batch_cat_all")
        if is_all:
            dpg.set_value("batch_cat_scene", True)
            dpg.set_value("batch_cat_prop", True)
            dpg.configure_item("batch_cat_scene", enabled=False)
            dpg.configure_item("batch_cat_prop", enabled=False)
        else:
            dpg.set_value("batch_cat_scene", False)
            dpg.set_value("batch_cat_prop", False)
            dpg.configure_item("batch_cat_scene", enabled=True)
            dpg.configure_item("batch_cat_prop", enabled=True)

        dpg.bind_item_theme("batch_cat_scene", "checkbox_state_theme")
        dpg.bind_item_theme("batch_cat_prop", "checkbox_state_theme")

    def on_start_batch_click(self, sender, app_data, user_data):
        if self.is_batch_running:
            return

        if not self.db:
            dpg.set_value("batch_status_msg", i18n("label_db_not_ready"))
            return

        # 1. Gather categories
        cats = []
        if dpg.get_value("batch_cat_all"):
            cats.append("all")
        else:
            if dpg.get_value("batch_cat_scene"):
                cats.append("scene")
            if dpg.get_value("batch_cat_prop"):
                cats.append("prop")

        if not cats:
            dpg.set_value("batch_status_msg", "Please select at least one category.")
            return

        batch_size = dpg.get_value("batch_size")

        # 2. Reset UI
        self.is_batch_running = True
        self.batch_stop_event.clear()
        dpg.configure_item("btn_start_batch", enabled=False)
        dpg.configure_item("btn_stop_batch", enabled=True)
        dpg.configure_item("batch_progress_bar", show=True, default_value=0.0)
        dpg.set_value("batch_progress_bar", 0.0)
        dpg.configure_item("batch_progress_text", show=True)
        dpg.set_value("batch_status_msg", "Scanning for assets...")

        # 3. Start thread
        self.executor.submit(self._run_batch_worker, cats, batch_size)

    def _run_batch_worker(self, cats, batch_size):
        try:
            # Step A: Discover all candidate assets
            raw_assets = self.db.get_all_animator_assets(cats)

            # Step B: Filter assets needing thumbnails
            force_overwrite = dpg.get_value("batch_force_overwrite")
            to_process = []
            for i_id, name, size, f_hash, key_val in raw_assets:
                if self.batch_stop_event.is_set():
                    break
                if force_overwrite or not thumb_manager.get_thumbnail(f_hash):
                    to_process.append((i_id, name, f_hash))

            total_to_process = len(to_process)
            if total_to_process == 0:
                self._queue_ui_task(
                    lambda: self._finalize_batch(i18n("msg_batch_finished"))
                )
                return

            self._queue_ui_task(
                lambda: dpg.set_value(
                    "batch_status_msg",
                    f"Found {total_to_process} assets needing thumbnails.",
                )
            )

            # Step C: Parallel Chunked Processing
            processed_count = 0
            user_chunk_size = dpg.get_value("batch_size")
            chunk_size = user_chunk_size if user_chunk_size > 0 else 32

            # Split to_process into a list of chunks
            chunks = [
                to_process[i : i + chunk_size]
                for i in range(0, total_to_process, chunk_size)
            ]

            # We use a Lock for safe progress updates
            progress_lock = threading.Lock()

            def process_one_chunk(chunk_data):
                nonlocal processed_count
                if self.batch_stop_event.is_set():
                    return

                # 1. Prepare chunk configs
                batch_configs = []
                for asset_id, name, asset_hash in chunk_data:
                    deps = self._get_recursive_hashes(asset_id)
                    paths = []
                    keys = []
                    for h, k in deps:
                        p = os.path.join(Config.get_data_root(), h[:2], h)
                        if os.path.exists(p):
                            paths.append(p)
                            keys.append(k)

                    batch_configs.append(
                        {
                            "id": asset_id,
                            "hash": asset_hash,
                            "paths": paths,
                            "keys": keys,
                            "logical_name": os.path.basename(name),
                        }
                    )

                # 2. Export Chunk FBX in one CLI call
                # Use /dev/shm on Linux for ultra-fast staging if available
                staging_base = (
                    "/dev/shm"
                    if os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK)
                    else None
                )

                with tempfile.TemporaryDirectory(dir=staging_base) as chunk_export_dir:
                    exported_results = UnityLogic.batch_export_to_fbx(
                        batch_configs, chunk_export_dir
                    )

                    # 3. Render thumbnails for the chunk
                    # Initialize the engine ONCE per chunk thread for ultra-fast rendering
                    batch_engine = None
                    try:
                        import f3d

                        batch_engine = f3d.Engine.create(offscreen=True)
                    except:
                        pass

                    for asset_hash, fbx_path in exported_results:
                        if self.batch_stop_event.is_set():
                            break

                        output_filename = f"{asset_hash}.png"
                        output_path = os.path.join(
                            Config.get_thumbnail_dir(), output_filename
                        )

                        if generate_thumbnail(
                            fbx_path, output_path, engine=batch_engine
                        ):
                            thumb_manager.set_thumbnail(asset_hash, output_path)

                    # Engine will be cleaned up by GC or we can explicitly delete reference
                    batch_engine = None

                with progress_lock:
                    processed_count += len(chunk_data)
                    progress = processed_count / total_to_process
                    self._queue_ui_task(
                        lambda p=progress, c=processed_count, t=total_to_process: (
                            self._update_batch_progress(p, c, t)
                        )
                    )

            # Run 2 CLI chunks in parallel.
            # This balances CPU/Disk/RAM usage without overwhelming the system.
            with ThreadPoolExecutor(max_workers=2) as chunk_pool:
                chunk_pool.map(process_one_chunk, chunks)

            self._queue_ui_task(
                lambda: self._finalize_batch(
                    i18n("msg_batch_finished")
                    if not self.batch_stop_event.is_set()
                    else i18n("msg_batch_stopped")
                )
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            err_msg = str(e)
            print(f"Batch worker fatal error: {err_msg}")
            self._queue_ui_task(
                lambda msg=err_msg: self._finalize_batch(f"Fatal Error: {msg}")
            )

    def _update_batch_progress(self, progress, count, total):
        dpg.set_value("batch_progress_bar", progress)
        dpg.set_value(
            "batch_progress_text", f"{i18n('label_progress')} {count} / {total}"
        )

    def _finalize_batch(self, message):
        self.is_batch_running = False
        dpg.set_value("batch_status_msg", message)
        dpg.configure_item("btn_start_batch", enabled=True)
        dpg.configure_item("btn_stop_batch", enabled=False)
        # Refresh current view if it has an animator
        if hasattr(self, "current_asset_id") and self.current_asset_id:
            for prefix in self._detail_prefixes():
                self._check_and_display_thumbnail(prefix, self.current_asset_hash)
                self._update_thumbnail_button(prefix, self.current_asset_id)
