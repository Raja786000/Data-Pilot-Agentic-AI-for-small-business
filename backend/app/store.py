"""Persistence layer: SQLite for records, JSON for settings, folders for datasets."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("DATAPILOT_DATA", ROOT / "data"))
DATASETS = DATA / "datasets"
DB = DATA / "datapilot.db"
SETTINGS = DATA / "settings.json"
DATA.mkdir(parents=True, exist_ok=True)
DATASETS.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jdump(x) -> str:
    return json.dumps(x, default=str, ensure_ascii=False)


def jload(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def _conn():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    return c


def execute(sql, args=()):
    with _lock:
        c = _conn()
        try:
            cur = c.execute(sql, args)
            c.commit()
            return cur.lastrowid
        finally:
            c.close()


def query(sql, args=()):
    with _lock:
        c = _conn()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()


def query_one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def _columns(table):
    return {r["name"] for r in query(f"PRAGMA table_info({table})")}


def _ensure(table, col, ddl):
    if col not in _columns(table):
        execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def init_db():
    execute("""CREATE TABLE IF NOT EXISTS datasets(
        id TEXT PRIMARY KEY, name TEXT, created_at TEXT, updated_at TEXT,
        files TEXT, overrides TEXT, rows INTEGER DEFAULT 0, is_sample INTEGER DEFAULT 0, version INTEGER DEFAULT 1)""")
    execute("""CREATE TABLE IF NOT EXISTS actions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT,
        priority TEXT DEFAULT 'medium', status TEXT DEFAULT 'pending',
        created_at TEXT, updated_at TEXT)""")
    for col, ddl in [("source", "TEXT DEFAULT 'manual'"), ("dedupe_key", "TEXT"), ("impact", "TEXT"),
                     ("evidence", "TEXT"), ("note", "TEXT"), ("due_date", "TEXT"), ("dataset_id", "TEXT")]:
        _ensure("actions", col, ddl)
    execute("""CREATE TABLE IF NOT EXISTS automations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT,
        trigger_type TEXT, enabled INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)""")
    for col, ddl in [("rule", "TEXT"), ("params", "TEXT"), ("schedule", "TEXT DEFAULT 'manual'"),
                     ("last_run_at", "TEXT"), ("last_message", "TEXT"), ("is_custom", "INTEGER DEFAULT 0")]:
        _ensure("automations", col, ddl)
    execute("""CREATE TABLE IF NOT EXISTS automation_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, automation_id INTEGER, ran_at TEXT,
        status TEXT, message TEXT, created_count INTEGER DEFAULT 0, trigger TEXT)""")
    execute("""CREATE TABLE IF NOT EXISTS chat(
        id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, text TEXT, meta TEXT, created_at TEXT)""")
    execute("""CREATE TABLE IF NOT EXISTS agent_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, summary TEXT, result TEXT, created_at TEXT)""")
    execute("""CREATE TABLE IF NOT EXISTS scenarios(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, inputs TEXT, result TEXT, created_at TEXT)""")


# ───────────────────────── settings ─────────────────────────
DEFAULTS = {
    "profile": {
        "business_name": "", "owner_name": "", "business_type": "retail",
        "currency": "₹", "number_style": "indian", "fy_start_month": 4,
        "low_stock_days": 7, "lead_time_days": 7, "safety_days": 3,
        "assumed_cost_pct": None, "default_period": "30d",
    },
    "ai": {"provider": "openai", "api_key": "", "model": "gpt-4o-mini", "base_url": ""},
    "webhook": {"url": ""},
    "active_dataset": None,
}


def _read_settings():
    raw = {}
    if SETTINGS.exists():
        raw = jload(SETTINGS.read_text(encoding="utf-8"), {}) or {}
    out = json.loads(json.dumps(DEFAULTS))
    # migrate old flat keys from earlier versions
    if raw.get("openai_api_key"):
        out["ai"]["api_key"] = raw["openai_api_key"]
    if raw.get("model"):
        out["ai"]["model"] = raw["model"]
    for k in ("profile", "ai", "webhook"):
        if isinstance(raw.get(k), dict):
            out[k].update(raw[k])
    out["active_dataset"] = raw.get("active_dataset")
    return out


def _write_settings(s):
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


def settings_full():
    return _read_settings()


def settings_public():
    s = _read_settings()
    key = s["ai"].get("api_key") or os.getenv("OPENAI_API_KEY", "")
    ai = dict(s["ai"])
    ai.pop("api_key", None)
    ai["configured"] = bool(key) or ai.get("provider") == "ollama"
    ai["key_hint"] = ("…" + key[-4:]) if key else ""
    return {"profile": s["profile"], "ai": ai, "webhook": s["webhook"], "active_dataset": s["active_dataset"]}


def update_profile(patch: dict):
    s = _read_settings()
    allowed = set(DEFAULTS["profile"])
    for k, v in patch.items():
        if k in allowed:
            s["profile"][k] = v
    _write_settings(s)
    return s["profile"]


def update_ai(patch: dict):
    s = _read_settings()
    for k in ("provider", "model", "base_url"):
        if k in patch and patch[k] is not None:
            s["ai"][k] = str(patch[k]).strip()
    if patch.get("api_key"):
        s["ai"]["api_key"] = patch["api_key"].strip()
    if patch.get("remove_key"):
        s["ai"]["api_key"] = ""
    _write_settings(s)
    return settings_public()["ai"]


def update_webhook(url: str):
    s = _read_settings()
    s["webhook"]["url"] = (url or "").strip()
    _write_settings(s)
    return s["webhook"]


def profile():
    return _read_settings()["profile"]


def set_active_dataset(ds_id):
    s = _read_settings()
    s["active_dataset"] = ds_id
    _write_settings(s)


# ───────────────────────── datasets ─────────────────────────
def dataset_dir(ds_id) -> Path:
    d = DATASETS / ds_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_dataset(name, files, is_sample=False):
    ds_id = uuid.uuid4().hex[:10]
    execute("INSERT INTO datasets(id,name,created_at,updated_at,files,overrides,rows,is_sample,version) VALUES(?,?,?,?,?,?,?,?,1)",
            (ds_id, name, now(), now(), jdump(files), jdump({}), 0, 1 if is_sample else 0))
    dataset_dir(ds_id)
    return ds_id


def get_dataset(ds_id):
    r = query_one("SELECT * FROM datasets WHERE id=?", (ds_id,))
    if not r:
        return None
    r["files"] = jload(r["files"], [])
    r["overrides"] = jload(r["overrides"], {})
    return r


def list_datasets():
    out = []
    for r in query("SELECT * FROM datasets ORDER BY updated_at DESC"):
        r["files"] = jload(r["files"], [])
        r["overrides"] = jload(r["overrides"], {})
        out.append(r)
    return out


def update_dataset(ds_id, **fields):
    cur = get_dataset(ds_id)
    if not cur:
        return None
    sets, args = [], []
    for k, v in fields.items():
        if k in ("files", "overrides"):
            v = jdump(v)
        sets.append(f"{k}=?")
        args.append(v)
    sets.append("updated_at=?")
    args.append(now())
    args.append(ds_id)
    execute(f"UPDATE datasets SET {', '.join(sets)} WHERE id=?", tuple(args))
    return get_dataset(ds_id)


def bump_version(ds_id):
    execute("UPDATE datasets SET version=version+1, updated_at=? WHERE id=?", (now(), ds_id))


def delete_dataset(ds_id):
    execute("DELETE FROM datasets WHERE id=?", (ds_id,))
    shutil.rmtree(DATASETS / ds_id, ignore_errors=True)
    s = _read_settings()
    if s.get("active_dataset") == ds_id:
        rest = list_datasets()
        s["active_dataset"] = rest[0]["id"] if rest else None
        _write_settings(s)


def active_dataset():
    s = _read_settings()
    ds = get_dataset(s["active_dataset"]) if s.get("active_dataset") else None
    if ds:
        return ds
    rest = list_datasets()
    if rest:
        set_active_dataset(rest[0]["id"])
        return rest[0]
    return None


# ───────────────────────── actions ─────────────────────────
def _action_row(r):
    r["evidence"] = jload(r.get("evidence"), None)
    r["priority"] = (r.get("priority") or "medium").lower()
    return r


def create_action(title, description, priority="medium", source="manual", dedupe_key=None,
                  impact=None, evidence=None, due_date=None):
    """Create an action. If an open/recent action with the same dedupe_key exists, return it instead."""
    priority = (priority or "medium").lower()
    if dedupe_key:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(timespec="seconds")
        ex = query_one("SELECT * FROM actions WHERE dedupe_key=? AND (status IN ('pending','approved') OR created_at>?) ORDER BY id DESC",
                       (dedupe_key, cutoff))
        if ex:
            r = _action_row(ex)
            r["created"] = False
            return r
    ds = get_dataset(_read_settings().get("active_dataset") or "")
    aid = execute("""INSERT INTO actions(title,description,priority,status,created_at,updated_at,source,dedupe_key,impact,evidence,due_date,dataset_id)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (title, description, priority, "pending", now(), now(), source, dedupe_key, impact,
                   jdump(evidence) if evidence else None, due_date, ds["id"] if ds else None))
    r = _action_row(query_one("SELECT * FROM actions WHERE id=?", (aid,)))
    r["created"] = True
    return r


