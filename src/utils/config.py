"""
src配下から `config.settings` を素直にimportできない実行環境向けの薄いラッパー。
（Airflowコンテナ内ではPYTHONPATHに config/ が含まれるため通常はconfig.settingsを直接使えばよい）
"""

from config.settings import settings  # noqa: F401

__all__ = ["settings"]
