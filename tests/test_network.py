from __future__ import annotations

import httpx

from mayzcats.network import _retry_delay, post_with_retries


def _response(headers: dict[str, str]) -> httpx.Response:
    return httpx.Response(500, headers=headers, request=httpx.Request("POST", "https://x"))


def test_retry_delay_prefers_retry_after_then_falls_back_to_backoff() -> None:
    assert _retry_delay(_response({"retry-after": "30"}), 1) == 30.0
    assert _retry_delay(_response({"retry-after": "600"}), 1) == 60.0
    assert _retry_delay(_response({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}), 2) == 2.0
    assert _retry_delay(_response({}), 3) == 4.0
    assert _retry_delay(None, 1) == 1.0


def test_post_with_retries_waits_the_delay_the_server_asked_for() -> None:
    class OverloadedClient:
        def post(self, url: str, **kwargs: object) -> httpx.Response:
            return _response({"retry-after": "30"})

    slept: list[float] = []
    post_with_retries(
        OverloadedClient(), "https://x", label="probe", max_attempts=2,
        progress=lambda message: None, sleep=slept.append,
    )
    assert slept == [30.0]
