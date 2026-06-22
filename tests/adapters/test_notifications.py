from __future__ import annotations

from typing import Any

import httpx
import pytest

from trading.adapters.notifications import LoggingNotifier, NotifierPort, NtfyNotifier
from trading.domain import Severity


def test_ntfy_notifier_constructs_without_real_server() -> None:
    notifier = NtfyNotifier(topic="kcrawley-tracker-test")

    assert isinstance(notifier, NotifierPort)
    assert notifier._client is None


async def test_logging_notifier_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    notifier = LoggingNotifier()

    await notifier.send("Test notification", "body", severity=Severity.WARNING, tags=["dev"])

    captured = capsys.readouterr()
    assert "Test notification" in captured.err
    assert '"severity":"WARNING"' in captured.err


def test_notifier_port_structural_check() -> None:
    assert isinstance(LoggingNotifier(), NotifierPort)
    assert isinstance(NtfyNotifier(topic="kcrawley-tracker-test"), NotifierPort)


async def test_send_critical_calls_send_with_critical_severity() -> None:
    class SpyNotifier(NtfyNotifier):
        def __init__(self) -> None:
            super().__init__(topic="kcrawley-tracker-test")
            self.calls: list[dict[str, Any]] = []

        async def send(
            self,
            title: str,
            body: str,
            severity: Severity = Severity.INFO,
            tags: list[str] | None = None,
            click_url: str | None = None,
        ) -> None:
            self.calls.append(
                {
                    "title": title,
                    "body": body,
                    "severity": severity,
                    "tags": tags,
                    "click_url": click_url,
                }
            )

    notifier = SpyNotifier()

    await notifier.send_critical("Critical title", "body", tags=["critical"], click_url="/alerts/1")

    assert notifier.calls == [
        {
            "title": "Critical title",
            "body": "body",
            "severity": Severity.CRITICAL,
            "tags": ["critical"],
            "click_url": "/alerts/1",
        }
    ]


async def test_ntfy_post_uses_expected_request_shape() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "abc123"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = NtfyNotifier(
        server_url="https://ntfy.example.test/",
        topic="/kcrawley-tracker-test/",
        auth_token="secret-token",
        client=client,
    )

    await notifier.send(
        "Pipeline stalled",
        "No updates received",
        severity=Severity.WARNING,
        tags=["pipeline", "stale"],
        click_url="https://tracker.example.test/audit",
    )
    await client.aclose()

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://ntfy.example.test/kcrawley-tracker-test"
    assert request.method == "POST"
    assert request.content == b"No updates received"
    assert request.headers["Title"] == "Pipeline stalled"
    assert request.headers["Priority"] == "high"
    assert request.headers["Tags"] == "pipeline,stale"
    assert request.headers["Click"] == "https://tracker.example.test/audit"
    assert request.headers["Authorization"] == "Bearer secret-token"
