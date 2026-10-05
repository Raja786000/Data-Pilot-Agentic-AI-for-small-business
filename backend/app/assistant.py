"""Question answering and the multi-agent investigation. Facts always come from code, never from the AI."""
from __future__ import annotations

import json
import re
import time

import numpy as np
import pandas as pd

from . import llm, store
from .forecast import forecast
from .insights import build_insights, build_signals
from .metrics import (Ctx, explore, get_ctx, group_table, inventory, customers, patterns, totals, pct_change, r2, pct_s, num_s)

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _n_from(q, default=5):
    m = re.search(r"\b(?:top|best|worst|bottom|first|lowest|highest)\s+(\d{1,2}|" + "|".join(NUM_WORDS) + r")\b", q)
    if m:
        v = m.group(1)
        return int(v) if v.isdigit() else NUM_WORDS[v]
    return default


def _period_from(q, default):
    if re.search(r"\b(today|yesterday)\b", q):
        return "7d"
    if re.search(r"last (week|7 days)|past week", q):
        return "7d"
    if re.search(r"last month|previous month", q):
        return "lastmonth"
    if re.search(r"this month|month so far", q):
        return "mtd"
    if re.search(r"last 90|quarter|3 months", q):
        return "90d"
    if re.search(r"this year|financial year|fy\b|year to date", q):
        return "fytd"
    if re.search(r"last year|12 months|all time|overall|ever", q):
        return "all" if "all" in q or "ever" in q or "overall" in q else "365d"
    if re.search(r"last 30|30 days", q):
        return "30d"
    return default


def _the(label):
    l = label.lower()
    return "the " + l if l.startswith("last") else l


def _day(iso):
    try:
        return pd.Timestamp(iso).strftime("%a %d %b")
    except Exception:
        return iso


def _intents(q: str, c: Ctx):
    q = q.lower()
    hit = []

    def has(*words):
        return any(re.search(r"\b" + w, q) for w in words)
    if has("why") and has("sales", "revenue", "profit", "income", "business", "drop", "down", "fall", "fell", "decreas", "declin", "lower", "increas", "grow", "chang") or has("what happened", "what changed", "reason for", "root cause", "explain"):
        hit.append("why")
    if has("forecast", "predict", "next week", "next month", "next 30", "expect", "projection", "future", "will my"):
        hit.append("forecast")
    if has("stock", "inventory", "reorder", "restock", "run out", "out of", "supplier", "order more"):
        hit.append("stock")
    if has("customer", "repeat", "loyal", "retention", "buyers", "churn"):
        hit.append("customers")
    if has("losing money", "loss", "below cost", "unprofitable", "worst", "lowest", "weak", "slow", "underperform", "bottom", "least"):
        hit.append("worst")
    if has("best", "top", "highest", "most", "star", "bestseller", "best-seller", "popular", "biggest"):
        hit.append("best")
    if has("profit", "margin", "earn", "make money", "making money"):
        hit.append("profit")
    if has("weekday", "which day", "busiest", "day of the week", "weekend", "monday", "friday", "saturday", "sunday"):
        hit.append("weekday")
    if has("what should i", "priority", "priorities", "fix first", "focus", "advice", "advise", "improve", "grow", "next step", "to do", "recommend", "this week", "action"):
        hit.append("plan")
    if has("quality", "missing", "clean", "columns", "rows", "my data", "dataset"):
        hit.append("data")
    if has("discount", "offer", "promo", "coupon"):
        hit.append("discount")
    for d in c.info["dims"]:
        if d not in ("product", "category") and re.search(r"\b" + re.escape(d.lower()) + r"s?\b", q):
            hit.append("dim:" + d)
    if has("summary", "overview", "how am i doing", "how is my business", "how's my business", "status", "snapshot") or not hit:
        hit.append("summary")
    if any(h.startswith("dim:") for h in hit) and "best" in hit and not re.search(r"product|item", q):
        hit.remove("best")
    # keep order, drop duplicates; limit to 3 topics
    seen, out = set(), []
    for h in hit:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:3]


