# PC Monitor

Personal hardware telemetry platform for Windows PCs.

* **Next.js + React + TypeScript** dashboard (Vercel)
* **Python FastAPI** backend (any Python host / container platform)
* **Python Windows agent** compiled to a single `PC-Monitor.exe`
* **Firebase Firestore** for storage

New PCs appear on the dashboard automatically the moment their agent registers -
there is no device list to maintain anywhere.

> **Monitoring only.** PC Monitor collects hardware/system telemetry (CPU, GPU,
> RAM, disk, network throughput, battery, temperatures). It deliberately has
> **no** remote control, screen capture, webcam/microphone access, keylogging,
> browser history, file browsing, remote shell or command execution. The agent
> runs as a normal, visible Windows background application.

---

## 1. Architecture

```
┌────────────────────┐   HTTPS    ┌────────────────────┐  Admin SDK  ┌──────────────┐
│  Next.js dashboard │ ─────────► │  FastAPI backend   │ ──────────► │   Firestore  │
│  (browser, Vercel) │            │  (auth, validation)│             │  (devices +  │
└────────────────────┘            └────────────────────┘             │  telemetry)  │
         ▲                                  ▲                          └──────────────┘
         │  NEXT_PUBLIC_API_URL             │  POST /api/devices/register
         │  (public URL only)               │  POST /api/devices/heartbeat
         │                                  │  POST /api/telemetry  (X-Device-Token)
┌────────┴───────────┐                      │
│ PC-Monitor.exe     │ ─────────────────────┘
│ PyInstaller, no GUI│
│ autostart via      │
│ HKCU Run           │
└────────────────────┘
```

The browser never talks to Firestore and never sees a secret. The EXE contains no
Firebase credentials - only its own per-device token, stored DPAPI-encrypted.

### Repository layout

```
pc-monitor/
├── backend/            FastAPI service + pytest suite
│   ├── app/
│   │   ├── main.py             app factory, middleware, /health, /api/meta
│   │   ├── api/                devices.py, telemetry.py, heartbeat.py, logs.py, deps.py
│   │   ├── services/           device_service.py, telemetry_service.py, cleanup_service.py
│   │   ├── models/             device.py, telemetry.py, common.py (pydantic v2)
│   │   ├── core/               config.py, firebase.py, security.py, middleware.py
│   │   └── utils/              validation.py, logging.py, time.py
│   ├── tests/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/           Next.js App Router dashboard + vitest suite
│   ├── app/dashboard/{page,devices,devices/[deviceId],logs,settings}
│   ├── components/     Dashboard, DeviceCard, DeviceGrid, DeviceHeader, charts, Sidebar, Navbar…
│   ├── hooks/usePolling.ts
│   ├── lib/            api.ts, types.ts, utils.ts
│   └── tests/
├── agent/              Windows monitoring agent
│   ├── src/            main, config, collector, cpu, gpu, memory, disk, network,
│   │                   battery, system, device, api, logger, startup
│   ├── tests/
│   ├── build.py        PyInstaller build → dist/PC-Monitor.exe
│   └── requirements.txt
├── firestore/          firestore.rules, firestore.indexes.json, TTL notes
├── .env.example
└── README.md
```

---

## 2. Requirements

| Component | Needs |
|-----------|-------|
| Backend | Python 3.11+, a Firebase project, any Python host |
| Frontend | Node.js 20+ |
| Agent | Windows 10/11, Python 3.11+ to build (not needed to run the EXE) |
| Build EXE | PyInstaller (build on Windows for a Windows target) |

---

## 3. Firebase setup

1. Create a project at <https://console.firebase.google.com>.
2. **Firestore Database** → Create database (Native mode).
3. **Project settings → Service accounts** → *Generate new private key*.
4. Copy `backend/.env.example` → `backend/.env` and fill in `FIREBASE_PROJECT_ID`,
   `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY` (keep the `\n` escapes).
   Never commit this file - it is already in `.gitignore`.
5. Deploy the locked-down rules and indexes:

   ```bash
   cd firestore
   firebase deploy --only firestore:rules,firestore:indexes
   ```

