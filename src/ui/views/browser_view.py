import dearpygui.dearpygui as dpg
from src.ui.i18n import i18n

class BrowserView:
    def __init__(self, controller):
        self.controller = controller

    def build_browser_tree(self):
        with dpg.group(tag="browse_group"):
            pass

        with dpg.group(tag="search_group", show=False):
            dpg.add_text(i18n("search_results"), color=[0, 255, 255])
            with dpg.child_window(tag="search_results", border=False):
                pass
