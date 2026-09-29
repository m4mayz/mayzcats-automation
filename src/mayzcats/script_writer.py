from __future__ import annotations

import re
from typing import Any, Protocol

from .llm import as_list, as_text
from .models import Candidate, ResearchBrief, ScriptPackage

STATIC_TAGS = ["cats", "cat lovers", "pets", "cute animals"]
FORBIDDEN_CLICKBAIT = (
    "you won't believe",
    "this will shock you",
    "shocking truth",
)
# The writer prompt names the structure, so models sometimes echo those names back as
# headings inside the narration. Nothing here is meant to be spoken.
SECTION_LABEL = re.compile(
    r"^[\s*#>\-]*(?:hook|context|main explanation|explanation|body|surprising detail|"
    r"closing question|closing|intro|outro)\s*[:\-–—]\s*",
    re.IGNORECASE | re.MULTILINE,
)


class JsonLLM(Protocol):
    def json(self, system: str, user: str) -> dict[str, Any]: ...


class ScriptWriter:
    def __init__(self, llm: JsonLLM) -> None:
        self.llm = llm

    def write(self, candidate: Candidate, brief: ResearchBrief) -> ScriptPackage:
        evidence = "\n".join(f"- {claim}" for claim in brief.claims)
        response = self.llm.json(
            """Write factual English narration for MayzCats. Structure: hook,
context, main explanation, surprising detail, closing question. Target about 45
seconds. Keep it family-friendly, warm, curious, slightly playful, and free of
cheap clickbait. Playful personification must read as humor rather than fact.
Use only supplied claims. Return JSON only. script is one spoken paragraph: no
section names, headings or labels, because every character of it is read aloud.
hashtags, tags, search_terms and beats must be JSON arrays, never one string.""",
            f"""Subject: {candidate.subject}\nAngle: {candidate.angle}\nSupported claims:\n{evidence}
Medical: {brief.medical}\nReturn keys script,
title, description, hashtags, tags, hook_text, hook_keyword, search_terms, beats,
mood, medical. Description is 1-2 sentences and must not expose internal source
traces. Hashtags include #shorts plus 2-4 relevant tags. Beats are ordered visual
segments. hook_keyword must occur exactly in hook_text.""",
        )
        return package_from_response(response, medical=brief.medical)

    def revise_for_duration(
        self,
        package: ScriptPackage,
        actual_duration: float,
        *,
        minimum: float = 35.0,
        maximum: float = 55.0,
    ) -> ScriptPackage:
        direction = "expand" if actual_duration < minimum else "shorten"
        response = self.llm.json(
            "Revise narration length without adding any new factual claim. Return JSON only.",
            f"""The narration measured {actual_duration:.2f} seconds. {direction.title()} it so
the same voice should land between {minimum:.0f} and {maximum:.0f} seconds. Preserve the
meaning, grounded facts, tone, metadata, hook, and closing question. Existing
package:\n{package.to_dict()}""",
        )
        return package_from_response(response, medical=package.medical)


def package_from_response(data: dict[str, Any], *, medical: bool) -> ScriptPackage:
    script = SECTION_LABEL.sub("", as_text(data.get("script"))).strip()
    title = _clean_text(SECTION_LABEL.sub("", as_text(data.get("title"))).strip())[:100]
    description = _clean_text(SECTION_LABEL.sub("", as_text(data.get("description"))).strip())
    if not script or not title or not description:
        raise ValueError("Script response is missing script, title, or description")
    lowered = f"{title} {script}".lower()
    if any(phrase in lowered for phrase in FORBIDDEN_CLICKBAIT):
        raise ValueError("Script response contains forbidden clickbait wording")

    hashtags = []
    # Hashtags are single tokens, so a string answer splits on spaces too.
    for value in ["#shorts", *as_list(data.get("hashtags"), separator=r"[\s,]+")]:
        tag = "#" + re.sub(r"[^A-Za-z0-9_]", "", str(value).lstrip("#"))
        if tag != "#" and tag.lower() not in {item.lower() for item in hashtags}:
            hashtags.append(tag)
    hashtags = hashtags[:5]
    if len(hashtags) < 3:
        hashtags.extend(tag for tag in ["#cats", "#catfacts"] if tag not in hashtags)

    tags = []
    for value in [*STATIC_TAGS, *as_list(data.get("tags"))]:
        tag = _clean_text(str(value).strip()).lower()
        if tag and tag not in tags:
            tags.append(tag)
    hook_text = _clean_text(SECTION_LABEL.sub("", as_text(data.get("hook_text"))).strip())
    hook_keyword = _clean_text(as_text(data.get("hook_keyword")).strip())
    if not hook_text or not hook_keyword or hook_keyword.lower() not in hook_text.lower():
        raise ValueError("hook_keyword must occur in hook_text")

    beats = [_clean_text(str(item).strip()) for item in as_list(data.get("beats"))
             if str(item).strip()]
    search_terms = [
        _clean_text(str(item).strip()) for item in as_list(data.get("search_terms"))
        if str(item).strip()
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
        mood=_clean_text(as_text(data.get("mood") or "warm playful").strip()),
        medical=medical,
    )


def _clean_text(text: str) -> str:
    # Remove control characters and emoji-style non-BMP symbols from public metadata.
    return "".join(char for char in text if char in "\n\t" or 32 <= ord(char) <= 0xFFFF).strip()
