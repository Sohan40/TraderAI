# Google Cloud Setup Checklist

## Minimal resources

- Google Cloud project dedicated to this experiment.
- Compute Engine Ubuntu LTS VM in an India region suitable for you.
- Reserved static external IPv4 associated with the VM.
- Secret Manager secrets for Kite/OpenAI/database application secrets.
- Service account limited to reading the required secrets and writing logs.
- Cloud Logging/Ops Agent.
- Firewall rules with least privilege.

## Suggested first deployment shape

Run Docker Compose on one VM:

- `api`: FastAPI control/auth endpoints.
- `worker`: market-data, scanners, agent calls, risk and execution loops.
- `postgres`: durable data.
- `redis`: ephemeral health/locks/arming state.
- `nginx`: HTTPS/reverse proxy once authentication UI is exposed.

Do not add Kubernetes or managed databases before the system proves useful.

## Static IP checklist

- Reserve the IP before setting up broker execution access.
- Attach it to the VM and record the value securely.
- From the VM, verify outbound egress uses the reserved IP.
- Configure the same IP in the broker developer/account workflow required for API orders.
- Treat releasing/changing the IP as a live-trading breaking change.
- Keep `TRADING_MODE=OFF` until the IP path is tested and reviewed.

## Secret checklist

Secrets:

- `KITE_API_KEY`
- `KITE_API_SECRET`
- `OPENAI_API_KEY`
- `DATABASE_PASSWORD`
- `REDIS_PASSWORD`
- `APP_JWT_SECRET`

Rules:

- Git contains only placeholders.
- Do not log secrets or access tokens.
- Restrict VM service-account permission to only required secret versions.
- Daily Kite access-token storage must be encrypted or protected and expire/invalidate according to broker session behaviour.

## Deployment checklist

- Docker and Compose installed.
- Time synchronization enabled; application stores UTC and displays IST.
- VM disk monitoring configured.
- HTTPS enabled before exposing login callback/dashboard publicly.
- Application boots in `OFF` mode after every deploy or process restart.
- Health endpoints available before worker starts processing.
- Reconciliation runs before live arming after worker restart.

## P02 deployment assets

- OFF-mode VM deployment documentation lives in `infra/gcp/README.md`.
- Production Compose for P02 runs only `api`, `postgres` and `redis`.
- Postgres and Redis must not be exposed publicly.
- `infra/gcp/env.prod` is a local VM file and must not be committed.
- Every deployment and rollback must keep `TRADING_MODE=OFF` and `LIVE_ARMED=false`.