def list_actions(status=None):
    if status and status != "all":
        rows = query("SELECT * FROM actions WHERE status=? ORDER BY id DESC", (status,))
    else:
        rows = query("SELECT * FROM actions ORDER BY id DESC")
    return [_action_row(r) for r in rows]


def get_action(aid):
    r = query_one("SELECT * FROM actions WHERE id=?", (aid,))
    return _action_row(r) if r else None


def update_action(aid, **fields):
    if not get_action(aid):
        return None
    allowed = {"title", "description", "priority", "status", "note", "due_date"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k}=?")
            args.append(v)
    if sets:
        sets.append("updated_at=?")
        args.append(now())
        args.append(aid)
        execute(f"UPDATE actions SET {', '.join(sets)} WHERE id=?", tuple(args))
    return get_action(aid)


def delete_action(aid):
    execute("DELETE FROM actions WHERE id=?", (aid,))


def action_counts():
    rows = query("SELECT status, COUNT(*) n FROM actions GROUP BY status")
    out = {"pending": 0, "approved": 0, "rejected": 0, "done": 0}
    for r in rows:
        out[r["status"]] = r["n"]
    out["all"] = sum(out.values())
    return out


# ───────────────────────── automations ─────────────────────────
def _auto_row(r):
    r["params"] = jload(r.get("params"), {}) or {}
    r["enabled"] = bool(r.get("enabled"))
    r["is_custom"] = bool(r.get("is_custom"))
    return r


