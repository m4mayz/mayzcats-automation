from __future__ import annotations

from .models import MediaAsset, Scene


def plan_scenes(*, duration: float, beats: list[str], assets: list[MediaAsset]) -> list[Scene]:
    if duration <= 0:
        raise ValueError("Narration duration must be positive")
    if not beats or not assets:
        raise ValueError("At least one beat and one asset are required")
    pool = assets
    count = min(len(beats), len(assets))
    beats = beats[:count]
    assets = assets[:count]
    if count == 1:
        scenes = [Scene(assets[0], 0.0, duration, 0)]
    else:
        opening = min(1.8, max(1.0, duration * 0.12))
        remaining = duration - opening
        weights = [max(1, len(beat.split())) for beat in beats[1:]]
        total_weight = sum(weights)
        cursor = opening
        scenes = [Scene(assets[0], 0.0, opening, 0)]
        for index, (asset, weight) in enumerate(zip(assets[1:], weights, strict=True), start=1):
            end = duration if index == count - 1 else cursor + remaining * weight / total_weight
            scenes.append(Scene(asset, cursor, end, index))
            cursor = end
    return _interleave_short_videos(scenes, pool)


def _interleave_short_videos(scenes: list[Scene], assets: list[MediaAsset]) -> list[Scene]:
    unique = list({asset.asset_id: asset for asset in assets}.values())
    if len(unique) < 2:
        return scenes

    result: list[Scene] = []
    previous = ""
    for scene in scenes:
        remaining = scene.end - scene.start
        cursor = scene.start
        index = next(i for i, asset in enumerate(unique) if asset.asset_id == scene.asset.asset_id)
        while remaining > 0.001:
            asset = unique[index % len(unique)]
            if asset.asset_id == previous:
                index += 1
                asset = unique[index % len(unique)]
            available = asset.duration if asset.kind == "video" and asset.duration else remaining
            chunk = min(remaining, max(0.1, available))
            end = min(scene.end, cursor + chunk)
            result.append(Scene(asset, cursor, end, scene.beat_index))
            previous = asset.asset_id
            remaining -= end - cursor
            cursor = end
            index += 1
    return result
