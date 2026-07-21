"""
PostgreSQL とのやり取りを担うリポジトリ層。
Airflowタスクや各ジェネレーターはこのクラスを通じてのみDBにアクセスする。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import psycopg2
import psycopg2.extras

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Phrase:
    id: Optional[int]
    phrase: str
    example: str
    scene: str
    topic: Optional[str] = None
    uploaded: bool = False
    created_at: Optional[datetime] = None


@dataclass
class VideoRecord:
    video_type: str
    title: str
    description: str = ""
    tags: list = field(default_factory=list)
    file_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    youtube_video_id: Optional[str] = None
    uploaded: bool = False
    scheduled_at: Optional[datetime] = None
    visibility: str = "private"
    id: Optional[int] = None


class Repository:
    """psycopg2 を薄くラップしたリポジトリ。都度接続し、都度closeする単純設計。"""

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or settings.database.dsn

    @contextlib.contextmanager
    def _conn(self):
        conn = psycopg2.connect(self.dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Phrases
    # ---------------------------------------------------------------

    def count_unused_phrases(self) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM phrases WHERE uploaded = FALSE")
                return cur.fetchone()[0]

    def insert_phrases(self, phrases: list[dict]) -> int:
        """Geminiが生成したフレーズ群をまとめてINSERTする"""
        if not phrases:
            return 0
        with self._conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO phrases (phrase, example, scene, topic)
                    VALUES %s
                    """,
                    [
                        (p["phrase"], p["example"], p["scene"], p.get("topic"))
                        for p in phrases
                    ],
                )
                return cur.rowcount

    def fetch_unused_phrases(self, limit: int, topic: Optional[str] = None) -> list[Phrase]:
        query = """
            SELECT id, phrase, example, scene, topic, uploaded, created_at
            FROM phrases
            WHERE uploaded = FALSE
        """
        params: list = []
        if topic:
            query += " AND topic = %s"
            params.append(topic)
        query += " ORDER BY created_at ASC LIMIT %s"
        params.append(limit)

        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                return [Phrase(**dict(row)) for row in rows]

    def fetch_most_common_topic(self) -> Optional[str]:
        """未使用フレーズの中で最も件数が多いトピックを返す（Long動画のテーマ選定に使用）"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT topic, COUNT(*) AS cnt
                    FROM phrases
                    WHERE uploaded = FALSE AND topic IS NOT NULL
                    GROUP BY topic
                    ORDER BY cnt DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                return row[0] if row else None

    def mark_phrases_used(self, phrase_ids: list[int]) -> None:
        if not phrase_ids:
            return
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE phrases
                    SET uploaded = TRUE, used_at = NOW()
                    WHERE id = ANY(%s)
                    """,
                    (phrase_ids,),
                )

    # ---------------------------------------------------------------
    # Videos
    # ---------------------------------------------------------------

    def insert_video(self, video: VideoRecord, phrase_ids: list[int]) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO videos
                        (video_type, title, description, tags, file_path,
                         thumbnail_path, youtube_video_id, uploaded,
                         scheduled_at, visibility)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        video.video_type,
                        video.title,
                        video.description,
                        video.tags,
                        video.file_path,
                        video.thumbnail_path,
                        video.youtube_video_id,
                        video.uploaded,
                        video.scheduled_at,
                        video.visibility,
                    ),
                )
                video_id = cur.fetchone()[0]

                if phrase_ids:
                    psycopg2.extras.execute_values(
                        cur,
                        "INSERT INTO video_phrases (video_id, phrase_id, position) VALUES %s",
                        [(video_id, pid, i) for i, pid in enumerate(phrase_ids)],
                    )
                return video_id

    def update_video_upload_result(
        self, video_id: int, youtube_video_id: str, uploaded: bool = True
    ) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE videos
                    SET youtube_video_id = %s, uploaded = %s
                    WHERE id = %s
                    """,
                    (youtube_video_id, uploaded, video_id),
                )

    # ---------------------------------------------------------------
    # Pipeline runs (監視・デバッグ用ログテーブル)
    # ---------------------------------------------------------------

    def start_pipeline_run(self, run_date: date, video_type: str) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_runs (run_date, video_type, status)
                    VALUES (%s, %s, 'started')
                    RETURNING id
                    """,
                    (run_date, video_type),
                )
                return cur.fetchone()[0]

    def finish_pipeline_run(
        self, run_id: int, status: str, video_id: Optional[int] = None, error: Optional[str] = None
    ) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = %s, video_id = %s, error = %s, finished_at = NOW()
                    WHERE id = %s
                    """,
                    (status, video_id, error, run_id),
                )
