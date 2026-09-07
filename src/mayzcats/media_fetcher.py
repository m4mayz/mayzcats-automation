from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

import httpx

from .models import MediaAsset

PEXELS_LICENSE = "https://www.pexels.com/license/"
PIXABAY_LICENSE = "https://pixabay.com/service/terms/"


def normalize_pexels_videos(data: dict[str, Any]) -> list[MediaAsset]:
    result: list[MediaAsset] = []
    for video in data.get("videos", []):
        files = [item for item in video.get("video_files", []) if item.get("link")]
        if not files:
            continue
        best = max(
            files,
            key=lambda item: (
                int(item.get("height", 0)) > int(item.get("width", 0)),
                int(item.get("width", 0)) * int(item.get("height", 0)),
            ),
        )
        width = int(best.get("width") or 0)
        height = int(best.get("height") or 0)
        result.append(
            MediaAsset(
                asset_id=f"pexels-video-{video.get('id')}",
                provider="pexels",
                kind="video",
                download_url=str(best["link"]),
                source_url=str(video.get("url", "")),
                creator=str((video.get("user") or {}).get("name", "Unknown")),
                license_name="Pexels License",
                license_url=PEXELS_LICENSE,
                width=width,
                height=height,
                duration=float(video.get("duration") or 0),
                score=_media_score(width, height, int(video.get("duration") or 0)),
            )
        )
    return result


def normalize_pexels_photos(data: dict[str, Any]) -> list[MediaAsset]:
    result: list[MediaAsset] = []
    for photo in data.get("photos", []):
        source = photo.get("src") or {}
        download_url = source.get("portrait") or source.get("large2x") or source.get("original")
        if not download_url:
            continue
        width = int(photo.get("width") or 0)
        height = int(photo.get("height") or 0)
        result.append(
            MediaAsset(
                asset_id=f"pexels-photo-{photo.get('id')}",
                provider="pexels",
                kind="image",
                download_url=str(download_url),
                source_url=str(photo.get("url", "")),
                creator=str(photo.get("photographer", "Unknown")),
                license_name="Pexels License",
                license_url=PEXELS_LICENSE,
                width=width,
                height=height,
                duration=None,
                score=_media_score(width, height, 0),
            )
        )
    return result


def normalize_pixabay_videos(data: dict[str, Any]) -> list[MediaAsset]:
    result: list[MediaAsset] = []
    for video in data.get("hits", []):
        variants = [item for item in (video.get("videos") or {}).values() if item.get("url")]
        if not variants:
            continue
        best = max(
            variants,
            key=lambda item: (
                int(item.get("height", 0)) > int(item.get("width", 0)),
                int(item.get("width", 0)) * int(item.get("height", 0)),
            ),
        )
        width = int(best.get("width") or 0)
        height = int(best.get("height") or 0)
        result.append(
            MediaAsset(
                asset_id=f"pixabay-video-{video.get('id')}",
                provider="pixabay",
                kind="video",
                download_url=str(best["url"]),
                source_url=str(video.get("pageURL", "")),
                creator=str(video.get("user", "Unknown")),
                license_name="Pixabay Content License",
                license_url=PIXABAY_LICENSE,
                width=width,
                height=height,
                duration=float(video.get("duration") or 0),
                score=_media_score(width, height, int(video.get("duration") or 0)),
            )
        )
    return result


def normalize_pixabay_images(data: dict[str, Any]) -> list[MediaAsset]:
    result: list[MediaAsset] = []
    for image in data.get("hits", []):
        download_url = image.get("largeImageURL") or image.get("webformatURL")
        if not download_url:
            continue
        width = int(image.get("imageWidth") or image.get("webformatWidth") or 0)
        height = int(image.get("imageHeight") or image.get("webformatHeight") or 0)
        result.append(
            MediaAsset(
                asset_id=f"pixabay-image-{image.get('id')}",
                provider="pixabay",
                kind="image",
                download_url=str(download_url),
                source_url=str(image.get("pageURL", "")),
                creator=str(image.get("user", "Unknown")),
                license_name="Pixabay Content License",
                license_url=PIXABAY_LICENSE,
                width=width,
                height=height,
                duration=None,
                score=_media_score(width, height, 0),
            )
        )
    return result


def _media_score(width: int, height: int, duration: int) -> float:
    portrait_bonus = 2.0 if height > width else 0.0
    resolution = min(width * height / (1080 * 1920), 2.0)
    duration_bonus = 0.5 if 3 <= duration <= 30 else 0.0
    return portrait_bonus + resolution + duration_bonus


