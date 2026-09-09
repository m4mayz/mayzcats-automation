from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


def _print_progress(message: str) -> None:
    print(message, flush=True)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Honour Retry-After; overloaded providers state the wait they actually want."""

    if response is not None:
        try:
            return min(60.0, max(0.0, float(response.headers.get("retry-after", ""))))
        except ValueError:
            pass  # ponytail: HTTP-date form is rare on JSON APIs; fall back to backoff.
    return min(8.0, float(2 ** (attempt - 1)))


def post_with_retries(
    http: httpx.Client,
    url: str,
    *,
    label: str,
    max_attempts: int = 3,
    progress: Callable[[str], None] = _print_progress,
    sleep: Callable[[float], None] = time.sleep,
    retry_statuses: set[int] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    statuses = RETRYABLE_HTTP_STATUSES if retry_statuses is None else retry_statuses
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        response: httpx.Response | None = None
        request_error: httpx.RequestError | None = None
        try:
            response = http.post(url, **kwargs)
            if response.status_code not in statuses:
                return response
            reason = f"HTTP {response.status_code}"
        except httpx.RequestError as exc:
            request_error = exc
            reason = type(exc).__name__

        if attempt == attempts:
            if request_error is not None:
                raise request_error
            assert response is not None
            return response

        delay = _retry_delay(response, attempt)
        progress(
            f"[Retry] {label} failed ({reason}); "
            f"attempt {attempt + 1}/{attempts} in {delay:.0f}s..."
        )
        sleep(delay)

    raise RuntimeError("Unreachable retry state")