# ───────────────────────── tools ─────────────────────────
def tool_summary(c: Ctx, q):
    oid = c.has["order_id"]
    cur = totals(c.cur, oid)
    prev = totals(c.prev, oid) if c.prev is not None else None
    ch = pct_change(cur["revenue"], prev["revenue"]) if prev else None
    facts = [("Sales", c.m(cur["revenue"])), ("Orders", f"{cur['orders']:,}")]
    if ch is not None:
        facts.append(("Change vs previous", pct_s(ch)))
    if cur["profit"] is not None:
        facts.append(("Profit" + (" (estimated)" if c.cost_mode == "estimated" else ""), c.m(cur["profit"])))
    text = f"For {_the(c.period['label'])}, sales are {c.m(cur['revenue'])} across {cur['orders']:,} {'orders' if oid else 'transactions'}."
    if ch is not None:
        text += f" That is {abs(ch):.1f}% {'higher' if ch >= 0 else 'lower'} than the previous period."
    if cur["profit"] is not None:
        text += f" {'Estimated profit' if c.cost_mode == 'estimated' else 'Profit'} is {c.m(cur['profit'])} ({cur['margin']:.1f}% margin)."
    top = build_insights(c)[:2]
    for i in top:
        text += f" {i['title']}."
    return {"text": text, "facts": facts, "page": "home"}


def drivers(c: Ctx):
    """Why did sales change? Price vs volume plus the biggest movers."""
    if c.prev is None:
        return None
    oid = c.has["order_id"]
    cur, prev = totals(c.cur, oid), totals(c.prev, oid)
    d = cur["revenue"] - prev["revenue"]
    res = {"delta": d, "pct": pct_change(cur["revenue"], prev["revenue"]), "cur": cur, "prev": prev}
    if c.has["units"] and prev["units"] and cur["units"]:
        pa, ca = prev["revenue"] / prev["units"], cur["revenue"] / cur["units"]
        res["volume_effect"] = (cur["units"] - prev["units"]) * pa
        res["price_effect"] = cur["units"] * (ca - pa)
    elif prev["orders"] and cur["orders"]:
        res["volume_effect"] = (cur["orders"] - prev["orders"]) * prev["aov"]
        res["price_effect"] = cur["orders"] * (cur["aov"] - prev["aov"])
        res["basis"] = "orders"
    movers = {}
    for dim, ok in (("category", c.has["category"]), ("product", c.has["product"])):
        if not ok:
            continue
        a = group_table(c.cur, dim, oid).set_index(dim)["revenue"]
        b = group_table(c.prev, dim, oid).set_index(dim)["revenue"]
        diff = a.sub(b, fill_value=0).sort_values()
        movers[dim] = {"down": [(k, float(v)) for k, v in diff.head(3).items() if v < 0], "up": [(k, float(v)) for k, v in diff.tail(3).items() if v > 0][::-1]}
    res["movers"] = movers
    return res


