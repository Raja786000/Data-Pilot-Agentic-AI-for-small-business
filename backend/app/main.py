"""DataPilot API. Every route returns JSON (even on errors) so the interface never receives an HTML error page."""
from __future__ import annotations

import io
import json
import re
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from . import assistant, automation, forecast as fc, ingest, insights, llm, metrics, store
from .sample import TEMPLATE_CSV, make_sample

store.init_db()
automation.seed()

app = FastAPI(title="DataPilot — Business Decision Intelligence", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ALLOWED_EXT = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm"}
MAX_BYTES = 150 * 1024 * 1024


@app.on_event("startup")
def _startup():
    automation.start_scheduler()


@app.exception_handler(Exception)
async def _any_error(request, exc):
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong on the server: {exc}"})


def ctx(period: Optional[str] = None) -> metrics.Ctx:
    try:
        return metrics.get_ctx(period)
    except metrics.NoData as e:
        raise HTTPException(409, str(e))
    except Exception as e:  # corrupt file, unreadable data, etc.
        raise HTTPException(422, f"Your data could not be analysed: {e}")


def summary(ds, info=None):
    return {"id": ds["id"], "name": ds["name"], "rows": ds["rows"], "created_at": ds["created_at"], "updated_at": ds["updated_at"],
            "is_sample": bool(ds["is_sample"]), "files": [f["name"] for f in ds["files"]]}


# ───────────────────────── health + state ─────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "DataPilot", "version": "4.0.0"}


@app.get("/api/state")
def state():
    ds = store.active_dataset()
    out: Dict[str, Any] = {"has_data": False, "dataset": None, "datasets": [summary(d) for d in store.list_datasets()],
                           "settings": store.settings_public(), "counts": store.action_counts(), "periods": [{"key": k, "label": v} for k, v in metrics.PERIODS],
                           "ai_presets": llm.PRESETS, "error": None}
    if ds:
        try:
            _, info = ingest.build_dataset(ds)
            out["has_data"] = True
            out["dataset"] = {**summary(ds), "has": info["has"], "dims": info["dims"], "numeric_extras": info["numeric_extras"], "date_range": info["date_range"],
                              "quality": info["quality"]["score"], "freq": info["freq"], "cost_mode": "actual" if info["has"]["cost"] else ("estimated" if store.profile().get("assumed_cost_pct") else None)}
        except Exception as e:
            out["error"] = f"The active dataset could not be read: {e}"
            out["has_data"] = False
    return out


# ───────────────────────── data: upload, mapping, preview ─────────────────────────
def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name)[:120] or "file"


async def _save_files(ds_id: str, files: List[UploadFile], start_index: int):
    saved, errors = [], []
    d = store.dataset_dir(ds_id)
    for n, f in enumerate(files, start=start_index):
        fname = f.filename or "upload"
        ext = Path(fname).suffix.lower()
        if ext not in ALLOWED_EXT:
            errors.append(f"{fname}: unsupported file type. Use CSV or Excel (.xlsx).")
            continue
        data = await f.read()
        if len(data) > MAX_BYTES:
            errors.append(f"{fname}: file is larger than 150 MB.")
            continue
        stored = f"{n:02d}_{_safe(fname)}"
        (d / stored).write_bytes(data)
        try:
            raw = ingest.read_table(d / stored)
            if len(raw) == 0:
                raise ValueError("The file has a header but no rows.")
            saved.append({"name": _safe(fname), "stored": stored, "rows": int(len(raw))})
        except Exception as e:
            (d / stored).unlink(missing_ok=True)
            errors.append(f"{fname}: {e}")
    return saved, errors


