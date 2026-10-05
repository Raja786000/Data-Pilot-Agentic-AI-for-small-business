# Running DataPilot

## Easiest: one click

* **Windows:** double-click `START_WINDOWS.bat`
* **Mac / Linux:** run `./START_MAC_LINUX.sh`

You need **Python 3.10+** and **Node.js 18+** installed once. The first start downloads packages and builds the interface (a few minutes). After that it opens in seconds at **http://localhost:8000**.

## With Docker

```
docker compose up --build
```
Open http://localhost:8000. Your data lives in a Docker volume.

## Development (two terminals, live reload)

```
# terminal 1
cd backend
python -m venv .venv && .venv\Scripts\activate      # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend
npm install
npm run dev          # opens http://localhost:5173 and proxies /api to port 8000
```

## Where is my data?
In `backend/data/` (datasets, actions, settings). Nothing leaves your computer unless you add an AI key or webhook in Settings. To start fresh, use Settings → Start over, or delete that folder's contents.

## Try it with the included files
`sample_data/` has three files: a kirana store (dd/mm/yyyy dates, ₹ amounts, stock, costs), a shopping-trends file with **no dates and no costs**, and an Excel file. Or press **Try a sample shop** on the welcome screen.

## Troubleshooting
* **"Cannot reach the DataPilot server"** – the backend is not running. Start it (step 1 above).
* **Blank white page after an update** – delete `frontend/dist` and run the start script again.
* **Port 8000 busy** – change `--port 8000` in the start script, or close the other program.
* **An AI key does nothing** – Settings → AI assistant → *Test connection* shows the exact reason.
