"""Main-thread ownership of Dear PyGui texture resources."""

import dearpygui.dearpygui as dpg


class TextureRegistry:
    """Atomically replace and clean up static textures by feature domain.

    Callers must invoke this class only from an already-queued UI task.  Image
    decoding belongs in workers; this class intentionally contains only DPG
    resource lifecycle operations.
    """

    def __init__(self, lock, registry_tag="main_texture_registry"):
        self._lock = lock
        self._registry_tag = registry_tag
        self.tags_by_domain = {}
        self._tag_by_image = {}

    def replace(self, domain, image_tag, data, width, height):
        """Bind a new texture before deleting the previous texture for an image."""
        with self._lock:
            if not dpg.does_item_exist(image_tag):
                return False

            texture_tag = dpg.generate_uuid()
            try:
                dpg.add_static_texture(
                    width=width,
                    height=height,
                    default_value=data,
                    tag=texture_tag,
                    parent=self._registry_tag,
                )
                dpg.configure_item(image_tag, texture_tag=texture_tag)
            except Exception:
                if dpg.does_item_exist(texture_tag):
                    dpg.delete_item(texture_tag)
                return False

            previous_tag = self._tag_by_image.get(image_tag)
            self._tag_by_image[image_tag] = texture_tag
            self.tags_by_domain.setdefault(domain, []).append(texture_tag)
            if previous_tag and dpg.does_item_exist(previous_tag):
                dpg.delete_item(previous_tag)
                self.tags_by_domain[domain] = [
                    tag for tag in self.tags_by_domain[domain] if tag != previous_tag
                ]
            return True

    def clear_domain(self, domain):
        """Delete all textures owned by a feature domain."""
        with self._lock:
            tags = self.tags_by_domain.get(domain, [])
            for tag in tags:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            removed = set(tags)
            self.tags_by_domain[domain] = []
            self._tag_by_image = {
                image_tag: tag
                for image_tag, tag in self._tag_by_image.items()
                if tag not in removed
            }
