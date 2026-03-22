import dearpygui.dearpygui as dpg
from src.constants import Config
from src.ui.i18n import i18n
import webbrowser

from .browser_view import BrowserView
from .search_view import SearchView
from .details_view import DetailsView


class MainView:
    def __init__(self, controller):
        self.controller = controller
        self.browser_view = BrowserView(controller)
        self.search_view = SearchView(controller)
        self.details_view = DetailsView(controller)

    def show_about(self, *args):
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

    def create_file_dialog(self):
        with dpg.file_dialog(
            directory_selector=True,
            show=False,
            callback=self.controller.on_export_selected,
            id="export_dialog",
            width=600,
            height=400,
        ):
            dpg.add_file_extension(".*")

        with dpg.file_dialog(
            directory_selector=True,
            show=False,
            callback=self.controller.on_settings_dir_selected,
            id="settings_dir_dialog",
            width=600,
            height=400,
        ):
            dpg.add_file_extension(".*")

    def create_main_layout(self):
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
                dpg.add_menu_item(label=i18n("menu_about"), callback=self.show_about)

        with dpg.tab_bar(tag="main_tabs", parent="PrimaryWindow"):
            with dpg.tab(label=i18n("tab_home"), tag="home_tab"):
                with dpg.group(horizontal=True):
                    # Left Column: Browser/Search (Fixed Search Bar)
                    with dpg.child_window(width=500, border=True, resizable_x=True):
                        self.search_view.build_search_bar(
                            "search_input",
                            self.controller.on_search,
                            self.controller.clear_search,
                            scroll_targets=["home_browse_scroll", "search_results"],
                        )
                        dpg.add_separator()

                        # Content area that scrolls
                        with dpg.child_window(tag="home_browse_scroll", border=False):
                            self.browser_view.build_browser_tree()

                    # Right Column: Details
                    with dpg.child_window(
                        tag="home_details_scroll", width=-1, border=True
                    ):
                        self.details_view.build_details_panel()

            with dpg.tab(label=i18n("tab_scene"), tag="scene_tab"):
                with dpg.group(horizontal=True):
                    # Left Column: Scene Browser/Search
                    with dpg.child_window(width=500, border=True, resizable_x=True):
                        self.search_view.build_search_bar(
                            "scene_search_input",
                            self.controller.on_scene_search,
                            self.controller.clear_scene_search,
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
                                callback=self.controller._on_view_mode_change,
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
                        self.details_view.build_details_panel(prefix="scene_")

            with dpg.tab(label=i18n("tab_prop"), tag="prop_tab"):
                with dpg.group(horizontal=True):
                    # Left Column: Prop Browser/Search
                    with dpg.child_window(width=500, border=True, resizable_x=True):
                        self.search_view.build_search_bar(
                            "prop_search_input",
                            self.controller.on_prop_search,
                            self.controller.clear_prop_search,
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
                                callback=self.controller._on_view_mode_change,
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
                        self.details_view.build_details_panel(prefix="prop_")

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
                            callback=self.controller._on_batch_cat_all_change,
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
                            callback=self.controller.on_start_batch_click,
                            width=150,
                        )
                        dpg.bind_item_theme("btn_start_batch", "button_state_theme")
                        dpg.add_button(
                            label=i18n("btn_stop_batch"),
                            tag="btn_stop_batch",
                            callback=self.controller.on_stop_batch_click,
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
                            callback=self.controller.apply_settings,
                        )
                        dpg.add_button(
                            label=i18n("btn_clear_cache"),
                            width=200,
                            callback=self.controller.on_clear_thumbnail_cache,
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
        self.controller._update_nav_buttons()
