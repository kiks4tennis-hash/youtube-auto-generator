"""
Pexels API から scene キーワードに合った背景画像をダウンロードするモジュール。
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

IMAGE_OUTPUT_DIR = settings.output_dir / "images"
IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# rembg(背景除去)のセグメンテーションモデルの保存先。
# 指定しないと ~/.u2net 配下（コンテナ再作成で消える）に落ちてしまうため、
# bind mount 済みの assets/models/ に固定し、初回ダウンロード(約176MB)を
# 使い回せるようにする。rembgをimportする前に設定する必要がある。
_MODEL_CACHE_DIR = settings.assets_dir / "models"
_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("U2NET_HOME", str(_MODEL_CACHE_DIR))

# 人物パネル用: 「疑問に思っている」「ひらめいた」「驚いている」など、表情が
# はっきり伝わる写真をPexelsで狙って検索するためのキーワード。
_EXPRESSION_QUERIES = [
    "confused thinking face",
    "surprised shocked face",
    "excited realization face",
    "curious puzzled face",
]

_REMBG_SESSION = None  # 初回使用時に遅延生成（モデル読み込みが重いため使い回す）


def _get_rembg_session():
    global _REMBG_SESSION
    if _REMBG_SESSION is None:
        from rembg import new_session

        _REMBG_SESSION = new_session("u2net")
    return _REMBG_SESSION


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

    def download_person_for_topic(
        self, scene: str, phrase_id: int, expression: str | None = None
    ) -> Path | None:
        """
        サムネイルの「人物パネル」用に、トピックのシーンに合う人物写真
        (縦長ポートレート)を検索してダウンロードする。

        表情が伝わる写真ほどクリック率に効くため、疑問/驚き/ひらめきといった
        表情のキーワードを掛け合わせて検索する（expression未指定時はランダム）。

        見つからない/失敗した場合は None を返す。呼び出し側(ThumbnailBuilder)は
        None であれば人物パネルを省略し、これまで通りのレイアウトにフォールバックする
        （＝ここが失敗しても動画生成自体は止めない）。
        """
        expression = expression or random.choice(_EXPRESSION_QUERIES)
        query = f"{scene} person {expression} portrait"
        out_path = IMAGE_OUTPUT_DIR / f"person_{phrase_id}.jpg"

        try:
            data = self._search(query, orientation="portrait")
            photos = data.get("photos", [])
            if not photos:
                # 表情キーワードが厳しすぎてヒットしない場合は、表情無しで再検索
                logger.warning(f"No Pexels 'person' results for '{query}', retrying without expression")
                data = self._search(f"{scene} person portrait", orientation="portrait")
                photos = data.get("photos", [])
                if not photos:
                    logger.warning(f"No Pexels 'person' results for scene='{scene}'")
                    return None

            image_url = photos[0]["src"]["large2x"]
            self._download(image_url, out_path)
            logger.info(f"Downloaded person image for scene='{scene}' -> {out_path}")
            return out_path
        except Exception as e:
            logger.error(f"Failed to fetch person image for scene='{scene}': {e}")
            return None

    def cutout_person_photo(self, photo_path: Path, phrase_id: int) -> Path | None:
        """download_person_for_topic() で取得した矩形の人物写真から、背景を除去した
        透過PNG（切り抜き）を作る。サムネイル側でこれを使うと、背景に馴染ませた
        矩形パネルではなく、人物だけを浮き上がらせた「リアクション」風の合成ができる。

        失敗した場合は None を返す。呼び出し側(ThumbnailBuilder)は None であれば
        従来の矩形パネル方式に自動フォールバックするため、ここが失敗しても
        動画生成自体は止まらない。"""
        if not photo_path or not photo_path.exists():
            return None

        out_path = IMAGE_OUTPUT_DIR / f"person_cutout_{phrase_id}.png"
        try:
            from PIL import Image
            from rembg import remove

            session = _get_rembg_session()
            with Image.open(photo_path) as src:
                cutout = remove(src.convert("RGB"), session=session)
            cutout.save(out_path)
            logger.info(f"Cut out person photo -> {out_path}")
            return out_path
        except Exception as e:
            logger.error(f"Failed to cut out person photo {photo_path}: {e}")
            return None

    @staticmethod
    def _fallback_image(out_path: Path) -> Path:
        """Pexels APIが失敗した場合のフォールバック: 単色画像を生成する"""
        from PIL import Image

        img = Image.new("RGB", (1920, 1080), color=(30, 41, 59))
        img.save(out_path)
        return out_path