def tool_why(c: Ctx, q):
    if not c.has["date"]:
        return {"text": "I can't compare periods because your data has no dates. Add a date column in Data Studio → Column mapping and ask again.", "facts": [], "page": "data"}
    dr = drivers(c)
    if not dr:
        return {"text": f"There is not enough history before {c.period['label'].lower()} to compare. Try a shorter period such as Last 7 days.", "facts": [], "page": None}
    m = c.m
    word = "rose" if dr["delta"] >= 0 else "fell"
    lines = [f"Sales {word} {abs(dr['pct'] or 0):.1f}% ({m(abs(dr['delta']))}) compared with the previous period."]
    facts = [("Now", m(dr["cur"]["revenue"])), ("Before", m(dr["prev"]["revenue"])), ("Difference", ("+" if dr["delta"] >= 0 else "-") + m(abs(dr["delta"])))]
    if "volume_effect" in dr:
        ve, pe = dr["volume_effect"], dr["price_effect"]
        unit = "items sold" if "basis" not in dr else "orders"
        lines.append(f"About {m(abs(ve))} of the change came from {'more' if ve >= 0 else 'fewer'} {unit}, and {m(abs(pe))} from {'higher' if pe >= 0 else 'lower'} {'prices and product mix' if 'basis' not in dr else 'bill size'}.")
    for dim, label in (("category", "category"), ("product", "product")):
        mv = dr["movers"].get(dim)
        if not mv:
            continue
        pick = mv["down"] if dr["delta"] < 0 else mv["up"]
        if pick:
            lines.append(f"Biggest {'drops' if dr['delta'] < 0 else 'gains'} by {label}: " + ", ".join(f"{k} ({'-' if v < 0 else '+'}{m(abs(v))})" for k, v in pick) + ".")
    inv = inventory(c)
    if inv["available"] and dr["delta"] < 0:
        risky = {i["product"] for i in inv["items"] if i["status"] in ("out", "critical", "low")}
        fell = {k for k, _ in dr["movers"].get("product", {}).get("down", [])}
        both = risky & fell
        if both:
            lines.append(f"Stock may be part of the reason: {', '.join(sorted(both))} fell in sales and are also low on stock.")
    return {"text": " ".join(lines), "facts": facts, "page": "insights",
            "actions": [{"title": "Find out why sales changed", "description": " ".join(lines[:2]), "priority": "high", "dedupe_key": "why-change"}] if dr["delta"] < -0.05 * dr["prev"]["revenue"] else []}


def tool_best(c: Ctx, q):
    dim = "category" if re.search(r"categor", q) and c.has["category"] else "product" if c.has["product"] else "category"
    n = _n_from(q.lower())
    metric = "profit" if (c.cost_mode and re.search(r"profit|margin", q)) else "units" if (c.has["units"] and re.search(r"sold|units|quantity|popular", q)) else "revenue"
    r = explore(c, dim, metric, n)
    rows = r["rows"][:n]
    label = {"revenue": "sales", "profit": "profit", "units": "items sold"}[metric]
    fmt = (lambda v: c.m(v)) if metric != "units" else (lambda v: num_s(v))
    plural = "categories" if dim == "category" else dim + "s"
    text = f"Your top {len(rows)} {plural} by {label}: " + "; ".join(f"{i + 1}. {x['name']} ({fmt(x[metric])})" for i, x in enumerate(rows)) + "."
    return {"text": text, "table": {"columns": [dim.title(), label.title(), "Share"], "rows": [[x["name"], fmt(x[metric]), f"{x['share']:.1f}%"] for x in rows]}, "facts": [], "page": "insights"}


def tool_worst(c: Ctx, q):
    n = _n_from(q.lower(), 5)
    if c.cost_mode and re.search(r"profit|loss|losing|below cost|margin|money", q.lower()):
        r = explore(c, "product", "profit", 200)
        rows = sorted([x for x in r["rows"] if x["profit"] is not None], key=lambda z: z["profit"])[:n]
        loss = [x for x in rows if x["profit"] < 0]
        if loss:
            text = f"{len(loss)} product(s) lose money: " + "; ".join(f"{x['name']} ({c.m(x['profit'])})" for x in loss) + ". Raise the price or cut the cost."
        else:
            text = "No product is selling below cost. The thinnest earners are: " + "; ".join(f"{x['name']} ({c.m(x['profit'])}, {x['margin']:.0f}% margin)" for x in rows[:n]) + "."
        return {"text": text, "table": {"columns": ["Product", "Sales", "Profit", "Margin"], "rows": [[x["name"], c.m(x["revenue"]), c.m(x["profit"]), f"{x['margin']:.1f}%" if x["margin"] is not None else "—"] for x in rows]}, "facts": [], "page": "insights",
                "actions": [{"title": "Fix products selling below cost", "description": text, "priority": "high", "dedupe_key": "below-cost"}] if loss else []}
    dim = "category" if re.search(r"categor", q.lower()) and c.has["category"] else "product"
    r = explore(c, dim, "revenue", 500)
    rows = r["rows"][-n:][::-1]
    text = f"Your {len(rows)} weakest {dim}s by sales: " + "; ".join(f"{x['name']} ({c.m(x['revenue'])})" for x in rows) + "."
    if not c.cost_mode:
        text += " Add costs or a typical cost % in Settings to see which ones actually lose money."
    return {"text": text, "table": {"columns": [dim.title(), "Sales", "Share"], "rows": [[x["name"], c.m(x["revenue"]), f"{x['share']:.1f}%"] for x in rows]}, "facts": [], "page": "insights"}


