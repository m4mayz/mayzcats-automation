from __future__ import annotations

from typing import Protocol

from .dedup import DuplicateDetector
from .models import Candidate, HistoryEntry


class JsonLLM(Protocol):
    def json(self, system: str, user: str) -> dict: ...


class CandidateGenerator:
    def __init__(self, llm: JsonLLM, *, max_candidates: int = 20) -> None:
        self.llm = llm
        self.max_candidates = min(max(1, max_candidates), 20)

    def generate(self, *, trend_context: str = "") -> list[Candidate]:
        evergreen_count = round(self.max_candidates * 0.8)
        trending_count = self.max_candidates - evergreen_count
        response = self.llm.json(
            """You are the MayzCats editorial planner. Return only a JSON object.
Create factual, family-friendly English YouTube Shorts topics about cats. Avoid
cheap clickbait, fabricated stories, graphic material, diagnosis, and treatment
instructions. A subject is what the video covers; an angle is the substantive
question or perspective. Wording variants are not distinct angles.""",
            f"""Generate at most {self.max_candidates} candidates: exactly
{evergreen_count} evergreen and {trending_count} trending when enough verified
trend context exists. Trend context:\n{trend_context or "No verified trend context."}
Return {{"candidates":[{{"subject":"...","angle":"...","kind":"evergreen|trending",
"rationale":"...","search_queries":["..."]}}]}}. Search queries must be useful
for both factual research and real cat visuals.""",
        )
        raw_candidates = response.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ValueError("Topic response must contain a candidates array")
        valid: list[Candidate] = []
        for raw in raw_candidates:
            kind = str(raw.get("kind", "")).strip().lower()
            subject = str(raw.get("subject", "")).strip()
            angle = str(raw.get("angle", "")).strip()
            if kind not in {"evergreen", "trending"} or not subject or not angle:
                continue
            valid.append(
                Candidate(
                    subject=subject,
                    angle=angle,
                    kind=kind,
                    rationale=str(raw.get("rationale", "")).strip(),
                    search_queries=[
                        str(item).strip()
                        for item in raw.get("search_queries", [])
                        if str(item).strip()
                    ][:4],
                )
            )
        evergreen = [item for item in valid if item.kind == "evergreen"]
        trending = [item for item in valid if item.kind == "trending"]
        result = [*evergreen[:evergreen_count], *trending[:trending_count]]
        if len(result) < self.max_candidates:
            selected = {id(item) for item in result}
            result.extend(item for item in valid if id(item) not in selected)
            result = result[: self.max_candidates]
        if not result:
            raise ValueError("The model returned no valid topic candidates")
        return result

    @staticmethod
    def choose_unused(
        candidates: list[Candidate],
        history: list[HistoryEntry],
        detector: DuplicateDetector,
    ) -> Candidate:
        for candidate in candidates:
            if detector.find_duplicate(candidate, history) is None:
                return candidate
        raise RuntimeError("All generated candidates duplicate a recent subject and angle")
