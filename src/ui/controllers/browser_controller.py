import dearpygui.dearpygui as dpg
from src.ui.i18n import i18n

class BrowserController:
    def __init__(self, app):
        self.app = app

    def render_browser_tree_items(self, parent):
        self.app._queue_ui_task(lambda: dpg.add_text(i18n("dir_browser"), color=[255, 200, 0], parent=parent))
        
        # Sort root items: directories first, then files
        root_items = sorted(self.app.tree_data.items(), key=lambda x: (isinstance(x[1], dict) and x[1].get("_is_file", False), x[0]))

        for name, content in root_items:
            self.render_node(name, content, parent)

    def render_node(self, name, content, parent):
        if isinstance(content, dict) and content.get("_is_file"):
            def add_f_item():
                self.app._add_file_selectable(
                    label=f"[F] {name}",
                    user_data=content,
                    parent=parent,
                )
            self.app._queue_ui_task(add_f_item)
        else:
            def add_d_node():
                node = dpg.add_tree_node(
                    label=f"[D] {name}",
                    parent=parent,
                    selectable=False,
                    span_full_width=True,
                )
                self.app.node_map[node] = content
                dpg.add_text("Click to load content...", parent=node)
                
                # Bind handler inside the main-thread task
                with dpg.item_handler_registry() as handler:
                    dpg.add_item_clicked_handler(callback=self.on_tree_click)
                dpg.bind_item_handler_registry(node, handler)
                
            self.app._queue_ui_task(add_d_node)

    def on_tree_click(self, sender, app_data, user_data, *args):
        node = app_data[1]
        if node not in self.app.node_map:
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

        content = self.app.node_map.pop(node)
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
                self.app._add_file_selectable(
                    label=l,
                    user_data=c,
                    parent=p,
                )
            self.app._queue_ui_task(add_sub_file)