def select_assets(assets: list[MediaAsset], *, count: int) -> list[MediaAsset]:
    if count < 1:
        return []
    unique: dict[str, MediaAsset] = {}
    for asset in assets:
        unique.setdefault(asset.asset_id, asset)
    ranked = sorted(
        unique.values(),
        key=lambda item: (
            item.kind == "video",
            item.score,
            item.height > item.width,
            item.width * item.height,
        ),
        reverse=True,
    )
    if not ranked:
        raise RuntimeError("No usable Pexels or Pixabay assets were found")
    result = ranked[:count]
    index = 0
    while len(result) < count:
        result.append(ranked[index % len(ranked)])
        index += 1
    return result


class MediaProvider(Protocol):
    def search_videos(self, query: str) -> list[MediaAsset]: ...

    def search_images(self, query: str) -> list[MediaAsset]: ...


class PexelsProvider:
    def __init__(self, api_key: str, *, http: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=60.0, follow_redirects=True)

    def search_videos(self, query: str) -> list[MediaAsset]:
        response = self.http.get(
            "https://api.pexels.com/v1/videos/search",
            headers={"Authorization": self.api_key},
            params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 12},
        )
        response.raise_for_status()
        return normalize_pexels_videos(response.json())

    def search_images(self, query: str) -> list[MediaAsset]:
        response = self.http.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": self.api_key},
            params={"query": query, "orientation": "portrait", "size": "large", "per_page": 12},
        )
        response.raise_for_status()
        return normalize_pexels_photos(response.json())


class PixabayProvider:
    def __init__(self, api_key: str, *, http: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=60.0, follow_redirects=True)

    def search_videos(self, query: str) -> list[MediaAsset]:
        response = self.http.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": self.api_key,
                "q": query[:100],
                "video_type": "film",
                "category": "animals",
                "safesearch": "true",
                "per_page": 12,
            },
        )
        response.raise_for_status()
        return normalize_pixabay_videos(response.json())

    def search_images(self, query: str) -> list[MediaAsset]:
        response = self.http.get(
            "https://pixabay.com/api/",
            params={
                "key": self.api_key,
                "q": query[:100],
                "image_type": "photo",
                "orientation": "vertical",
                "category": "animals",
                "safesearch": "true",
                "per_page": 12,
            },
        )
        response.raise_for_status()
        return normalize_pixabay_images(response.json())


class MediaFetcher:
    def __init__(
        self,
        providers: list[MediaProvider],
        *,
        http: httpx.Client | None = None,
        max_download_bytes: int = 150_000_000,
    ) -> None:
        self.providers = providers
        self.http = http or httpx.Client(timeout=180.0, follow_redirects=True)
        self.max_download_bytes = max_download_bytes

    def find(self, search_terms: list[str], *, count: int, minimum: int = 4) -> list[MediaAsset]:
        videos: list[MediaAsset] = []
        for term in search_terms[:6]:
            for provider in self.providers:
                videos.extend(provider.search_videos(term))
            if len({asset.asset_id for asset in videos}) >= count:
                break
        assets = videos
        if len({asset.asset_id for asset in assets}) < minimum:
            images: list[MediaAsset] = []
            for term in search_terms[:4]:
                for provider in self.providers:
                    images.extend(provider.search_images(term))
                if len({asset.asset_id for asset in [*assets, *images]}) >= count:
                    break
            assets = [*assets, *images]
        if len({asset.asset_id for asset in assets}) < minimum:
            raise RuntimeError(
                f"Only {len({asset.asset_id for asset in assets})} unique media assets found; "
                f"at least {minimum} are required"
            )
        return select_assets(assets, count=count)

    def download(self, asset: MediaAsset, directory: Path) -> MediaAsset:
        directory.mkdir(parents=True, exist_ok=True)
        extension = ".mp4" if asset.kind == "video" else ".jpg"
        digest = hashlib.sha256(asset.download_url.encode()).hexdigest()[:12]
        destination = directory / f"{asset.provider}-{digest}{extension}"
        if not destination.exists():
            self._download_url(asset.download_url, destination)
        asset.local_path = destination
        return asset

    def _download_url(self, url: str, destination: Path) -> None:
        total = 0
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with self.http.stream("GET", url) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > self.max_download_bytes:
                            raise RuntimeError("Media download exceeded configured size limit")
                        handle.write(chunk)
            if total == 0:
                raise RuntimeError("Media download returned an empty file")
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
