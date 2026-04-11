import dearpygui.dearpygui as dpg
from src.core.i18n import i18n


class DetailsView:
    def __init__(self, controller):
        self.controller = controller

    def build_details_panel(self, prefix=""):
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
                callback=self.controller.go_back,
                tag=nav_back_tag,
                enabled=False,
            )
            dpg.add_button(
                label=i18n("btn_forward"),
                callback=self.controller.go_forward,
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
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label=i18n("btn_export"),
                    width=140,
                    callback=lambda: dpg.show_item("export_dialog"),
                )
                dpg.add_button(
                    label=i18n("btn_export_all"),
                    width=140,
                    callback=lambda: dpg.show_item("export_all_dialog"),
                )
            dpg.add_text("", tag=f"{prefix}ui_export_status", wrap=500)

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
