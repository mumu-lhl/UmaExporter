import dearpygui.dearpygui as dpg
from src.ui.i18n import i18n


class SearchView:
    def __init__(self, controller):
        self.controller = controller

    def build_search_bar(
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
