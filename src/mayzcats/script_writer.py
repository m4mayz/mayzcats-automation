from __future__ import annotations

import re
from typing import Any, Protocol

from .models import Candidate, ResearchBrief, ScriptPackage

STATIC_TAGS = ["cats", "cat lovers", "pets", "cute animals"]
FORBIDDEN_CLICKBAIT = (
    "you won't believe",
    "this will shock you",
    "shocking truth",
)


class JsonLLM(Protocol):
    def json(self, system: str, user: str) -> dict[str, Any]: ...


class ScriptWriter:
    def __init__(self, llm: JsonLLM) -> None:
        self.llm = llm

    def write(self, candidate: Candidate, brief: ResearchBrief) -> ScriptPackage:
        evidence = "\n".join(f"- {claim}" for claim in brief.claims)
        disclaimer = brief.vet_disclaimer or "Not applicable"
        response = self.llm.json(
            """Write factual English narration for MayzCats. Structure: hook,
context, main explanation, surprising detail, closing question. Target about 45
seconds. Keep it family-friendly, warm, curious, slightly playful, and free of
cheap clickbait. Playful personification must read as humor rather than fact.
Use only supplied claims. Return JSON only.""",
            f"""Subject: {candidate.subject}\nAngle: {candidate.angle}\nSupported claims:\n{evidence}
Medical: {brief.medical}\nRequired disclaimer: {disclaimer}\nReturn keys script,
title, description, hashtags, tags, hook_text, hook_keyword, search_terms, beats,
mood, medical. Description is 1-2 sentences and must not expose internal source
traces. Hashtags include #shorts plus 2-4 relevant tags. Beats are ordered visual
segments. hook_keyword must occur exactly in hook_text.""",
        )
        package = package_from_response(response, medical=brief.medical)
        return ensure_vet_disclaimer(package, brief.vet_disclaimer)

    def revise_for_duration(
        self,
        package: ScriptPackage,
        actual_duration: float,
        *,
        minimum: float = 35.0,
        maximum: float = 55.0,
        required_disclaimer: str | None = None,
    ) -> ScriptPackage:
        direction = "expand" if actual_duration < minimum else "shorten"
        response = self.llm.json(
            "Revise narration length without adding any new factual claim. Return JSON only.",
            f"""The narration measured {actual_duration:.2f} seconds. {direction.title()} it so
the same voice should land between {minimum:.0f} and {maximum:.0f} seconds. Preserve the
meaning, grounded facts, tone, metadata, hook, closing question, and medical
disclaimer. Existing package:\n{package.to_dict()}""",
        )
        revised = package_from_response(response, medical=package.medical)
        return ensure_vet_disclaimer(revised, required_disclaimer)


def ensure_vet_disclaimer(
    package: ScriptPackage, required_disclaimer: str | None
) -> ScriptPackage:
    disclaimer = str(required_disclaimer or "").strip()
    if package.medical and disclaimer and disclaimer.casefold() not in package.script.casefold():
        package.script = f"{package.script.rstrip()} {disclaimer}"
    return package


def package_from_response(data: dict[str, Any], *, medical: bool) -> ScriptPackage:
    script = str(data.get("script", "")).strip()
    title = _clean_text(str(data.get("title", "")).strip())[:100]
    description = _clean_text(str(data.get("description", "")).strip())
    if not script or not title or not description:
        raise ValueError("Script response is missing script, title, or description")
    lowered = f"{title} {script}".lower()
    if any(phrase in lowered for phrase in FORBIDDEN_CLICKBAIT):
        raise ValueError("Script response contains forbidden clickbait wording")

    hashtags = []
    for value in ["#shorts", *data.get("hashtags", [])]:
        tag = "#" + re.sub(r"[^A-Za-z0-9_]", "", str(value).lstrip("#"))
        if tag != "#" and tag.lower() not in {item.lower() for item in hashtags}:
            hashtags.append(tag)
    hashtags = hashtags[:5]
    if len(hashtags) < 3:
        hashtags.extend(tag for tag in ["#cats", "#catfacts"] if tag not in hashtags)

    tags = []
    for value in [*STATIC_TAGS, *data.get("tags", [])]:
        tag = _clean_text(str(value).strip()).lower()
        if tag and tag not in tags:
            tags.append(tag)
    hook_text = _clean_text(str(data.get("hook_text", "")).strip())
    hook_keyword = _clean_text(str(data.get("hook_keyword", "")).strip())
    if not hook_text or not hook_keyword or hook_keyword.lower() not in hook_text.lower():
        raise ValueError("hook_keyword must occur in hook_text")

    beats = [_clean_text(str(item).strip()) for item in data.get("beats", []) if str(item).strip()]
    search_terms = [
        _clean_text(str(item).strip()) for item in data.get("search_terms", []) if str(item).strip()
    ]
    if not beats or not search_terms:
        raise ValueError("Script response requires beats and search_terms")
    return ScriptPackage(
        script=script,
        title=title,
        description=description,
        hashtags=hashtags,
        tags=tags[:12],
        hook_text=hook_text,
        hook_keyword=hook_keyword,
        search_terms=search_terms[:8],
        beats=beats[:12],
        mood=_clean_text(str(data.get("mood", "warm playful")).strip()),
        medical=medical,
    )


def _clean_text(text: str) -> str:
    # Remove control characters and emoji-style non-BMP symbols from public metadata.
    return "".join(char for char in text if char in "\n\t" or 32 <= ord(char) <= 0xFFFF).strip()
