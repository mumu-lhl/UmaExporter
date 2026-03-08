import webbrowser
import multiprocessing
import os
import threading
import time
import platform
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

import dearpygui.dearpygui as dpg

from src.constants import Config
from src.database import UmaDatabase
from src.unity_logic import UnityLogic
from src.ui.controllers import DragMixin, NavigationMixin, PreviewMixin
from src.ui.i18n import i18n


def _launch_f3d_viewer(queue):
    """Worker function for f3d viewer as a singleton process"""
    import f3d
    import os

    current_mesh = None
    try:
        eng = f3d.Engine.create()
        scene = eng.scene
        interactor = eng.interactor
        window = eng.window

        eng.options.update(
            {
                "model.scivis.cells": True,
                "model.scivis.enable": True,
                "model.scivis.array_name": "Colors",
                "model.scivis.component": 0,
                "ui.axis": True,
                # "ui.fps": True,
                "render.grid.enable": True,
                "render.light.intensity": 2.5,
                "render.hdri.ambient": True,
                "render.effect.tone_mapping": True,
                # "render.effect.ambient_occlusion": True,
            }
        )

        def update_scene(path):
            nonlocal current_mesh
            if current_mesh and os.path.exists(current_mesh):
                try:
                    os.remove(current_mesh)
                except:
                    pass
            current_mesh = path
            scene.clear()
            scene.add(path)
            window.render()
            print(f"[F3D] Loaded mesh: {path}")

        def timer_callback(t=None):
            # Check for new mesh in queue without blocking
            try:
                if not queue.empty():
                    new_path = queue.get_nowait()
                    if new_path == "STOP":
                        return False  # Stop interactor
                    update_scene(new_path)
            except Exception as e:
                print(f"[F3D] Callback error: {e}")
            return True  # Continue interactor

        # Initial wait for first mesh (blocking)
        print("[F3D] Waiting for first mesh...")
        first_path = queue.get()
        if first_path == "STOP":
            return

        update_scene(first_path)

        # Start interactor with a timer callback (100ms interval)
        print("[F3D] Starting interactor...")
        interactor.start(0.1, timer_callback)

    except KeyboardInterrupt:
        print("[F3D] Viewer interrupted by user (Ctrl+C).")
    except Exception as e:
        print(f"F3D Viewer Error: {e}")
    finally:
        if current_mesh and os.path.exists(current_mesh):
            try:
                os.remove(current_mesh)
            except:
                pass
        print("[F3D] Viewer process exiting.")


