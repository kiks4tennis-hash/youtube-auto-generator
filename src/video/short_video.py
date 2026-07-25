"""
YouTube Shorts (9:16, 1フレーズ完結型) の生成フロー。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config.settings import settings
from database.repository import Phrase, Repository, VideoRecord
from generators.metadata_generator import MetadataGenerator
from media.image_downloader import ImageDownloader
from planner.video_planner import VideoPlanner
from tts.edge_tts import TTSGenerator
from utils.logger import get_logger
from video.video_builder import Segment, VideoBuilder

logger = get_logger(__name__)


@dataclass
class ShortVideoResult:
    video_id: int
    file_path: Path
    title: str
    description: str
    tags: list[str]
    phrase_ids: list[int]


class ShortVideoPipeline:
    def __init__(self):
        self.repository = Repository()
        self.planner = VideoPlanner(self.repository)
        self.tts = TTSGenerator()
        self.images = ImageDownloader()
        self.metadata_gen = MetadataGenerator()
        self.builder = VideoBuilder(video_type="short")

    def run(self) -> ShortVideoResult:
        plan = self.planner.plan("short")
        phrase = plan.phrases[0]

        audio = self.tts.generate_for_phrase(phrase.id, phrase.phrase, phrase.example)
        image_path = self.images.download_for_scene(phrase.scene, phrase.id, "short")

        segment = Segment(
            image=image_path,
            phrase_audio=audio["phrase_audio"],
            example_audio=audio["example_audio"],
            phrase_text=phrase.phrase,
            example_text=phrase.example,
        )

        tmp_dir = settings.output_dir / "videos" / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        raw_segment_path = tmp_dir / f"short_{phrase.id}_raw.mp4"
        self.builder.render_segment(segment, raw_segment_path)

        final_path = settings.output_dir / "videos" / f"short_{phrase.id}.mp4"
        self.builder.finalize(raw_segment_path, final_path)

        metadata = self.metadata_gen.generate("short", plan.topic, [phrase])

        video_record = VideoRecord(
            video_type="short",
            title=metadata.title,
            description=metadata.description,
            tags=metadata.tags,
            file_path=str(final_path),
            visibility=settings.youtube.default_visibility,
        )
        video_id = self.repository.insert_video(video_record, phrase_ids=[phrase.id])
        self.repository.mark_phrases_used([phrase.id])

        raw_segment_path.unlink(missing_ok=True)

        return ShortVideoResult(
            video_id=video_id,
            file_path=final_path,
            title=metadata.title,
            description=metadata.description,
            tags=metadata.tags,
            phrase_ids=[phrase.id],
        )


def build_short_video() -> dict:
    """Airflowタスクから呼び出すエントリポイント。XCom経由で結果を渡せるようdictを返す"""
    result = ShortVideoPipeline().run()
    return {
        "video_id": result.video_id,
        "file_path": str(result.file_path),
        "title": result.title,
        "description": result.description,
        "tags": result.tags,
        "video_type": "short",
    }


if __name__ == "__main__":
    print(build_short_video())
