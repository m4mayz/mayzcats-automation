from __future__ import annotations

import math
from typing import Protocol

from .models import Candidate, HistoryEntry


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None

    def encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding vectors must have equal non-zero dimensions")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class DuplicateDetector:
    def __init__(
        self,
        embedder: Embedder,
        subject_threshold: float = 0.90,
    ) -> None:
        self.embedder = embedder
        self.subject_threshold = subject_threshold

    def find_duplicate(
        self, candidate: Candidate, history: list[HistoryEntry]
    ) -> HistoryEntry | None:
        if not history:
            return None
        texts = [candidate.subject, *(entry.subject for entry in history)]
        vectors = self.embedder.encode(texts)
        candidate_subject = vectors[0]
        for index, entry in enumerate(history):
            subject_vector = vectors[index + 1]
            if cosine_similarity(candidate_subject, subject_vector) >= self.subject_threshold:
                return entry
        return None
