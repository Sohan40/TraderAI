# P02 — Google Cloud VM, Static IP and Deployment


## Objective

Deploy the safe OFF-mode application to one Google Compute Engine VM with a reserved static IP and controlled secret delivery. No trading execution exists yet.

## Deliverables

- `infra/gcp/README.md` with manual GCP console/CLI steps:
  - project and required APIs;
  - service account with least privilege;
  - Ubuntu VM;
  - reserved static external IPv4;
  - firewall rules;
  - Secret Manager integration;
  - Ops Agent/logging;
  - rollback.
- Docker Compose production overlay for API/Postgres/Redis; worker may be stubbed.
- Deployment script or GitHub Actions workflow that:
  - deploys containers;
  - never injects live-arm state;
  - verifies `/healthz` and `/readyz`;
  - starts with trading OFF.
- Backup/restore notes for the database.
- VM outbound-IP verification command and a place to record static-IP validation without committing the actual sensitive mapping unnecessarily.

## Safety requirements

- No real secret value in repository or workflow output.
- No public unauthenticated control routes.
- Live mode remains impossible.
- Deployment restarts clear any arming flag.

## Acceptance criteria

- App reachable securely or through an SSH tunnel for initial testing.
- Logs visible in Cloud Logging or clearly documented local container logs.
- Reserved IP remains assigned after VM restart.
- Health check succeeds in OFF mode.

## Codex prompt

```text
Implement only P02_GCP_INFRA_DEPLOYMENT.

Add infrastructure documentation, Docker production deployment assets and safe health deployment checks.
Do not add broker authentication or order execution.
Use Secret Manager references/placeholders only; no secrets.
Ensure deployment always starts TRADING_MODE=OFF and LIVE_ARMED=false.
Run validation checks possible locally and report manual GCP steps still required.
```
