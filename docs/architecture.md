# アーキテクチャ

設計書.md の構成図に対応する実装マッピングです。

```
Airflow Scheduler (dags/youtube_pipeline.py)
        │
        ▼
PostgreSQL Phrase DB (database/schema.sql, src/database/repository.py)
        │
┌───────┴────────┐
▼                ▼
Phrase Inventory  Video Planner
Check             (src/planner/video_planner.py)
(generators/
 phrase_generator.py:
 ensure_phrase_inventory)
        │
        ▼
Gemini API (generators/phrase_generator.py, metadata_generator.py)
        │
        ▼
Video Generation Pipeline
┌───────┬────────────────┬──────────┐
▼        ▼                ▼          
Edge TTS  Pexels Image     Gemini Metadata
(tts/     (media/          (generators/
 edge_tts) image_downloader) metadata_generator)
        │
        ▼
FFmpeg Renderer (video/video_builder.py)
        │
┌───────┴────────┐
▼                ▼
Shorts Builder    Long Builder
(video/short_video.py) (video/long_video.py)
        │
        ▼
Thumbnail Builder (media/thumbnail_builder.py, Longのみ)
        │
        ▼
YouTube Data API (uploader/youtube_uploader.py)
        │
        ▼
Scheduled Upload -> DB更新 (repository.update_video_upload_result)
```

## Airflow タスク粒度

`dags/youtube_pipeline.py` は以下のタスクで構成されます。

1. `ensure_phrase_inventory` — フレーズ在庫が閾値未満ならGeminiで補充
2. `build_short_video` — 音声・画像・字幕・メタデータ生成〜レンダリングまで一括
3. `upload_short_video` — YouTubeへアップロード
4. `should_build_long_video` — 曜日条件によるショートサーキット
5. `build_long_video` — Long動画版の一括生成
6. `upload_long_video` — YouTubeへアップロード

各 `build_*` タスク内部で Voice/Image/Subtitle/Metadata/Thumbnail の生成が
連鎖的に呼び出されるため、Airflow上のタスク数は絞りつつ、内部モジュールは
設計書通り疎結合に分割しています。