@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...), mode: str = "replace", name: str = ""):
    if not files:
        raise HTTPException(400, "Choose at least one file.")
    active = store.active_dataset()
    append = mode == "append" and active is not None
    if append:
        ds_id = active["id"]
        saved, errors = await _save_files(ds_id, files, len(active["files"]))
        if not saved:
            raise HTTPException(400, "No file could be added. " + " ".join(errors))
        ds = store.update_dataset(ds_id, files=active["files"] + saved)
    else:
        tmp_id = store.create_dataset(name.strip() or (Path(files[0].filename or "Upload").stem[:40] + (f" + {len(files) - 1} more" if len(files) > 1 else "")), [])
        saved, errors = await _save_files(tmp_id, files, 1)
        if not saved:
            store.delete_dataset(tmp_id)
            raise HTTPException(400, "No file could be read. " + " ".join(errors))
        ds = store.update_dataset(tmp_id, files=saved)
        ds_id = tmp_id
        store.set_active_dataset(ds_id)
    ingest.invalidate(ds_id)
    store.bump_version(ds_id)
    ds = store.get_dataset(ds_id)
    try:
        x, info = ingest.build_dataset(ds)
    except Exception as e:
        raise HTTPException(422, f"The file was saved but could not be analysed: {e}")
    store.update_dataset(ds_id, rows=int(len(x)))
    ran = []
    try:
        ran = automation.run_on_upload()
    except Exception:
        pass
    return {"ok": True, "dataset": summary(store.get_dataset(ds_id)), "files": [s["name"] for s in saved], "warnings": errors, "notes": info["notes"],
            "needs_mapping": not info["has"]["revenue"], "quality": info["quality"]["score"], "automations_run": [{"message": r["message"], "created": len(r["created"])} for r in ran]}


@app.post("/api/sample")
@app.post("/api/demo")
def sample():
    df = make_sample()
    ds_id = store.create_dataset("Sample shop (demo data)", [], True)
    d = store.dataset_dir(ds_id)
    df.to_csv(d / "01_sample_shop.csv", index=False)
    store.update_dataset(ds_id, files=[{"name": "sample_shop.csv", "stored": "01_sample_shop.csv", "rows": len(df)}], rows=len(df))
    store.set_active_dataset(ds_id)
    return {"ok": True, "dataset": summary(store.get_dataset(ds_id))}


