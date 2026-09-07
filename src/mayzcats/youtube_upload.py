from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .models import PostPayload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}


SUPPORTED_PRIVACY_STATUSES = {"private", "public"}


def build_video_body(payload: PostPayload) -> dict[str, Any]:
    if payload.privacy not in SUPPORTED_PRIVACY_STATUSES:
        raise ValueError(
            "YouTube privacy must be one of: " + ", ".join(sorted(SUPPORTED_PRIVACY_STATUSES))
        )
    if payload.category_id != "15":
        raise ValueError("MayzCats V1 category must be Pets & Animals (15)")
    if payload.made_for_kids:
        raise ValueError("MayzCats V1 made-for-kids setting must be false")
    return {
        "snippet": {
            "title": payload.title,
            "description": payload.description,
            "tags": payload.tags,
            "categoryId": "15",
        },
        "status": {
            "privacyStatus": payload.privacy,
            "selfDeclaredMadeForKids": False,
        },
    }


def load_credentials(
    client_secret: Path,
    token_file: Path,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow

    credentials = None
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        if not client_secret.exists():
            raise FileNotFoundError(f"YouTube OAuth client secret not found: {client_secret}")
        flow = Flow.from_client_secrets_file(
            str(client_secret), scopes=SCOPES, redirect_uri="http://localhost:8080/"
        )
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        print_fn("Open this URL, approve the MayzCats channel, then copy the full localhost URL")
        print_fn(authorization_url)
        returned_url = input_fn("Paste the full redirected localhost URL: ").strip()
        query = parse_qs(urlsplit(returned_url).query)
        if query.get("state", [""])[0] != state:
            raise RuntimeError("OAuth state did not match; authorization was not accepted")
        if query.get("error"):
            raise RuntimeError(f"YouTube authorization failed: {query['error'][0]}")
        code = query.get("code", [""])[0]
        if not code:
            raise RuntimeError("The redirected URL did not include an authorization code")
        flow.fetch_token(code=code)
        credentials = flow.credentials
    token_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = token_file.with_suffix(".json.tmp")
    temporary.write_text(credentials.to_json(), encoding="utf-8")
    temporary.replace(token_file)
    return credentials


class YoutubeUploader:
    def __init__(
        self,
        client_secret: Path,
        token_file: Path,
        *,
        chunk_size: int = 8 * 1024 * 1024,
        max_retries: int = 5,
        service: Any | None = None,
    ) -> None:
        self.client_secret = Path(client_secret)
        self.token_file = Path(token_file)
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.service = service

    def _service(self):
        if self.service is None:
            from googleapiclient.discovery import build

            credentials = load_credentials(self.client_secret, self.token_file)
            self.service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        return self.service

    def upload(self, video_path: Path, payload: PostPayload) -> str:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        body = build_video_body(payload)
        media = MediaFileUpload(
            str(video_path), chunksize=self.chunk_size, resumable=True, mimetype="video/mp4"
        )
        request = (
            self._service()
            .videos()
            .insert(
                part="snippet,status",
                body=body,
                media_body=media,
                notifySubscribers=False,
            )
        )
        retries = 0
        while True:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f"[YouTube] Upload {int(status.progress() * 100)}%")
                if response is None:
                    continue
                video_id = response.get("id")
                if not video_id:
                    raise RuntimeError("YouTube upload response did not include a video ID")
                return str(video_id)
            except HttpError as exc:
                status_code = int(getattr(exc.resp, "status", 0))
                if status_code not in RETRIABLE_STATUS_CODES or retries >= self.max_retries:
                    raise
            except (OSError, TimeoutError):
                if retries >= self.max_retries:
                    raise
            retries += 1
            time.sleep(random.uniform(0, min(60, 2**retries)))


def payload_from_file(path: Path) -> PostPayload:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PostPayload(
        title=data["title"],
        description=data["description"],
        tags=list(data["tags"]),
        category_id=data.get("category_id", "15"),
        privacy=data.get("privacy", "private"),
        made_for_kids=bool(data.get("made_for_kids", False)),
    )
