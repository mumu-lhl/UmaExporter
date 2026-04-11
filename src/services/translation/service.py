import os
import json
import requests
import threading
from src.core.config import Config


class TranslationService:
    def __init__(self, app=None):
        self.app = app
        self._translations = {}
        self._lock = threading.Lock()
        self._cache_dir = os.path.join(Config.get_app_data_dir(), "translations")
        if not os.path.exists(self._cache_dir):
            os.makedirs(self._cache_dir, exist_ok=True)

        self.en_url = "https://raw.githubusercontent.com/UmaTL/hachimi-tl-en/refs/heads/main/localized_data/text_data_dict.json"
        self.zh_url = "https://raw.githubusercontent.com/Hachimi-Hachimi/tl-zh-cn/dev/localized_data/text_data_dict.json"

    def _get_cache_path(self, lang):
        return os.path.join(self._cache_dir, f"text_data_{lang}.json")

    def load_cached(self):
        lang = Config.get_effective_language()
        cache_path = self._get_cache_path(lang)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    with self._lock:
                        self._translations = json.load(f)
                print(f"Loaded cached translations for {lang}")
                return True
            except Exception as e:
                print(f"Failed to load cached translations: {e}")
        return False

    def download_translations(self, callback=None):
        lang = Config.get_effective_language()
        if lang not in ["English", "Chinese"]:
            if callback:
                callback(False)
            return

        url = self.en_url if lang == "English" else self.zh_url

        def _worker():
            try:
                print(f"Downloading translations from {url}...")
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                data = response.json()

                cache_path = self._get_cache_path(lang)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                with self._lock:
                    self._translations = data

                print(f"Translations for {lang} updated successfully.")
                if callback:
                    callback(True)
            except Exception as e:
                print(f"Failed to download translations: {e}")
                if callback:
                    callback(False)

        threading.Thread(target=_worker, daemon=True).start()

    def get_text(self, category_id, index):
        cat_str = str(category_id)
        idx_str = str(index)
        with self._lock:
            category = self._translations.get(cat_str)
            if category:
                return category.get(idx_str)
        return None
