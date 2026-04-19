# Connectivity Aware Routing

> Real-time connectivity-aware route planning with live signal heatmaps,
> multi-mode routing, and a React Native Android dashboard.

---

## Project Structure

```text
connectivity-aware-routing/
├── services/
│   ├── routing-engine/     # Python route scoring + FastAPI
│   ├── data-service/       # Tile ingestion + cache API + heatmap tiles
│   ├── prediction-service/ # Signal prediction API
│   ├── telemetry-service/  # Lightweight system telemetry API
│   └── visualization/      # React/Vite frontend dashboard
├── dashboard-native/       # React Native Android tablet app
├── docker-compose.yml      # Full stack Docker orchestration
├── run-local.ps1           # Local dev startup script (PowerShell)
└── README.md
```

---

## Prerequisites

### For PowerShell (`run-local.ps1`)
- Windows 10/11
- PowerShell 5.1 or later
- Python 3.10+ (added to `PATH`)
- Node.js 18+ and npm
- Git

### For Docker
- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- Docker Compose v2+
- 8GB RAM minimum recommended

---

## Running Locally — PowerShell

### Step 1 — Clone the repository

```powershell
git clone <repo-url>
cd connectivity-aware-routing
```

### Step 2 — Configure environment

Copy the example env file:

```powershell
Copy-Item services\data-service\.env.example services\data-service\.env
```

Edit `services/data-service/.env` and fill in required values.

### Step 3 — Run the startup script

Right-click PowerShell → Run as Administrator (first time only)

```powershell
.\run-local.ps1
```

This will:
- Load environment variables from `services/data-service/.env`
- Install Python dependencies for backend services
- Install Node dependencies for `services/visualization`
- Start all required local services
- Print service URLs when ready

### Service URLs (local)

| Service | URL |
|---|---|
| Data Service API | http://localhost:8001 |
| Routing Engine API | http://localhost:8002 |
| Prediction Service API | http://localhost:8003 |
| Telemetry Service API | http://localhost:8004 |
| Frontend Dashboard | http://localhost:5173 |

---

## Running with Docker

### Step 1 — Clone the repository

```bash
git clone <repo-url>
cd connectivity-aware-routing
```

### Step 2 — Configure environment

```bash
cp services/data-service/.env.example services/data-service/.env
```

### Step 3 — Build and start all services

```bash
docker compose up --build
```

To run in background:

```bash
docker compose up --build -d
```

### Step 4 — Check service health

```bash
docker compose ps
```

All services should show status `healthy`.

### Stopping

```bash
docker compose down
```

To also remove volumes:

```bash
docker compose down -v
```

---

## Android Tablet App (React Native)

See `dashboard-native/README.md` for full setup.

Quick build (requires JDK 17 and Android SDK):

```powershell
cd dashboard-native\android
.\gradlew.bat assembleRelease
```

APK output:

```text
dashboard-native/android/app/build/outputs/apk/release/app-release.apk
```

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| DATA_SERVICE_URL | URL of the data service | http://localhost:8001 |
| ROUTING_ENGINE_URL | URL of the routing engine | http://localhost:8002 |
| CITY | Default city to load | bangalore |
| OPENCELLID_KEYS | Comma-separated OpenCellID API keys | key1,key2,key3 |

---

## Common Issues

### PowerShell execution policy error

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Port already in use

Check which process is using the port:

```powershell
netstat -ano | findstr :8001
```

Kill it or change the port in `.env`.

### Docker build fails on M1/M2 Mac

Add under each service in `docker-compose.yml`:

```yaml
platform: linux/amd64
```

### Heatmap not loading over custom domain

Ensure all tile URLs use relative paths (`/api/tiles/...`) not localhost URLs.
Check `vite.config.ts` proxy config.

---

## Architecture Overview

```text
[User Browser]
     │
     ▼
[Visualization — Vite/React]
     │
     ├──▶ [Data Service — FastAPI] ──▶ [Tile Store / Signal DB]
     │
     └──▶ [Routing Engine — FastAPI] ──▶ [Graph + Signal Scoring]
```

---

## License

MIT