def tool_profit(c: Ctx, q):
    cur = totals(c.cur, c.has["order_id"])
    if cur["profit"] is None:
        return {"text": "I can't calculate profit because there are no costs in your data. Upload a file with a cost column, or set a typical cost % in Settings → Business profile and I will estimate it.", "facts": [], "page": "settings"}
    est = " (an estimate based on your typical cost %)" if c.cost_mode == "estimated" else ""
    text = f"Profit for {_the(c.period['label'])} is {c.m(cur['profit'])}{est}, a {cur['margin']:.1f}% margin on {c.m(cur['revenue'])} sales."
    if c.has["product"] and c.cost_mode == "actual":
        r = explore(c, "product", "profit", 3)["rows"]
        text += " Most profitable: " + ", ".join(f"{x['name']} ({c.m(x['profit'])})" for x in r) + "."
    return {"text": text, "facts": [("Profit", c.m(cur["profit"])), ("Margin", f"{cur['margin']:.1f}%")], "page": "insights"}


def tool_stock(c: Ctx, q):
    inv = inventory(c)
    if not inv["available"]:
        return {"text": inv["reason"], "facts": [], "page": "data"}
    s = inv["summary"]
    need = [i for i in inv["items"] if i["status"] in ("out", "critical", "low")]
    if not need:
        return {"text": f"Stock looks healthy: none of your {s['total']} products is below {inv['settings']['low_stock_days']:.0f} days of cover.", "facts": [("Products tracked", s["total"])], "page": "inventory"}
    text = f"{len(need)} product(s) need attention: " + "; ".join(f"{i['product']} ({'out of stock' if i['status'] == 'out' else str(round(i['days_left'], 1)) + ' days left'}, order about {i['reorder_qty']:,})" for i in need[:6]) + f". Roughly {c.m(s['revenue_at_risk'])} of sales are at risk before new stock arrives."
    return {"text": text, "table": {"columns": ["Product", "In stock", "Days left", "Order"], "rows": [[i["product"], num_s(i["stock"]), "0" if i["status"] == "out" else num_s(i["days_left"]), f"{i['reorder_qty']:,}"] for i in need[:8]]}, "facts": [("Need action", s["needs_action"]), ("Sales at risk", c.m(s["revenue_at_risk"]))], "page": "inventory",
            "actions": [{"title": f"Reorder {i['product']}", "description": f"Stock {num_s(i['stock'])}, selling {i['per_day']}/day. Suggested order {i['reorder_qty']:,} units.", "priority": "high", "dedupe_key": f"stock:{i['product']}"} for i in need[:3]]}


def tool_forecast(c: Ctx, q):
    ql = q.lower()
    hz = 30 if re.search(r"next month|30 days", ql) else 7 if re.search(r"next week|7 days", ql) else None
    f = forecast(c, "profit" if (re.search(r"profit", ql) and c.cost_mode) else "revenue", hz)
    if not f["available"]:
        return {"text": f["reason"], "facts": [], "page": "data"}
    s = f["summary"]
    text = f"I expect {f['metric_label'].lower()} of about {c.m(s['total'])} over the next {f['horizon']} {f['unit']}s" + (f", {abs(s['change']):.1f}% {'above' if s['change'] >= 0 else 'below'} the last {f['horizon']} {f['unit']}s" if s["change"] is not None else "") + f". The strongest day should be {_day(s['peak'])} and the weakest {_day(s['low'])}. The model ({f['model']['name'].lower()}) was about {f['accuracy']:.0f}% accurate when tested on your recent history, so treat it as a planning guide."
    return {"text": text, "facts": [("Expected total", c.m(s["total"])), ("Accuracy on past data", f"{f['accuracy']:.0f}%")], "page": "forecast"}


