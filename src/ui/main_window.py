import dearpygui.dearpygui as dpg
import os
import threading
import queue
from concurrent.futures import ThreadPoolExecutor

from src.database import UmaDatabase
from src.constants import Config
from src.ui.i18n import i18n
from src.unity_logic import UnityLogic
from src.thumbnail_manager import ThumbnailManager as thumb_manager

# Views
from src.ui.views.main_view import MainView

# Services
from src.ui.services.f3d_service import F3dService
from src.ui.services.thumbnail_service import ThumbnailService

# Controllers
from src.ui.controllers.preview_controller import PreviewController
from src.ui.controllers.drag_controller import DragController
from src.ui.controllers.navigation_controller import NavigationController
from src.ui.controllers.search_controller import SearchController
from src.ui.controllers.browser_controller import BrowserController
from src.ui.controllers.shortcut_controller import ShortcutController
from src.ui.controllers.batch_controller import BatchController


class UmaExporterApp:
    def __init__(self):
        Config.load()

        # Database & Executor
        self.db = None
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.ui_tasks = queue.Queue()
        self.is_db_loading = False
        self.max_ui_tasks_per_frame = 32
        
        # Application State
        self.node_map = {}
        self.tree_data = {}
        self.file_item_data = {}
        self.last_selected = None
        
        # Navigation State
        self.history_back = []
        self.history_forward = []
        self.current_asset_id = None
        self.current_asset_hash = None
        self.current_asset_data = None
        self.is_navigating = False
        
        # Drag State
        self.drag_preview_active = False
        self.current_view_is_drag_preview = False
        self.last_hover_scan_time = 0
        self.hover_scan_interval = 0.05
        self.last_drag_preview_item = None
        self.pending_drag_preview = None
        self.drag_preview_interval = 0.05
        self.last_drag_preview_time = 0
        self.middle_drag_active = False
        self.middle_drag_target = None
        self.middle_drag_start_mouse_y = None
        self.middle_drag_start_scroll_y = None
        self.middle_drag_speed = 1.0
        self.last_tab_drag_switch_target = None
        self.last_tab_drag_switch_time = 0
        self.tab_drag_switch_interval = 0.5
        
        # Preview State
        self.selection_request_id = 0
        self.texture_request_ids = {}
        self.thumbnail_request_ids = {
            "": 0,
            "scene_": 0,
            "prop_": 0
        }
        self.last_unity_selected = {}
        self.thumbnail_texture_tags = {}
        self.preview_texture_tags = {}
        self.cached_recursive_hashes = {}
        self.cached_deps = {}
        self.cached_rev_deps = {}
        self.scene_auto_preview_request = None
        self.prop_auto_preview_request = None
        
        # Lazy Thumbnail Processing State
        self.last_lazy_scan_time = 0
        self.lazy_scan_interval = 0.2
        self.texture_lock = threading.Lock()
        
        # View Modes
        self.scene_view_mode = "list"
        self.prop_view_mode = "list"
        self.search_thumbnail_textures = {"scene_": [], "prop_": []}
        self.thumbnail_columns = {"scene_": 0, "prop_": 0}
        self.thumbnail_items = {"scene_": [], "prop_": []}
        self.lazy_thumb_queues = {"scene_": [], "prop_": []}
        
        # Batch Processor State
        self.is_batch_running = False
        self.batch_stop_event = threading.Event()
        
        # Initialize Services
        self.f3d_service = F3dService()
        self.thumbnail_service = ThumbnailService(self.executor, self)
        
        # Initialize Controllers
        self.preview_controller = PreviewController(self)
        self.drag_controller = DragController(self)
        self.navigation_controller = NavigationController(self)
        self.search_controller = SearchController(self)
        self.browser_controller = BrowserController(self)
        self.shortcut_controller = ShortcutController(self)
        self.batch_controller = BatchController(self)
        
        # Build UI Structure
        self._setup_dearpygui()
        
        # Initialize Views
        self.main_view = MainView(self) # We pass self as controller proxy to MainView for simplicity
        
        # Map some proxy callbacks for MainView because it binds to self.controller.*
        self.on_search = self.search_controller.on_search
        self.clear_search = self.search_controller.clear_search
        self.on_scene_search = self.search_controller.on_scene_search
        self.clear_scene_search = self.search_controller.clear_scene_search
        self.on_prop_search = self.search_controller.on_prop_search
        self.clear_prop_search = self.search_controller.clear_prop_search
        self._on_view_mode_change = self.search_controller.on_view_mode_change
        self._on_batch_cat_all_change = self.batch_controller.on_batch_cat_all_change
        self.on_start_batch_click = self.batch_controller.on_start_batch_click
        self.on_stop_batch_click = self.batch_controller.on_stop_batch_click
        self._update_nav_buttons = self.navigation_controller._update_nav_buttons
        self.go_back = self.navigation_controller.go_back
        self.go_forward = self.navigation_controller.go_forward
        
        self._init_ui()
        self._db_load_worker()

    def _setup_dearpygui(self):
        dpg.create_context()
        if not hasattr(dpg, "_context_created"):
            dpg._context_created = True
            
            with dpg.handler_registry(tag="global_drag_handlers"):
                dpg.add_mouse_move_handler(callback=self.drag_controller._on_mouse_move)
                dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=self.drag_controller._on_mouse_move)
                dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Middle, callback=self.drag_controller._on_middle_mouse_down)
                dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Middle, callback=self.drag_controller._on_middle_mouse_drag)
                dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Middle, callback=self.drag_controller._on_middle_mouse_release)
                dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=self.drag_controller._on_left_mouse_release)

            self.shortcut_controller.setup_shortcuts()

    def _setup_font_and_theme(self):
        self._setup_fonts()

        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 5, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 5, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 4, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_ScrollbarRounding, 5, category=dpg.mvThemeCat_Core)
        dpg.bind_theme(global_theme)
        
        with dpg.theme(tag="button_state_theme"):
            with dpg.theme_component(dpg.mvButton, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Button, [60, 60, 60])
                dpg.add_theme_color(dpg.mvThemeCol_Text, [130, 130, 130])

        with dpg.theme(tag="checkbox_state_theme"):
            with dpg.theme_component(dpg.mvCheckbox, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Text, [128, 128, 128])
                dpg.add_theme_color(dpg.mvThemeCol_CheckMark, [80, 80, 80])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, [50, 50, 50])
                dpg.add_theme_style(dpg.mvStyleVar_Alpha, 0.5, category=dpg.mvThemeCat_Core)

    def _setup_fonts(self):
        import platform
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
        elif system == "Darwin":
            if is_chinese:
                font_paths.append("/System/Library/Fonts/PingFang.ttc")
            font_paths.append("/System/Library/Fonts/Helvetica.ttc")
        elif system == "Linux":
            if is_chinese:
                font_paths.append("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
                font_paths.append("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
                font_paths.append("/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc")
            font_paths.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
            font_paths.append("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf")

        actual_font = ""
        for p in font_paths:
            if os.path.exists(p):
                actual_font = p
                break

        if actual_font:
            if dpg.does_item_exist("main_font_registry"):
                dpg.delete_item("main_font_registry")
            font_size = 20 if is_chinese else 16
            with dpg.font_registry(tag="main_font_registry"):
                with dpg.font(actual_font, font_size) as default_font:
                    dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                    if is_chinese:
                        dpg.add_font_range_hint(dpg.mvFontRangeHint_Chinese_Full)
                        dpg.add_font_range(0x4E00, 0x9FFF)
                    dpg.bind_font(default_font)

    def _init_ui(self):
        dpg.create_viewport(
            title="Uma Musume Exporter", width=1200, height=800
        )
        self._setup_font_and_theme()
        
        with dpg.texture_registry(show=False, tag="main_texture_registry"):
            dpg.add_static_texture(width=100, height=100, default_value=[0.2, 0.2, 0.2, 1.0]*10000, tag="thumb_placeholder")

        dpg.setup_dearpygui()
        
        self.main_view.create_file_dialog()
        self.main_view.create_main_layout()

        # Add a simple loading modal
        with dpg.window(label="Loading...", modal=True, show=False, tag="loading_modal", no_title_bar=True, pos=(500, 350), width=200, height=100):
            dpg.add_text("Parsing Database...")
            dpg.add_loading_indicator(style=1)

        dpg.set_primary_window("PrimaryWindow", True)
        dpg.show_viewport()

    def _db_load_worker(self):
        """Asynchronously initialize the database and load its index."""
        db_path = Config.get_db_path()
        if not Config.BASE_PATH or not os.path.exists(db_path):
            self._queue_ui_task(lambda: dpg.set_value("main_tabs", "settings_tab"))
            return

        def run_db_load():
            try:
                self.is_db_loading = True
                self._queue_ui_task(lambda: dpg.show_item("loading_modal"))

                db = UmaDatabase(Config.get_db_path())
                UnityLogic.set_key_provider(db.get_key_by_hash)
                tree_data = db.load_index()

                def finalize():
                    self.db = db
                    self.tree_data = tree_data
                    self.is_db_loading = False
                    dpg.hide_item("loading_modal")

                    self.browser_controller.render_browser_tree_items("browse_group")
                    self.executor.submit(self.search_controller.render_scene_results, "")
                    self.executor.submit(self.search_controller.render_prop_results, "")

                self._queue_ui_task(finalize)

            except Exception as e:
                print(f"Failed to load database: {e}")
                self._queue_ui_task(lambda: dpg.hide_item("loading_modal"))
                self.is_db_loading = False

        self.executor.submit(run_db_load)

    def _set_database_ready(self, tree_data):
        self.tree_data = tree_data
        
        if dpg.does_item_exist("home_browse_scroll"):
            dpg.delete_item("home_browse_scroll", children_only=True)
            self.browser_controller.render_browser_tree_items("home_browse_scroll")

        dpg.set_value(
            "settings_status_msg", i18n("msg_db_ready") + f" ({self.db.db_path})"
        )
        
        self.search_controller.render_scene_results()
        self.search_controller.render_prop_results()

    def _queue_ui_task(self, func):
        self.ui_tasks.put(func)

    def _drain_ui_tasks(self):
        for _ in range(self.max_ui_tasks_per_frame):
            try:
                func = self.ui_tasks.get_nowait()
            except queue.Empty:
                return
            try:
                func()
            except Exception as e:
                print(f"UI task error: {e}")

    def _add_file_selectable(self, label, user_data, parent, span_columns=False, tag=None):
        safe_label = label if isinstance(label, str) else str(label)
        if "\\x00" in safe_label:
            safe_label = safe_label.replace("\\x00", "")
        if not safe_label:
            safe_label = "(unnamed)"

        kwargs = {
            "label": safe_label,
            "callback": self.on_file_click,
            "user_data": user_data,
            "parent": parent,
            "span_columns": span_columns,
        }
        if tag:
             kwargs["tag"] = tag

        try:
             s = dpg.add_selectable(**kwargs)
             self.file_item_data[s] = user_data
             return s
        except Exception:
             pass
        return None

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
        self.preview_controller._set_dependency_sections_visible(not is_drag_preview)
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
                self.history_back.append(self.navigation_controller._snapshot_asset_data(current_data))
                self.history_forward.clear()

        self.last_unity_selected = {"": None, "scene_": None, "prop_": None}
        self.current_asset_id = user_data["id"]
        self.current_asset_data = user_data

        self.navigation_controller._update_nav_buttons()

        # Handle visual selection state - deselect previous
        if self.last_selected and dpg.does_item_exist(self.last_selected):
            # Normalize for comparison using integer IDs if possible
            last_id = self.last_selected
            sender_id = sender
            
            if last_id != sender_id:
                try:
                    t = dpg.get_item_type(self.last_selected)
                    if "mvSelectable" in t:
                        dpg.set_value(self.last_selected, False)
                    elif "mvImage" in t:
                        dpg.configure_item(self.last_selected, tint_color=[255, 255, 255, 255])
                except Exception:
                    pass

        # Apply selection to new item
        if sender and dpg.does_item_exist(sender):
            try:
                t = dpg.get_item_type(sender)
                if "mvSelectable" in t:
                    dpg.set_value(sender, True)
                elif "mvImage" in t:
                    dpg.configure_item(sender, tint_color=[150, 200, 255, 255])
            except Exception:
                pass
            self.last_selected = sender
        elif not sender:
            # Fallback for programmatic selection
            self.last_selected = self.navigation_controller._select_existing_result_item(user_data["id"])
            if self.last_selected and dpg.does_item_exist(self.last_selected):
                t = dpg.get_item_type(self.last_selected)
                if "mvImage" in t:
                    dpg.configure_item(self.last_selected, tint_color=[150, 200, 255, 255])
                elif "mvSelectable" in t:
                    dpg.set_value(self.last_selected, True)

        active_prefix = ""
        # Improved prefix detection for both string aliases and integer IDs
        if is_scene_click_context:
            active_prefix = "scene_"
        elif is_prop_click_context:
            active_prefix = "prop_"
        elif active_tab_alias == "home_tab":
            active_prefix = ""

        for prefix in self.preview_controller._detail_prefixes():
            # During drag, prioritize the active view to keep it snappy.
            # If we can't determine active prefix, update all to be safe.
            is_active = (prefix == active_prefix) or not active_prefix
            
            if not is_drag_preview or is_active:
                self.preview_controller._update_asset_properties_panel(prefix, user_data)
                
            if not is_drag_preview:
                dpg.configure_item(f"{prefix}ui_unity_image_container", show=False)
                dpg.delete_item(f"{prefix}ui_unity_image_container", children_only=True)

        h = user_data["hash"]
        self.current_asset_hash = h

        # Always reset detail containers to clear previous state
        self.preview_controller._reset_detail_containers(is_drag_preview=is_drag_preview)

        phys_path = os.path.join(Config.get_data_root(), h[:2], h)
        asset_id = user_data["id"]
        bundle_key = user_data.get("key")

        if is_drag_preview:
            if is_scene_click_context or is_prop_click_context:
                prefix = "scene_" if is_scene_click_context else "prop_"
                self.preview_controller._check_and_display_thumbnail(prefix, h)
                return
            
            # For general assets during drag, only preview texture if we aren't spamming tasks
            self.preview_controller._preview_drag_texture_async(
                phys_path, asset_id, request_id, bundle_key=bundle_key
            )
            return

        # Full load for non-drag
        self.preview_controller._reset_detail_containers(is_drag_preview=False)
        self.preview_controller._load_unity_async(phys_path, asset_id, request_id, bundle_key=bundle_key)
        self.preview_controller._load_deps_async(asset_id, request_id)
        self.preview_controller._load_rev_deps_async(asset_id, request_id)

    def _is_still_selected(self, asset_id):
        return self.current_asset_id == asset_id

    def on_export_selected(self, sender, app_data):
        print(f"Export to: {app_data['file_path_name']}")

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
        dpg.set_value("settings_status_msg", i18n("msg_restart_required"))

    def on_clear_thumbnail_cache(self, sender, app_data, user_data):
        try:
            thumb_manager.clear_all()
            dpg.set_value("settings_status_msg", i18n("msg_clear_cache_success"))
        except Exception as e:
            dpg.set_value("settings_status_msg", f"Failed to clear cache: {e}")

    def _on_app_exit(self):
        self.f3d_service.cleanup()

    def run(self):
        try:
            while dpg.is_dearpygui_running():
                self._drain_ui_tasks()
                self.search_controller.process_lazy_thumbnails()
                dpg.render_dearpygui_frame()
        except KeyboardInterrupt:
             pass
        finally:
            self._on_app_exit()
            dpg.destroy_context()
            self.executor.shutdown(wait=False)
