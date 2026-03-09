import os
import json
import platform
import locale
import sys

from src.utils import is_nuitka

CONFIG_FILE = "config.json"


class Config:
    @staticmethod
    def get_bundle_dir():
        """Returns the base directory of the application, handling PyInstaller and Nuitka bundles.
        When frozen or compiled, returns the directory containing the executable.
        """
        if getattr(sys, "frozen", False) or is_nuitka():
            # For PyInstaller onedir and Nuitka standalone:
            # sys.executable is the binary, os.path.dirname(sys.executable) is the bundle folder root.
            return os.path.dirname(sys.executable)
        else:
            # Running from source
            return os.path.abspath(os.getcwd())

    # Default fallback path
    BASE_PATH = ""
    # Language: "Auto", "English", "Chinese"
    LANGUAGE = "Auto"
    # Data region (jp, global)
    REGION = "jp"
    # Runtime flag: detected if the database is encrypted
    DB_ENCRYPTED = False

    @classmethod
    def get_effective_language(cls):
        """Returns the actual language (English or Chinese) after resolving Auto."""
        if cls.LANGUAGE != "Auto":
            return cls.LANGUAGE

        # Try multiple ways to get system language
        try:
            # 1. Windows specific check (more robust than locale)
            if platform.system() == "Windows":
                import ctypes

                # GetUserDefaultUILanguage returns LCID (e.g. 0x0804 for zh-CN)
                lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                if (lcid & 0xFF) == 0x04:  # 0x04 is Chinese language group
                    return "Chinese"

            # 2. Standard locale check
            lang_code, _ = (
                locale.getlocale()
            )  # getlocale is preferred over getdefaultlocale
            if lang_code and "zh" in lang_code.lower():
                return "Chinese"

            # 3. Check environment variables (common on Linux/macOS)
            for env_var in ["LANG", "LC_ALL", "LC_CTYPE"]:
                val = os.environ.get(env_var, "").lower()
                if "zh" in val:
                    return "Chinese"
        except:
            pass

        return "English"

    @classmethod
    def _get_windows_defaults(cls):
        if platform.system() != "Windows":
            return []

        user_profile = os.environ.get("USERPROFILE", "")
        if not user_profile:
            return []

        return [
            os.path.join(user_profile, "AppData", "LocalLow", "Cygames", "umamusume"),
            os.path.join(user_profile, "Umamusume"),
        ]

    @classmethod
    def is_valid_path(cls, path):
        if not path:
            return False
        # Check for essential parts: meta database and dat folder
        has_meta = os.path.exists(os.path.join(path, "meta"))
        has_dat = os.path.exists(os.path.join(path, "dat"))
        return has_meta and has_dat

    @classmethod
    def load(cls):
        # 1. Try config file first
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    path = data.get("base_path", "")
                    if cls.is_valid_path(path):
                        cls.BASE_PATH = path
                        print(
                            f"Loaded valid config path from {CONFIG_FILE}: {cls.BASE_PATH}"
                        )

                    cls.LANGUAGE = data.get("language", "Auto")
                    cls.REGION = data.get("region", "jp")
                    print(f"Loaded language: {cls.LANGUAGE}, region: {cls.REGION}")
                    return
            except Exception as e:
                print(f"Failed to load config: {e}")

        # 2. Try Windows defaults if on Windows
        for p in cls._get_windows_defaults():
            if cls.is_valid_path(p):
                cls.BASE_PATH = p
                print(f"Found default Windows path: {p}")
                return

        # 3. Last resort (empty or previous default)
        print("No valid data path found.")

    @classmethod
    def save(cls):
        try:
            with open(CONFIG_FILE, "w") as f:
                data = {
                    "base_path": cls.BASE_PATH,
                    "language": cls.LANGUAGE,
                    "region": cls.REGION,
                }
                json.dump(data, f, indent=4)
                print(f"Saved config to {CONFIG_FILE}")
        except Exception as e:
            print(f"Failed to save config: {e}")

    @classmethod
    def get_app_data_dir(cls):
        """Returns the system-standard directory for application data (thumbnails, cache, etc.)."""
        app_name = "UmaExporter"
        system = platform.system()

        if system == "Windows":
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
            path = os.path.join(base, app_name)
        elif system == "Darwin":  # macOS
            path = os.path.expanduser(f"~/Library/Application Support/{app_name}")
        else:  # Linux/Other
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            path = os.path.join(base, app_name)

        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return path

    @classmethod
    def get_thumbnail_dir(cls):
        """Returns the directory where thumbnails are stored."""
        path = os.path.join(cls.get_app_data_dir(), "thumbnails")
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return path

    @classmethod
    def get_app_db_path(cls):
        """Returns the path to the main application database (for thumbnails, settings, etc.)."""
        return os.path.join(cls.get_app_data_dir(), "app_data.db")

    @classmethod
    def get_db_path(cls):
        return os.path.join(cls.BASE_PATH, "meta") if cls.BASE_PATH else ""

    @classmethod
    def get_data_root(cls):
        return os.path.join(cls.BASE_PATH, "dat") if cls.BASE_PATH else ""

    @classmethod
    def set_base_path(cls, path):
        cls.BASE_PATH = path
