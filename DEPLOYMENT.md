# Deploying TFC-Plane to any Docker machine

Production deployment pulls **prebuilt images from GHCR** — no source build needed.

## Prerequisites

- Docker Engine + Docker Compose v2 (`docker compose version`)
- Network access to `ghcr.io`

> If the GHCR packages are private, authenticate once before pulling
> (use a Personal Access Token with `read:packages`; never store it in a file):
>
> ```bash
> echo "<YOUR_GITHUB_PAT>" | docker login ghcr.io -u <YOUR_GITHUB_USERNAME> --password-stdin
> ```

## Steps

1. Copy these files from the repository to the target machine (same directory):
   - `docker-compose.prod.yml`
   - `.env.production.example`
   - `deploy.sh` (optional convenience)

2. Create the environment file and edit the required values:

   ```bash
   cp .env.production.example .env
   nano .env    # set real passwords, SECRET_KEY, domain, etc.
   ```

   Minimum values to change in `.env`:
   - `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD`, `SECRET_KEY`, `LIVE_SERVER_SECRET_KEY`
   - `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (MinIO credentials)
   - `APP_DOMAIN` and `WEB_URL` / `CORS_ALLOWED_ORIGINS` (e.g. `http://192.168.1.50`)
   - `TFC_IMAGE_PREFIX` must be `ghcr.io/<lowercase-github-owner>` (default already correct for this repo)

3. Start the stack:

   ```bash
   ./deploy.sh          # pulls images + docker compose -f docker-compose.prod.yml up -d
   ```

   or manually:

   ```bash
   docker compose -f docker-compose.prod.yml pull
   docker compose -f docker-compose.prod.yml up -d
   ```

4. First start: the `migrator` container applies DB migrations (once). Watch it:

   ```bash
   docker compose -f docker-compose.prod.yml logs -f migrator
   ```

## Access points (HTTP only, per current configuration)

| Surface | URL |
|---|---|
| Web app | `http://<host>/` |
| Admin (god mode) | `http://<host>/god-mode/` |
| Public spaces | `http://<host>/spaces/` |
| Live websocket | `http://<host>/live/` |

## Maintenance

```bash
docker compose -f docker-compose.prod.yml ps            # status
docker compose -f docker-compose.prod.yml logs -f api   # follow logs
docker compose -f docker-compose.prod.yml pull && \
docker compose -f docker-compose.prod.yml up -d         # upgrade to new images
```

## Data & backups (important)

All state lives in **named Docker volumes** — `pgdata`, `redisdata`, `uploads`, `rabbitmq_data`, `logs_*`:

- They survive `docker compose down` and container recreation.
- ⚠️ **`docker compose down -v` DELETES all project data** — never use it in production.
- Back up with:
  - Postgres: `docker compose -f docker-compose.prod.yml exec plane-db pg_dump -U plane plane > backup.sql`
  - MinIO files: `mc mirror` / copy the `uploads` volume.
