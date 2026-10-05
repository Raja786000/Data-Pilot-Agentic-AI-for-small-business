# DataPilot v4 — decision intelligence for small businesses

Upload your sales (CSV or Excel). DataPilot works out what is making money, what is running out, what may happen next, and what to do. **You approve every action.**

Start: see **RUN.md** (double-click `START_WINDOWS.bat`).

## What changed from v3
| Your request | What was done |
|---|---|
| Fonts too small / poor style | 18px base text (adjustable: Normal / Large / Extra large in Settings), Atkinson Hyperlegible (designed for readability) + Fraunces headings |
| "Add more" button broken | Root cause: a CSS rule styled every `<label>` in headers like a tiny coloured caption, making the button text invisible. Replaced; upload now has clear *Replace* / *Add to current data* choice |
| Whole site goes blank on click | Root cause: no error boundary, so any render error unmounted the whole React tree. Now every page is isolated, every API call returns safe messages, and empty/failed responses show a clear state |
| Dummy values, must use real data | No built-in fake numbers. Smart column detection (names + content), manual column mapping, ₹/commas/dd-mm-yyyy/Excel dates, files with no dates, no costs or no quantity |
| Automation not working | 8 real rules + custom alerts, editable limits, schedules (on upload / daily / weekly), run history, no duplicate actions |
| Actions, Agent Lab, AI chat | Rebuilt: approve / reject / done / reopen / delete / add your own; investigation with a visible step trace; chat answers from real calculations (AI optional) |
| Insights / forecast / signals not using the data | All computed from the active dataset: plain-English findings, group comparisons with 80/20 classes, weekday and monthly patterns, 4-model forecast with backtest accuracy, anomaly / slowdown / stock / margin signals |
| Settings | Business profile, currency + Indian/International numbers, financial year, typical cost %, stock rules, theme, text size, AI provider (OpenAI, OpenRouter, Groq, Ollama, custom) with *Test connection*, webhook, reset |
| Responsive | Desktop sidebar → drawer menu + bottom tab bar on phones, tables scroll inside their card, print-ready report |
| New features | Stock & reorder quantities, customer groups, what-if scenarios with price curve, printable report, quick sale entry, multiple datasets, webhook on approval, cleaned-data download |

## Design principle
Numbers are always calculated by code (pandas / scikit-learn). The optional AI only rephrases verified facts, so it cannot invent figures.

## Layout
```
backend/app/   ingest.py (column detection) · metrics.py · insights.py · forecast.py
               assistant.py (chat + investigation) · automation.py · llm.py · store.py · main.py (API)
frontend/src/  App.jsx · pagesA/B/C.jsx · ui.jsx · api.js · styles.css
sample_data/   files to try
```