def tool_customers(c: Ctx, q):
    cu = customers(c)
    if not cu["available"]:
        return {"text": cu["reason"], "facts": [], "page": "customers"}
    text = f"You have {cu['total']:,} customers. {cu['repeat_rate']:.0f}% bought more than once, and your top 10% bring {cu['top10_share']:.0f}% of sales."
    if cu["segments"].get("At risk"):
        text += f" {cu['segments']['At risk']} repeat customers have gone quiet and are worth contacting."
    return {"text": text, "facts": [("Customers", f"{cu['total']:,}"), ("Repeat rate", f"{cu['repeat_rate']:.0f}%")], "page": "customers"}


def tool_weekday(c: Ctx, q):
    p = patterns(c)
    if not p.get("available"):
        return {"text": p.get("reason", "Not enough data for day-of-week patterns."), "facts": [], "page": "insights"}
    w = sorted(p["weekday"], key=lambda z: -z["avg_revenue"])
    text = f"{w[0]['day']} is your strongest day (about {c.m(w[0]['avg_revenue'])} on average) and {w[-1]['day']} your weakest ({c.m(w[-1]['avg_revenue'])})."
    return {"text": text, "table": {"columns": ["Day", "Average sales"], "rows": [[x["day"], c.m(x["avg_revenue"])] for x in p["weekday"]]}, "facts": [], "page": "insights"}


def tool_dim(c: Ctx, q, dim):
    r = explore(c, dim, "revenue", 8)
    rows = r["rows"]
    if not rows:
        return {"text": f"No data for {dim}.", "facts": []}
    text = f"By {dim}, “{rows[0]['name']}” leads with {c.m(rows[0]['revenue'])} ({rows[0]['share']:.0f}% of sales) and “{rows[-1]['name']}” is lowest with {c.m(rows[-1]['revenue'])}."
    if rows[0]["aov"] and rows[-1]["aov"]:
        top_aov = max(rows, key=lambda z: z["aov"] or 0)
        text += f" The highest average bill is “{top_aov['name']}” at {c.m(top_aov['aov'])}."
    return {"text": text, "table": {"columns": [dim, "Sales", "Share", "Avg bill"], "rows": [[x["name"], c.m(x["revenue"]), f"{x['share']:.1f}%", c.m(x["aov"])] for x in rows]}, "facts": [], "page": "insights"}


def tool_discount(c: Ctx, q):
    ins = [i for i in build_insights(c) if i["id"] == "discount"]
    if not ins:
        return {"text": "I could not find a discount column in your data, so I can't measure how discounts perform.", "facts": [], "page": "data"}
    return {"text": ins[0]["title"] + ". " + ins[0]["detail"], "facts": [], "page": "insights"}


def tool_plan(c: Ctx, q):
    acts = ranked_recommendations(c)[:4]
    if not acts:
        return {"text": "Nothing urgent stands out. Keep an eye on stock and sales trends, and check back after your next upload.", "facts": [], "page": "home"}
    text = "Here is what I would do first: " + " ".join(f"{i + 1}) {a['title']}." for i, a in enumerate(acts))
    text += " " + " ".join(a["description"] for a in acts[:2])
    return {"text": text, "table": {"columns": ["Priority", "Action", "Why it matters"], "rows": [[a["priority"].title(), a["title"], a.get("impact") or "—"] for a in acts]}, "facts": [], "page": "actions", "actions": acts}


def tool_data(c: Ctx, q):
    qq = c.info["quality"]
    bad = [k["label"] + ": " + k["detail"] for k in qq["checks"] if k["status"] in ("warn", "bad")]
    text = f"Your data has {c.info['rows']:,} rows and {c.info['columns']} columns" + (f", covering {c.info['date_range']['start']} to {c.info['date_range']['end']}" if c.info["date_range"] else ", with no dates") + f". Data quality is {qq['score']}/100."
    if bad:
        text += " Things to check: " + " ".join(bad[:3])
    return {"text": text, "facts": [("Rows", f"{c.info['rows']:,}"), ("Quality", f"{qq['score']}/100")], "page": "data"}


