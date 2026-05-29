# Backup and Restore

## Why Backups Matter

P02 runs PostgreSQL on the same VM as the API and Redis. That is acceptable for the MVP bootstrap, but all journal, order, model-run, and future trading records will depend on PostgreSQL durability.

Before later paper or live phases, backups must be reviewed, tested, and retained outside Docker volumes.

## Manual Backup

Run from the VM with `infra/gcp/env.prod` present:

```bash
set -a
. infra/gcp/env.prod
set +a
mkdir -p backups
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml exec -T postgres \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom \
  > "backups/postgres-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Do not put database passwords on the command line. Keep backup files outside Docker volumes and copy them to protected storage.

## Manual Restore Into a Separate Environment

Restore into a separate test database or VM first:

```bash
set -a
. infra/gcp/env.prod
set +a
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml exec -T postgres \
  pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --clean --if-exists \
  < backups/POSTGRES_BACKUP_FILE.dump
```

Review the target environment carefully before restore. A restore can overwrite database objects.

## Rollback Safety

Rollback scripts must never silently delete PostgreSQL or Redis Docker volumes.

Do not run destructive volume commands such as:

```bash
docker compose down -v
docker volume rm
```

unless you have a verified backup, you are targeting a non-production test environment, and you have reviewed the exact volume names.

## P02 Boundary

This phase provides manual backup and restore guidance only. Automated backup scheduling, retention policy, restore drills, and alerting belong before later paper/live phases.