@app.get("/api/template.csv")
def template():
    return Response(TEMPLATE_CSV, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=datapilot_template.csv"})


@app.get("/api/datasets")
def datasets():
    act = store.active_dataset()
    return {"datasets": [summary(d) for d in store.list_datasets()], "active": act["id"] if act else None}


@app.post("/api/datasets/{ds_id}/activate")
def activate(ds_id: str):
    if not store.get_dataset(ds_id):
        raise HTTPException(404, "Dataset not found.")
    store.set_active_dataset(ds_id)
    return {"ok": True}


@app.post("/api/datasets/{ds_id}/rename")
def rename(ds_id: str, body: Dict[str, Any]):
    nm = str(body.get("name", "")).strip()[:80]
    if not nm or not store.get_dataset(ds_id):
        raise HTTPException(400, "Enter a name for the dataset.")
    store.update_dataset(ds_id, name=nm)
    return {"ok": True}


@app.delete("/api/datasets/{ds_id}")
def delete_ds(ds_id: str):
    ingest.invalidate(ds_id)
    store.delete_dataset(ds_id)
    return {"ok": True}


def _mapping_view(ds):
    x, info = ingest.build_dataset(ds)
    det = info["detections"][0] if info["detections"] else {"roles": {}, "candidates": {}}
    roles = []
    for r in ingest.ROLES:
        used = info["roles"].get(r)
        d = det["roles"].get(r, {})
        roles.append({"role": r, "label": ingest.ROLE_LABELS[r], "help": ingest.ROLE_HELP[r], "column": used,
                      "confidence": d.get("confidence") if d.get("column") == used else ("you chose" if used else None), "candidates": det["candidates"].get(r, [])})
    ov = ds.get("overrides") or {}
    return {"roles": roles, "columns": info["all_columns"], "date_mode": ov.get("date_mode") or ("column" if info["roles"].get("date") else "none"),
            "rows_per_period": ov.get("rows_per_period") or 1, "sequence_start": ov.get("sequence_start") or "2026-01-01", "drop_duplicates": bool(ov.get("drop_duplicates")),
            "notes": info["notes"], "quality": info["quality"], "has": info["has"], "files": [f["name"] for f in ds["files"]], "rows": info["rows"]}


@app.get("/api/mapping")
def get_mapping():
    ds = store.active_dataset()
    if not ds:
        raise HTTPException(409, "No data yet.")
    try:
        return _mapping_view(ds)
    except Exception as e:
        raise HTTPException(422, f"Could not read the dataset: {e}")


@app.post("/api/mapping")
def set_mapping(body: Dict[str, Any]):
    ds = store.active_dataset()
    if not ds:
        raise HTTPException(409, "No data yet.")
    ov = dict(ds.get("overrides") or {})
    if isinstance(body.get("mapping"), dict):
        m = dict(ov.get("mapping") or {})
        for r, col in body["mapping"].items():
            if r in ingest.ROLES:
                m[r] = col if col else "__none__"
        ov["mapping"] = m
    for k in ("date_mode", "rows_per_period", "sequence_start", "drop_duplicates"):
        if k in body:
            ov[k] = body[k]
    if ov.get("date_mode") not in (None, "column", "none", "sequence"):
        raise HTTPException(400, "Unknown date option.")
    store.update_dataset(ds["id"], overrides=ov)
    ingest.invalidate(ds["id"])
    store.bump_version(ds["id"])
    ds = store.get_dataset(ds["id"])
    try:
        x, _ = ingest.build_dataset(ds)
        store.update_dataset(ds["id"], rows=int(len(x)))
        return _mapping_view(store.get_dataset(ds["id"]))
    except Exception as e:
        raise HTTPException(422, f"That mapping could not be applied: {e}")


@app.get("/api/data")
def data_preview(limit: int = 100, offset: int = 0, q: str = ""):
    c = ctx("all")
    x = c.x.drop(columns=[k for k in ("_cost", "_profit", "_rev_c", "_revenue_missing", "_source") if k in c.x.columns])
    if q.strip():
        mask = pd.Series(False, index=x.index)
        for col in ("product", "category", "customer", "order_id"):
            mask |= x[col].astype(str).str.contains(q.strip(), case=False, na=False, regex=False)
        x = x[mask]
    total = len(x)
    page = x.iloc[max(0, offset): max(0, offset) + max(1, min(limit, 500))].copy()
    if "date" in page:
        page["date"] = page["date"].dt.strftime("%Y-%m-%d")
    page = page.astype(object).where(page.notna(), "")
    return {"columns": list(page.columns), "rows": page.to_dict("records"), "total_rows": int(total)}


@app.get("/api/export/cleaned.csv")
def export_clean():
    c = ctx("all")
    x = c.x.drop(columns=[k for k in ("_cost", "_profit", "_rev_c", "_revenue_missing") if k in c.x.columns])
    return Response(x.to_csv(index=False), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=datapilot_cleaned_data.csv"})


@app.post("/api/rows")
def add_rows(body: Dict[str, Any]):
    """Quick entry: add sales one by one without a spreadsheet."""
    rows = body.get("rows") or []
    ds = store.active_dataset()
    if not rows:
        raise HTTPException(400, "Add at least one sale.")
    clean = []
    for r in rows:
        try:
            units = float(r.get("quantity") or 1)
            price = float(r.get("unit_price") or 0)
            amount = float(r.get("amount") or 0) or units * price
        except Exception:
            raise HTTPException(400, "Quantity, price and amount must be numbers.")
        if amount <= 0 and not r.get("allow_zero"):
            raise HTTPException(400, "Enter a sales amount, or a quantity and price.")
        clean.append({"Date": (r.get("date") or datetime.now().strftime("%Y-%m-%d")), "Category": r.get("category") or "", "Product": r.get("product") or "",
                      "Quantity": units, "Unit Price": price or round(amount / units, 2), "Sales Amount": round(amount, 2), "Cost": r.get("cost") or "", "Customer": r.get("customer") or ""})
    if not ds:
        ds_id = store.create_dataset("My sales", [])
        store.set_active_dataset(ds_id)
        ds = store.get_dataset(ds_id)
    d = store.dataset_dir(ds["id"])
    path = d / "99_manual_entries.csv"
    df = pd.DataFrame(clean)
    if path.exists():
        df = pd.concat([pd.read_csv(path), df], ignore_index=True)
    df.to_csv(path, index=False)
    files = [f for f in ds["files"] if f["stored"] != "99_manual_entries.csv"] + [{"name": "Quick entries", "stored": "99_manual_entries.csv", "rows": len(df)}]
    store.update_dataset(ds["id"], files=files)
    ingest.invalidate(ds["id"])
    store.bump_version(ds["id"])
    x, _ = ingest.build_dataset(store.get_dataset(ds["id"]))
    store.update_dataset(ds["id"], rows=int(len(x)))
    return {"ok": True, "added": len(clean), "total_rows": int(len(x))}


# ───────────────────────── analysis ─────────────────────────
@app.get("/api/dashboard")
def dashboard(period: str = ""):
    c = ctx(period or None)
    out = metrics.dashboard(c)
    out["insights"] = insights.build_insights(c)[:6]
    sg = insights.build_signals(c)
    out["signals"] = sg[:5]
    out["signal_counts"] = {"total": len(sg), "high": sum(1 for s in sg if s["severity"] == "high")}
    out["dataset"] = summary(c.ds)
    out["cost_mode"] = c.cost_mode
    return out


@app.get("/api/insights")
def get_insights(period: str = ""):
    c = ctx(period or None)
    return {"insights": insights.build_insights(c), "period": metrics.period_public(c.period), "quality": c.info["quality"]}


@app.get("/api/explore")
def get_explore(dim: str = "product", metric: str = "revenue", period: str = ""):
    c = ctx(period or None)
    try:
        return metrics.explore(c, dim, metric)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/patterns")
def get_patterns():
    return metrics.patterns(ctx("all"))


@app.get("/api/inventory")
def get_inventory():
    c = ctx("all")
    return metrics.inventory(c)


@app.get("/api/customers")
def get_customers(period: str = ""):
    return metrics.customers(ctx(period or "all"))


@app.get("/api/signals")
def get_signals(period: str = ""):
    return insights.signals_payload(ctx(period or None))


@app.get("/api/forecast")
def get_forecast(metric: str = "revenue", horizon: int = 0):
    c = ctx("all")
    out = fc.forecast(c, metric, horizon or None)
    out["metrics"] = [{"key": k, "label": v} for k, v in fc.METRICS.items() if k != "profit" or c.cost_mode]
    out["currency"] = c.sym
    return out


@app.get("/api/scenario/defaults")
def scenario_defaults():
    c = ctx("all")
    est = fc.estimate_elasticity(c)
    base = fc.forecast(c, "revenue") if c.has["date"] else {"available": False}
    return {"elasticity": est, "has_cost": bool(c.cost_mode), "baseline_total": base.get("summary", {}).get("total") if base.get("available") else None,
            "baseline_label": f"next {base['horizon']} {base['unit']}s" if base.get("available") else "your whole data file"}


@app.post("/api/scenario")
def scenario(body: Dict[str, Any]):
    c = ctx("all")
    try:
        inp = {k: body.get(k) for k in ("price_change", "demand_change", "cost_change", "discount", "extra_spend", "elasticity")}
        inp = {k: (v if v not in (None, "") else (None if k == "elasticity" else 0)) for k, v in inp.items()}
        res = fc.scenario(c, inp)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"Check the numbers you entered: {e}")
    return res


@app.get("/api/scenarios")
def list_scenarios():
    return {"scenarios": store.list_scenarios()}


@app.post("/api/scenarios")
def save_scenario(body: Dict[str, Any]):
    name = str(body.get("name") or "").strip()[:60] or "My scenario"
    sid = store.save_scenario(name, body.get("inputs") or {}, body.get("result") or {})
    return {"ok": True, "id": sid}


@app.delete("/api/scenarios/{sid}")
def del_scenario(sid: int):
    store.delete_scenario(sid)
    return {"ok": True}


# ───────────────────────── actions ─────────────────────────
def fire_webhook(event: str, action: dict):
    url = store.settings_full()["webhook"].get("url")
    if not url:
        return

    def _go():
        try:
            body = json.dumps({"event": event, "action": action, "sent_at": store.now()}, default=str).encode()
            req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


@app.get("/api/actions")
def get_actions(status: str = "all"):
    return {"actions": store.list_actions(status), "counts": store.action_counts()}


@app.post("/api/actions")
def create_action(body: Dict[str, Any]):
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Give the action a title.")
    a = store.create_action(title[:140], str(body.get("description") or "")[:1000], body.get("priority") or "medium", body.get("source") or "manual",
                            body.get("dedupe_key"), body.get("impact"), body.get("evidence"), body.get("due_date"))
    return {"action": a, "counts": store.action_counts()}


@app.patch("/api/actions/{aid}")
def patch_action(aid: int, body: Dict[str, Any]):
    if body.get("status") and body["status"] not in ("pending", "approved", "rejected", "done"):
        raise HTTPException(400, "Unknown status.")
    a = store.update_action(aid, **{k: body.get(k) for k in ("title", "description", "priority", "status", "note", "due_date")})
    if not a:
        raise HTTPException(404, "Action not found.")
    if body.get("status") in ("approved", "done"):
        fire_webhook("action." + body["status"], a)
    return {"action": a, "counts": store.action_counts()}


@app.post("/api/actions/{aid}/{status}")
def set_action_status(aid: int, status: str):
    return patch_action(aid, {"status": status})


@app.delete("/api/actions/{aid}")
def del_action(aid: int):
    store.delete_action(aid)
    return {"ok": True, "counts": store.action_counts()}


# ───────────────────────── automations ─────────────────────────
@app.get("/api/automations")
def get_automations():
    return {"automations": automation.public_list(), "schedules": automation.SCHEDULES, "runs": store.list_runs(25),
            "custom": {"metrics": automation.CUSTOM_METRICS, "conditions": automation.CUSTOM_CONDITIONS}}


@app.post("/api/automations")
def create_custom(body: Dict[str, Any]):
    name = str(body.get("name") or "").strip()[:60]
    metric, cond = body.get("metric"), body.get("condition")
    if not name or metric not in automation.CUSTOM_METRICS or cond not in automation.CUSTOM_CONDITIONS:
        raise HTTPException(400, "Name your alert and choose what to watch.")
    try:
        params = {"metric": metric, "condition": cond, "value": float(body.get("value")), "window_days": int(body.get("window_days") or 7)}
    except Exception:
        raise HTTPException(400, "Enter a number for the limit.")
    a = store.create_automation(name, f"Alert when {automation.CUSTOM_METRICS[metric].lower()} {automation.CUSTOM_CONDITIONS[cond]} {params['value']:g} (last {params['window_days']} days).",
                                "custom", params, body.get("schedule") or "daily", True, True)
    return {"automation": a}


@app.post("/api/automations/{aid}/run")
def run_automation(aid: int):
    try:
        return automation.run(aid, "manual")
    except KeyError:
        raise HTTPException(404, "Automation not found.")


@app.post("/api/automations/{aid}")
def update_automation(aid: int, body: Dict[str, Any]):
    cur = store.get_automation(aid)
    if not cur:
        raise HTTPException(404, "Automation not found.")
    fields: Dict[str, Any] = {}
    if "enabled" in body:
        fields["enabled"] = bool(body["enabled"])
    if "schedule" in body:
        if body["schedule"] not in automation.SCHEDULES:
            raise HTTPException(400, "Unknown schedule.")
        fields["schedule"] = body["schedule"]
    if isinstance(body.get("params"), dict):
        meta = {f["key"]: f for f in automation.CATALOG.get(cur["rule"], {}).get("fields", [])}
        p = dict(cur["params"])
        for k, v in body["params"].items():
            if k in meta:
                try:
                    v = float(v)
                except Exception:
                    raise HTTPException(400, f"{meta[k]['label']} must be a number.")
                p[k] = max(meta[k]["min"], min(meta[k]["max"], v))
            elif cur["rule"] == "custom" and k in ("value", "window_days", "metric", "condition"):
                p[k] = v
        fields["params"] = p
    return {"automation": store.update_automation(aid, **fields)}


@app.delete("/api/automations/{aid}")
def delete_custom(aid: int):
    store.delete_automation(aid)
    return {"ok": True}


# ───────────────────────── AI chat + agents ─────────────────────────
@app.post("/api/chat")
def chat(body: Dict[str, Any]):
    q = str(body.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "Type a question first.")
    ctx(None)  # raises a friendly 409 if there is no data
    store.add_chat("user", q)
    try:
        r = assistant.answer(q, body.get("period") or None)
    except Exception as e:
        r = {"answer": f"I ran into a problem while analysing that: {e}", "facts": [], "table": None, "actions": [], "tools": [], "powered_by": "DataPilot analysis", "followups": [], "page": None}
    store.add_chat("assistant", r["answer"], {k: r.get(k) for k in ("facts", "table", "actions", "tools", "powered_by", "llm_error", "followups", "page")})
    return r


@app.get("/api/chat/history")
def chat_history():
    return {"messages": store.chat_history(60)}


@app.delete("/api/chat")
def clear_chat():
    store.clear_chat()
    return {"ok": True}


@app.post("/api/agent/run")
def agent_run(body: Dict[str, Any]):
    q = str(body.get("question") or "").strip() or "What should I focus on right now?"
    ctx(None)
    return assistant.investigate(q, body.get("period") or None)


@app.get("/api/agent/runs")
def agent_runs():
    return {"runs": store.list_agent_runs(15)}


@app.get("/api/agent/runs/{rid}")
def agent_run_get(rid: int):
    r = store.get_agent_run(rid)
    if not r:
        raise HTTPException(404, "Run not found.")
    return r["result"]


# ───────────────────────── report + notifications ─────────────────────────
@app.get("/api/report")
def report(period: str = ""):
    c = ctx(period or None)
    d = metrics.dashboard(c)
    ins = insights.build_insights(c)
    sg = insights.build_signals(c)
    inv = metrics.inventory(c)
    f = fc.forecast(c, "revenue") if c.has["date"] else {"available": False}
    pend = [a for a in store.list_actions("pending")][:8]
    prof = c.prof
    return {"title": f"{prof.get('business_name') or 'Business'} — performance report", "generated": datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "period": d["period"], "dataset": c.ds["name"], "kpis": d["kpis"], "headline": d["headline"], "categories": d["categories"], "products": d["products"],
            "insights": ins[:8], "signals": sg[:8], "forecast": {"available": f.get("available"), "summary": f.get("summary"), "unit": f.get("unit"), "horizon": f.get("horizon"),
                                                                    "accuracy": f.get("accuracy"), "model": (f.get("model") or {}).get("name")} if f.get("available") else {"available": False, "reason": f.get("reason")},
            "stock": [i for i in inv.get("items", []) if i["status"] in ("out", "critical", "low")][:8] if inv.get("available") else [], "pending_actions": pend,
            "notes": c.info["notes"], "quality": c.info["quality"]["score"], "currency": c.sym}


@app.get("/api/notifications")
def notifications():
    pend = store.list_actions("pending")
    return {"count": len(pend), "pending": pend[:6], "runs": store.list_runs(5)}


# ───────────────────────── settings ─────────────────────────
@app.get("/api/settings")
def get_settings():
    return {**store.settings_public(), "ai_presets": llm.PRESETS, "periods": [{"key": k, "label": v} for k, v in metrics.PERIODS]}


@app.post("/api/settings/profile")
def save_profile(body: Dict[str, Any]):
    patch: Dict[str, Any] = {}
    for k, v in body.items():
        if k in ("low_stock_days", "lead_time_days", "safety_days", "fy_start_month"):
            try:
                patch[k] = max(1, min(int(float(v)), 365 if k != "fy_start_month" else 12))
            except Exception:
                raise HTTPException(400, f"{k.replace('_', ' ').capitalize()} must be a number.")
        elif k == "assumed_cost_pct":
            if v in (None, ""):
                patch[k] = None
            else:
                try:
                    patch[k] = max(0.0, min(float(v), 99.0))
                except Exception:
                    raise HTTPException(400, "Typical cost % must be a number between 0 and 99.")
        elif k in ("business_name", "owner_name", "currency", "business_type", "number_style", "default_period"):
            patch[k] = str(v)[:60]
    prof = store.update_profile(patch)
    metrics.ingest.invalidate()  # cost assumptions affect cached frames
    return {"profile": prof}


@app.post("/api/settings/ai")
def save_ai(body: Dict[str, Any]):
    return {"ai": store.update_ai(body)}


@app.post("/api/settings/ai/test")
def test_ai():
    text, err = llm.complete("You are a connection test.", "Reply with the single word: OK", timeout=25)
    cfg = llm.config()
    return {"ok": bool(text), "reply": text, "error": err, "model": cfg["model"], "provider": cfg["provider"]}


@app.post("/api/settings/webhook")
def save_webhook(body: Dict[str, Any]):
    url = str(body.get("url") or "").strip()
    if url and not re.match(r"^https?://", url):
        raise HTTPException(400, "The link must start with http:// or https://")
    return {"webhook": store.update_webhook(url)}


@app.post("/api/settings/webhook/test")
def test_webhook():
    url = store.settings_full()["webhook"].get("url")
    if not url:
        raise HTTPException(400, "Save a webhook link first.")
    try:
        req = urllib.request.Request(url, data=json.dumps({"event": "test", "message": "DataPilot webhook test"}).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return {"ok": True, "status": r.status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/settings/reset")
def reset(body: Dict[str, Any]):
    if body.get("confirm") != "RESET":
        raise HTTPException(400, "Type RESET to confirm.")
    ingest.invalidate()
    store.reset_everything()
    automation.seed()
    return {"ok": True}


# Serve the built interface if present (npm run build) so one command runs everything.
try:
    from fastapi.staticfiles import StaticFiles
    _dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if _dist.exists():
        app.mount("/", StaticFiles(directory=str(_dist), html=True), name="ui")
except Exception:
    pass
