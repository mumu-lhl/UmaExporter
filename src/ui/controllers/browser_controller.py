import dearpygui.dearpygui as dpg

from src.core.i18n import i18n


class BrowserController:
    def __init__(self, app):
        self.app = app

    def render_browser_tree_items(self, parent):
        """Load only the root directory; descendants are fetched on expansion."""
        self.app.browser_request_id += 1
        generation = self.app.browser_request_id
        dpg.add_text(
            i18n("msg_loading"),
            color=[255, 200, 0],
            parent=parent,
        )
        self._request_directory("", parent, generation)

    def _request_directory(self, prefix, parent, generation):
        database = self.app.db
        if not database:
            return

        future = self.app.executor.submit(database.list_directory, prefix)

        def complete(done):
            try:
                directories, files = done.result()
            except Exception:
                directories, files = (), ()
            self.app._queue_ui_task(
                lambda: self._apply_directory(
                    database,
                    prefix,
                    parent,
                    generation,
                    directories,
                    files,
                )
            )

        future.add_done_callback(complete)

    def _apply_directory(
        self,
        database,
        prefix,
        parent,
        generation,
        directories,
        files,
    ):
        if generation != self.app.browser_request_id:
            return
        if database is not self.app.db or not dpg.does_item_exist(parent):
            return

        dpg.delete_item(parent, children_only=True)
        if not prefix:
            dpg.add_text(i18n("dir_browser"), color=[255, 200, 0], parent=parent)

        for name in directories:
            child_prefix = f"{prefix}/{name}" if prefix else name
            self._add_directory_node(name, child_prefix, parent)
        for name, data in files:
            self.app._add_file_selectable(
                label=f"[F] {name}",
                user_data=data,
                parent=parent,
            )

    def _add_directory_node(self, name, prefix, parent):
        node = dpg.add_tree_node(
            label=f"[D] {name}",
            parent=parent,
            selectable=False,
            span_full_width=True,
        )
        self.app.node_map[node] = prefix
        dpg.add_text(i18n("msg_loading"), parent=node)
        with dpg.item_handler_registry() as handler:
            dpg.add_item_clicked_handler(callback=self.on_tree_click)
        dpg.bind_item_handler_registry(node, handler)

    def on_tree_click(self, sender, app_data, user_data, *args):
        node = app_data[1]
        prefix = self.app.node_map.pop(node, None)
        if prefix is None:
            return
        self._request_directory(prefix, node, self.app.browser_request_id)
