# Scripts

This directory contains narrowly scoped local maintenance and operational scripts.

`traderctl` is a thin wrapper around `python -m app.ops.cli`. It sets
`PYTHONPATH=backend` for repository-root use and calls only the loopback
operator API.

It defaults to `python3` and honors `PYTHON` when another interpreter is
required. P07 commands are `decision-status`, `decision-evaluate --signal-id
<id> [--force]`, `decision-recommendations --limit <n>`,
`decision-auto-status`, and `decision-evaluate-latest --limit <n>`.

No deployment, broker order, cloud, or live-trading automation exists here.
