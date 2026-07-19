# Archiviator

Self-hosted home catalog: everything you own, where it lives, with photos, tags, search,
QR labels, a visual house map, and Google Drive-linked documents. Runs on a Windows PC,
reachable from your iPhone via Tailscale.

- Backend: FastAPI + SQLAlchemy 2 + SQLite (WAL) + Alembic — `backend/`
- Frontend: React 18 + TypeScript + Vite + Tailwind — `frontend/`
- Data lives in `C:\archiviator-data\` (override with env `ARCHIVIATOR_DATA_DIR`)
- Public URL (Tailscale): `https://threadripper.tail3670c0.ts.net`

## Development

```powershell
# Backend (Python 3.13)
cd backend
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m app.cli create-user <username>   # first run only
.venv\Scripts\python -m app.main                          # http://127.0.0.1:8422

# Frontend dev server (hot reload, proxies /api to 8422)
cd frontend
npm install
npm run dev                                               # http://localhost:5175

# Tests
backend\.venv\Scripts\python -m pytest backend/tests -q
```

Migrations run automatically at server startup (`alembic upgrade head`). To create a new
migration: `.venv\Scripts\alembic revision -m "..."` in `backend/`.

## Production on this PC

1. Build the frontend once: `cd frontend && npm run build` — the backend then serves
   `frontend/dist` itself at port 8422 (SPA fallback included; unknown `/api` routes stay JSON 404s).
2. Expose via Tailscale (real HTTPS certificate, same URL at home and away):
   ```powershell
   tailscale serve --bg http://127.0.0.1:8422
   ```
3. Run as a Windows service so it survives reboots — with [NSSM](https://nssm.cc):
   ```powershell
   nssm install Archiviator "C:\...\archiviator\backend\.venv\Scripts\python.exe" "-m app.main"
   nssm set Archiviator AppDirectory "C:\...\archiviator\backend"
   nssm set Archiviator AppStdout "C:\archiviator-data\logs\out.log"
   nssm set Archiviator AppStderr "C:\archiviator-data\logs\err.log"
   nssm start Archiviator
   ```
   (Alternative: Task Scheduler "At startup" task, without auto-restart on crash.)

## Important operational notes

- **QR labels encode `https://threadripper.tail3670c0.ts.net/a/{tag}`** — never print labels
  before confirming this hostname; changing it later invalidates every printed sticker.
- The auth refresh token slides for 90 days so the phone never hits a login wall mid-scan.
- Nightly backups (from M6): WAL-safe `VACUUM INTO` + ZIP pushed to Google Drive.
- Google Drive integration (M9) reuses the gdriveexchanger OAuth client; the Google Cloud
  consent screen must be **"In production"**, otherwise refresh tokens expire every 7 days.

## Google Drive setup (one-time)

1. Admin → Drive page: paste the path to your existing OAuth client secret JSON
   (the `client_secret_*.json` in gdriveexchanger's credentials folder — referenced
   in place, never copied). **The Google Cloud consent screen must be "In
   production"**, otherwise refresh tokens die every 7 days.
2. Click Connect — a browser window opens **on this PC** for the one-time consent.
3. Pick your scans folder; new scans then appear in the Drive inbox for attaching
   to catalog entries. Optionally enable nightly backup upload (folder
   "Archiviator Backups", newest 7 kept).

## iOS Shortcuts quick capture (optional)

Admin → Device tokens → create one. Shortcut: Scan QR → Take Photo →
Get Contents of URL: POST `https://threadripper.tail3670c0.ts.net/api/v1/intake/capture`,
Request Body = Form with the photo as field `file`, header
`Authorization: Bearer <token>`. The token can ONLY capture — it cannot read or
delete anything.

## Milestones

All complete: M1 skeleton · M2 entity tree · M3 photos/attachments ·
M4 metadata+search · M5 QR+labels · M6 inventory+seeding+backups ·
M7 rapid intake · M8 house map · M9 Google Drive. 371 backend tests.
Full plan: `C:\Users\Luca\.claude\plans\i-want-to-start-quirky-mountain.md`
