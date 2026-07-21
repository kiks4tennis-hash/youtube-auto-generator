"""
YouTube Data API v3 を使って動画をアップロードするモジュール。
OAuth2認証情報は事前に `python -m uploader.youtube_uploader --auth` 等で
token.json を発行しておく前提（初回のみ人手が必要。以後は自動更新される）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config.settings import settings
from database.repository import Repository
from utils.logger import get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


@dataclass
class UploadRequest:
    video_id_db: int
    file_path: str
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    category_id: str = "27"  # Education
    thumbnail_path: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    visibility: str = "private"


class YouTubeUploader:
    def __init__(self):
        self.repository = Repository()

    # -----------------------------------------------------------
    # 認証
    # -----------------------------------------------------------

    def _get_credentials(self) -> Credentials:
        token_path = Path(settings.youtube.token_file)
        creds: Optional[Credentials] = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.youtube.client_secrets_file, SCOPES
                )
                # サーバー環境ではrun_console、ローカルではrun_local_serverを使う
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def _client(self):
        creds = self._get_credentials()
        return build("youtube", "v3", credentials=creds)

    # -----------------------------------------------------------
    # アップロード
    # -----------------------------------------------------------

    def upload(self, req: UploadRequest) -> str:
        youtube = self._client()

        status: dict = {"selfDeclaredMadeForKids": False}
        if req.scheduled_at:
            status["privacyStatus"] = "private"
            status["publishAt"] = req.scheduled_at.astimezone().isoformat()
        else:
            status["privacyStatus"] = req.visibility

        body = {
            "snippet": {
                "title": req.title,
                "description": req.description,
                "tags": req.tags,
                "categoryId": req.category_id,
            },
            "status": status,
        }

        media = MediaFileUpload(req.file_path, chunksize=-1, resumable=True, mimetype="video/mp4")

        logger.info(f"Uploading video '{req.title}' ({req.file_path}) to YouTube...")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status_progress, response = request.next_chunk()
            if status_progress:
                logger.info(f"Upload progress: {int(status_progress.progress() * 100)}%")

        youtube_video_id = response["id"]
        logger.info(f"Upload complete. YouTube video id = {youtube_video_id}")

        if req.thumbnail_path and os.path.exists(req.thumbnail_path):
            youtube.thumbnails().set(
                videoId=youtube_video_id,
                media_body=MediaFileUpload(req.thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            logger.info("Custom thumbnail uploaded.")

        self.repository.update_video_upload_result(req.video_id_db, youtube_video_id, uploaded=True)
        return youtube_video_id


def upload_video(video_result: dict, scheduled_at: Optional[str] = None) -> str:
    """
    Airflowタスクから呼ばれるエントリポイント。
    video_result は short_video.build_short_video() / long_video.build_long_video() の戻り値。
    """
    uploader = YouTubeUploader()
    req = UploadRequest(
        video_id_db=video_result["video_id"],
        file_path=video_result["file_path"],
        title=video_result["title"],
        description=video_result["description"],
        tags=video_result.get("tags", []),
        thumbnail_path=video_result.get("thumbnail_path"),
        scheduled_at=datetime.fromisoformat(scheduled_at) if scheduled_at else None,
        visibility=settings.youtube.default_visibility,
    )
    return uploader.upload(req)
