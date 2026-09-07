from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


def _print_progress(message: str) -> None:
    print(message, flush=True)


def post_with_retries(
    http: httpx.Client,
    url: str,
    *,
    label: str,
    max_attempts: int = 3,
    progress: Callable[[str], None] = _print_progress,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> httpx.Response:
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        response: httpx.Response | None = None
        request_error: httpx.RequestError | None = None
        try:
            response = http.post(url, **kwargs)
            if response.status_code not in RETRYABLE_HTTP_STATUSES:
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

        delay = min(8.0, float(2 ** (attempt - 1)))
        progress(
            f"[Retry] {label} failed ({reason}); "
            f"attempt {attempt + 1}/{attempts} in {delay:.0f}s..."
        )
        sleep(delay)

    raise RuntimeError("Unreachable retry state")
