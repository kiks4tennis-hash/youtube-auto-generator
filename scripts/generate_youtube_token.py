"""
YouTube Data API の初回OAuth2認証を行うための、ホストマシン専用スクリプト。

Airflowコンテナの中にはブラウザが無いため、`YouTubeUploader._get_credentials()`を
コンテナ内でいきなり実行すると `webbrowser.Error: could not locate runnable browser`
になります。このスクリプトを **ブラウザが使えるホストマシン側(Windows/Mac/Linuxの
普段使いの環境)** で1回だけ実行し、生成された token.json を config/token.json に
配置してください。以後はrefresh_tokenにより自動更新されるため、コンテナ内で
ブラウザを開く必要は二度とありません。

使い方 (プロジェクトルートで実行):
    pip install google-auth-oauthlib google-api-python-client google-auth
    python scripts/generate_youtube_token.py

実行するとブラウザが自動で開き、Googleアカウントでのログイン・権限許可を求められます。
許可すると `config/token.json` が生成されます。
"""

from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRETS_FILE = PROJECT_ROOT / "config" / "client_secret.json"
TOKEN_FILE = PROJECT_ROOT / "config" / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def main() -> None:
    if not CLIENT_SECRETS_FILE.exists():
        print(f"ERROR: {CLIENT_SECRETS_FILE} が見つかりません。")
        print("Google Cloud Console で発行したOAuth2クライアント(デスクトップアプリ)の")
        print("JSONファイルを config/client_secret.json として配置してください。")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"認証に成功しました。トークンを保存しました -> {TOKEN_FILE}")
    print("このファイルはAirflowコンテナの config/ にもマウントされているため、")
    print("そのままDAGからのアップロードで再利用されます（以後ブラウザ操作は不要です）。")


if __name__ == "__main__":
    main()
