import os
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
        self.stage_info = {}
        self.stage_export_prefix = ""
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

    def load_hierarchy_async(
        self, prefix, phys_path, bundle_key, asset_id, logical_path=None
    ):
        """Asynchronously extracts and renders the scene hierarchy for a bundle."""
        if prefix not in self.request_ids:
            self.request_ids[prefix] = 0
        self.request_ids[prefix] += 1
        req_id = self.request_ids[prefix]

        if not logical_path and hasattr(self.app, "current_asset_data") and self.app.current_asset_data:
            logical_path = (
                self.app.current_asset_data.get("full_path")
                or self.app.current_asset_data.get("name")
            )

        status_text_tag = f"{prefix}ui_hierarchy_status"
        if dpg.does_item_exist(status_text_tag):
            dpg.set_value(status_text_tag, i18n("msg_loading_hierarchy"))
            dpg.configure_item(status_text_tag, show=True)

        def worker():
            try:
                tree = UnityLogic.get_scene_hierarchy(
                    phys_path, bundle_key=bundle_key
                )
            except Exception as e:
                print(f"[HIERARCHY] Error parsing hierarchy: {e}")
                tree = ()

            stage_group, stage_prefabs = None, ()
            db = getattr(self.app, "db", None)
            if logical_path and db:
                try:
                    stage_group, stage_prefabs = UnityLogic.find_stage_related_prefabs(
                        logical_path, db
                    )
                except Exception as e:
                    print(f"[HIERARCHY] Error finding stage prefabs: {e}")

            return tree, stage_group, stage_prefabs

        future = self.app.executor.submit(worker)

        def done_callback(f):
            try:
                tree, stage_group, stage_prefabs = f.result()
            except Exception as ex:
                print(f"[HIERARCHY] Future error: {ex}")
                tree, stage_group, stage_prefabs = (), None, ()

            self.app._queue_ui_task(
                lambda: self._apply_hierarchy_result(
                    prefix,
                    req_id,
                    asset_id,
                    phys_path,
                    bundle_key,
                    tree,
                    stage_group=stage_group,
                    stage_prefabs=stage_prefabs,
                    logical_path=logical_path,
                )
            )

        future.add_done_callback(done_callback)

    def _apply_hierarchy_result(
        self,
        prefix,
        req_id,
        asset_id,
        phys_path,
        bundle_key,
        tree,
        stage_group=None,
        stage_prefabs=(),
        logical_path=None,
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
            "logical_path": logical_path,
        }
        self.stage_info[prefix] = {
            "group": stage_group,
            "prefabs": stage_prefabs,
            "logical_path": logical_path,
        }
        self.selected_node[prefix] = None

        has_stage = bool(stage_prefabs and len(stage_prefabs) > 1)
        banner_tag = f"{prefix}ui_stage_banner"
        if dpg.does_item_exist(banner_tag):
            dpg.configure_item(banner_tag, show=has_stage)

        badge_tag = f"{prefix}ui_stage_badge"
        if dpg.does_item_exist(badge_tag):
            badge_text = f"🏟️ {stage_group} ({len(stage_prefabs)} Parts)" if has_stage else ""
            dpg.set_value(badge_tag, badge_text)

        for btn_name in (
            "ui_assemble_stage_btn",
            "ui_preview_stage_fbx_btn",
            "ui_export_stage_fbx_btn",
        ):
            btn_tag = f"{prefix}{btn_name}"
            if dpg.does_item_exist(btn_tag):
                dpg.configure_item(btn_tag, show=has_stage)

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
        parents = [f"{prefix}ui_hierarchy_inspector_parent"]
        detached_inspector = f"{self.detached_window_tag}_inspector_container"
        if dpg.does_item_exist(detached_inspector):
            parents.append(detached_inspector)

        for inspector_parent in parents:
            if not dpg.does_item_exist(inspector_parent):
                continue
            dpg.delete_item(inspector_parent, children_only=True)

            if not node:
                dpg.add_text(
                    i18n("label_select_file"),
                    parent=inspector_parent,
                    color=[130, 130, 130],
                )
                continue

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

    def assemble_stage_hierarchy(self, prefix):
        """Assembles all companion prefabs into a unified macro stage hierarchy."""
        info = self.stage_info.get(prefix)
        logical_path = None
        if info and info.get("logical_path"):
            logical_path = info["logical_path"]
        elif hasattr(self.app, "current_asset_data") and self.app.current_asset_data:
            logical_path = (
                self.app.current_asset_data.get("full_path")
                or self.app.current_asset_data.get("name")
            )

        if not logical_path or not getattr(self.app, "db", None):
            return

        tabbar = f"{prefix}ui_unity_view_tabbar"
        target_tab = f"{prefix}ui_unity_tab_hierarchy"
        if dpg.does_item_exist(tabbar) and dpg.does_item_exist(target_tab):
            try:
                dpg.set_value(tabbar, target_tab)
            except Exception:
                pass

        status_text_tag = f"{prefix}ui_hierarchy_status"
        if dpg.does_item_exist(status_text_tag):
            dpg.set_value(status_text_tag, i18n("msg_stage_assembling"))
            dpg.configure_item(status_text_tag, show=True)

        def worker():
            return UnityLogic.get_assembled_stage_hierarchy(logical_path, self.app.db)

        def on_done(f):
            try:
                macro_tree = f.result()
            except Exception as e:
                print(f"[HIERARCHY] Error assembling stage: {e}")
                macro_tree = ()

            def ui_update():
                if prefix in self.current_tree_data:
                    self.current_tree_data[prefix]["tree"] = macro_tree
                self.render_tree(prefix)
                detached_tree_container = f"{self.detached_window_tag}_tree_container"
                if dpg.does_item_exist(detached_tree_container):
                    self.render_tree(prefix, parent_tag=detached_tree_container)

            self.app._queue_ui_task(ui_update)

        self.app.executor.submit(worker).add_done_callback(on_done)

    def _set_stage_progress(self, prefix, message, is_done=False):
        """Update stage progress text across all visible stage UI locations."""
        color = (
            [0, 255, 100]
            if is_done or (message and str(message).startswith("✓"))
            else [255, 200, 80]
        )

        def update():
            for tag in (
                f"{prefix}ui_stage_status",
                f"{self.detached_window_tag}_stage_status",
            ):
                if dpg.does_item_exist(tag):
                    dpg.set_value(tag, message)
                    dpg.configure_item(tag, show=bool(message), color=color)

        if hasattr(self.app, "_queue_ui_task"):
            self.app._queue_ui_task(update)
        else:
            update()

    def preview_stage_fbx(self, prefix):
        """Exports all companion prefabs of the stage to temporary FBX files and loads them into F3D viewer."""
        info = self.stage_info.get(prefix)
        logical_path = None
        if info and info.get("logical_path"):
            logical_path = info["logical_path"]
        elif hasattr(self.app, "current_asset_data") and self.app.current_asset_data:
            logical_path = (
                self.app.current_asset_data.get("full_path")
                or self.app.current_asset_data.get("name")
            )

        if not logical_path or not getattr(self.app, "db", None):
            return

        def set_status(msg, is_done=False):
            self._set_stage_progress(prefix, msg, is_done=is_done)

        set_status(i18n("msg_stage_scanning"))

        def worker():
            return UnityLogic.export_assembled_stage_fbx(
                logical_path, self.app.db, progress_callback=set_status
            )

        def on_done(f):
            try:
                fbx_files = f.result()
            except Exception as e:
                print(f"[HIERARCHY] Error exporting stage for preview: {e}", flush=True)
                fbx_files = []

            def ui_update():
                if fbx_files and hasattr(self.app, "f3d_service"):
                    # Filter out volumetric light beams (blinklight) for F3D preview,
                    # because F3D cannot render additive transparency shaders and renders them as solid black cones.
                    preview_files = [
                        f
                        for f in fbx_files
                        if "blinklight" not in os.path.basename(f).lower()
                    ] or fbx_files
                    set_status(i18n("msg_stage_loading_f3d").format(len(preview_files)))
                    print(
                        f"[STAGE] Loading {len(preview_files)} model(s) into F3D viewer...",
                        flush=True,
                    )
                    combined_path = ";".join(preview_files)
                    self.app.f3d_service.load_mesh(combined_path)
                    set_status(
                        i18n("msg_stage_done").format(len(preview_files)),
                        is_done=True,
                    )
                else:
                    set_status("")

            self.app._queue_ui_task(ui_update)

        self.app.executor.submit(worker).add_done_callback(on_done)

    def on_export_stage_click(self, prefix):
        """Opens directory selector to export all assembled stage FBX models."""
        self.stage_export_prefix = prefix
        if dpg.does_item_exist("stage_export_dialog"):
            dpg.show_item("stage_export_dialog")

    def on_stage_export_directory_selected(self, sender, app_data):
        """Callback when user selects an export directory for stage models."""
        target_dir = app_data.get("file_path_name")
        if not target_dir or not os.path.isdir(target_dir):
            return

        prefix = getattr(self, "stage_export_prefix", "")
        info = self.stage_info.get(prefix)
        logical_path = None
        if info and info.get("logical_path"):
            logical_path = info["logical_path"]
        elif hasattr(self.app, "current_asset_data") and self.app.current_asset_data:
            logical_path = (
                self.app.current_asset_data.get("full_path")
                or self.app.current_asset_data.get("name")
            )

        if not logical_path or not getattr(self.app, "db", None):
            return

        def set_status(msg):
            self._set_stage_progress(prefix, msg)

        set_status(i18n("msg_stage_assembling"))

        def worker():
            return UnityLogic.export_assembled_stage_fbx(
                logical_path,
                self.app.db,
                export_dir=target_dir,
                progress_callback=set_status,
            )

        def on_done(f):
            try:
                exported_files = f.result()
            except Exception as e:
                print(f"[HIERARCHY] Error exporting stage models: {e}", flush=True)
                exported_files = []

            def ui_update():
                set_status(f"✓ {len(exported_files)} FBX")
                export_status_tag = f"{prefix}ui_export_status"
                if dpg.does_item_exist(export_status_tag):
                    dpg.set_value(
                        export_status_tag,
                        i18n("msg_stage_exported").format(target_dir),
                    )
                    dpg.configure_item(export_status_tag, color=[0, 255, 0])

            self.app._queue_ui_task(ui_update)

        self.app.executor.submit(worker).add_done_callback(on_done)

    def open_detached_window(self, prefix):
        """Pops out the scene hierarchy into an independent, large resizable window."""
        if dpg.does_item_exist(self.detached_window_tag):
            dpg.delete_item(self.detached_window_tag)

        stage_prefabs = self.stage_info.get(prefix, {}).get("prefabs", ())
        has_stage = bool(stage_prefabs and len(stage_prefabs) > 1)

        with dpg.window(
            label=f"{i18n('label_unity_scene_hierarchy')} - Detached Inspector",
            tag=self.detached_window_tag,
            width=900,
            height=680,
            pos=[100, 100],
        ):
            with dpg.group(horizontal=True):
                # Left Column: Large Tree View
                with dpg.child_window(width=500, border=True, resizable_x=True):
                    with dpg.group(horizontal=True):
                        dpg.add_text(i18n("label_unity_scene_hierarchy"), color=[0, 255, 255])
                        if has_stage:
                            dpg.add_button(
                                label=i18n("btn_assemble_stage"),
                                callback=lambda: self.assemble_stage_hierarchy(prefix),
                            )
                            dpg.add_button(
                                label=i18n("btn_preview_stage_fbx"),
                                callback=lambda: self.preview_stage_fbx(prefix),
                            )
                            dpg.add_button(
                                label=i18n("btn_export_stage_fbx"),
                                callback=lambda: self.on_export_stage_click(prefix),
                            )
                            dpg.add_text(
                                "",
                                tag=f"{self.detached_window_tag}_stage_status",
                                color=[255, 200, 80],
                                show=False,
                            )
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