def list_automations():
    return [_auto_row(r) for r in query("SELECT * FROM automations ORDER BY is_custom, id")]


def get_automation(aid):
    r = query_one("SELECT * FROM automations WHERE id=?", (aid,))
    return _auto_row(r) if r else None


def create_automation(name, description, rule, params, schedule="manual", enabled=False, is_custom=False):
    aid = execute("""INSERT INTO automations(name,description,trigger_type,enabled,created_at,updated_at,rule,params,schedule,is_custom)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (name, description, rule, 1 if enabled else 0, now(), now(), rule, jdump(params), schedule, 1 if is_custom else 0))
    return get_automation(aid)


def update_automation(aid, **fields):
    if not get_automation(aid):
        return None
    sets, args = [], []
    for k, v in fields.items():
        if k == "enabled":
            v = 1 if v else 0
        if k == "params":
            v = jdump(v)
        if k in ("enabled", "params", "schedule", "name", "description", "last_run_at", "last_message"):
            sets.append(f"{k}=?")
            args.append(v)
    if sets:
        sets.append("updated_at=?")
        args.append(now())
        args.append(aid)
        execute(f"UPDATE automations SET {', '.join(sets)} WHERE id=?", tuple(args))
    return get_automation(aid)


def delete_automation(aid):
    execute("DELETE FROM automations WHERE id=? AND is_custom=1", (aid,))


def log_run(aid, status, message, created, trigger):
    execute("INSERT INTO automation_runs(automation_id,ran_at,status,message,created_count,trigger) VALUES(?,?,?,?,?,?)",
            (aid, now(), status, message, created, trigger))
    execute("UPDATE automations SET last_run_at=?, last_message=? WHERE id=?", (now(), message, aid))


def list_runs(limit=30):
    return query("""SELECT r.*, a.name FROM automation_runs r LEFT JOIN automations a ON a.id=r.automation_id
                    ORDER BY r.id DESC LIMIT ?""", (limit,))


# ───────────────────────── chat / agent / scenarios ─────────────────────────
def add_chat(role, text, meta=None):
    return execute("INSERT INTO chat(role,text,meta,created_at) VALUES(?,?,?,?)", (role, text, jdump(meta) if meta else None, now()))


def chat_history(limit=60):
    rows = query("SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,))[::-1]
    for r in rows:
        r["meta"] = jload(r.get("meta"), None)
    return rows


def clear_chat():
    execute("DELETE FROM chat")


def save_agent_run(question, summary, result):
    return execute("INSERT INTO agent_runs(question,summary,result,created_at) VALUES(?,?,?,?)", (question, summary, jdump(result), now()))


def list_agent_runs(limit=15):
    rows = query("SELECT id,question,summary,created_at FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,))
    return rows


def get_agent_run(rid):
    r = query_one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    if r:
        r["result"] = jload(r["result"], {})
    return r


def save_scenario(name, inputs, result):
    return execute("INSERT INTO scenarios(name,inputs,result,created_at) VALUES(?,?,?,?)", (name, jdump(inputs), jdump(result), now()))


def list_scenarios():
    rows = query("SELECT * FROM scenarios ORDER BY id DESC LIMIT 20")
    for r in rows:
        r["inputs"] = jload(r["inputs"], {})
        r["result"] = jload(r["result"], {})
    return rows


def delete_scenario(sid):
    execute("DELETE FROM scenarios WHERE id=?", (sid,))


def reset_everything():
    for t in ("actions", "automation_runs", "chat", "agent_runs", "scenarios", "datasets"):
        execute(f"DELETE FROM {t}")
    shutil.rmtree(DATASETS, ignore_errors=True)
    DATASETS.mkdir(parents=True, exist_ok=True)
    s = _read_settings()
    s["active_dataset"] = None
    _write_settings(s)