class UmaExporterApp(DragMixin, NavigationMixin, PreviewMixin):
    def __init__(self):

        Config.load()
        self.db = None
        self.tree_data = {}
        self.executor = ThreadPoolExecutor(max_workers=8)

        # Only initialize DB if we have a path
        if Config.BASE_PATH:
            try:
                self.db = UmaDatabase(Config.get_db_path())
                UnityLogic.set_key_provider(self.db.get_key_by_hash)
                self.tree_data = self.db.load_index()
            except Exception as e:
                print(f"Failed to initialize database: {e}")

        self.node_map = {}
        self.last_selected = None
        self.last_unity_selected = {"": None, "scene_": None, "prop_": None}
        self.current_asset_id = None
        self.current_asset_data = None
        self.texture_lock = threading.Lock()
        self.preview_texture_tags = {"": None, "scene_": None, "prop_": None}
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
        self.ui_tasks = Queue()
        self.max_ui_tasks_per_frame = 8
        self.cached_deps = {}
        self.cached_rev_deps = {}
        self.cached_recursive_hashes = {}

        # F3D singleton process management
        self.f3d_process = None
        self.f3d_queue = None

        # Navigation history
        self.history_back = []
        self.history_forward = []
        self.is_navigating = False

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

    def run(self):
        dpg.create_context()
        self._setup_fonts()
        dpg.add_texture_registry(tag="main_texture_registry")
        self._create_file_dialog()
        self._create_main_layout()
        self._setup_shortcuts()

        dpg.create_viewport(title="Uma Musume Exporter", width=1200, height=800)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        self._update_nav_buttons()

        if not Config.BASE_PATH:
            dpg.set_value("main_tabs", "settings_tab")

        dpg.set_primary_window("PrimaryWindow", True)
        try:
            while dpg.is_dearpygui_running():
                self._drain_ui_tasks()
                dpg.render_dearpygui_frame()
        finally:
            if self.f3d_queue:
                try:
                    self.f3d_queue.put("STOP")
                except:
                    pass
            if self.f3d_process and self.f3d_process.is_alive():
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
                        dpg.add_separator()
                        with dpg.child_window(tag="scene_results_parent", border=False):
                            self._render_scene_results("")

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
                        dpg.add_separator()
                        with dpg.child_window(tag="prop_results_parent", border=False):
                            self._render_prop_results("")

                    # Right Column: Details
                    with dpg.child_window(
                        tag="prop_details_scroll", width=-1, border=True
                    ):
                        self._build_details_panel(prefix="prop_")

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
            self._render_browser_tree_items("browse_group")

        with dpg.group(tag="search_group", show=False):
            dpg.add_text(i18n("search_results"), color=[0, 255, 255])
            with dpg.child_window(tag="search_results", border=False):
                pass

    def _render_browser_tree_items(self, parent):
        dpg.add_text(i18n("dir_browser"), color=[255, 200, 0], parent=parent)
        root_dirs = []
        root_files = []
        for name, content in self.tree_data.items():
            if isinstance(content, dict) and "_is_file" in content:
                root_files.append((name, content))
            else:
                root_dirs.append((name, content))

        for name, content in sorted(root_dirs):
            self.render_node(name, content, parent)
        for name, content in sorted(root_files):
            self.render_node(name, content, parent)

    def _build_details_panel(self, prefix=""):
        nav_back_tag = f"{prefix}nav_back_btn"
        nav_forward_tag = f"{prefix}nav_forward_btn"
        path_tag = f"{prefix}ui_path"
        details_group_tag = f"{prefix}details_group"
        hash_tag = f"{prefix}ui_hash"
        size_tag = f"{prefix}ui_size"
        phys_tag = f"{prefix}ui_phys"
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
            dpg.add_text("", tag=f"{prefix}ui_path_label", wrap=650)
            with dpg.group(horizontal=True):
                dpg.add_text(i18n("prop_storage_hash"))
                dpg.add_input_text(tag=hash_tag, readonly=True, width=-1)
            dpg.add_text("", tag=size_tag)
            dpg.add_text("", tag=phys_tag, color=[120, 150, 255])
            dpg.add_spacer(height=10)
            dpg.add_button(
                label=i18n("btn_export"),
                width=200,
                callback=lambda: dpg.show_item("export_dialog"),
            )

            dpg.add_spacer(height=20)
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
        if isinstance(content, dict) and "_is_file" in content:
            self._add_file_selectable(
                label=f"[F] {name}",
                user_data=content,
                parent=parent,
            )
        else:
            node = dpg.add_tree_node(
                label=f"[D] {name}",
                parent=parent,
                selectable=False,
                span_full_width=True,
            )
            self.node_map[node] = content
            dpg.add_text("Click to load content...", parent=node)
            with dpg.item_handler_registry() as handler:
                dpg.add_item_clicked_handler(callback=self.on_tree_click)
            dpg.bind_item_handler_registry(node, handler)

    def on_tree_click(self, sender, app_data, user_data, *args):
        node = app_data[1]
        if node not in self.node_map:
            return

        children = dpg.get_item_children(node, slot=1)
        for child in children:
            if dpg.get_item_type(child) == "mvAppItemType::mvText":
                dpg.delete_item(child)
                break
        else:
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
            self._add_file_selectable(
                label=label,
                user_data=sub_content,
                parent=node,
            )

    def _add_file_selectable(
        self, label, user_data, parent=None, tag=None, span_columns=False
    ):
        kwargs = {
            "label": label,
            "callback": self.on_file_click,
            "user_data": user_data,
        }
        if parent is not None:
            kwargs["parent"] = parent
        if tag is not None:
            kwargs["tag"] = tag
        if span_columns:
            kwargs["span_columns"] = True

        item = dpg.add_selectable(**kwargs)
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

        if self.last_selected and dpg.does_item_exist(self.last_selected):
            try:
                dpg.set_value(self.last_selected, False)
            except:
                pass

        if sender:
            dpg.set_value(sender, True)
            self.last_selected = sender
        else:
            self.last_selected = self._select_existing_result_item(user_data["id"])

        for prefix in self._detail_prefixes():
            self._update_asset_properties_panel(prefix, user_data)
            if not is_drag_preview:
                dpg.configure_item(f"{prefix}ui_unity_image_container", show=False)
                dpg.delete_item(f"{prefix}ui_unity_image_container", children_only=True)

        h = user_data["hash"]

        self._reset_detail_containers(is_drag_preview=is_drag_preview)

        phys_path = os.path.join(Config.get_data_root(), h[:2], h)
        asset_id = user_data["id"]
        bundle_key = user_data.get("key")

        if is_drag_preview:
            self._preview_drag_texture_async(
                phys_path, asset_id, request_id, bundle_key=bundle_key
            )
            return

        self._load_unity_async(phys_path, asset_id, request_id, bundle_key=bundle_key)
        self._load_deps_async(asset_id, request_id)
        self._load_rev_deps_async(asset_id, request_id)

    def _ensure_f3d_viewer(self):
        """Ensure the f3d viewer process is running"""
        if self.f3d_process is None or not self.f3d_process.is_alive():
            self.f3d_queue = multiprocessing.Queue()
            self.f3d_process = multiprocessing.Process(
                target=_launch_f3d_viewer, args=(self.f3d_queue,)
            )
            self.f3d_process.start()

    def on_search(self, sender, app_data, user_data, *args):
        if not self.db:
            return
        query = dpg.get_value("search_input").strip()
        if not query:
            self.clear_search()
            return

        dpg.configure_item("browse_group", show=False)
        dpg.configure_item("search_group", show=True)
        dpg.delete_item("search_results", children_only=True)

        rows = self.db.search_assets(query)
        if not rows:
            dpg.add_text(i18n("label_no_assets"), parent="search_results")
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
                item = self._add_file_selectable(
                    label=name,
                    tag=f"search_item_{i_id}",
                    user_data=u_data,
                    parent="search_results",
                    span_columns=True,
                )
                if first_item is None:
                    first_item = (item, u_data)

            if first_item:
                self.on_file_click(first_item[0], None, first_item[1])

    def on_scene_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("scene_search_input").strip()
        self._render_scene_results(query)

    def _render_scene_results(self, query=""):
        dpg.delete_item("scene_results_parent", children_only=True)
        if not self.db:
            dpg.add_text(
                i18n("label_db_not_ready"),
                parent="scene_results_parent",
                color=[200, 120, 120],
            )
            return

        rows = self.db.search_scenes(query)
        if not rows:
            dpg.add_text(i18n("label_no_scenes"), parent="scene_results_parent")
            return

        first_item = None
        for i_id, name, size, f_hash, key_val in rows:
            u_data = {
                "id": i_id,
                "full_path": name,
                "size": size,
                "hash": f_hash,
                "key": key_val,
            }
            display_name = self._scene_display_name(name)
            item = self._add_file_selectable(
                label=display_name,
                tag=f"scene_item_{i_id}",
                user_data=u_data,
                parent="scene_results_parent",
                span_columns=True,
            )
            if first_item is None:
                first_item = (item, u_data)

        if first_item and query:
            self.on_file_click(first_item[0], None, first_item[1])

    def _scene_display_name(self, full_path):
        normalized = full_path.lstrip("/")
        prefix = "3d/env/"
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
        return full_path

    def clear_search(self, *args):
        dpg.set_value("search_input", "")
        dpg.configure_item("browse_group", show=True)
        dpg.configure_item("search_group", show=False)

    def clear_scene_search(self, *args):
        dpg.set_value("scene_search_input", "")
        self._render_scene_results("")

    def on_prop_search(self, sender, app_data, user_data, *args):
        query = dpg.get_value("prop_search_input").strip()
        self._render_prop_results(query)

    def _render_prop_results(self, query=""):
        dpg.delete_item("prop_results_parent", children_only=True)
        if not self.db:
            dpg.add_text(
                i18n("label_db_not_ready"),
                parent="prop_results_parent",
                color=[200, 120, 120],
            )
            return

        rows = self.db.search_props(query)
        if not rows:
            dpg.add_text(
                i18n("label_no_props"),
                parent="prop_results_parent",
            )
            return

        first_item = None
        for i_id, name, size, f_hash, key_val in rows:
            u_data = {
                "id": i_id,
                "full_path": name,
                "size": size,
                "hash": f_hash,
                "key": key_val,
            }
            display_name = self._prop_display_name(name)
            item = self._add_file_selectable(
                label=display_name,
                tag=f"prop_item_{i_id}",
                user_data=u_data,
                parent="prop_results_parent",
                span_columns=True,
            )
            if first_item is None:
                first_item = (item, u_data)

        if first_item and query:
            self.on_file_click(first_item[0], None, first_item[1])

    def _prop_display_name(self, full_path):
        normalized = full_path.lstrip("/")
        prefixes = ["3d/chara/prop/", "3d/chara/toonprop/", "3d/chara/richprop/"]
        for prefix in prefixes:
            if normalized.startswith(prefix):
                return normalized[len(prefix) :]
        return full_path

    def clear_prop_search(self, *args):
        dpg.set_value("prop_search_input", "")
        self._render_prop_results("")

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
