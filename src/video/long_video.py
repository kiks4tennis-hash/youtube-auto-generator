"""
Long-form Video (16:9, 15〜30フレーズ) の生成フロー。
複数フレーズを Intro -> Phrase#1..N -> Review -> Outro の構成でつなげる。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config.settings import settings
from database.repository import Phrase, Repository, VideoRecord
from generators.metadata_generator import MetadataGenerator
from media.image_downloader import ImageDownloader
from media.thumbnail_builder import ThumbnailBuilder
from planner.video_planner import VideoPlanner
from tts.edge_tts import TTSGenerator
from utils.logger import get_logger
from video.video_builder import Segment, VideoBuilder

logger = get_logger(__name__)


@dataclass
class LongVideoResult:
    video_id: int
    file_path: Path
    thumbnail_path: Path
    title: str
    description: str
    tags: list[str]
    phrase_ids: list[int]


class LongVideoPipeline:
    def __init__(self):
        self.repository = Repository()
        self.planner = VideoPlanner(self.repository)
        self.tts = TTSGenerator()
        self.images = ImageDownloader()
        self.metadata_gen = MetadataGenerator()
        self.thumbnails = ThumbnailBuilder()
        self.builder = VideoBuilder(video_type="long")

    def run(self) -> LongVideoResult:
        plan = self.planner.plan("long")
        phrases = plan.phrases

        tmp_dir = settings.output_dir / "videos" / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        segment_paths: list[Path] = []
        first_image: Path | None = None

        for phrase in phrases:
            audio = self.tts.generate_for_phrase(phrase.id, phrase.phrase, phrase.example)
            image_path = self.images.download_for_scene(phrase.scene, phrase.id, "long")
            if first_image is None:
                first_image = image_path

            segment = Segment(
                image=image_path,
                phrase_audio=audio["phrase_audio"],
                example_audio=audio["example_audio"],
                phrase_text=phrase.phrase,
                example_text=phrase.example,
            )
            raw_segment_path = tmp_dir / f"long_{phrase.id}_raw.mp4"
            self.builder.render_segment(segment, raw_segment_path)
            segment_paths.append(raw_segment_path)

        # 動画IDが先に必要な命名のため、DB挿入は結合前に仮払い出しはせず、
        # 一時IDとしてplanの先頭phrase.idを使ってファイル名を決める
        provisional_id = phrases[0].id

        concatenated_path = tmp_dir / f"long_{provisional_id}_concat.mp4"
        self.builder.concat_segments(segment_paths, concatenated_path)

        final_path = settings.output_dir / "videos" / f"long_{provisional_id}.mp4"
        self.builder.finalize(concatenated_path, final_path)

        metadata = self.metadata_gen.generate("long", plan.topic, phrases)

        thumbnail_path = self.thumbnails.build(
            video_id=provisional_id,
            main_title=f"{len(phrases)} Daily English Expressions",
            sub_title=plan.topic,
            background_image=first_image,
        )

        video_record = VideoRecord(
            video_type="long",
            title=metadata.title,
            description=metadata.description,
            tags=metadata.tags,
            file_path=str(final_path),
            thumbnail_path=str(thumbnail_path),
            visibility=settings.youtube.default_visibility,
        )
        phrase_ids = [p.id for p in phrases]
        video_id = self.repository.insert_video(video_record, phrase_ids=phrase_ids)
        self.repository.mark_phrases_used(phrase_ids)

        for p in segment_paths:
            p.unlink(missing_ok=True)
        concatenated_path.unlink(missing_ok=True)

        return LongVideoResult(
            video_id=video_id,
            file_path=final_path,
            thumbnail_path=thumbnail_path,
            title=metadata.title,
            description=metadata.description,
            tags=metadata.tags,
            phrase_ids=phrase_ids,
        )


def build_long_video() -> dict:
    """Airflowタスクから呼び出すエントリポイント。XCom経由で結果を渡せるようdictを返す"""
    result = LongVideoPipeline().run()
    return {
        "video_id": result.video_id,
        "file_path": str(result.file_path),
        "thumbnail_path": str(result.thumbnail_path),
        "title": result.title,
        "description": result.description,
        "tags": result.tags,
        "video_type": "long",
    }


if __name__ == "__main__":
    print(build_long_video())