TOOLS = {"summary": tool_summary, "why": tool_why, "best": tool_best, "worst": tool_worst, "profit": tool_profit, "stock": tool_stock,
         "forecast": tool_forecast, "customers": tool_customers, "weekday": tool_weekday, "plan": tool_plan, "data": tool_data, "discount": tool_discount}


def ranked_recommendations(c: Ctx):
    seen, out = set(), []
    items = [s["action"] for s in build_signals(c) if s.get("action")] + [i["action"] for i in build_insights(c) if i.get("action")]
    order = {"high": 0, "medium": 1, "low": 2}
    for a in sorted(items, key=lambda a: order.get(a["priority"], 1)):
        k = a.get("dedupe_key") or a["title"]
        if k in seen:
            continue
        seen.add(k)
        out.append(a)
    return out


SYSTEM = ("You are DataPilot, a friendly business advisor for small-shop owners. Answer in simple, plain language (no jargon), in at most 140 words. "
          "Use ONLY the verified facts provided. Never invent numbers. If the facts do not answer the question, say what is missing. "
          "Use the currency symbol as written. End with one short practical suggestion.")


def answer(question: str, period=None):
    c = get_ctx(_period_from(question.lower(), period))
    intents = _intents(question, c)
    results, used = [], []
    for it in intents:
        try:
            r = tool_dim(c, question, it[4:]) if it.startswith("dim:") else TOOLS[it](c, question)
        except Exception as e:  # keep the chat alive even if one tool fails
            r = {"text": f"I could not complete the '{it}' analysis ({e}).", "facts": []}
        results.append(r)
        used.append(it)
    local = "\n\n".join(r["text"] for r in results)
    facts = [f for r in results for f in r.get("facts", [])][:6]
    table = next((r["table"] for r in results if r.get("table")), None)
    actions = [a for r in results for a in r.get("actions", [])][:4]
    page = next((r["page"] for r in results if r.get("page")), None)
    text, powered, llm_error = local, "DataPilot analysis", None
    if llm.config()["ready"]:
        hist = store.chat_history(6)
        convo = "\n".join(f"{h['role']}: {h['text'][:300]}" for h in hist[-4:])
        user = f"Owner's question: {question}\nPeriod: {c.period['label']}\nCurrency: {c.sym}\nVerified facts:\n{local}\n" + (f"\nRecent conversation:\n{convo}" if convo else "")
        out, err = llm.complete(SYSTEM, user[:7000])
        if out:
            text, powered = out, f"AI · {llm.config()['model']}"
        else:
            llm_error = err
    followups = {"why": ["Which products need stock?", "What should I do this week?"], "stock": ["Show my forecast", "Which products are the best sellers?"],
                 "forecast": ["Why did sales change?", "What should I do this week?"]}.get(used[0], ["Why did sales change?", "Which products need stock?", "What should I do this week?"])
    return {"answer": text, "facts": [{"label": a, "value": b} for a, b in facts], "table": table, "actions": actions, "tools": used,
            "powered_by": powered, "llm_error": llm_error, "followups": followups, "page": page, "period": c.period["label"]}


