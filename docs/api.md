# 外部API利用まとめ

| API | 用途 | 認証方式 | 備考 |
|---|---|---|---|
| Gemini API | フレーズ生成・メタデータ生成 | APIキー (GEMINI_API_KEY) | response_mime_type=application/json でJSON強制 |
| Edge TTS | 音声合成 | 不要（無料） | edge-tts ライブラリ経由、非同期API |
| Pexels API | 背景画像取得 | APIキー (PEXELS_API_KEY) | 失敗時は単色画像にフォールバック |
| YouTube Data API v3 | 動画・サムネイルアップロード | OAuth2 (初回のみ人手認証) | scope: youtube.upload, youtube |
