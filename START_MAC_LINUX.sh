#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Install Python 3 first: https://www.python.org/downloads/"; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js LTS first: https://nodejs.org/"; exit 1; }
[ -d backend/.venv ] || python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -q -r backend/requirements.txt
[ -d frontend/node_modules ] || (cd frontend && npm install)
[ -d frontend/dist ] || (cd frontend && npm run build)
echo; echo "DataPilot is running at http://localhost:8000  (Ctrl+C to stop)"
(sleep 2; (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || (command -v open >/dev/null && open http://localhost:8000) || true) &
cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
