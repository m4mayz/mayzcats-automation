from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mayzcats.dedup import DuplicateDetector
from mayzcats.llm import extract_json_object
from mayzcats.models import Candidate, HistoryEntry, ResearchBrief, ScriptPackage, SourceTrace
from mayzcats.research import (
    InsufficientResearchError,
    normalize_sources,
    validate_source_numbers,
)
from mayzcats.script_writer import ScriptWriter
from mayzcats.topic_engine import CandidateGenerator


class FakeEmbedder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return self.payload


def test_extract_json_accepts_fenced_response_and_rejects_trailing_garbage() -> None:
    assert extract_json_object('```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(ValueError, match="JSON object"):
        extract_json_object("answer: none")


def test_duplicate_requires_similar_subject_and_similar_angle() -> None:
    vectors = {
        "cats kneading blankets": [1.0, 0.0],
        "why they do it": [0.0, 1.0],
        "cats making biscuits on blankets": [0.99, 0.01],
        "the emotional reason behind kneading": [0.02, 0.98],
        "cats kneading their owners": [0.98, 0.02],
        "how owners should respond": [0.8, 0.6],
    }
    history = [
        HistoryEntry(
            "cats kneading blankets",
            "why they do it",
            datetime(2026, 9, 1, tzinfo=UTC),
            "vid1",
        )
    ]
    detector = DuplicateDetector(FakeEmbedder(vectors), 0.90, 0.90)

    wording_variant = Candidate(
        "cats making biscuits on blankets",
        "the emotional reason behind kneading",
        "evergreen",
    )
    different_angle = Candidate(
        "cats kneading their owners", "how owners should respond", "evergreen"
    )

    assert detector.find_duplicate(wording_variant, history) is history[0]
    assert detector.find_duplicate(different_angle, history) is None


def test_candidate_generator_caps_results_and_keeps_valid_mix() -> None:
    candidates = [
        {
            "subject": f"subject {i}",
            "angle": f"angle {i}",
            "kind": "evergreen" if i < 16 else "trending",
            "rationale": "useful",
            "search_queries": [f"cat query {i}"],
        }
        for i in range(25)
    ]
    generator = CandidateGenerator(FakeLLM({"candidates": candidates}), max_candidates=20)

    result = generator.generate(trend_context="current cat conversations")

    assert len(result) == 20
    assert sum(item.kind == "evergreen" for item in result) == 16
    assert sum(item.kind == "trending" for item in result) == 4


def test_candidate_generator_enforces_mix_even_when_model_orders_trends_first() -> None:
    candidates = [
        {
            "subject": f"trend {i}",
            "angle": f"trend angle {i}",
            "kind": "trending",
            "search_queries": ["cats"],
        }
        for i in range(20)
    ] + [
        {
            "subject": f"evergreen {i}",
            "angle": f"evergreen angle {i}",
            "kind": "evergreen",
            "search_queries": ["cats"],
        }
        for i in range(20)
    ]

    result = CandidateGenerator(FakeLLM({"candidates": candidates}), max_candidates=20).generate()

    assert sum(item.kind == "evergreen" for item in result) == 16
    assert sum(item.kind == "trending" for item in result) == 4


def test_source_normalization_deduplicates_urls_and_enforces_minimum() -> None:
    raw = [
        {"title": "A", "url": "https://example.com/a", "content": "fact a", "score": 0.9},
        {"title": "A duplicate", "url": "https://example.com/a", "content": "fact", "score": 0.8},
        {"title": "B", "url": "https://vet.example/b", "content": "fact b", "score": 0.7},
        {"title": "C", "url": "https://journal.example/c", "content": "fact c", "score": 0.6},
    ]

    sources = normalize_sources(raw, minimum=3)

    assert [source.title for source in sources] == ["A", "B", "C"]
    with pytest.raises(InsufficientResearchError, match="at least 4"):
        normalize_sources(raw, minimum=4)


def test_fact_validation_requires_two_valid_source_numbers() -> None:
    assert validate_source_numbers([1, 3, 3], source_count=3) == [1, 3]
    with pytest.raises(InsufficientResearchError, match="two distinct"):
        validate_source_numbers([1], source_count=3)
    with pytest.raises(InsufficientResearchError, match="outside"):
        validate_source_numbers([1, 4], source_count=3)


def test_medical_script_automatically_appends_the_required_vet_disclaimer() -> None:
    response = {
        "script": "A general health explanation without the required warning.",
        "title": "A Cat Health Sign",
        "description": "General education about a cat sign.",
        "hashtags": ["#shorts", "#cats", "#cathealth"],
        "tags": ["cat health"],
        "hook_text": "Notice THIS cat sign",
        "hook_keyword": "THIS",
        "search_terms": ["cat health sign"],
        "beats": ["cat resting", "owner calling veterinarian"],
        "mood": "calm educational",
        "medical": True,
    }
    brief = ResearchBrief(
        summary="General information",
        claims=["A supported claim"],
        sources=[SourceTrace("Vet", "https://vet.example", "fact", 1.0, "now")],
        medical=True,
        vet_disclaimer="Ask a veterinarian about changes in your cat's health.",
    )
    writer = ScriptWriter(FakeLLM(response))

    package = writer.write(Candidate("Cat sign", "what it can indicate", "evergreen"), brief)

    assert package.script == (
        "A general health explanation without the required warning. "
        "Ask a veterinarian about changes in your cat's health."
    )


def test_duration_revision_restores_a_required_disclaimer_dropped_by_the_llm() -> None:
    response = {
        "script": "A shorter general health explanation.",
        "title": "A Cat Health Sign",
        "description": "General education about a cat sign.",
        "hashtags": ["#shorts", "#cats", "#cathealth"],
        "tags": ["cat health"],
        "hook_text": "Notice THIS cat sign",
        "hook_keyword": "THIS",
        "search_terms": ["cat health sign"],
        "beats": ["cat resting", "owner calling veterinarian"],
        "mood": "calm educational",
        "medical": True,
    }
    original = ScriptPackage(
        script="A long medical narration. Ask a veterinarian about changes in your cat's health.",
        title="A Cat Health Sign",
        description="General education about a cat sign.",
        hashtags=["#shorts", "#cats", "#cathealth"],
        tags=["cat health"],
        hook_text="Notice THIS cat sign",
        hook_keyword="THIS",
        search_terms=["cat health sign"],
        beats=["cat resting", "owner calling veterinarian"],
        mood="calm educational",
        medical=True,
    )
    writer = ScriptWriter(FakeLLM(response))

    revised = writer.revise_for_duration(
        original,
        60.0,
        required_disclaimer="Ask a veterinarian about changes in your cat's health.",
    )

    assert revised.script.endswith("Ask a veterinarian about changes in your cat's health.")