6. Enable the TTL policy (see `firestore/README.md`) so telemetry expires after
   7 days automatically. The backend also tries to enable it at startup.

Data model, field-by-field: [`firestore/README.md`](firestore/README.md).

---

## 4. Backend setup

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                   # fill in Firebase values + DEVICE_AUTH_SECRET
uvicorn app.main:app --reload --port 8000
```

* Health: <http://localhost:8000/health>
* Interactive API docs: <http://localhost:8000/docs> and `/redoc`
* `USE_INMEMORY_DB=true` runs without Firebase (data is lost on restart - for
  local development and the test-suite only).

Generate a strong secret:

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"   # DEVICE_AUTH_SECRET
```

### Endpoints

| Method | Path | Who | Purpose |
|--------|------|-----|---------|
| POST | `/api/devices/register` | agent | Register, receive the device token |
| POST | `/api/devices/heartbeat` | agent | Liveness (every 60 s) |
| POST | `/api/telemetry` | agent | Submit one sample |
| GET | `/api/devices` | dashboard | All registered devices (discovery) |
| GET | `/api/devices/{deviceId}` | dashboard | Device detail |
| GET | `/api/devices/{deviceId}/telemetry?range=1h\|6h\|24h\|7d` | dashboard | History |
| GET | `/api/devices/{deviceId}/logs` | dashboard | Per-device activity |
| PATCH | `/api/devices/{deviceId}` | dashboard | Name, interval, startup preference |
| DELETE | `/api/devices/{deviceId}` | dashboard | Remove + revoke token + purge telemetry |
| GET | `/api/logs` | dashboard | Fleet-wide activity feed |
| GET | `/api/system/cleanup` | dashboard | Retention/TTL status |
| GET | `/health`, `/api/meta` | anyone | Health and client configuration |

---

## 5. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env.local            # set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                            # http://localhost:3000
```

Routes: `/dashboard`, `/dashboard/devices`, `/dashboard/devices/[deviceId]`,
`/dashboard/logs`, `/dashboard/settings`.

### Protecting the dashboard

There is no in-app login by design (this is a private, single-operator tool).
Keep the deployment private at the edge instead:

* **Vercel**: enable *Deployment Protection* (Vercel Authentication) or
  Standard Protection on the production project, **and/or**
* restrict `FRONTEND_URL`/CORS in the backend to your own dashboard origin, and
* keep the backend on a host that requires an API key or IP allow-list.

The dashboard never contains a secret: `NEXT_PUBLIC_API_URL` is just a URL.
Device tokens live only in Firestore (hashed) and on the PC (DPAPI).

---

## 6. Windows agent

### Run from source

```bash
cd agent
pip install -r requirements.txt
set API_URL=http://localhost:8000
python -m src.main
```

First run generates a device id, collects hardware facts, registers with the
backend and stores its token under `%LOCALAPPDATA%\PC-Monitor\`.

### CLI

| Command | Effect |
|---------|--------|
| `PC-Monitor.exe` | Run in the background (default) |
| `PC-Monitor.exe --status` | Print local configuration as JSON |
| `PC-Monitor.exe --once` | Upload a single sample and exit |
| `PC-Monitor.exe --interval 60` | Change the sampling interval |
| `PC-Monitor.exe --api-url https://api.example.com` | Point at another backend |
| `PC-Monitor.exe --enable-startup` / `--no-startup` | Turn Windows autostart on/off |
| `PC-Monitor.exe --reset` | Forget device id + token (forces re-registration) |
| `PC-Monitor.exe --log-level DEBUG` | More detail in the local log |

### Background behaviour and autostart

* The PyInstaller build is `--onefile --windowed`: no GUI, no console window, it
  simply runs in the background (visible in Task Manager).
