"""
Pexels API から scene キーワードに合った背景画像をダウンロードするモジュール。
"""

from __future__ import annotations

from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

IMAGE_OUTPUT_DIR = settings.output_dir / "images"
IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class ImageDownloader:
    def __init__(self):
        self.api_key = settings.pexels.api_key
        self.base_url = settings.pexels.base_url

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _search(self, query: str, orientation: str) -> dict:
        resp = requests.get(
            f"{self.base_url}/search",
            headers={"Authorization": self.api_key},
            params={"query": query, "per_page": 5, "orientation": orientation},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _download(self, url: str, out_path: Path) -> None:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)

    def download_for_scene(self, scene: str, phrase_id: int, video_type: str) -> Path:
        """
        scene キーワードに合う画像を検索してダウンロードする。
        short -> 縦長 (portrait), long -> 横長 (landscape)
        """
        orientation = "portrait" if video_type == "short" else "landscape"
        out_path = IMAGE_OUTPUT_DIR / f"{video_type}_{phrase_id}.jpg"

        try:
            data = self._search(scene, orientation)
            photos = data.get("photos", [])
            if not photos:
                logger.warning(f"No Pexels results for '{scene}', using fallback color background")
                return self._fallback_image(out_path)

            image_url = photos[0]["src"]["large2x"]
            self._download(image_url, out_path)
            logger.info(f"Downloaded background image for scene='{scene}' -> {out_path}")
            return out_path
        except Exception as e:
            logger.error(f"Failed to fetch image for scene='{scene}': {e}. Using fallback.")
            return self._fallback_image(out_path)

    @staticmethod
    def _fallback_image(out_path: Path) -> Path:
        """Pexels APIが失敗した場合のフォールバック: 単色画像を生成する"""
        from PIL import Image

        img = Image.new("RGB", (1920, 1080), color=(30, 41, 59))
        img.save(out_path)
        return out_path
