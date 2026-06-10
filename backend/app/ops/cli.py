"""VM-local standard-library client for operator-protected TraderAI routes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, TextIO, cast
from urllib import error, parse, request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ENV_FILE = Path("infra/gcp/env.prod")
COMMANDS: dict[str, tuple[str, str]] = {
    "status": ("GET", "/api/v1/ops/market-ops/status"),
    "start": ("POST", "/api/v1/ops/market-ops/start"),
    "stop": ("POST", "/api/v1/ops/market-ops/stop"),
    "preopen": ("POST", "/api/v1/ops/market-ops/run-preopen-check"),
    "start-stream": ("POST", "/api/v1/ops/market-ops/run-start-stream"),
    "verify-stream": ("POST", "/api/v1/ops/market-ops/run-verify-stream"),
    "universe": ("POST", "/api/v1/ops/market-ops/run-universe-selection"),
    "scanner": ("POST", "/api/v1/ops/market-ops/run-scanner-batch"),
    "stop-stream": ("POST", "/api/v1/ops/market-ops/run-stop-stream"),
    "test-telegram": ("POST", "/api/v1/ops/market-ops/test-notification"),
    "kite-status": ("GET", "/api/v1/broker/kite/session/status"),
    "kite-login-url": ("POST", "/api/v1/broker/kite/login-url"),
    "stream-status": ("GET", "/api/v1/market-data/stream/status"),
    "paper-status": ("GET", "/api/v1/paper/status"),
    "paper-report": ("GET", "/api/v1/paper/report"),
    "paper-trades": ("GET", "/api/v1/paper/trades"),
    "paper-replay": ("POST", "/api/v1/paper/run-replay"),
    "decision-status": ("GET", "/api/v1/decision/status"),
    "decision-evaluate": ("POST", "/api/v1/decision/evaluate"),
    "decision-recommendations": ("GET", "/api/v1/decision/recommendations"),
    "decision-auto-status": ("GET", "/api/v1/decision/auto-status"),
    "decision-evaluate-latest": ("POST", "/api/v1/decision/evaluate-latest"),
}


class ResponseLike(Protocol):
    def __enter__(self) -> ResponseLike: ...
    def __exit__(self, *args: object) -> object: ...
    def read(self) -> bytes: ...


class UrlOpener(Protocol):
    def __call__(self, req: request.Request, *, timeout: float) -> ResponseLike: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TraderAI VM-local operator CLI")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--operator-token")
    parser.add_argument("--env-file", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        command_parser = subparsers.add_parser(command)
        if command == "paper-replay":
            command_parser.add_argument("--symbol")
            command_parser.add_argument("--from", dest="from_time")
            command_parser.add_argument("--to", dest="to_time")
            command_parser.add_argument("--limit", type=int)
        elif command == "decision-evaluate":
            command_parser.add_argument("--signal-id", type=int, required=True)
            command_parser.add_argument("--force", action="store_true")
        elif command in {"decision-recommendations", "decision-evaluate-latest"}:
            command_parser.add_argument("--limit", type=int)
    return parser


def resolve_operator_token(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str],
    cwd: Path,
) -> str:
    if args.operator_token:
        return str(args.operator_token)
    if environ.get("OPERATOR_AUTH_TOKEN"):
        return environ["OPERATOR_AUTH_TOKEN"]
    if args.env_file is not None:
        return _read_env_token(args.env_file)
    default_path = cwd / DEFAULT_ENV_FILE
    if default_path.is_file():
        return _read_env_token(default_path)
    return ""


def run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    opener: UrlOpener | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = build_parser().parse_args(argv)
    actual_environ = environ if environ is not None else os.environ
    actual_cwd = cwd or Path.cwd()
    actual_opener = opener or cast(UrlOpener, request.urlopen)
    try:
        token = resolve_operator_token(args, environ=actual_environ, cwd=actual_cwd)
    except OSError:
        print("Unable to read operator token env file.", file=stderr)
        return 2
    if not token:
        print("OPERATOR_AUTH_TOKEN is not configured.", file=stderr)
        return 2

    method, path = COMMANDS[args.command]
    query = _query_for(args)
    url = f"{str(args.base_url).rstrip('/')}{path}"
    if query:
        url = f"{url}?{parse.urlencode(query)}"
    req = request.Request(
        url,
        data=b"" if method == "POST" else None,
        headers={"X-Operator-Token": token, "Accept": "application/json"},
        method=method,
    )
    try:
        with actual_opener(req, timeout=15.0) as response:
            body = response.read()
    except error.HTTPError as exc:
        body = exc.read()
        detail = _safe_error_body(body, token)
        print(f"HTTP {exc.code}: {detail}", file=stderr)
        return 1
    except (error.URLError, TimeoutError, OSError):
        print("TraderAI API request failed.", file=stderr)
        return 1

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        print("TraderAI API returned invalid JSON.", file=stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
    return 0


def _query_for(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "paper-replay":
        values = {
            "symbol": args.symbol,
            "from": args.from_time,
            "to": args.to_time,
            "limit": args.limit,
        }
    elif args.command == "decision-evaluate":
        values = {"signal_id": args.signal_id, "force": args.force}
    elif args.command in {"decision-recommendations", "decision-evaluate-latest"}:
        values = {"limit": args.limit}
    else:
        return {}
    return {key: value for key, value in values.items() if value is not None}


def _read_env_token(path: Path) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "OPERATOR_AUTH_TOKEN":
            continue
        normalized = value.strip()
        if (
            len(normalized) >= 2
            and normalized[0] == normalized[-1]
            and normalized[0] in {"'", '"'}
        ):
            normalized = normalized[1:-1]
        return normalized
    return ""


def _safe_error_body(body: bytes, token: str) -> str:
    try:
        decoded = body.decode("utf-8")
    except UnicodeError:
        return "request rejected"
    safe = decoded.replace(token, "[redacted]") if token else decoded
    try:
        payload = json.loads(safe)
    except json.JSONDecodeError:
        return safe[:500] or "request rejected"
    if isinstance(payload, dict) and "detail" in payload:
        return json.dumps(payload["detail"], sort_keys=True)[:500]
    return json.dumps(payload, sort_keys=True)[:500]


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
