from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

VOICE_ID = "cgSgspJ2msm6clMCkdW9"


def safe_error(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"message": response.text[:300]}
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    if isinstance(detail, dict):
        allowed = ("type", "code", "status", "message")
        return {name: detail[name] for name in allowed if name in detail}
    return {"message": str(detail)[:300]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely diagnose MayzCats ElevenLabs keys")
    parser.add_argument("env_file", nargs="?", type=Path, default=Path(".env"))
    parser.add_argument("--voice-id", default=VOICE_ID)
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    keys = [
        value.strip()
        for value in str(values.get("ELEVENLABS_API_KEYS") or "").split(",")
        if value.strip()
    ]
    if not keys:
        raise SystemExit("ELEVENLABS_API_KEYS is empty")

    client = httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0))
    results: list[dict[str, Any]] = []
    for index, key in enumerate(keys, start=1):
        headers = {"xi-api-key": key}
        subscription = client.get(
            "https://api.elevenlabs.io/v1/user/subscription", headers=headers
        )
        subscription_result: dict[str, Any] = {"http": subscription.status_code}
        if subscription.is_success:
            data = subscription.json()
            subscription_result.update(
                {
                    "tier": data.get("tier"),
                    "used": data.get("character_count"),
                    "limit": data.get("character_limit"),
                    "status": data.get("status"),
                }
            )
        else:
            subscription_result["error"] = safe_error(subscription)

        voice = client.get(
            f"https://api.elevenlabs.io/v1/voices/{args.voice_id}", headers=headers
        )
        voice_result: dict[str, Any] = {"http": voice.status_code}
        if voice.is_success:
            data = voice.json()
            voice_result.update({"name": data.get("name"), "category": data.get("category")})
        else:
            voice_result["error"] = safe_error(voice)

        tts = client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{args.voice_id}/with-timestamps",
            params={"output_format": "mp3_44100_128"},
            headers={**headers, "Content-Type": "application/json"},
            json={
                "text": "Hi",
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "use_speaker_boost": True,
                    "speed": 1.08,
                },
            },
        )
        tts_result: dict[str, Any] = {"http": tts.status_code}
        if tts.is_success:
            data = tts.json()
            tts_result["audio_returned"] = bool(data.get("audio_base64"))
        else:
            tts_result["error"] = safe_error(tts)

        results.append(
            {
                "key_index": index,
                "subscription": subscription_result,
                "voice": voice_result,
                "tts_two_characters": tts_result,
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
