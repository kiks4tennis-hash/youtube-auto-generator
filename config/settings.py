"""
プロジェクト全体の設定値を一元管理するモジュール。
環境変数(.env) と config/video_profiles.yaml を読み込み、
アプリケーションのどこからでも `from config.settings import settings` で参照できるようにする。
"""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# .env を読み込む（存在しない場合は無視される）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class DatabaseSettings(BaseModel):
    host: str = Field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    port: int = Field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    db: str = Field(default_factory=lambda: os.getenv("POSTGRES_DB", "youtube_pipeline"))
    user: str = Field(default_factory=lambda: os.getenv("POSTGRES_USER", "airflow"))
    password: str = Field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", ""))

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class GeminiSettings(BaseModel):
    api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))


class PexelsSettings(BaseModel):
    api_key: str = Field(default_factory=lambda: os.getenv("PEXELS_API_KEY", ""))
    base_url: str = "https://api.pexels.com/v1"


class TTSSettings(BaseModel):
    phrase_voice: str = Field(default_factory=lambda: os.getenv("EDGE_TTS_VOICE", "en-US-JennyNeural"))
    example_voice: str = Field(default_factory=lambda: os.getenv("EDGE_TTS_VOICE_EXAMPLE", "en-US-GuyNeural"))


class YouTubeSettings(BaseModel):
    client_secrets_file: str = Field(
        default_factory=lambda: os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "config/client_secret.json")
    )
    token_file: str = Field(default_factory=lambda: os.getenv("YOUTUBE_TOKEN_FILE", "config/token.json"))
    channel_id: str = Field(default_factory=lambda: os.getenv("YOUTUBE_CHANNEL_ID", ""))
    default_visibility: str = Field(default_factory=lambda: os.getenv("DEFAULT_VISIBILITY", "private"))


class PipelineSettings(BaseModel):
    phrase_inventory_threshold: int = Field(
        default_factory=lambda: int(os.getenv("PHRASE_INVENTORY_THRESHOLD", "30"))
    )
    phrase_generation_batch: int = Field(
        default_factory=lambda: int(os.getenv("PHRASE_GENERATION_BATCH", "100"))
    )
    timezone: str = Field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Tokyo"))


class Settings(BaseModel):
    project_root: Path = PROJECT_ROOT
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    pexels: PexelsSettings = Field(default_factory=PexelsSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    youtube: YouTubeSettings = Field(default_factory=YouTubeSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)

    output_dir: Path = PROJECT_ROOT / "output"
    assets_dir: Path = PROJECT_ROOT / "assets"

    @property
    def video_profiles(self) -> dict:
        return _load_video_profiles(self.project_root)

    def profile(self, video_type: str) -> dict:
        """'short' または 'long' のレンダリングプロファイルを返す"""
        profiles = self.video_profiles
        if video_type not in profiles:
            raise ValueError(f"Unknown video_type: {video_type}")
        return profiles[video_type]


@lru_cache
def _load_video_profiles(project_root: Path) -> dict:
    path = project_root / "config" / "video_profiles.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


settings = Settings()
