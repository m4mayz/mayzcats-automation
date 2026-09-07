from __future__ import annotations

from .models import MediaAsset, Scene


def plan_scenes(*, duration: float, beats: list[str], assets: list[MediaAsset]) -> list[Scene]:
    if duration <= 0:
        raise ValueError("Narration duration must be positive")
    if not beats or not assets:
        raise ValueError("At least one beat and one asset are required")
    count = min(len(beats), len(assets))
    beats = beats[:count]
    assets = assets[:count]
    if count == 1:
        return [Scene(assets[0], 0.0, duration, 0)]

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
    return scenes
