"""
その日どんな動画を作るか（Short / Long, どのフレーズを使うか）を決定するプランナー。
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings
from database.repository import Phrase, Repository
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VideoPlan:
    video_type: str          # "short" | "long"
    topic: str
    phrases: list[Phrase]


class VideoPlanner:
    def __init__(self, repository: Repository | None = None):
        self.repository = repository or Repository()

    def plan_short(self) -> VideoPlan:
        profile = settings.profile("short")
        n = profile["phrases_per_video"]
        phrases = self.repository.fetch_unused_phrases(limit=n)
        if not phrases:
            raise RuntimeError("No unused phrases available for Shorts. Run phrase generation first.")
        topic = phrases[0].topic or "Daily English"
        logger.info(f"Planned SHORT video: topic='{topic}', phrases={len(phrases)}")
        return VideoPlan(video_type="short", topic=topic, phrases=phrases)

    def plan_long(self) -> VideoPlan:
        profile = settings.profile("long")
        target_n = profile["phrases_per_video"]
        min_n = profile["min_phrases_per_video"]

        topic = self.repository.fetch_most_common_topic()
        phrases = self.repository.fetch_unused_phrases(limit=target_n, topic=topic)

        if len(phrases) < min_n:
            # 特定トピックだけでは足りない場合はトピック問わず補充する
            logger.info(
                f"Only {len(phrases)} phrases for topic='{topic}', "
                f"topping up without topic filter"
            )
            phrases = self.repository.fetch_unused_phrases(limit=target_n)
            topic = "Mixed English Expressions"

        if len(phrases) < min_n:
            raise RuntimeError(
                f"Not enough unused phrases for a Long video "
                f"(have {len(phrases)}, need at least {min_n})"
            )

        logger.info(f"Planned LONG video: topic='{topic}', phrases={len(phrases)}")
        return VideoPlan(video_type="long", topic=topic, phrases=phrases)

    def plan(self, video_type: str) -> VideoPlan:
        if video_type == "short":
            return self.plan_short()
        elif video_type == "long":
            return self.plan_long()
        raise ValueError(f"Unknown video_type: {video_type}")
