import os
import time

import dearpygui.dearpygui as dpg

from src.constants import Config
from src.unity_logic import UnityLogic
from src.ui.i18n import i18n


class PreviewMixin:
    def _format_size(self, size_bytes):
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError):
            return "Unknown"
        if size_bytes < 1024:
            return f"{size_bytes} Bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def _update_asset_properties_panel(self, prefix, user_data):
        dpg.configure_item(f"{prefix}details_group", show=True)
        # Keep the top-level path display but also update the detailed label inside the group
        dpg.set_value(
            f"{prefix}ui_path", f"{i18n('prop_logical_path')}{user_data['full_path']}"
        )
        dpg.set_value(
            f"{prefix}ui_path_label",
            f"{i18n('prop_logical_path')}{user_data['full_path']}",
        )
        # Only set the hash value to the copyable field
        dpg.set_value(f"{prefix}ui_hash", user_data["hash"])
        formatted_size = self._format_size(user_data["size"])
        dpg.set_value(f"{prefix}ui_size", f"{i18n('prop_file_size')}{formatted_size}")
        h = user_data["hash"]
        dpg.set_value(f"{prefix}ui_phys", f"{i18n('prop_phys_loc')}dat/{h[:2]}/{h}")

    def _reset_detail_containers(self, is_drag_preview=False):
        for prefix in self._detail_prefixes():
            if not is_drag_preview:
                self._clear_preview_texture(prefix)
            messages = []
            if not is_drag_preview:
                messages.append((f"{prefix}ui_unity_parent", i18n("msg_loading_unity")))
                messages.extend(
                    [
                        (f"{prefix}ui_dep_parent", i18n("msg_loading_deps")),
                        (f"{prefix}ui_rev_dep_parent", i18n("msg_loading_rev_deps")),
                    ]
                )
            for tag, msg in messages:
                dpg.delete_item(tag, children_only=True)
                dpg.add_text(msg, parent=tag, color=[150, 150, 150])

    def _set_dependency_sections_visible(self, visible):
        for prefix in self._detail_prefixes():
            dpg.configure_item(f"{prefix}ui_dep_section", show=visible)
            dpg.configure_item(f"{prefix}ui_rev_dep_section", show=visible)

    def _load_unity_async(
        self, phys_path, current_asset_id, request_id, bundle_key=None
    ):
        def worker():
            return UnityLogic.get_unity_assets(phys_path, bundle_key=bundle_key)

        future = self.executor.submit(worker)

        def done_callback(f):
            try:
                objs = f.result()
            except Exception:
                objs = []
            self._queue_ui_task(
                lambda: self._apply_unity_objects_result(
                    phys_path, current_asset_id, request_id, objs, bundle_key=bundle_key
                )
            )

        future.add_done_callback(done_callback)

    def _apply_unity_objects_result(
        self, phys_path, current_asset_id, request_id, objs, bundle_key=None
    ):
        if request_id != self.selection_request_id:
            return
        if not self._is_still_selected(current_asset_id):
            return

        for prefix in self._detail_prefixes():
            self._render_unity_objects(prefix, phys_path, objs, bundle_key=bundle_key)

        if (
            self.scene_auto_preview_request
            and self.scene_auto_preview_request.get("asset_id") == current_asset_id
            and self.scene_auto_preview_request.get("request_id") == request_id
        ):
            first_animator = next((obj for obj in objs if obj[0] == "Animator"), None)
            if first_animator:
                _, animator_name, path_id = first_animator
                animator_tag = f"scene_unity_obj_{path_id}"
                sender = animator_tag if dpg.does_item_exist(animator_tag) else None
                self.on_unity_obj_click(
                    sender,
                    None,
                    (
                        phys_path,
                        path_id,
                        "Animator",
                        "scene_",
                        animator_name,
                        bundle_key,
                    ),
                )
                self.scene_auto_preview_request = None
                return

        if (
            self.prop_auto_preview_request
            and self.prop_auto_preview_request.get("asset_id") == current_asset_id
            and self.prop_auto_preview_request.get("request_id") == request_id
        ):
            first_animator = next((obj for obj in objs if obj[0] == "Animator"), None)
            if first_animator:
                _, animator_name, path_id = first_animator
                animator_tag = f"prop_unity_obj_{path_id}"
                sender = animator_tag if dpg.does_item_exist(animator_tag) else None
                self.on_unity_obj_click(
                    sender,
                    None,
                    (
                        phys_path,
                        path_id,
                        "Animator",
                        "prop_",
                        animator_name,
                        bundle_key,
                    ),
                )
                self.prop_auto_preview_request = None
                return

        # Auto-preview if there is exactly one Texture2D.
        single_texture_path_id = self._find_single_texture_path_id(objs)
        if single_texture_path_id is not None:
            u_type = "Texture2D"
            path_id = single_texture_path_id
            for prefix in self._detail_prefixes():
                self.on_unity_obj_click(
                    f"{prefix}unity_obj_{path_id}",
                    None,
                    (phys_path, path_id, u_type, prefix, None, bundle_key),
                )

    def _preview_drag_texture_async(
        self, phys_path, current_asset_id, request_id, bundle_key=None
    ):
        def worker():
            return UnityLogic.get_unity_assets(phys_path, bundle_key=bundle_key)

        future = self.executor.submit(worker)

        def done_callback(f):
            try:
                objs = f.result()
            except Exception:
                objs = ()
            texture_path_id = self._find_single_texture_path_id(objs)
            self._queue_ui_task(
                lambda: self._apply_drag_texture_candidate(
                    phys_path,
                    current_asset_id,
                    request_id,
                    texture_path_id,
                    objs,
                    bundle_key=bundle_key,
                )
            )

        future.add_done_callback(done_callback)

    def _apply_drag_texture_candidate(
        self,
        phys_path,
        current_asset_id,
        request_id,
        texture_path_id,
        objs,
        bundle_key=None,
    ):
        if request_id != self.selection_request_id:
            return
        if not self._is_still_selected(current_asset_id):
            return
        if not self.current_view_is_drag_preview:
            return

        for prefix in self._detail_prefixes():
            # Render internal objects even during drag
            self._render_unity_objects(prefix, phys_path, objs, bundle_key=bundle_key)

            image_container_tag = f"{prefix}ui_unity_image_container"
            header_tag = f"{prefix}ui_texture_preview_header"

            if texture_path_id is None:
                # If it's a drag preview and no texture found, we hide it immediately
                # Or we could keep previous, but that might be confusing if the file is NOT a texture.
                dpg.configure_item(image_container_tag, show=False)
                dpg.delete_item(image_container_tag, children_only=True)
                continue

            # Ensure header exists without clearing everything if we're dragging
            if not dpg.does_item_exist(header_tag):
                dpg.delete_item(image_container_tag, children_only=True)
                dpg.add_spacer(height=5, parent=image_container_tag)
                dpg.add_text(
                    i18n("label_texture_preview"),
                    color=[0, 255, 255],
                    parent=image_container_tag,
                    tag=header_tag,
                )

            dpg.configure_item(image_container_tag, show=True)
            self._load_texture_preview_async(
                phys_path,
                texture_path_id,
                prefix,
                current_asset_id,
                request_id,
                bundle_key=bundle_key,
            )

    def _find_single_texture_path_id(self, objs):
        texture_ids = [
            path_id for u_type, _u_name, path_id in objs if u_type == "Texture2D"
        ]
        if len(texture_ids) == 1:
            return texture_ids[0]
        return None

    def _render_unity_objects(self, prefix, phys_path, objs, bundle_key=None):
        parent_tag = f"{prefix}ui_unity_parent"
        dpg.delete_item(parent_tag, children_only=True)

        if not objs:
            dpg.add_text(i18n("msg_no_unity_objs"), parent=parent_tag)
            return

        with dpg.table(
            header_row=True,
            resizable=True,
            parent=parent_tag,
            policy=dpg.mvTable_SizingStretchProp,
        ):
            dpg.add_table_column(label="Type", width_fixed=True)
            dpg.add_table_column(label="Name")
            for u_type, u_name, path_id in objs[:200]:
                with dpg.table_row():
                    dpg.add_text(u_type)
                    tag = f"{prefix}unity_obj_{path_id}"
                    dpg.add_selectable(
                        label=u_name,
                        tag=tag,
                        callback=self.on_unity_obj_click,
                        user_data=(
                            phys_path,
                            path_id,
                            u_type,
                            prefix,
                            u_name,
                            bundle_key,
                        ),
                        span_columns=True,
                    )

    def on_unity_obj_click(self, sender, app_data, user_data, *args):
        phys_path, path_id, u_type, prefix = user_data[:4]
        object_name = user_data[4] if len(user_data) > 4 else None
        bundle_key = user_data[5] if len(user_data) > 5 else None
        image_container_tag = f"{prefix}ui_unity_image_container"
        preview_loading_tag = f"{prefix}ui_preview_loading"

        # Toggle selection: if clicking the same object, deselect it
        if sender and sender == self.last_unity_selected.get(prefix):
            dpg.set_value(sender, False)
            self.last_unity_selected[prefix] = None
            dpg.configure_item(image_container_tag, show=False)
            dpg.delete_item(image_container_tag, children_only=True)
            return

        # Single selection logic for a new item
        last_selected = self.last_unity_selected.get(prefix)
        if last_selected and dpg.does_item_exist(last_selected):
            dpg.set_value(last_selected, False)

        if sender and dpg.does_item_exist(sender):
            dpg.set_value(sender, True)
            self.last_unity_selected[prefix] = sender
        else:
            self.last_unity_selected[prefix] = None

        dpg.configure_item(image_container_tag, show=False)
        dpg.delete_item(image_container_tag, children_only=True)

        header_tag = f"{prefix}ui_texture_preview_header"

        if u_type in ["Texture2D", "Sprite"]:
            dpg.add_spacer(height=5, parent=image_container_tag)
            dpg.add_text(
                i18n("label_texture_preview"),
                color=[0, 255, 255],
                parent=image_container_tag,
                tag=header_tag,
            )
            if not self.current_view_is_drag_preview:
                dpg.add_text(
                    i18n("msg_loading"),
                    parent=image_container_tag,
                    tag=preview_loading_tag,
                )
            dpg.configure_item(image_container_tag, show=True)
            self._load_texture_preview_async(
                phys_path,
                path_id,
                prefix,
                self.current_asset_id,
                self.selection_request_id,
                bundle_key=bundle_key,
            )
        elif u_type == "Mesh":
            dpg.add_spacer(height=5, parent=image_container_tag)
            dpg.add_text(
                i18n("label_mesh_actions"),
                color=[0, 255, 255],
                parent=image_container_tag,
            )
            dpg.add_text(
                i18n("msg_preparing_mesh"),
                parent=image_container_tag,
                tag=preview_loading_tag,
            )
            dpg.add_button(
                label=i18n("btn_force_preview"),
                parent=image_container_tag,
                callback=self.on_mesh_preview_click,
                user_data=(phys_path, path_id, prefix, bundle_key),
            )
            dpg.configure_item(image_container_tag, show=True)

            # Auto launch/update on click (Async)
            self.on_mesh_preview_click(
                None, None, (phys_path, path_id, prefix, bundle_key)
            )
        elif u_type == "Animator":
            dpg.add_spacer(height=5, parent=image_container_tag)
            dpg.add_text(
                i18n("label_animator_actions"),
                color=[0, 255, 255],
                parent=image_container_tag,
            )
            dpg.add_text(
                i18n("msg_exporting_fbx"),
                parent=image_container_tag,
                tag=preview_loading_tag,
                color=[255, 200, 0],
            )
            dpg.add_button(
                label=i18n("btn_force_preview"),
                parent=image_container_tag,
                callback=self.on_animator_preview_click,
                user_data=(phys_path, path_id, prefix, object_name, bundle_key),
            )
            dpg.configure_item(image_container_tag, show=True)

            # Auto launch/update on click (Async)
            self.on_animator_preview_click(
                None, None, (phys_path, path_id, prefix, object_name, bundle_key)
            )

    def on_mesh_preview_click(self, sender, app_data, user_data, *args):
        phys_path, path_id = user_data[:2]
        prefix = user_data[2] if len(user_data) > 2 else ""
        bundle_key = user_data[3] if len(user_data) > 3 else None
        preview_loading_tag = f"{prefix}ui_preview_loading"
        image_container_tag = f"{prefix}ui_unity_image_container"
        asset_id = self.current_asset_id
        request_id = self.selection_request_id
        future = self.executor.submit(
            UnityLogic.save_mesh_to_tmp, phys_path, path_id, bundle_key=bundle_key
        )

        def done_callback(f):
            try:
                tmp_mesh_path = f.result()
            except Exception:
                tmp_mesh_path = None
            self._queue_ui_task(
                lambda: self._apply_mesh_preview_result(
                    tmp_mesh_path,
                    preview_loading_tag,
                    image_container_tag,
                    asset_id,
                    request_id,
                )
            )

        future.add_done_callback(done_callback)

    def _apply_mesh_preview_result(
        self,
        tmp_mesh_path,
        preview_loading_tag,
        image_container_tag,
        asset_id,
        request_id,
    ):
        if request_id != self.selection_request_id or asset_id != self.current_asset_id:
            return
        if dpg.does_item_exist(preview_loading_tag):
            dpg.delete_item(preview_loading_tag)
        if tmp_mesh_path:
            self._ensure_f3d_viewer()
            try:
                self.f3d_process.stdin.write(f"{tmp_mesh_path}\n")
                self.f3d_process.stdin.flush()
            except Exception as e:
                print(f"Failed to send mesh to F3D: {e}")
            return
        dpg.add_text(
            "Failed to prepare mesh.",
            parent=image_container_tag,
            color=[255, 0, 0],
        )

    def on_animator_preview_click(self, sender, app_data, user_data, *args):
        prefix = user_data[2] if len(user_data) > 2 else ""
        object_name = user_data[3] if len(user_data) > 3 else None
        preview_loading_tag = f"{prefix}ui_preview_loading"
        image_container_tag = f"{prefix}ui_unity_image_container"
        asset_id = self.current_asset_id
        request_id = self.selection_request_id
        future = self.executor.submit(
            self._build_animator_preview, asset_id, object_name
        )

        def done_callback(f):
            try:
                tmp_fbx_path = f.result()
            except Exception:
                tmp_fbx_path = None
            self._queue_ui_task(
                lambda: self._apply_animator_preview_result(
                    tmp_fbx_path,
                    preview_loading_tag,
                    image_container_tag,
                    asset_id,
                    request_id,
                )
            )

        future.add_done_callback(done_callback)

    def _build_animator_preview(self, asset_id, object_name=None):
        results = self._get_recursive_hashes(asset_id)
        paths = []
        bundle_keys = []
        for h, k in results:
            p = os.path.join(Config.get_data_root(), h[:2], h)
            if os.path.exists(p):
                paths.append(p)
                bundle_keys.append(k)
        return UnityLogic.save_animator_to_tmp(
            paths, object_name, bundle_keys=bundle_keys
        )

    def _get_recursive_hashes(self, asset_id):
        if asset_id not in self.cached_recursive_hashes:
            self.cached_recursive_hashes[asset_id] = (
                self.db.get_all_recursive_dependencies(asset_id)
            )
        return self.cached_recursive_hashes[asset_id]

    def _apply_animator_preview_result(
        self,
        tmp_fbx_path,
        preview_loading_tag,
        image_container_tag,
        asset_id,
        request_id,
    ):
        if request_id != self.selection_request_id or asset_id != self.current_asset_id:
            return
        if dpg.does_item_exist(preview_loading_tag):
            dpg.delete_item(preview_loading_tag)
        if tmp_fbx_path:
            self._ensure_f3d_viewer()
            try:
                self.f3d_process.stdin.write(f"{tmp_fbx_path}\n")
                self.f3d_process.stdin.flush()
            except Exception as e:
                print(f"Failed to send FBX to F3D: {e}")
            return
        dpg.add_text(
            "Failed to export FBX for preview.",
            parent=image_container_tag,
            color=[255, 0, 0],
        )

    def _load_texture_preview_async(
        self,
        phys_path,
        path_id,
        prefix="",
        asset_id=None,
        request_id=None,
        bundle_key=None,
    ):
        self.texture_request_ids[prefix] = self.texture_request_ids.get(prefix, 0) + 1
        texture_request_id = self.texture_request_ids[prefix]
        if asset_id is None:
            asset_id = self.current_asset_id
        if request_id is None:
            request_id = self.selection_request_id
        future = self.executor.submit(
            UnityLogic.get_texture_data, phys_path, path_id, bundle_key=bundle_key
        )

        def done_callback(f):
            try:
                data_flat, width, height = f.result()
                error = None
            except Exception as e:
                data_flat, width, height = None, 0, 0
                error = str(e)
            self._queue_ui_task(
                lambda: self._apply_texture_preview_result(
                    data_flat,
                    width,
                    height,
                    path_id,
                    prefix,
                    asset_id,
                    request_id,
                    texture_request_id,
                    error,
                )
            )

        future.add_done_callback(done_callback)

    def _apply_texture_preview_result(
        self,
        data_flat,
        width,
        height,
        path_id,
        prefix,
        asset_id,
        request_id,
        texture_request_id,
        error=None,
    ):
        preview_loading_tag = f"{prefix}ui_preview_loading"
        image_container_tag = f"{prefix}ui_unity_image_container"
        image_tag = f"{prefix}ui_preview_image"

        if request_id != self.selection_request_id or asset_id != self.current_asset_id:
            return
        if texture_request_id != self.texture_request_ids.get(prefix, 0):
            return
        if error:
            if dpg.does_item_exist(preview_loading_tag):
                dpg.set_value(preview_loading_tag, f"Error: {error}")
            return
        try:
            if data_flat is None:
                if dpg.does_item_exist(preview_loading_tag):
                    dpg.set_value(preview_loading_tag, "Failed to load image data.")
                return
            if width <= 0 or height <= 0:
                if dpg.does_item_exist(preview_loading_tag):
                    dpg.set_value(preview_loading_tag, "Invalid texture size.")
                return

            expected_size = width * height * 4
            actual_size = len(data_flat)
            if actual_size != expected_size:
                if dpg.does_item_exist(preview_loading_tag):
                    dpg.set_value(
                        preview_loading_tag,
                        f"Texture data size mismatch: expected {expected_size}, got {actual_size}.",
                    )
                return

            tex_tag = f"{prefix}unity_tex_{path_id}_{int(time.time() * 1000)}"
            with self.texture_lock:
                try:
                    dpg.add_static_texture(
                        width=width,
                        height=height,
                        default_value=data_flat,
                        tag=tex_tag,
                        parent="main_texture_registry",
                    )
                except Exception:
                    fallback_data = (
                        data_flat.tolist()
                        if hasattr(data_flat, "tolist")
                        else list(data_flat)
                    )
                    dpg.add_static_texture(
                        width=width,
                        height=height,
                        default_value=fallback_data,
                        tag=tex_tag,
                        parent="main_texture_registry",
                    )

                if dpg.does_item_exist(image_tag):
                    dpg.delete_item(image_tag)

                if dpg.does_item_exist(preview_loading_tag):
                    dpg.delete_item(preview_loading_tag)

                scale = min(1.0, 450 / width)
                dpg.add_image(
                    tex_tag,
                    parent=image_container_tag,
                    width=int(width * scale),
                    height=int(height * scale),
                    tag=image_tag,
                )

                # Now clear the PREVIOUS texture tag from registry
                self._clear_preview_texture(prefix)
                self.preview_texture_tags[prefix] = tex_tag

        except Exception as e:
            if dpg.does_item_exist(preview_loading_tag):
                dpg.set_value(preview_loading_tag, f"Error: {str(e)}")

    def _clear_preview_texture(self, prefix):
        tag = self.preview_texture_tags.get(prefix)
        if tag and dpg.does_item_exist(tag):
            dpg.delete_item(tag)
        self.preview_texture_tags[prefix] = None

    def _load_deps_async(self, current_asset_id, request_id):
        if not self.db:
            return
        cached = self.cached_deps.get(current_asset_id)
        if cached is not None:
            self._queue_ui_task(
                lambda: self._apply_dependency_result(
                    current_asset_id,
                    request_id,
                    cached,
                    "ui_dep_parent",
                    "No dependencies found.",
                )
            )
            return

        future = self.executor.submit(self.db.get_dependencies, current_asset_id)

        def done_callback(f):
            try:
                deps = f.result()
            except Exception:
                deps = []
            self.cached_deps[current_asset_id] = deps
            self._queue_ui_task(
                lambda: self._apply_dependency_result(
                    current_asset_id,
                    request_id,
                    deps,
                    "ui_dep_parent",
                    i18n("msg_no_deps"),
                )
            )

        future.add_done_callback(done_callback)

    def _load_rev_deps_async(self, current_asset_id, request_id):
        if not self.db:
            return
        cached = self.cached_rev_deps.get(current_asset_id)
        if cached is not None:
            self._queue_ui_task(
                lambda: self._apply_dependency_result(
                    current_asset_id,
                    request_id,
                    cached,
                    "ui_rev_dep_parent",
                    i18n("msg_no_rev_deps"),
                )
            )
            return

        future = self.executor.submit(
            self.db.get_reverse_dependencies, current_asset_id
        )

        def done_callback(f):
            try:
                rev_deps = f.result()
            except Exception:
                rev_deps = []
            self.cached_rev_deps[current_asset_id] = rev_deps
            self._queue_ui_task(
                lambda: self._apply_dependency_result(
                    current_asset_id,
                    request_id,
                    rev_deps,
                    "ui_rev_dep_parent",
                    i18n("msg_no_rev_deps"),
                )
            )

        future.add_done_callback(done_callback)

    def _apply_dependency_result(
        self, current_asset_id, request_id, data, parent_suffix, empty_msg
    ):
        if request_id != self.selection_request_id:
            return
        if not self._is_still_selected(current_asset_id):
            return
        for prefix in self._detail_prefixes():
            self._fill_dependency_table(
                f"{prefix}{parent_suffix}",
                data,
                empty_msg,
            )

    def _detail_prefixes(self):
        prefixes = [""]
        if dpg.does_alias_exist("scene_ui_path"):
            prefixes.append("scene_")
        if dpg.does_alias_exist("prop_ui_path"):
            prefixes.append("prop_")
        return prefixes

    def _fill_dependency_table(self, parent, data, empty_msg):
        dpg.delete_item(parent, children_only=True)
        if not data:
            dpg.add_text(empty_msg, parent=parent)
            return
        with dpg.table(
            header_row=True,
            resizable=True,
            parent=parent,
            policy=dpg.mvTable_SizingStretchProp,
        ):
            dpg.add_table_column(label="Type", width_fixed=True)
            dpg.add_table_column(label="Asset Path")
            for name, d_type, asset_id, size, f_hash, key_val in data:
                with dpg.table_row():
                    dpg.add_text(f"Type {d_type}")
                    asset_info = {
                        "id": asset_id,
                        "size": size,
                        "hash": f_hash,
                        "full_path": name,
                        "key": key_val,
                        "is_from_dep": True,  # Mark as navigation source
                    }
                    self._add_file_selectable(
                        label=name,
                        user_data=asset_info,
                        span_columns=True,
                    )

    def _is_still_selected(self, asset_id):
        return self.current_asset_id == asset_id

    def _get_recursive_hashes(self, asset_id):
        if asset_id not in self.cached_recursive_hashes:
            self.cached_recursive_hashes[asset_id] = (
                self.db.get_all_recursive_dependencies(asset_id)
            )
        return self.cached_recursive_hashes[asset_id]