* **Startup is enabled on first run** through the normal, visible Windows
  mechanism: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` → `PC-Monitor`.
  The user can see and change it in *Task Manager → Startup apps*, or run
  `PC-Monitor.exe --no-startup`. Nothing is hidden, and no service/driver or
  scheduled task is created.
* A named mutex keeps a single instance per machine.

### Local files

| Path | Contents |
|------|----------|
| `%LOCALAPPDATA%\PC-Monitor\config.json` | Device id, name, API URL, interval, startup flag |
| `%LOCALAPPDATA%\PC-Monitor\token.dat` | Device token, DPAPI-encrypted (never logged) |
| `%LOCALAPPDATA%\PC-Monitor\logs\agent.log` | Rotating log (2 MB × 3) |

### Build `PC-Monitor.exe`

```bash
cd agent
pip install -r requirements.txt
python build.py --clean
# → agent/dist/PC-Monitor.exe  (single file, no Python required on the target PC)
python build.py --console      # debug build with a console window
```

Copy the EXE to the target PC and run it once. To preconfigure it, run
`PC-Monitor.exe --api-url https://api.example.com --name "Gaming PC"` first.

---

## 7. Multiple PCs

1. Copy `PC-Monitor.exe` to each machine and run it.
2. Each agent mints its own `PC-XXXXXXXX` id and receives its own token.
3. `GET /api/devices` returns all of them; each gets its own page, history and
   logs at `/dashboard/devices/<deviceId>`.
4. Removing a device in the dashboard revokes its token: the old EXE gets
   401/403, stops uploading, and logs how to re-register (`--reset`).

---

## 8. Retention and cost

* `expiresAt = timestamp + TELEMETRY_RETENTION_DAYS` (default 7, hard max 7).
* Firestore TTL deletes expired telemetry on Google's side; the backend cleanup
  job (`CLEANUP_INTERVAL_MINUTES`, batched, paginated, repeatable) is the
  fallback. Both only ever touch `telemetry` documents.
* Device documents, names, status and last-seen never expire.
* Ingestion rejects samples older than the retention window, so expired history
  cannot be recreated.
* Cost model for one PC at a 30 s interval: 2 writes/min ≈ 120/h ≈ 2 880/day
  ≈ 20 160/week. The dashboard only queries the range it is displaying and
  down-samples server-side to at most `MAX_TELEMETRY_POINTS` (1500) points.

---

## 9. Deployment

### Backend

Any Python host (Render, Railway, Fly.io, Cloud Run, Azure App Service, a VPS).
`backend/Dockerfile` is included:

```bash
docker build -t pc-monitor-api ./backend
docker run -p 8000:8000 --env-file backend/.env pc-monitor-api
```

Set `ENVIRONMENT=production`, a real `FRONTEND_URL`, and HTTPS termination
(hosting platforms provide it).

### Frontend

```bash
cd frontend
NEXT_PUBLIC_API_URL=https://api.example.com npx vercel --prod
```

### Firestore TTL

Follow [`firestore/README.md`](firestore/README.md). `GET /api/system/cleanup`
reports whether the policy is active and when the fallback last ran.

---

## 10. Environment variables

