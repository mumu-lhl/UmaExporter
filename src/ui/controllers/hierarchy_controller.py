import dearpygui.dearpygui as dpg
from src.core.i18n import i18n
from src.core.unity import UnityLogic


class HierarchyController:
    """Controller for managing the Unity Scene Hierarchy view, node inspection,
    and sub-tree extraction.
    """

    def __init__(self, app):
        self.app = app
        self.request_ids = {"": 0, "scene_": 0, "prop_": 0, "home_": 0}
        self.current_tree_data = {}
        self.selected_node = {}
        self.detached_window_tag = "hierarchy_detached_window"

    def _ensure_handler_registry(self):
        """Creates the shared click handler registry for tree nodes lazily after DPG context is ready."""
        try:
            if not dpg.does_alias_exist("tree_node_click_registry") and not dpg.does_item_exist("tree_node_click_registry"):
                with dpg.item_handler_registry(tag="tree_node_click_registry"):
                    dpg.add_item_clicked_handler(callback=self._on_tree_node_clicked)
        except Exception:
            pass

    def _on_tree_node_clicked(self, sender, app_data, user_data):
        """Invoked when a tree node is clicked via the item handler registry."""
        if isinstance(app_data, (list, tuple)) and len(app_data) >= 2:
            item = app_data[1]
            if dpg.does_item_exist(item):
                data = dpg.get_item_user_data(item)
                if data and isinstance(data, (list, tuple)) and len(data) >= 2:
                    self.on_node_selected(data[0], data[1])

    def load_hierarchy_async(self, prefix, phys_path, bundle_key, asset_id):
        """Asynchronously extracts and renders the scene hierarchy for a bundle."""
        if prefix not in self.request_ids:
            self.request_ids[prefix] = 0
        self.request_ids[prefix] += 1
        req_id = self.request_ids[prefix]

        status_text_tag = f"{prefix}ui_hierarchy_status"
        if dpg.does_item_exist(status_text_tag):
            dpg.set_value(status_text_tag, i18n("msg_loading_hierarchy"))
            dpg.configure_item(status_text_tag, show=True)

        def worker():
            try:
                tree = UnityLogic.get_scene_hierarchy(
                    phys_path, bundle_key=bundle_key
                )
                return tree
            except Exception as e:
                print(f"[HIERARCHY] Error parsing hierarchy: {e}")
                return ()

        future = self.app.executor.submit(worker)

        def done_callback(f):
            try:
                tree = f.result()
            except Exception as ex:
                print(f"[HIERARCHY] Future error: {ex}")
                tree = ()

            self.app._queue_ui_task(
                lambda: self._apply_hierarchy_result(
                    prefix, req_id, asset_id, phys_path, bundle_key, tree
                )
            )

        future.add_done_callback(done_callback)

    def _apply_hierarchy_result(
        self, prefix, req_id, asset_id, phys_path, bundle_key, tree
    ):
        current_id = getattr(self.app, "current_asset_id", None)
        if (
            req_id != self.request_ids.get(prefix)
            or (current_id is not None and str(asset_id) != str(current_id))
        ):
            return

        status_text_tag = f"{prefix}ui_hierarchy_status"
        if dpg.does_item_exist(status_text_tag):
            dpg.configure_item(status_text_tag, show=False)

        self.current_tree_data[prefix] = {
            "tree": tree,
            "phys_path": phys_path,
            "bundle_key": bundle_key,
        }
        self.selected_node[prefix] = None

        self.render_tree(prefix)

    def render_tree(self, prefix, parent_tag=None):
        """Renders the scene hierarchy tree into the target container."""
        if parent_tag is None:
            parent_tag = f"{prefix}ui_hierarchy_tree_parent"

        if not dpg.does_item_exist(parent_tag):
            return

        dpg.delete_item(parent_tag, children_only=True)
        self._ensure_handler_registry()

        tree_info = self.current_tree_data.get(prefix)
        if not tree_info or not tree_info.get("tree"):
            dpg.add_text(
                i18n("label_hierarchy_empty"),
                parent=parent_tag,
                color=[150, 150, 150],
            )
            self._update_inspector(prefix, None)
            return

        tree_roots = tree_info["tree"]

        def count_nodes(n):
            return 1 + sum(count_nodes(c) for c in n.get("children", ()))

        total_count = sum(count_nodes(r) for r in tree_roots)
        status_text_tag = f"{prefix}ui_hierarchy_status"
        if dpg.does_item_exist(status_text_tag):
            dpg.set_value(status_text_tag, f"({total_count} nodes)")
            dpg.configure_item(status_text_tag, show=True)

        for root_node in tree_roots:
            self._add_tree_widget(root_node, parent_tag, prefix, default_open=True)

        self._update_inspector(prefix, None)

    def _add_tree_widget(self, node, parent_tag, prefix, default_open=False):
        name = node.get("name", "Unnamed")
        comps = node.get("components", ())
        children = node.get("children", ())
        has_mesh = "MeshFilter" in comps or "SkinnedMeshRenderer" in comps

        # Compact component summary
        comp_summary = ""
        if comps:
            display_comps = [c for c in comps if c != "Transform"]
            if display_comps:
                comp_summary = f" [{', '.join(display_comps[:3])}{'...' if len(display_comps) > 3 else ''}]"

        node_label = f"{name}{comp_summary}"

        if children:
            tree_node = dpg.add_tree_node(
                label=node_label,
                parent=parent_tag,
                default_open=default_open,
                user_data=(node, prefix),
            )
            dpg.bind_item_handler_registry(tree_node, "tree_node_click_registry")
            for child in children:
                self._add_tree_widget(child, tree_node, prefix, default_open=False)
        else:
            dpg.add_selectable(
                label=f"  {node_label}",
                parent=parent_tag,
                user_data=(node, prefix),
                callback=lambda s, a, u: self.on_node_selected(u[0], u[1]),
            )

    def on_node_selected(self, node, prefix):
        """Invoked when a node in the hierarchy is clicked."""
        self.selected_node[prefix] = node
        self._update_inspector(prefix, node)

    def _update_inspector(self, prefix, node):
        """Updates the property inspector panel with the selected node's details."""
        inspector_parent = f"{prefix}ui_hierarchy_inspector_parent"
        if not dpg.does_item_exist(inspector_parent):
            return

        dpg.delete_item(inspector_parent, children_only=True)

        if not node:
            dpg.add_text(
                i18n("label_select_file"),
                parent=inspector_parent,
                color=[130, 130, 130],
            )
            return

        name = node.get("name", "Unnamed")
        go_id = node.get("go_path_id", 0)
        tf_id = node.get("tf_path_id", 0)
        comps = node.get("components", ())
        mesh_name = node.get("mesh_name")
        mesh_path_id = node.get("mesh_path_id")
        materials = node.get("materials", ())
        pos = node.get("local_pos", (0.0, 0.0, 0.0))
        rot = node.get("local_rot", (0.0, 0.0, 0.0, 1.0))
        scale = node.get("local_scale", (1.0, 1.0, 1.0))

        dpg.add_text(f"{name}", parent=inspector_parent, color=[0, 255, 255])
        dpg.add_text(
            f"GameObject PathID: {go_id}",
            parent=inspector_parent,
            color=[160, 160, 160],
        )
        dpg.add_text(
            f"Transform PathID: {tf_id}",
            parent=inspector_parent,
            color=[160, 160, 160],
        )

        dpg.add_separator(parent=inspector_parent)
        dpg.add_text(
            f"{i18n('label_transform')}:",
            parent=inspector_parent,
            color=[255, 200, 100],
        )
        dpg.add_text(
            f"  Pos: ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})",
            parent=inspector_parent,
        )
        dpg.add_text(
            f"  Rot: ({rot[0]:.2f}, {rot[1]:.2f}, {rot[2]:.2f}, {rot[3]:.2f})",
            parent=inspector_parent,
        )
        dpg.add_text(
            f"  Scale: ({scale[0]:.2f}, {scale[1]:.2f}, {scale[2]:.2f})",
            parent=inspector_parent,
        )

        dpg.add_separator(parent=inspector_parent)
        dpg.add_text(
            f"{i18n('label_components')} ({len(comps)}):",
            parent=inspector_parent,
            color=[100, 255, 100],
        )
        for comp in comps:
            dpg.add_text(f"  • {comp}", parent=inspector_parent)

        if mesh_name:
            dpg.add_separator(parent=inspector_parent)
            dpg.add_text(f"Mesh: {mesh_name}", parent=inspector_parent, color=[255, 255, 0])
            if mesh_path_id:
                tree_info = self.current_tree_data.get(prefix, {})
                phys_path = tree_info.get("phys_path")
                bundle_key = tree_info.get("bundle_key")
                dpg.add_button(
                    label=f"3D Preview ({mesh_name})",
                    parent=inspector_parent,
                    callback=lambda: self._preview_mesh(
                        phys_path, mesh_path_id, prefix, bundle_key
                    ),
                )

        if materials:
            dpg.add_separator(parent=inspector_parent)
            dpg.add_text(
                f"Materials ({len(materials)}):",
                parent=inspector_parent,
                color=[255, 150, 255],
            )
            for mat in materials:
                dpg.add_text(f"  • {mat}", parent=inspector_parent)

    def _preview_mesh(self, phys_path, mesh_path_id, prefix, bundle_key):
        """Previews the mesh via the existing preview controller."""
        if hasattr(self.app, "preview_controller"):
            self.app.preview_controller.on_mesh_preview_click(
                None, None, (phys_path, mesh_path_id, prefix, bundle_key)
            )

    def open_detached_window(self, prefix):
        """Pops out the scene hierarchy into an independent, large resizable window."""
        if dpg.does_item_exist(self.detached_window_tag):
            dpg.delete_item(self.detached_window_tag)

        with dpg.window(
            label=f"{i18n('label_unity_scene_hierarchy')} - Detached Inspector",
            tag=self.detached_window_tag,
            width=850,
            height=650,
            pos=[100, 100],
        ):
            with dpg.group(horizontal=True):
                # Left Column: Large Tree View
                with dpg.child_window(width=480, border=True, resizable_x=True):
                    dpg.add_text(i18n("label_unity_scene_hierarchy"), color=[0, 255, 255])
                    dpg.add_separator()
                    with dpg.child_window(
                        tag=f"{self.detached_window_tag}_tree_container", border=False
                    ):
                        self.render_tree(
                            prefix, parent_tag=f"{self.detached_window_tag}_tree_container"
                        )

                # Right Column: Inspector Details
                with dpg.child_window(width=-1, border=True):
                    dpg.add_text(i18n("label_hierarchy_inspector"), color=[0, 255, 0])
                    dpg.add_separator()
                    with dpg.child_window(
                        tag=f"{self.detached_window_tag}_inspector_container", border=False
                    ):
                        current_node = self.selected_node.get(prefix)
                        if current_node:
                            self._update_inspector(
                                prefix, current_node
                            )
                        else:
                            dpg.add_text(
                                i18n("label_select_file"), color=[130, 130, 130]
                            )
