"""Owner-approved automations: rules that watch the data and create reviewable actions."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import store
from .insights import build_signals
from .metrics import Ctx, NoData, get_ctx, inventory, totals, pct_change, pct_s, num_s, group_table

SCHEDULES = {"manual": "Only when I click Run", "on_upload": "Whenever I upload data", "daily": "Every day", "weekly": "Every week"}

CATALOG = {
    "low_stock": {"name": "Low-stock watch", "description": "Flags products that will run out within a set number of days.", "params": {"cover_days": 7}, "schedule": "on_upload",
                  "fields": [{"key": "cover_days", "label": "Warn when stock lasts fewer than (days)", "min": 1, "max": 60}]},
    "reorder": {"name": "Reorder list", "description": "Builds one purchase list with suggested quantities for everything running low.", "params": {}, "schedule": "weekly", "fields": []},
    "daily_brief": {"name": "Daily business brief", "description": "Summarises sales, profit, stock and signals in a few lines.", "params": {}, "schedule": "daily", "fields": []},
    "sales_drop": {"name": "Sales drop alert", "description": "Alerts you when recent sales fall below the period before.", "params": {"drop_pct": 15, "window_days": 7}, "schedule": "on_upload",
                   "fields": [{"key": "drop_pct", "label": "Alert when sales fall by (%)", "min": 3, "max": 80}, {"key": "window_days", "label": "Compare the last (days)", "min": 3, "max": 60}]},
    "anomaly": {"name": "Unusual-day watch", "description": "Flags days with unusually low or high sales in the last two weeks.", "params": {}, "schedule": "on_upload", "fields": []},
    "margin_guard": {"name": "Margin guard", "description": "Warns when products sell below a minimum profit margin.", "params": {"min_margin": 10}, "schedule": "weekly",
                     "fields": [{"key": "min_margin", "label": "Minimum margin (%)", "min": 1, "max": 90}]},
    "dead_stock": {"name": "Slow-stock cleanup", "description": "Lists stock that has not sold in 30 days so you can clear it.", "params": {}, "schedule": "weekly", "fields": []},
    "data_freshness": {"name": "Data reminder", "description": "Reminds you to upload new sales when your data gets old.", "params": {"max_age_days": 3}, "schedule": "daily",
                       "fields": [{"key": "max_age_days", "label": "Remind me after (days without new data)", "min": 1, "max": 30}]},
}

CUSTOM_METRICS = {"sales": "Sales", "orders": "Orders", "avg_bill": "Average bill", "profit_margin": "Profit margin (%)", "items_sold": "Items sold"}
CUSTOM_CONDITIONS = {"drops_by_pct": "drops by (%)", "rises_by_pct": "rises by (%)", "below": "is below", "above": "is above"}


def seed():
    existing = {a["rule"] for a in store.list_automations() if a["rule"]}
    for old in store.list_automations():
        if not old["rule"]:
            store.execute("DELETE FROM automations WHERE id=?", (old["id"],))
    for key, d in CATALOG.items():
        if key not in existing:
            store.create_automation(d["name"], d["description"], key, d["params"], d["schedule"], False)


def _upsert_pending(key, title, desc, priority, source="automation", impact=None, evidence=None):
    ex = store.query_one("SELECT id FROM actions WHERE dedupe_key=? AND status='pending' ORDER BY id DESC", (key,))
    if ex:
        store.update_action(ex["id"], title=title, description=desc, priority=priority)
        return store.get_action(ex["id"]), False
    a = store.create_action(title, desc, priority, source, key, impact, evidence)
    return a, bool(a.get("created"))


def _res(created, found, message, report=None):
    return {"created": created, "found": found, "message": message, "report": report}


# ───────────────────────── rule implementations ─────────────────────────
def r_low_stock(c: Ctx, p):
    inv = inventory(c)
    if not inv["available"]:
        return _res([], 0, "No stock column in your data, so there is nothing to check.")
    days = float(p.get("cover_days") or 7)
    risky = [i for i in inv["items"] if i["status"] == "out" or (i["days_left"] is not None and i["days_left"] < days and i["status"] != "dead")]
    created = []
    for i in risky[:8]:
        left = "is out of stock" if i["status"] == "out" else f"has about {i['days_left']:.0f} day(s) of stock left"
        a, new = _upsert_pending(f"stock:{i['product']}", f"Low stock: {i['product']}", f"{i['product']} {left}. Sells about {i['per_day']}/day, {num_s(i['stock'])} in stock. Suggested order: {i['reorder_qty']:,} units.",
                                 "high" if i["status"] in ("out", "critical") else "medium", impact=f"{c.m(i['revenue_at_risk'])} sales at risk" if i["revenue_at_risk"] else None)
        created.append(a) if new else None
    return _res(created, len(risky), f"{len(risky)} product(s) below {days:.0f} days of stock; {len(created)} new action(s) created." if risky else "All products have enough stock.")


def r_reorder(c: Ctx, p):
    inv = inventory(c)
    if not inv["available"]:
        return _res([], 0, "No stock column in your data, so a reorder list cannot be built.")
    items = [i for i in inv["items"] if i["reorder_qty"] > 0 and i["status"] in ("out", "critical", "low", "watch")]
    if not items:
        return _res([], 0, "Nothing needs reordering right now.")
    lines = "; ".join(f"{i['product']} × {i['reorder_qty']:,}" for i in items[:15])
    a, new = _upsert_pending("reorder-list", f"Purchase list: {len(items)} product(s) to reorder", f"Suggested quantities (covering lead time + safety + 14 days): {lines}.", "high" if any(i["status"] in ("out", "critical") for i in items) else "medium")
    return _res([a] if new else [], len(items), f"Purchase list ready with {len(items)} product(s)." + (" Added to Actions." if new else " Existing list updated."), lines)


def _brief(c: Ctx):
    cur = totals(c.cur, c.has["order_id"])
    prev = totals(c.prev, c.has["order_id"]) if c.prev is not None else None
    ch = pct_change(cur["revenue"], prev["revenue"]) if prev else None
    parts = [f"Sales {c.m(cur['revenue'])}" + (f" ({pct_s(ch)} vs before)" if ch is not None else ""), f"{cur['orders']:,} orders"]
    if cur["profit"] is not None:
        parts.append(f"profit {c.m(cur['profit'])}")
    sigs = build_signals(c)
    hi = [s for s in sigs if s["severity"] == "high"]
    txt = ", ".join(parts) + f". {len(hi)} high-priority signal(s)" + (": " + "; ".join(s["title"] for s in hi[:3]) if hi else "") + "."
    return txt


def r_daily_brief(c: Ctx, p):
    txt = _brief(c)
    today = datetime.now().strftime("%Y-%m-%d")
    a, new = _upsert_pending(f"brief:{today}", f"Business brief for {datetime.now():%d %b}", txt, "low")
    return _res([a] if new else [], 1, txt, txt)


def r_sales_drop(c: Ctx, p):
    if not c.has["date"]:
        return _res([], 0, "Your data has no dates, so sales cannot be compared over time.")
    w, thr = int(p.get("window_days") or 7), float(p.get("drop_pct") or 15)
    end = c.x["date"].max()
    cur = c.x[c.x["date"] > end - pd.Timedelta(days=w)]["revenue"].sum()
    prev = c.x[(c.x["date"] <= end - pd.Timedelta(days=w)) & (c.x["date"] > end - pd.Timedelta(days=2 * w))]["revenue"].sum()
    ch = pct_change(cur, prev)
    if ch is None or ch > -thr:
        return _res([], 0, f"Sales changed {pct_s(ch)} over the last {w} days: within your {thr:.0f}% limit.")
    a, new = _upsert_pending("rule:sales-drop", f"Sales fell {abs(ch):.0f}% in the last {w} days", f"{c.m(cur)} versus {c.m(prev)} in the {w} days before. Check stock, prices and any events.", "high", impact=f"{c.m(prev - cur)} lower")
    return _res([a] if new else [], 1, f"Sales are down {abs(ch):.0f}%, beyond your {thr:.0f}% limit." + (" Action created." if new else " Existing action updated."))


def r_anomaly(c: Ctx, p):
    an = [s for s in build_signals(c) if s["type"] == "Sales anomaly" and s["tone"] == "bad" and s.get("action")]
    created = []
    for s in an[:3]:
        a, new = _upsert_pending(s["id"], s["action"]["title"], s["action"]["description"], "medium")
        created.append(a) if new else None
    return _res(created, len(an), f"{len(an)} unusually low day(s) in the last two weeks; {len(created)} new action(s)." if an else "No unusual days in the last two weeks.")


def r_margin_guard(c: Ctx, p):
    if not c.cost_mode:
        return _res([], 0, "No cost data, so margins cannot be checked. Add costs or set a typical cost % in Settings.")
    mm = float(p.get("min_margin") or 10)
    t = group_table(c.cur, "product", c.has["order_id"])
    t = t[t["margin"].notna() & (t["margin"] < mm) & (t["revenue"] > 0)].sort_values("margin")
    if t.empty:
        return _res([], 0, f"Every product earns at least {mm:.0f}% margin.")
    lines = "; ".join(f"{r.product} ({r.margin:.0f}%)" for r in t.head(8).itertuples())
    a, new = _upsert_pending("rule:margin", f"{len(t)} product(s) below {mm:.0f}% margin", f"Review prices or supplier costs: {lines}.", "medium")
    return _res([a] if new else [], len(t), f"{len(t)} product(s) are below {mm:.0f}% margin." + (" Action created." if new else ""), lines)


def r_dead_stock(c: Ctx, p):
    inv = inventory(c)
    if not inv["available"]:
        return _res([], 0, "No stock column in your data.")
    dead = [i for i in inv["items"] if i["status"] == "dead"]
    if not dead:
        return _res([], 0, "No slow-moving stock found.")
    a, new = _upsert_pending("dead-stock", f"{len(dead)} product(s) have not sold in 30 days", "Consider a clearance offer or bundle: " + ", ".join(i["product"] for i in dead[:10]) + ".", "low")
    return _res([a] if new else [], len(dead), f"{len(dead)} slow product(s) found.")


def r_freshness(c: Ctx, p):
    if not c.has["date"]:
        return _res([], 0, "Your data has no dates.")
    if c.ds.get("is_sample"):
        return _res([], 0, "This is sample data, so no reminder is needed.")
    lim = int(p.get("max_age_days") or 3)
    age = (pd.Timestamp(datetime.now().date()) - c.x["date"].max()).days
    if age <= lim:
        return _res([], 0, f"Latest data is {age} day(s) old. That is fresh enough.")
    a, new = _upsert_pending("rule:fresh", "Upload your latest sales", f"Your newest sale in DataPilot is from {c.x['date'].max():%d %b %Y} ({age} days ago). Upload recent data so alerts and forecasts stay accurate.", "medium")
    return _res([a] if new else [], 1, f"Data is {age} days old.")


RUNNERS = {"low_stock": r_low_stock, "reorder": r_reorder, "daily_brief": r_daily_brief, "sales_drop": r_sales_drop, "anomaly": r_anomaly,
           "margin_guard": r_margin_guard, "dead_stock": r_dead_stock, "data_freshness": r_freshness}


def r_custom(c: Ctx, p):
    metric, cond, val, w = p.get("metric", "sales"), p.get("condition", "drops_by_pct"), float(p.get("value", 10)), int(p.get("window_days", 7))
    if not c.has["date"]:
        return _res([], 0, "Your data has no dates.")
    end = c.x["date"].max()
    cur_df = c.x[c.x["date"] > end - pd.Timedelta(days=w)]
    prev_df = c.x[(c.x["date"] <= end - pd.Timedelta(days=w)) & (c.x["date"] > end - pd.Timedelta(days=2 * w))]

    def metric_val(df):
        t = totals(df, c.has["order_id"])
        return {"sales": t["revenue"], "orders": t["orders"], "avg_bill": t["aov"] or 0, "profit_margin": t["margin"] if t["margin"] is not None else float("nan"), "items_sold": t["units"]}[metric]
    a, b = metric_val(cur_df), metric_val(prev_df)
    ch = pct_change(a, b)
    hit = (cond == "drops_by_pct" and ch is not None and ch <= -val) or (cond == "rises_by_pct" and ch is not None and ch >= val) or (cond == "below" and a < val) or (cond == "above" and a > val)
    label = CUSTOM_METRICS.get(metric, metric)
    shown = c.m(a) if metric in ("sales", "avg_bill") else f"{a:.1f}" if metric == "profit_margin" else num_s(a)
    if not hit:
        return _res([], 0, f"Condition not met. {label} over the last {w} days: {shown}" + (f" ({pct_s(ch)} vs before)." if ch is not None else "."))
    key = f"custom:{p.get('_id', 0)}"
    a_, new = _upsert_pending(key, f"Alert: {label} {CUSTOM_CONDITIONS.get(cond, cond)} {val:g}", f"{label} over the last {w} days is {shown}" + (f" ({pct_s(ch)} vs the {w} days before)." if ch is not None else "."), "medium")
    return _res([a_] if new else [], 1, f"Condition met: {label} is {shown}." + (" Action created." if new else ""))


# ───────────────────────── execution ─────────────────────────
def run(aid: int, trigger="manual"):
    auto = store.get_automation(aid)
    if not auto:
        raise KeyError("Automation not found.")
    try:
        c = get_ctx(store.profile().get("default_period") or "30d")
        params = dict(auto["params"])
        if auto["rule"] == "custom":
            params["_id"] = aid
            res = r_custom(c, params)
        else:
            res = RUNNERS[auto["rule"]](c, params)
        status = "ok"
    except NoData as e:
        res, status = _res([], 0, str(e)), "skipped"
    except Exception as e:  # noqa
        res, status = _res([], 0, f"Could not run: {e}"), "failed"
    store.log_run(aid, status, res["message"], len(res["created"]), trigger)
    return {"ok": status != "failed", "status": status, "message": res["message"], "created": res["created"], "found": res["found"], "report": res.get("report"), "automation_id": aid}


def run_on_upload():
    out = []
    for a in store.list_automations():
        if a["enabled"] and a["schedule"] == "on_upload":
            out.append(run(a["id"], "upload"))
    return out


def _due(a, now):
    if not a["enabled"] or a["schedule"] not in ("daily", "weekly"):
        return False
    gap = timedelta(days=1 if a["schedule"] == "daily" else 7)
    if not a.get("last_run_at"):
        return True
    try:
        last = datetime.fromisoformat(a["last_run_at"])
    except Exception:
        return True
    return now - last >= gap


def tick():
    now = datetime.now(timezone.utc)
    ran = []
    for a in store.list_automations():
        if _due(a, now):
            ran.append(run(a["id"], "schedule"))
    return ran


_started = False


def start_scheduler(interval=60):
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            try:
                tick()
            except Exception:
                pass
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True, name="datapilot-scheduler").start()


def public_list():
    out = []
    for a in store.list_automations():
        meta = CATALOG.get(a["rule"], {})
        out.append({**a, "fields": meta.get("fields", []), "schedule_label": SCHEDULES.get(a["schedule"], a["schedule"])})
    return out
