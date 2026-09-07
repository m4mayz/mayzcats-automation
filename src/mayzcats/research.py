from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from .models import Candidate, ResearchBrief, SourceTrace
from .network import post_with_retries


class InsufficientResearchError(RuntimeError):
    pass


def _print_progress(message: str) -> None:
    print(message, flush=True)


def validate_source_numbers(values: list[Any], *, source_count: int, minimum: int = 2) -> list[int]:
    numbers: list[int] = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise InsufficientResearchError(
                "Fact checker returned a non-numeric source number"
            ) from exc
        if not 1 <= number <= source_count:
            raise InsufficientResearchError(
                f"Fact checker source number {number} is outside 1-{source_count}"
            )
        if number not in numbers:
            numbers.append(number)
    if len(numbers) < min(minimum, source_count):
        raise InsufficientResearchError("Fact validation requires two distinct source numbers")
    return numbers


def normalize_sources(raw_results: list[dict[str, Any]], *, minimum: int = 3) -> list[SourceTrace]:
    seen: set[str] = set()
    sources: list[SourceTrace] = []
    retrieved_at = datetime.now(UTC).isoformat()
    for raw in raw_results:
        url = str(raw.get("url", "")).strip()
        content = str(raw.get("content", "")).strip()
        if not url or not content:
            continue
        parsed = urlsplit(url)
        canonical = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
        if canonical in seen:
            continue
        seen.add(canonical)
        sources.append(
            SourceTrace(
                title=str(raw.get("title", parsed.netloc)).strip() or parsed.netloc,
                url=url,
                content=content,
                score=float(raw.get("score", 0.0) or 0.0),
                retrieved_at=retrieved_at,
            )
        )
    if len(sources) < minimum:
        raise InsufficientResearchError(
            f"Research requires at least {minimum} distinct usable sources; got {len(sources)}"
        )
    return sources


class TavilyClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 120.0,
        max_attempts: int = 3,
        progress: Callable[[str], None] = _print_progress,
        http: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=min(30.0, timeout)))
        self.max_attempts = max_attempts
        self.progress = progress

    def search(
        self,
        query: str,
        *,
        max_results: int = 8,
        topic: str = "general",
        search_depth: str = "advanced",
        time_range: str | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "query": query,
            "topic": topic,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "safe_search": True,
        }
        if time_range:
            payload["time_range"] = time_range
        response = post_with_retries(
            self.http,
            "https://api.tavily.com/search",
            label=f"Tavily search: {query[:70]}",
            max_attempts=self.max_attempts,
            progress=self.progress,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if not isinstance(results, list):
            raise ValueError("Tavily response did not contain a results array")
        return results


class JsonLLM(Protocol):
    def json(self, system: str, user: str) -> dict[str, Any]: ...


class Researcher:
    def __init__(
        self,
        tavily: TavilyClient,
        llm: JsonLLM,
        *,
        minimum_sources: int = 3,
        max_results: int = 8,
        progress: Callable[[str], None] = _print_progress,
    ) -> None:
        self.tavily = tavily
        self.llm = llm
        self.minimum_sources = minimum_sources
        self.max_results = max_results
        self.progress = progress

    def discover_trends(self) -> str:
        results = self.tavily.search(
            "current cat behavior pet culture stories and discussions",
            max_results=self.max_results,
            topic="news",
            time_range="week",
        )
        if not results:
            return ""
        return "\n".join(
            f"- {item.get('title', '')}: {item.get('content', '')[:500]} ({item.get('url', '')})"
            for item in results[: self.max_results]
        )

    def research(self, candidate: Candidate) -> ResearchBrief:
        queries = candidate.search_queries or [f"{candidate.subject} {candidate.angle} cat facts"]
        raw: list[dict[str, Any]] = []
        selected_queries = queries[:3]
        for index, query in enumerate(selected_queries, start=1):
            self.progress(
                f"[Research {index}/{len(selected_queries) + 2}] Searching sources: {query}"
            )
            raw.extend(self.tavily.search(query, max_results=self.max_results, topic="general"))
            self.progress(f"[Research] Collected {len(raw)} raw results so far")
        sources = normalize_sources(raw, minimum=self.minimum_sources)
        self.progress(
            f"[Research {len(selected_queries) + 1}/{len(selected_queries) + 2}] "
            f"Normalized {len(sources)} distinct sources"
        )
        evidence = "\n\n".join(
            f"SOURCE {index}: {source.title}\nURL: {source.url}\nEXCERPT: {source.content}"
            for index, source in enumerate(sources, start=1)
        )
        self.progress(
            f"[Research {len(selected_queries) + 2}/{len(selected_queries) + 2}] "
            "Validating claims with the LLM..."
        )
        response = self.llm.json(
            """You are a careful cat-content fact checker. Use only the supplied
source excerpts. Reject unsupported claims. Medical content may explain general
signs but may not diagnose or prescribe; it must include a concise veterinarian
disclaimer. Return JSON only.""",
            f"""Topic: {candidate.subject}\nAngle: {candidate.angle}\n\n{evidence}\n\n
Return {{"summary":"...","claims":["..."],"source_numbers":[1,2],
"medical":false,"vet_disclaimer":null}}. Every claim must be supported by at
least one numbered source and the brief must use at least two distinct sources.
Keep source traces internal.""",
        )
        claims = [str(item).strip() for item in response.get("claims", []) if str(item).strip()]
        summary = str(response.get("summary", "")).strip()
        medical = bool(response.get("medical", False))
        disclaimer = response.get("vet_disclaimer")
        if not claims or not summary:
            raise InsufficientResearchError("Fact checker returned no supported claims")
        validate_source_numbers(
            list(response.get("source_numbers") or []), source_count=len(sources)
        )
        if medical and not str(disclaimer or "").strip():
            raise InsufficientResearchError("Medical research requires a veterinarian disclaimer")
        return ResearchBrief(
            summary=summary,
            claims=claims,
            sources=sources,
            medical=medical,
            vet_disclaimer=str(disclaimer).strip() if disclaimer else None,
        )