**Backend** (`backend/.env`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `FIREBASE_PROJECT_ID` | – | Firestore project |
| `FIREBASE_CLIENT_EMAIL` | – | Admin SDK service account |
| `FIREBASE_PRIVATE_KEY` | – | Admin SDK private key |
| `GOOGLE_APPLICATION_CREDENTIALS` | – | Alternative: path to the JSON key |
| `DEVICE_AUTH_SECRET` | – | HMAC pepper for device tokens (≥16 chars) |
| `TELEMETRY_RETENTION_DAYS` | `7` | Retention window (max 7) |
| `FRONTEND_URL` | `http://localhost:3000` | CORS allow-list (first origin) |
| `EXTRA_CORS_ORIGINS` | – | Extra origins, comma separated |
| `ONLINE_THRESHOLD_SECONDS` | `120` | ONLINE while `lastSeen` is fresher |
| `DEFAULT_TELEMETRY_INTERVAL_SECONDS` | `30` | Sampling interval |
| `MAX_TELEMETRY_POINTS` | `1500` | Max chart points per request |
| `MAX_REQUEST_BYTES` | `65536` | Request body limit |
| `RATE_LIMIT_TELEMETRY_PER_MINUTE` | `12` | Agent telemetry limit |
| `RATE_LIMIT_HEARTBEAT_PER_MINUTE` | `20` | Agent heartbeat limit |
| `RATE_LIMIT_REGISTER_PER_HOUR` | `30` | Registration limit |
| `CLEANUP_INTERVAL_MINUTES` | `30` | Fallback cleanup cadence |
| `CLEANUP_SECRET` | – | `POST /internal/cleanup` (X-Cleanup-Token) |
| `USE_INMEMORY_DB` | `false` | Development/test store |

**Frontend** (`frontend/.env.local`): `NEXT_PUBLIC_API_URL`,
`NEXT_PUBLIC_REFRESH_SECONDS` (default `15`).

**Agent** (environment or `config.json`): `API_URL`,
`TELEMETRY_INTERVAL_SECONDS`, `PC_MONITOR_DEVICE_NAME`, `PC_MONITOR_HOME`.

---

## 11. Security

* **HTTPS everywhere** in production (terminate at the platform).
* **Per-device tokens**: 256-bit `secrets` tokens, stored only as an HMAC-SHA256
  hash in Firestore; verified in constant time; never displayed in the
  dashboard; never written to logs; rotated on re-registration.
* **Secret hygiene**: `FIREBASE_*`, `DEVICE_AUTH_SECRET` and `CLEANUP_SECRET`
  live only in the backend. Nothing sensitive is in `NEXT_PUBLIC_*` or in the EXE.
* **Input validation**: Pydantic v2 models reject CPU/GPU/RAM/disk > 100,
  negative values, absurd VRAM/speeds, NaN/Inf, malformed timestamps, unknown
  fields and oversized payloads (64 KB).
* **Rate limiting** on telemetry, heartbeat, registration and dashboard reads
  (sliding window, `429` + `Retry-After`).
* **CORS** restricted to the configured dashboard origins.
* **Security headers** (`nosniff`, `DENY` frames, `no-referrer`) and JSON error
  envelopes; log redaction scrubs anything token-shaped.
* **Firestore rules** deny all direct client access.
* **Removal revokes** the token and purges telemetry; the old agent cannot keep
  uploading.

### Explicitly out of scope

No remote keyboard/mouse control, no remote desktop, no screen capture, no
webcam or microphone, no keylogging, no browser history, no password collection,
no file browsing, no remote shell, no command execution, no stealth or hidden
persistence.

---

## 12. Testing

```bash
# Backend - 61 tests: API, device tokens, validation, retention/cleanup, rate limits
cd backend && python -m pytest

# Agent - 39 tests: collectors, sensors, tokens, retries, startup, CLI
cd agent && python -m pytest

# Frontend - 24 tests: components, charts, formatting, API client
cd frontend && npm test
npm run typecheck
```

Covered explicitly: expired telemetry is deleted, recent telemetry remains,
device documents survive cleanup, and multiple devices stay independent.

---

## 13. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Device never appears | Is the backend reachable from the PC? Check `curl https://api/health` and the agent log. |
| `409 device_already_registered` | Remove the device in the dashboard, or run `PC-Monitor.exe --reset`. |
| `401/403` on uploads | The device was removed or the backend lost state → `--reset`. |
| `429` in the agent log | Interval is too aggressive; set `TELEMETRY_INTERVAL_SECONDS=30` or raise the limit. |
| `413 payload_too_large` | Raise `MAX_REQUEST_BYTES` (or reduce `cpuPerCore` reporting). |
| `422 validation_error` | A sensor returned an out-of-range value - check the response body, it names the field. |
| Dashboard shows “Cannot reach the API” | `NEXT_PUBLIC_API_URL` wrong, backend down, or CORS origin not in `FRONTEND_URL`/`EXTRA_CORS_ORIGINS`. |
| Empty charts | No samples in that range yet, or the device is offline - try `1h`. |
| Temperatures show “—” | Expected on most Windows machines: no user-mode thermal API. NVIDIA works via NVML. |
| Cleanup never deletes | TTL enabled → Firestore does it; otherwise check `GET /api/system/cleanup` and `CLEANUP_SECRET`. |
| Agent does not start with Windows | Run `PC-Monitor.exe --enable-startup`; check Task Manager → Startup apps. |

---

## 14. License

Provided as-is for personal use.