# ───────────────────────── multi-agent investigation ─────────────────────────
def investigate(question: str, period=None):
    c = get_ctx(period)
    steps = []

    def step(name, role, fn):
        t = time.time()
        try:
            detail, data = fn()
            status = "done"
        except Exception as e:
            detail, data, status = f"Could not finish: {e}", {}, "failed"
        steps.append({"name": name, "role": role, "status": status, "detail": detail, "data": data, "ms": int((time.time() - t) * 1000)})
        return data

    def profiler():
        di = c.info["date_range"]
        used = [k for k, v in c.info["roles"].items() if v]
        return (f"Read {c.info['rows']:,} rows and {c.info['columns']} columns" + (f" from {di['start']} to {di['end']}" if di else "") + f". Recognised: {', '.join(used)}.", {"rows": c.info["rows"], "roles": used})
    step("Data Profiler", "Understands your file", profiler)

    def quality():
        q = c.info["quality"]
        bad = [k for k in q["checks"] if k["status"] in ("warn", "bad")]
        return (f"Quality score {q['score']}/100." + (f" {len(bad)} check(s) need a look: " + "; ".join(k["label"] for k in bad[:3]) + "." if bad else " All checks passed."), {"score": q["score"]})
    step("Quality Agent", "Checks the data can be trusted", quality)

    sigs = []

    def signal():
        nonlocal sigs
        sigs = build_signals(c)
        hi = [s for s in sigs if s["severity"] == "high"]
        return (f"Found {len(sigs)} signal(s), {len(hi)} high priority." + (" Top: " + sigs[0]["title"] + "." if sigs else ""), {"count": len(sigs), "high": len(hi)})
    step("Signal Agent", "Watches for problems and unusual days", signal)

    dr_text = []

    def rootcause():
        r = tool_why(c, "why did sales change")
        dr_text.append(r["text"])
        return r["text"], {}
    step("Root-cause Agent", "Explains what changed and why", rootcause)

    def fc():
        f = forecast(c)
        if not f["available"]:
            return f["reason"], {}
        s = f["summary"]
        return (f"Next {f['horizon']} {f['unit']}s: about {c.m(s['total'])} ({pct_s(s['change'])} vs the last {f['horizon']}). Backtest accuracy {f['accuracy']:.0f}% using {f['model']['name'].lower()}.", {"accuracy": f["accuracy"]})
    step("Forecast Agent", "Looks ahead", fc)

    def stock():
        r = tool_stock(c, "stock")
        return r["text"], {}
    if c.has["inventory"]:
        step("Inventory Agent", "Protects you from stock-outs", stock)

    def cust():
        r = tool_customers(c, "")
        return r["text"], {}
    if c.has["customer"] and customers(c).get("available"):
        step("Customer Agent", "Finds loyal and quiet customers", cust)

    recs = []

    def recommend():
        nonlocal recs
        recs = ranked_recommendations(c)[:6]
        return (f"Ranked {len(recs)} recommended action(s) by urgency and impact." if recs else "No urgent actions found.", {"count": len(recs)})
    step("Recommendation Agent", "Turns evidence into next steps", recommend)

    created = []
    for r in recs:
        a = store.create_action(r["title"], r["description"], r["priority"], "agent", r.get("dedupe_key"), r.get("impact"), {"question": question})
        created.append(a)
    new_n = sum(1 for a in created if a.get("created"))
    steps.append({"name": "Approval Gate", "role": "You stay in control", "status": "waiting",
                  "detail": (f"{new_n} new action(s) were added to your Action Center and are waiting for your approval." if new_n else "Nothing new to approve. Existing actions are already in your Action Center.") + " Nothing is executed automatically.",
                  "data": {}, "ms": 0})

    ins = build_insights(c)
    findings = [i["title"] + ". " + i["detail"] for i in ins[:4]]
    summary = " ".join(dr_text[:1]) or (ins[0]["title"] if ins else "Analysis complete.")
    powered = "DataPilot analysis"
    llm_error = None
    if llm.config()["ready"]:
        user = f"Owner's question: {question}\nCurrency: {c.sym}\nVerified findings:\n" + "\n".join("- " + f for f in findings) + "\nTop actions:\n" + "\n".join("- " + r["title"] + ": " + r["description"] for r in recs[:4])
        out, err = llm.complete(SYSTEM, user[:7000])
        if out:
            summary, powered = out, f"AI · {llm.config()['model']}"
        else:
            llm_error = err
    result = {"question": question, "summary": summary, "findings": findings, "steps": steps, "recommendations": created, "powered_by": powered, "llm_error": llm_error, "period": c.period["label"]}
    rid = store.save_agent_run(question, summary[:300], result)
    result["id"] = rid
    return result
