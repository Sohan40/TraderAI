# GCP OFF-Mode Deployment

## Scope

P02 prepares deployment assets for the current OFF-mode backend and storage scaffold only.

The deployed stack is:

- `api`: existing FastAPI backend from P01.
- `postgres`: local PostgreSQL container on the VM.
- `redis`: local Redis container on the VM.

No market data, AI agent, broker authentication, order execution, dashboard, worker process, or live-trading functionality exists in this phase. Every deployment must start with `TRADING_MODE=OFF` and `LIVE_ARMED=false`.

## Manual Google Cloud Setup

Run these steps manually from your workstation or the Google Cloud console. Do not run them from deployment scripts.

Use placeholders and record real values outside Git:

```bash
export PROJECT_ID="REPLACE_OUTSIDE_GIT"
export REGION="asia-south1"
export ZONE="REPLACE_OUTSIDE_GIT"
export VM_NAME="REPLACE_OUTSIDE_GIT"
```

Create or select a project:

```bash
gcloud projects create "${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"
```

Enable required APIs:

```bash
gcloud services enable compute.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable logging.googleapis.com
gcloud services enable monitoring.googleapis.com
```

Create a dedicated VM service account:

```bash
gcloud iam service-accounts create zerodha-ai-trader-vm \
  --display-name="Zerodha AI Trader VM"
```

Reserve a regional static external IPv4 address:

```bash
gcloud compute addresses create zerodha-ai-trader-ip \
  --region="${REGION}"
```

Create an Ubuntu LTS VM and assign the reserved IP. Use the actual reserved address value outside Git:

```bash
gcloud compute instances create "${VM_NAME}" \
  --zone="${ZONE}" \
  --machine-type=e2-small \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --address="RESERVED_STATIC_IP_RECORDED_OUTSIDE_GIT" \
  --boot-disk-size=30GB \
  --service-account="zerodha-ai-trader-vm@${PROJECT_ID}.iam.gserviceaccount.com" \
  --scopes=https://www.googleapis.com/auth/cloud-platform
```

Install Docker and Compose on the VM:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in after adding your user to the `docker` group.

Install the Ops Agent manually:

```bash
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
sudo bash add-google-cloud-ops-agent-repo.sh --also-install
```

Review `ops-agent-config.yaml` before copying it to `/etc/google-cloud-ops-agent/config.yaml`.

## VM Recommendation

- Ubuntu LTS.
- India-adjacent region such as `asia-south1`.
- Small general-purpose VM such as `e2-small` for API/Postgres/Redis testing.
- Persistent boot disk with enough room for Docker images, logs, and PostgreSQL data.
- No Kubernetes in P02.
- No Cloud SQL in P02; PostgreSQL stays on the VM for the MVP bootstrap.

## Firewall and Access

- Prefer SSH through secure access methods such as OS Login, IAP tunneling, or IP-restricted SSH.
- Do not expose PostgreSQL or Redis publicly.
- The production Compose file binds the API to `127.0.0.1:${APP_PORT:-8000}` for local VM checks or SSH tunneling.
- If you need a temporary firewall rule for health validation, restrict source IPs tightly and remove the rule afterward.
- HTTPS, reverse proxy, and authentication are required before any future public dashboard, login flow, or broker callback endpoint is exposed.

## Static-IP Verification

Future broker order execution depends on a stable registered outbound IP. Verify the VM egress IP before P03 and again before any live-order phase:

```bash
infra/gcp/verify_outbound_ip.sh
```

Compare the printed IP manually with the reserved static IP recorded outside the repository. Do not commit the IP value. Zerodha developer/account configuration belongs to later broker and execution phases.

## Secret Manager Plan

Future secrets expected in Secret Manager:

- `KITE_API_KEY`
- `KITE_API_SECRET`
- `OPENAI_API_KEY`
- `DATABASE_PASSWORD`
- `REDIS_PASSWORD`
- `APP_JWT_SECRET`

For P02, only database and Redis configuration is needed to run the current application. The app does not read Kite or OpenAI secrets yet. Future secret retrieval must use least-privilege access for the VM service account, scoped only to required secret versions.

Do not place real secret values in `env.prod`, shell history, logs, or committed files.

## Logging and Operations

P01 emits JSON application logs to stdout. For local inspection on the VM:

```bash
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml logs api
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml logs postgres
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml logs redis
```

Use the Google Cloud Ops Agent to ship VM and container logs to Cloud Logging. The starter `ops-agent-config.yaml` is intentionally conservative and may need adjustment based on the VM Docker log path.

Monitor disk space because PostgreSQL runs on the same VM:

```bash
df -h
docker system df
docker volume ls
```

Before paper or live phases, add a reviewed backup routine and prove restore into a separate test environment.

## Deployment

Copy or pull this repository onto the VM, then create the local production env file:

```bash
cp infra/gcp/env.prod.example infra/gcp/env.prod
chmod 600 infra/gcp/env.prod
chmod +x infra/gcp/*.sh
```

Edit `infra/gcp/env.prod` on the VM. Keep:

```env
TRADING_MODE=OFF
LIVE_ARMED=false
```

Deploy:

```bash
infra/gcp/deploy.sh
```

The deploy script:

- refuses deployment unless trading is OFF and not armed;
- builds and starts API/Postgres/Redis;
- runs Alembic migrations;
- verifies `/healthz`, `/readyz`, and root mode status.

Manual verification:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/
```

## Rollback

Rollback must never delete database volumes automatically.

After checking out a known-good Git revision or reviewing an image tag change, run:

```bash
infra/gcp/rollback.sh KNOWN_GOOD_REVISION_OR_IMAGE_TAG
```

Rollback restarts the API in OFF mode and runs verification. If a migration needs reversal, handle it manually only after backing up PostgreSQL.

Every restart must preserve:

```env
TRADING_MODE=OFF
LIVE_ARMED=false
```
