# YouTube English Video Auto Generator

英語学習チャンネル「Taky's Language School」向けの、動画企画〜生成〜アップロードまでを
完全自動化するパイプラインです。設計書（設計書.md）に基づいて実装しています。

## できること

- Gemini APIで日常英語フレーズ・動画メタデータを自動生成
- Edge TTSで無料のAIナレーションを生成
- Pexels APIから場面に合った背景画像を自動取得
- FFmpegでテキスト焼き込み・字幕・BGM付きの動画を自動レンダリング
- Pillowでロングフォーム動画用サムネイルを自動生成
- YouTube Data APIでスケジュールアップロード
- Apache Airflowで日次実行を完全自動化（Shorts毎日 / Long動画は週2回）

## セットアップ

### 1. 環境変数

```bash
cp .env.example .env
# .env を編集し、以下を設定
#  - GEMINI_API_KEY   (https://aistudio.google.com/apikey)
#  - PEXELS_API_KEY   (https://www.pexels.com/api/)
#  - POSTGRES_PASSWORD など
```

### 2. YouTube OAuth2 クレデンシャル

Google Cloud Console で YouTube Data API v3 を有効化し、
OAuth2クライアント（デスクトップアプリ）のクレデンシャルをダウンロードして
`config/client_secret.json` として配置してください。

初回のみ、以下を手元で実行してブラウザ認証を行い `config/token.json` を発行します
（以降はrefresh_tokenで自動更新されるため人手は不要）。

```bash
python -c "from uploader.youtube_uploader import YouTubeUploader; YouTubeUploader()._get_credentials()"
```

### 3. 素材の配置

- `assets/fonts/NotoSansJP-Bold.ttf` … テキスト焼き込み用フォント
- `assets/bgm/short_bgm.mp3`, `assets/bgm/long_bgm.mp3` … 著作権フリーのBGM

これらが無い場合でもパイプラインは動作しますが、フォントはデフォルトフォントに、
BGMは無音にフォールバックします。

### 4. 起動

```bash
docker compose up airflow-init
docker compose up -d
```

http://localhost:8080 （初期ユーザー: admin / admin）から
`youtube_english_video_pipeline` DAGを有効化してください。

## ローカルでの単体実行（Airflowを使わない動作確認）

```bash
pip install -r requirements.txt
export PYTHONPATH=src:.   # "." はプロジェクトルート。config.xxx を import 可能にするため
python -m generators.phrase_generator      # フレーズ生成のみ確認
python -m video.short_video                # Short動画1本を生成
python -m video.long_video                 # Long動画1本を生成
```

## ディレクトリ構成

設計書.md の「Folder Structure」に準拠しています。主要モジュール:

| モジュール | 役割 |
| --- | --- |
| `src/generators/phrase_generator.py` | Geminiでフレーズ生成 & DB保存 |
| `src/generators/metadata_generator.py` | Geminiでタイトル/説明/タグ生成 |
| `src/planner/video_planner.py` | Short/Longの動画企画（使用フレーズ選定） |
| `src/tts/edge_tts.py` | Edge TTSで音声合成 |
| `src/media/image_downloader.py` | Pexelsで背景画像取得 |
| `src/media/subtitle_generator.py` | SRT字幕生成 |
| `src/media/thumbnail_builder.py` | サムネイル生成（Long専用） |
| `src/video/video_builder.py` | FFmpeg共通レンダリングロジック |
| `src/video/short_video.py` / `long_video.py` | Short/Longの生成フロー全体 |
| `src/uploader/youtube_uploader.py` | YouTubeへのアップロード |
| `dags/youtube_pipeline.py` | Airflow DAG本体 |

## 今後の拡張予定

設計書.mdの「Future Improvements」を参照してください
（TikTok/Instagram Reels展開、多言語対応、分析ダッシュボードなど）。
