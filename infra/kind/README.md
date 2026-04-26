# Local dev with kind + Tilt

## Prerequisites

- Docker Desktop (or Docker Engine on Linux)
- `kubectl` >= 1.28
- `helm` >= 3.14
- `tilt` >= 0.33 — https://docs.tilt.dev/install.html
- `kind` >= 0.23 — bootstrap.sh auto-installs if missing on Linux/macOS

## Start the stack

```bash
cd /path/to/rag-p
chmod +x infra/kind/bootstrap.sh
./infra/kind/bootstrap.sh
tilt up
```

That's it. bootstrap.sh is idempotent — safe to run again.

## What gets deployed

| Service | URL |
|---|---|
| API (FastAPI) | http://api.localhost |
| Web (Next.js) | http://localhost |
| Langfuse | http://langfuse.localhost |
| API direct | http://localhost:8000 |
| Web direct | http://localhost:3000 |

## Hosts file (macOS/Linux)

```
127.0.0.1 api.localhost langfuse.localhost
```

On Windows: `C:\Windows\System32\drivers\etc\hosts`

## Teardown

```bash
./infra/scripts/teardown.sh
```

## Seed dev data

```bash
./infra/scripts/seed-dev-data.sh
```
