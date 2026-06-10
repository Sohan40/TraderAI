from __future__ import annotations

import io
import json
from email.message import Message
from pathlib import Path
from urllib import error, parse, request

import pytest

from app.ops.cli import COMMANDS, DEFAULT_BASE_URL, run


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.mark.parametrize(("command", "method", "path"), [
    (command, method, path)
    for command, (method, path) in COMMANDS.items()
    if command not in {"paper-replay", "decision-evaluate", "decision-recommendations"}
])
def test_cli_maps_commands_to_operator_routes(
    command: str,
    method: str,
    path: str,
) -> None:
    captured: list[request.Request] = []

    def opener(req: request.Request, *, timeout: float) -> FakeResponse:
        captured.append(req)
        return FakeResponse({"ok": True})

    stdout = io.StringIO()
    result = run(
        [command],
        environ={"OPERATOR_AUTH_TOKEN": "operator-secret"},
        opener=opener,
        stdout=stdout,
    )
    req = captured[0]

    assert result == 0
    assert req.get_method() == method
    assert req.full_url == f"{DEFAULT_BASE_URL}{path}"
    assert req.get_header("X-operator-token") == "operator-secret"
    assert json.loads(stdout.getvalue()) == {"ok": True}


def test_cli_loads_token_from_default_env_prod_and_supports_base_url(tmp_path: Path) -> None:
    env_file = tmp_path / "infra" / "gcp" / "env.prod"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("OPERATOR_AUTH_TOKEN='file-token'\n", encoding="utf-8")
    captured: list[request.Request] = []

    def opener(req: request.Request, *, timeout: float) -> FakeResponse:
        captured.append(req)
        return FakeResponse({"ok": True})

    result = run(
        ["--base-url", "http://localhost:9000", "status"],
        environ={},
        cwd=tmp_path,
        opener=opener,
        stdout=io.StringIO(),
    )
    req = captured[0]

    assert result == 0
    assert req.full_url == "http://localhost:9000/api/v1/ops/market-ops/status"
    assert req.get_header("X-operator-token") == "file-token"


def test_cli_token_precedence_prefers_argument_then_environment(tmp_path: Path) -> None:
    env_file = tmp_path / "operator.env"
    env_file.write_text("OPERATOR_AUTH_TOKEN=file-token\n", encoding="utf-8")
    tokens: list[str] = []

    def opener(req: request.Request, *, timeout: float) -> FakeResponse:
        header = req.get_header("X-operator-token")
        assert header is not None
        tokens.append(header)
        return FakeResponse({"ok": True})

    assert run(
        ["--operator-token", "argument-token", "--env-file", str(env_file), "status"],
        environ={"OPERATOR_AUTH_TOKEN": "environment-token"},
        opener=opener,
        stdout=io.StringIO(),
    ) == 0
    assert run(
        ["--env-file", str(env_file), "status"],
        environ={"OPERATOR_AUTH_TOKEN": "environment-token"},
        opener=opener,
        stdout=io.StringIO(),
    ) == 0
    assert tokens == ["argument-token", "environment-token"]


def test_cli_passes_paper_replay_query_parameters() -> None:
    captured: list[request.Request] = []

    def opener(req: request.Request, *, timeout: float) -> FakeResponse:
        captured.append(req)
        return FakeResponse({"ok": True})

    result = run(
        [
            "paper-replay",
            "--symbol",
            "NSE:SBIN",
            "--from",
            "2026-06-09T05:00:00Z",
            "--to",
            "2026-06-09T10:00:00Z",
            "--limit",
            "25",
        ],
        environ={"OPERATOR_AUTH_TOKEN": "operator-secret"},
        opener=opener,
        stdout=io.StringIO(),
    )
    req = captured[0]
    query = parse.parse_qs(parse.urlsplit(req.full_url).query)

    assert result == 0
    assert req.get_method() == "POST"
    assert query == {
        "symbol": ["NSE:SBIN"],
        "from": ["2026-06-09T05:00:00Z"],
        "to": ["2026-06-09T10:00:00Z"],
        "limit": ["25"],
    }


def test_cli_passes_decision_parameters() -> None:
    captured: list[request.Request] = []

    def opener(req: request.Request, *, timeout: float) -> FakeResponse:
        captured.append(req)
        return FakeResponse({"ok": True})

    assert run(
        ["decision-evaluate", "--signal-id", "15", "--force"],
        environ={"OPERATOR_AUTH_TOKEN": "operator-secret"},
        opener=opener,
        stdout=io.StringIO(),
    ) == 0
    assert run(
        ["decision-recommendations", "--limit", "25"],
        environ={"OPERATOR_AUTH_TOKEN": "operator-secret"},
        opener=opener,
        stdout=io.StringIO(),
    ) == 0
    assert run(
        ["decision-evaluate-latest", "--limit", "3"],
        environ={"OPERATOR_AUTH_TOKEN": "operator-secret"},
        opener=opener,
        stdout=io.StringIO(),
    ) == 0

    evaluate_query = parse.parse_qs(parse.urlsplit(captured[0].full_url).query)
    recommendations_query = parse.parse_qs(parse.urlsplit(captured[1].full_url).query)
    latest_query = parse.parse_qs(parse.urlsplit(captured[2].full_url).query)
    assert evaluate_query == {"signal_id": ["15"], "force": ["True"]}
    assert recommendations_query == {"limit": ["25"]}
    assert latest_query == {"limit": ["3"]}


def test_traderctl_defaults_to_python3() -> None:
    wrapper = Path("scripts/traderctl").read_text(encoding="utf-8")
    assert 'exec "${PYTHON:-python3}" -m app.ops.cli "$@"' in wrapper


def test_cli_http_error_is_nonzero_and_redacts_operator_token() -> None:
    token = "operator-secret"

    def opener(req: request.Request, *, timeout: float) -> FakeResponse:
        raise error.HTTPError(
            req.full_url, 403, "Forbidden", Message(), io.BytesIO(
                json.dumps({"detail": f"rejected {token}"}).encode()
            )
        )

    stderr = io.StringIO()
    result = run(
        ["status"],
        environ={"OPERATOR_AUTH_TOKEN": token},
        opener=opener,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert token not in stderr.getvalue()
    assert "[redacted]" in stderr.getvalue()
