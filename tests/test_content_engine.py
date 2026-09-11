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


@pytest.mark.parametrize(("old", "new"), [
    ("Feline slow blink communication", "Slow Blinking Communication"),
    ("The feline slow blink", "The slow blink response"),
    ("Whisker Proprioception", "Whisker Fatigue"),
    ("Feline Whiskers (Vibrissae)", "Cat Whisker Anatomy"),
    ("Cat Purring Physiology", "Feline purr anatomy and biomechanics"),
])
def test_actual_published_topic_variants_are_duplicates(old, new):
    history = [HistoryEntry(old, "old angle", datetime(2026, 9, 1, tzinfo=UTC), "old")]
    detector = DuplicateDetector(FakeEmbedder({old: [1, 0], new: [0, 1]}))
    assert detector.find_duplicate(Candidate(new, "new angle", "evergreen"), history) is history[0]


def test_semantic_judge_catches_synonyms_below_embedding_threshold():
    old, new = "Kneading blankets", "Making biscuits"
    history = [HistoryEntry(old, "comfort", datetime(2026, 9, 1, tzinfo=UTC), "old")]
    detector = DuplicateDetector(
        FakeEmbedder({old: [1, 0], new: [0, 1]}),
        llm=FakeLLM({"duplicate_index": 0}),
    )
    assert detector.find_duplicate(Candidate(new, "origins", "evergreen"), history) is history[0]


@pytest.mark.parametrize("response", [{}, {"duplicate_index": False}, {"duplicate_index": 9}])
def test_invalid_semantic_verdict_does_not_accept_topic(response):
    history = [HistoryEntry("sleep", "why", datetime(2026, 9, 1, tzinfo=UTC), "old")]
    detector = DuplicateDetector(
        FakeEmbedder({"sleep": [1, 0], "hunting": [0, 1]}), llm=FakeLLM(response)
    )
    with pytest.raises(ValueError, match="verdict"):
        detector.find_duplicate(Candidate("hunting", "why", "evergreen"), history)


def test_extract_json_accepts_fenced_response_and_rejects_trailing_garbage() -> None:
    assert extract_json_object('```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(ValueError, match="JSON object"):
        extract_json_object("answer: none")


def test_duplicate_rejects_similar_subject_even_with_a_different_angle() -> None:
    vectors = {
        "cats kneading blankets": [1.0, 0.0],
        "cats making biscuits on blankets": [0.99, 0.01],
        "cats kneading their owners": [0.98, 0.02],
    }
    history = [
        HistoryEntry(
            "cats kneading blankets",
            "why they do it",
            datetime(2026, 9, 1, tzinfo=UTC),
            "vid1",
        )
    ]
    detector = DuplicateDetector(FakeEmbedder(vectors), 0.90)

    wording_variant = Candidate(
        "cats making biscuits on blankets",
        "the emotional reason behind kneading",
        "evergreen",
    )
    different_angle = Candidate(
        "cats kneading their owners", "how owners should respond", "evergreen"
    )

    assert detector.find_duplicate(wording_variant, history) is history[0]
    assert detector.find_duplicate(different_angle, history) is history[0]


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


def test_medical_script_does_not_request_or_append_a_vet_disclaimer() -> None:
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
    )
    writer = ScriptWriter(FakeLLM(response))

    package = writer.write(Candidate("Cat sign", "what it can indicate", "evergreen"), brief)

    assert package.script == "A general health explanation without the required warning."
    assert all("disclaimer" not in prompt.lower() for call in writer.llm.calls for prompt in call)


def test_duration_revision_does_not_request_a_disclaimer() -> None:
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
    )

    assert revised.script == "A shorter general health explanation."
    assert all("disclaimer" not in prompt.lower() for call in writer.llm.calls for prompt in call)


