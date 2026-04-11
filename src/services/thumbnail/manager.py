import os
import shutil
from src.core.config import Config


class ThumbnailManager:
    @staticmethod
    def get_character_cache_dir():
        """Returns the directory where character images are stored."""
        path = os.path.join(Config.get_thumbnail_dir(), "characters")
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def get_character_cache(cache_name):
        """Returns the cache path for a character image filename."""
        if not cache_name:
            return None

        path = os.path.join(
            ThumbnailManager.get_character_cache_dir(), f"{cache_name}.png"
        )
        if os.path.exists(path):
            return path
        return None

    @staticmethod
    def get_character_cache_path(cache_name):
        """Returns the standard cache path for a character image filename."""
        if not cache_name:
            return None
        return os.path.join(
            ThumbnailManager.get_character_cache_dir(), f"{cache_name}.png"
        )

    @staticmethod
    def get_thumbnail(asset_hash):
        """Returns the thumbnail path for the given asset hash, if it exists."""
        if not asset_hash:
            return None

        path = os.path.join(Config.get_thumbnail_dir(), f"{asset_hash}.png")
        if os.path.exists(path):
            return path
        return None

    @staticmethod
    def set_thumbnail(asset_hash, thumbnail_path):
        """
        Sets or updates the thumbnail for the given asset hash.
        This handles moving the generated thumbnail to the standard location if needed.
        """
        if not asset_hash or not thumbnail_path:
            return

        target_path = os.path.join(Config.get_thumbnail_dir(), f"{asset_hash}.png")

        # If the provided path is already the target path, do nothing
        if os.path.abspath(thumbnail_path) == os.path.abspath(target_path):
            return

        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            # If it's a different path, copy it to the standard location
            if os.path.exists(thumbnail_path):
                shutil.copy2(thumbnail_path, target_path)
        except Exception as e:
            print(f"Error saving thumbnail for {asset_hash}: {e}")

    @staticmethod
    def remove_thumbnail(asset_hash):
        """Removes the thumbnail file for the given asset hash."""
        if not asset_hash:
            return

        path = ThumbnailManager.get_thumbnail(asset_hash)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    def clear_all():
        """Clears all thumbnail files."""
        thumb_dir = Config.get_thumbnail_dir()
        if os.path.exists(thumb_dir):
            for f in os.listdir(thumb_dir):
                if f.endswith(".png"):
                    try:
                        os.remove(os.path.join(thumb_dir, f))
                    except OSError:
                        pass
