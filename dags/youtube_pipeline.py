"""
YouTube English Video Auto Generator - メインDAG

毎日実行され、以下を自動で行う:
  1. フレーズ在庫チェック（不足していればGeminiで補充）
  2. Short動画1本 + （曜日条件などに応じて）Long動画1本の生成
  3. YouTubeへのスケジュールアップロード

設計書の対応:
  Check Phrase Inventory -> Generate New Phrases (if needed) -> Create Video Plan ->
  Generate Voice -> Download Images -> Render Video -> Generate Thumbnail ->
  Generate Metadata -> Upload to YouTube -> Update Database

  ※ 本DAGでは Voice/Images/Metadata/Thumbnail の生成は各 build_*_video タスク内で
    一体で実行される（video/short_video.py, video/long_video.py 参照）。
    Airflow上ではタスクの可観測性のため generate_phrases -> build_video -> upload という
    粒度でタスク化している。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator

# コンテナ内で src/ 配下と config/ 配下のモジュールをimportできるようにする。
# - "generators.xxx" 等は src/ を、"config.xxx" はプロジェクトルート(config/の親)を
#   PYTHONPATHに含める必要がある点に注意（configディレクトリ自体を追加すると
#   `import config.prompts` が壊れる）。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = str(PROJECT_ROOT / "src")
ROOT_PATH = str(PROJECT_ROOT)
for p in (SRC_PATH, ROOT_PATH):
    if p not in sys.path:
        sys.path.insert(0, p)

default_args = {
    "owner": "taky",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


# ---------------------------------------------------------------
# タスク関数
# ---------------------------------------------------------------

def task_ensure_phrase_inventory(**context):
    from generators.phrase_generator import ensure_phrase_inventory

    inserted = ensure_phrase_inventory()
    context["ti"].xcom_push(key="phrases_generated", value=inserted)
    return inserted


def task_build_short_video(**context):
    from video.short_video import build_short_video

    result = build_short_video()
    context["ti"].xcom_push(key="short_video_result", value=result)
    return result


def task_upload_short_video(**context):
    from uploader.youtube_uploader import upload_video

    result = context["ti"].xcom_pull(task_ids="build_short_video", key="short_video_result")
    youtube_id = upload_video(result)
    return youtube_id


def task_should_build_long_video(**context) -> bool:
    """
    毎日Long動画まで作ると素材消費が激しいため、通常は曜日で間引く（例: 週2本）。
    テスト時などに毎回Long動画を作りたい場合は、.envで
        FORCE_BUILD_LONG_VIDEO=true
    を設定するとこの間引きをスキップできる。
    """
    if os.getenv("FORCE_BUILD_LONG_VIDEO", "false").lower() in ("1", "true", "yes"):
        return True

    execution_date: datetime = context["logical_date"]
    return execution_date.weekday() in (1, 4)  # 火曜・金曜のみLong動画を作る


def task_build_long_video(**context):
    from video.long_video import build_long_video

    result = build_long_video()
    context["ti"].xcom_push(key="long_video_result", value=result)
    return result


def task_upload_long_video(**context):
    from uploader.youtube_uploader import upload_video

    result = context["ti"].xcom_pull(task_ids="build_long_video", key="long_video_result")
    youtube_id = upload_video(result)
    return youtube_id


# ---------------------------------------------------------------
# DAG定義
# ---------------------------------------------------------------

with DAG(
    dag_id="youtube_english_video_pipeline",
    description="Fully automated English learning video generation & upload pipeline",
    default_args=default_args,
    schedule_interval="0 21 * * *",  # 毎日21:00 UTC (=日本時間 翌6:00)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["youtube", "english", "content-automation"],
) as dag:

    ensure_phrase_inventory = PythonOperator(
        task_id="ensure_phrase_inventory",
        python_callable=task_ensure_phrase_inventory,
    )

    build_short_video = PythonOperator(
        task_id="build_short_video",
        python_callable=task_build_short_video,
    )

    upload_short_video = PythonOperator(
        task_id="upload_short_video",
        python_callable=task_upload_short_video,
    )

    should_build_long_video = ShortCircuitOperator(
        task_id="should_build_long_video",
        python_callable=task_should_build_long_video,
    )

    build_long_video = PythonOperator(
        task_id="build_long_video",
        python_callable=task_build_long_video,
    )

    upload_long_video = PythonOperator(
        task_id="upload_long_video",
        python_callable=task_upload_long_video,
    )

    # フレーズ在庫確保 -> Short動画生成・アップロード
    ensure_phrase_inventory >> build_short_video >> upload_short_video

    # フレーズ在庫確保 -> (曜日条件) -> Long動画生成・アップロード
    ensure_phrase_inventory >> should_build_long_video >> build_long_video >> upload_long_video