def test_repeated_duplicate_gate_reuses_the_verdict_until_history_changes() -> None:
    vectors = {
        "kneading blankets": [1.0, 0.0],
        "night zoomies": [0.0, 1.0],
        "sunbeam napping": [0.5, 0.5],
    }
    history = [
        HistoryEntry("kneading blankets", "comfort", datetime(2026, 9, 1, tzinfo=UTC), "old")
    ]
    llm = FakeLLM({"duplicate_index": None})
    detector = DuplicateDetector(FakeEmbedder(vectors), llm=llm)
    candidate = Candidate("night zoomies", "why at 3am", "evergreen")

    # The pipeline gates the same candidate three times per run.
    assert [detector.find_duplicate(candidate, history) for _ in range(3)] == [None] * 3
    assert len(llm.calls) == 1

    history.append(
        HistoryEntry("sunbeam napping", "why", datetime(2026, 9, 2, tzinfo=UTC), "old2")
    )
    assert detector.find_duplicate(candidate, history) is None
    assert len(llm.calls) == 2


def test_research_prompt_clips_long_source_bodies_before_calling_the_llm() -> None:
    from mayzcats.research import EXCERPT_CHARS, Researcher

    class FatTavily:
        def search(self, query, **kwargs):
            return [
                {"title": f"t{i}", "url": f"https://s{i}.test", "content": "x" * 20_000}
                for i in range(8)
            ]

    llm = FakeLLM({"summary": "s", "claims": ["c"], "source_numbers": [1, 2], "medical": False})
    researcher = Researcher(FatTavily(), llm, progress=lambda message: None)
    brief = researcher.research(
        Candidate("cat naps", "why", "evergreen", search_queries=["a", "b", "c"])
    )

    user_prompt = llm.calls[0][1]
    assert "x" * (EXCERPT_CHARS + 1) not in user_prompt
    # Every source stays numbered, so source_numbers keep validating against the prompt.
    assert user_prompt.count("SOURCE ") == len(brief.sources)
    assert len(user_prompt) < 20_000


def _response(**overrides):
    base = {
        "script": "Cats knead blankets because it comforts them.",
        "title": "Why Cats Knead",
        "description": "A sourced explanation.",
        "hashtags": ["#cats", "#catfacts"],
        "tags": ["kneading"],
        "hook_text": "Cats knead for a reason",
        "hook_keyword": "knead",
        "search_terms": ["cat kneading"],
        "beats": ["cat kneading"],
        "mood": "warm",
    }
    return {**base, **overrides}


def test_string_hashtags_do_not_become_one_tag_per_character() -> None:
    from mayzcats.script_writer import package_from_response

    package = package_from_response(
        _response(hashtags="#shorts #cats #catfacts"), medical=False
    )

    assert package.hashtags == ["#shorts", "#cats", "#catfacts"]


def test_sectioned_script_is_narrated_without_its_labels() -> None:
    from mayzcats.script_writer import package_from_response

    as_dict = package_from_response(
        _response(script={
            "hook": "Ever watched a cat knead?",
            "closing question": "What does your cat do?",
        }),
        medical=False,
    )
    as_headings = package_from_response(
        _response(script="Hook: Ever watched a cat knead?\nClosing question: What now?"),
        medical=False,
    )

    for text in (as_dict.script, as_headings.script):
        lowered = text.lower()
        assert "hook" not in lowered and "closing question" not in lowered
        assert "{" not in text and "'" not in text
    assert as_dict.script == "Ever watched a cat knead?\nWhat does your cat do?"


@pytest.mark.parametrize("field", ["tags", "beats", "search_terms"])
def test_other_string_list_fields_survive_the_same_shape(field) -> None:
    from mayzcats.script_writer import package_from_response

    package = package_from_response(_response(**{field: "first, second"}), medical=False)

    assert "first" in getattr(package, field)


def test_string_claims_do_not_become_one_claim_per_character() -> None:
    from mayzcats.research import Researcher

    class Tavily:
        def search(self, query, **kwargs):
            return [
                {"title": f"t{i}", "url": f"https://s{i}.test", "content": "cats nap a lot"}
                for i in range(3)
            ]

    llm = FakeLLM({
        "summary": "Cats nap often.",
        "claims": "Cats nap 16 hours a day, Naps come in short bursts",
        "source_numbers": "1,2",
        "medical": False,
    })
    brief = Researcher(Tavily(), llm, progress=lambda message: None).research(
        Candidate("cat naps", "why", "evergreen", search_queries=["a"])
    )

    assert brief.claims == ["Cats nap 16 hours a day", "Naps come in short bursts"]
