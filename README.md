# Connectivity Aware Routing

Real-time connectivity-aware route planning with live signal heatmaps, multi-mode routing, and dashboard UIs for local visualization and infotainment-style display.

---

## Tech Stack

### Backend Services
- Python 3.11
- FastAPI
- NetworkX + OSMnx
- NumPy / optional CuPy GPU acceleration
- SQLite tile and tower cache

### Primary Frontend (`services/visualization`)
- React + Vite
- TypeScript
- Leaflet / React-Leaflet

### Dashboard UI (`app/app`)
- React + Vite
- TypeScript
- MUI + Radix UI
- Axios for backend API integration

---

## Project Structure

```text
connectivity-aware-routing/
├── services/
│   ├── data-service/         # Tower cache, tile API, hotspot/coverage data
│   ├── routing-engine/       # Route scoring and pathfinding API
│   ├── prediction-service/   # Signal prediction API
│   ├── telemetry-service/    # Lightweight telemetry API
│   ├── visualization/        # Main React/Vite map frontend
│   └── visualization1/       # Legacy/reference frontend snapshot
├── app/
│   └── app/                  # Alternate dashboard UI
├── gateway/                  # Nginx gateway config
├── cache/                    # Local runtime cache
├── docker-compose.yml        # Full stack Docker orchestration
├── run-local.ps1             # Local Windows startup script
└── README.md
```

---

## Running Locally — PowerShell

### Prerequisites
- Windows 10/11
- PowerShell 5.1+
- Python 3.10+ on `PATH`
- Node.js 18+ and npm

### Setup

```powershell
git clone <repo-url>
cd connectivity-aware-routing
Copy-Item services\data-service\.env.example services\data-service\.env
```

Edit `services/data-service/.env` and set required values.

### Start the stack

```powershell
.\run-local.ps1
```

This script:
- resolves paths dynamically from the script location
- loads `services/data-service/.env`
- installs missing backend/frontend dependencies when needed
- starts backend services and the main visualization frontend

### Local service URLs

| Service | URL |
|---|---|
| Data Service | http://localhost:8001 |
| Routing Engine | http://localhost:8002 |
| Prediction Service | http://localhost:8003 |
| Telemetry Service | http://localhost:8004 |
| Main Frontend | http://localhost:5173 |

---

## Running with Docker

```bash
git clone <repo-url>
cd connectivity-aware-routing
cp services/data-service/.env.example services/data-service/.env
docker compose up --build
```

Run in background:

```bash
docker compose up --build -d
```

Check status:

```bash
docker compose ps
```

Stop:

```bash
docker compose down
```

Remove volumes too:

```bash
docker compose down -v
```

---

## Dashboard App (`app/app`)

`app/app` is a separate React + Vite dashboard UI. It is useful for infotainment-style or kiosk/dashboard rendering and is already wired for direct HTTPS API use.

Run it separately:

```powershell
cd app\app
npm install
npm run dev
```

Build it:

```powershell
cd app\app
npm run build
```

---

## Routing Modes

The route planner operates on a road-network graph where intersections are nodes and road segments are edges. The system exposes three practical route modes:

### Fastest
- prioritizes travel time
- minimizes delay and congestion cost
- best when ETA matters more than signal continuity

### Balanced
- balances travel time and connectivity
- aims for a practical compromise between speed and signal quality

### Connected
- strongly prefers signal-rich corridors
- will accept longer travel time to avoid weak or dead-signal segments where possible

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| DATA_SERVICE_URL | URL used by routing clients | http://localhost:8001 |
| ROUTING_ENGINE_URL | Routing API URL | http://localhost:8002 |
| DEFAULT_CITY | Default city to load | bangalore |
| OPENCELLID_KEYS | Comma-separated OpenCellID keys | key1,key2,key3 |

---

## Common Issues

### PowerShell execution policy error

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Port already in use

```powershell
netstat -ano | findstr :8001
```

Kill the conflicting process or free the port before rerunning `run-local.ps1`.

### Heatmap not loading over a custom domain
- use relative tile URLs such as `/api/tiles/...`
- avoid hardcoded `localhost` tile URLs
- verify frontend proxy or gateway config

### Docker build issues on Apple Silicon
If needed, add this under affected services:

```yaml
platform: linux/amd64
```

---

## Architecture Overview

```text
[Browser / Dashboard]
        │
        ├──▶ [Visualization / app/app]
        │
        ├──▶ [Data Service] ──▶ [Tower cache / tile store / hotspot data]
        │
        └──▶ [Routing Engine] ──▶ [Graph + edge scoring + route selection]
                           │
                           └──▶ [Prediction Service]
```

---

## License

MIT
