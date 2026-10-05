"""Plain-English insights and monitoring signals computed from the real data."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from .metrics import (Ctx, group_table, inventory, customers, totals, pct_change, r2, num_s, pct_s, period_public)

TONE_RANK = {"bad": 0, "warn": 1, "good": 2, "info": 3}
SEV = {"bad": "high", "warn": "medium", "good": "low", "info": "low"}


def _ins(id, tone, title, detail, page=None, action=None, weight=0, evidence=None):
    return {"id": id, "tone": tone, "severity": SEV[tone], "title": title, "detail": detail, "page": page,
            "action": action, "weight": weight, "evidence": evidence or {}}


def _act(title, desc, priority="medium", key=None, impact=None):
    return {"title": title, "description": desc, "priority": priority, "dedupe_key": key, "impact": impact}


# ───────────────────────── insights ─────────────────────────
def build_insights(c: Ctx):
    out = []
    oid = c.has["order_id"]
    cur, prev = totals(c.cur, oid), (totals(c.prev, oid) if c.prev is not None else None)
    m = c.m
    if not c.has["revenue"]:
        return [_ins("no_rev", "bad", "No sales amount column found", "Pick the column that holds your sales amount in Data Studio → Column mapping. Until then most analysis is empty.", "data")]

    # 1. sales trend
    if prev and prev["revenue"]:
        ch = pct_change(cur["revenue"], prev["revenue"])
        diff = cur["revenue"] - prev["revenue"]
        tone = "good" if ch >= 3 else "bad" if ch <= -8 else "warn" if ch <= -3 else "info"
        word = "up" if ch >= 0 else "down"
        parts = []
        if prev["orders"]:
            parts.append(f"orders {pct_s(pct_change(cur['orders'], prev['orders']))}")
        if prev["aov"] and cur["aov"]:
            parts.append(f"average bill {pct_s(pct_change(cur['aov'], prev['aov']))}")
        act = None
        if tone in ("bad", "warn") and ch <= -8:
            act = _act("Find out why sales dropped", f"Sales fell {abs(ch):.1f}% ({m(abs(diff))}) versus the previous period. Check the biggest falling products and categories in Insights, stock availability and any pricing changes.", "high", "sales-drop", f"{m(abs(diff))} lower sales")
        out.append(_ins("trend", tone, f"Sales are {word} {abs(ch):.1f}% versus the previous period",
                        f"{m(cur['revenue'])} now compared with {m(prev['revenue'])} before ({m(abs(diff))} {'more' if diff >= 0 else 'less'}). " + ("; ".join(parts).capitalize() + "." if parts else ""),
                        "forecast", act, 100 + abs(ch), {"change_pct": r2(ch)}))
    # 2. movers
    if c.prev is not None:
        for dim, has in (("category", c.has["category"]), ("product", c.has["product"])):
            if not has:
                continue
            a = group_table(c.cur, dim, oid).set_index(dim)["revenue"]
            b = group_table(c.prev, dim, oid).set_index(dim)["revenue"]
            d = a.sub(b, fill_value=0).sort_values()
            if len(d) < 2:
                continue
            worst, best = d.index[0], d.index[-1]
            plural = "categories" if dim == "category" else "products"
            total_prev = b.sum() or 1
            if d.iloc[0] < 0 and abs(d.iloc[0]) / total_prev > 0.02:
                pv = float(b.get(worst, 0))
                ch = pct_change(float(a.get(worst, 0)), pv)
                out.append(_ins(f"fall_{dim}", "warn", f"{worst} fell the most among your {plural}",
                                f"Down {m(abs(d.iloc[0]))}" + (f" ({pct_s(ch)})" if ch is not None else "") + " versus the previous period. This single change explains a large part of the movement in total sales.",
                                "insights", _act(f"Review {dim} “{worst}”", f"“{worst}” sold {m(abs(d.iloc[0]))} less than in the previous period. Check price, stock availability and competition for it.", "medium", f"fall:{dim}:{worst}", f"{m(abs(d.iloc[0]))} lower"), 70 + abs(d.iloc[0]) / total_prev * 100))
            if d.iloc[-1] > 0 and d.iloc[-1] / total_prev > 0.02:
                out.append(_ins(f"rise_{dim}", "good", f"{best} grew the most among your {plural}",
                                f"Up {m(d.iloc[-1])} versus the previous period. Make sure you have enough stock and consider promoting it further.", "insights", None, 40 + d.iloc[-1] / total_prev * 100))
            break  # one dimension is enough to avoid repeating the same story
    # 3. concentration
    if c.has["product"]:
        pt = group_table(c.cur, "product", oid).sort_values("revenue", ascending=False)
        tot = pt["revenue"].sum()
        if tot > 0 and len(pt) >= 5:
            cum = pt["revenue"].cumsum() / tot
            n80 = int((cum < 0.8).sum() + 1)
            top1 = pt.iloc[0]
            share1 = top1["revenue"] / tot * 100
            tone = "warn" if share1 >= 35 else "info"
            out.append(_ins("concentration", tone, f"{n80} of your {len(pt)} products bring in 80% of sales",
                            f"“{top1['product']}” alone is {share1:.0f}% of sales. " + ("Depending this much on one item is risky: keep it well stocked and look for a second strong seller." if share1 >= 35 else "Keep these products well stocked and review the slow ones at the tail."),
                            "insights", None, 35 + (share1 if share1 >= 35 else 0), {"products_for_80pct": n80}))
    # 4. weekday
    if c.has["date"] and (c.period["days"] or 0) >= 21:
        d = c.cur.groupby("date")["revenue"].sum().reindex(pd.date_range(c.period["start"], c.period["end"]), fill_value=0)
        wk = d.groupby(d.index.dayofweek).mean()
        if len(wk) == 7 and wk.mean() > 0:
            names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            hi, lo = int(wk.idxmax()), int(wk.idxmin())
            if wk.iloc[lo] > 0 and wk.iloc[hi] > wk.iloc[lo] * 1.2:
                out.append(_ins("weekday", "info", f"{names[hi]} is your strongest day, {names[lo]} your weakest",
                                f"An average {names[hi]} brings {m(wk.iloc[hi])}, about {wk.iloc[hi] / wk.iloc[lo]:.1f}× an average {names[lo]} ({m(wk.iloc[lo])}). Plan staff and stock around this, and try an offer on {names[lo]}.", "insights", None, 30))
    # 5. best day
    if c.has["date"] and (c.period["days"] or 0) >= 14:
        d = c.cur.groupby("date")["revenue"].sum()
        if len(d) > 5 and d.median() > 0 and d.max() > 2 * d.median():
            out.append(_ins("best_day", "info", f"Best day was {d.idxmax():%d %b} with {m(d.max())}",
                            f"That is {d.max() / d.median():.1f}× a typical day. If you ran an offer or event that day, it is worth repeating.", None, None, 20))
    # 6. discounts
    if c.has["discount"]:
        df = c.cur
        used = df["discount"] == 1
        if used.any() and (~used).any():
            a_d, a_n = df[used]["revenue"].mean(), df[~used]["revenue"].mean()
            share = used.mean() * 100
            diff = pct_change(a_d, a_n)
            if diff is not None:
                tone = "warn" if (diff < -5 and share > 40) else "info"
                out.append(_ins("discount", tone, f"{share:.0f}% of purchases used a discount",
                                f"Discounted purchases average {m(a_d)} versus {m(a_n)} without a discount ({pct_s(diff)}). " + ("Discounts do not seem to be lifting basket size, so check whether they are giving margin away." if diff < 0 else "Discounted purchases are larger, which suggests offers are working."),
                                "insights", None, 45 if tone == "warn" else 25))
    # 7. customers
    cu = customers(c)
    if cu.get("available"):
        out.append(_ins("repeat", "good" if cu["repeat_rate"] >= 40 else "info", f"{cu['repeat_rate']:.0f}% of customers bought more than once",
                        f"Your top 10% of customers bring {cu['top10_share']:.0f}% of sales. Looking after them with a thank-you or early access pays back quickly.", "customers", None, 30))
        atr = cu["segments"].get("At risk", 0)
        if atr:
            out.append(_ins("at_risk", "warn", f"{atr} repeat customers have gone quiet",
                            "They bought more than once but not recently. A friendly message or small offer can win them back.", "customers",
                            _act("Win back quiet customers", f"{atr} repeat customers have not bought recently. Send them a short message or offer.", "medium", "winback"), 50))
    # 8. margin
    if c.cost_mode and c.has["product"]:
        pt = group_table(c.cur, "product", oid)
        pt = pt[pt["profit"].notna() & (pt["revenue"] > 0)]
        loss = pt[pt["profit"] < 0].sort_values("profit")
        if len(loss):
            tot_loss = float(loss["profit"].sum())
            out.append(_ins("loss_products", "bad", f"{len(loss)} product{'s' if len(loss) > 1 else ''} sell below cost",
                            f"{', '.join(loss['product'].head(3))}{' and more' if len(loss) > 3 else ''} lose {m(abs(tot_loss))} together. Raise the price, cut the cost, or stop selling them.", "insights",
                            _act("Fix products selling below cost", f"Products losing money: {', '.join(loss['product'].head(5))}. Total loss {m(abs(tot_loss))}. Review prices and supplier costs.", "high", "below-cost", f"{m(abs(tot_loss))} lost"), 90))
        thin = pt[(pt["margin"] < 10) & (pt["profit"] >= 0) & (pt["revenue"] > pt["revenue"].sum() * 0.03)]
        if len(thin):
            out.append(_ins("thin_margin", "warn", f"{len(thin)} big seller{'s' if len(thin) > 1 else ''} earn under 10% margin",
                            f"{', '.join(thin['product'].head(3))}: lots of sales but little profit. A small price rise here goes straight to your bottom line.", "insights", None, 55))
        if prev and cur["margin"] is not None and prev["margin"] is not None and cur["margin"] - prev["margin"] <= -2:
            out.append(_ins("margin_drop", "warn", f"Profit margin fell from {prev['margin']:.1f}% to {cur['margin']:.1f}%",
                            "Costs grew faster than sales. Check supplier price increases and discounts.", "insights",
                            _act("Investigate falling margin", f"Margin dropped {prev['margin'] - cur['margin']:.1f} points. Compare supplier prices and discounting.", "high", "margin-drop"), 80))
    elif not c.cost_mode:
        out.append(_ins("no_cost", "info", "Profit is unknown because there are no costs in your data",
                        "Upload a file with a cost column, or set a typical cost % in Settings → Business profile to see an estimated profit.", "settings", None, 28))
    # 9. stock
    inv = inventory(c)
    if inv["available"]:
        s = inv["summary"]
        if s["needs_action"]:
            first = [i["product"] for i in inv["items"] if i["status"] in ("out", "critical", "low")][:3]
            out.append(_ins("stock", "bad" if (s["out"] or s["critical"]) else "warn", f"{s['needs_action']} product{'s' if s['needs_action'] > 1 else ''} will run out soon",
                            f"{', '.join(first)}{' and more' if s['needs_action'] > 3 else ''}. About {c.m(s['revenue_at_risk'])} of sales are at risk before new stock arrives.", "inventory", None, 95))
        if s["dead"]:
            out.append(_ins("dead", "info", f"{s['dead']} product{'s' if s['dead'] > 1 else ''} have stock but no recent sales",
                            "Money is tied up in slow stock. Consider a clearance offer or bundling.", "inventory", None, 25))
    # 10. returns
    if c.has["revenue"]:
        neg = c.cur[c.cur["revenue"] < 0]["revenue"].sum()
        gross = c.cur[c.cur["revenue"] > 0]["revenue"].sum()
        if gross and abs(neg) / gross > 0.03:
            out.append(_ins("returns", "warn", f"Returns are {abs(neg) / gross * 100:.1f}% of sales", f"{c.m(abs(neg))} was refunded. Look at which products come back most.", "insights", None, 45))
    # 11. dimension gaps (segments)
    gaps = []
    base = c.cur["revenue"].mean() if len(c.cur) else 0
    for dim in c.info["dims"]:
        if dim in ("product", "category") and c.has["date"] and False:
            continue
        if dim in ("product", "category"):
            continue
        g = c.cur.groupby(dim)["revenue"].agg(["mean", "size"])
        g = g[g["size"] >= max(30, len(c.cur) * 0.05)]
        if len(g) < 2 or base <= 0:
            continue
        dev = (g["mean"] - base) / base * 100
        k = dev.abs().idxmax()
        if abs(dev[k]) >= 8:
            gaps.append((abs(dev[k]) * math.sqrt(g.loc[k, "size"]), dim, k, dev[k], g.loc[k, "size"]))
    for _, dim, k, dv, n in sorted(gaps, reverse=True)[:2]:
        out.append(_ins(f"seg_{dim}", "info", f"{dim}: “{k}” spends {abs(dv):.0f}% {'more' if dv > 0 else 'less'} per purchase than average",
                        f"Based on {int(n):,} purchases. Open Insights → Breakdowns to compare every {dim.lower()} side by side.", "insights", None, 18))
    # 12. data health
    q = c.info["quality"]["score"]
    if q < 70:
        out.append(_ins("quality", "warn", f"Data quality is {q}/100", "Some checks failed. Review them in Data Studio so the numbers can be trusted.", "data", None, 60))
    out.sort(key=lambda i: (-i["weight"]))
    return out


# ───────────────────────── signals ─────────────────────────
def build_signals(c: Ctx):
    sig = []
    oid = c.has["order_id"]
    m = c.m
    if c.has["date"] and c.has["revenue"]:
        x = c.x[c.x["date"].notna()]
        end = x["date"].max()
        full = x.groupby("date")["revenue"].sum().reindex(pd.date_range(x["date"].min(), end), fill_value=0.0)
        hist = full.tail(120)
        if len(hist) >= 28:
            dow = hist.groupby(hist.index.dayofweek).transform("mean")
            adj = hist / dow.replace(0, np.nan)
            adj = adj.replace([np.inf, -np.inf], np.nan).fillna(1.0)
            med = adj.median()
            mad = (adj - med).abs().median() * 1.4826 or adj.std() or 1
            z = (adj - med) / mad
            flagged = z[(z.abs() > 3.5) & ((adj / med - 1).abs() > 0.35)]
            for d, zz in flagged.sort_index(ascending=False).head(5).items():
                expected = float(med * dow[d])
                val = float(hist[d])
                low = zz < 0
                days_ago = (end - d).days
                sig.append({"id": f"anom:{d:%Y-%m-%d}", "type": "Sales anomaly", "severity": "high" if (low and days_ago <= 14) else "medium",
                            "tone": "bad" if low else "info", "date": d.strftime("%Y-%m-%d"), "value": r2(val),
                            "title": f"{'Unusually low' if low else 'Unusually high'} sales on {d:%d %b}",
                            "detail": f"Sales were {m(val)} against about {m(expected)} expected for a {d:%A}. " + ("Check whether the shop was closed, stock ran out or there was a data entry gap." if low else "Check whether an offer, event or bulk order explains it."),
                            "page": "insights", "action": _act(f"Check what happened on {d:%d %b}", f"Sales on {d:%d %b} were {m(val)} versus about {m(expected)} expected.", "medium", f"anom:{d:%Y-%m-%d}") if low and days_ago <= 14 else None})
        if len(full) >= 21:
            a, b = full.tail(7).sum(), full.iloc[-14:-7].sum()
            if b > 0:
                ch = (a - b) / b * 100
                if ch <= -15:
                    sig.append({"id": "slow7", "type": "Sales slowdown", "severity": "high", "tone": "bad", "date": end.strftime("%Y-%m-%d"), "value": r2(a),
                                "title": f"Last 7 days are {abs(ch):.0f}% below the week before",
                                "detail": f"{m(a)} versus {m(b)}. A sudden fall usually has a cause you can fix: stock-outs, a price change or a competitor.", "page": "forecast",
                                "action": _act("Investigate this week's sales drop", f"The last 7 days brought {m(a)} compared with {m(b)} the week before ({ch:.0f}%).", "high", "slow7", f"{m(b - a)} lower")})
                elif ch >= 25:
                    sig.append({"id": "surge7", "type": "Sales surge", "severity": "low", "tone": "good", "date": end.strftime("%Y-%m-%d"), "value": r2(a),
                                "title": f"Last 7 days are {ch:.0f}% above the week before",
                                "detail": f"{m(a)} versus {m(b)}. Make sure stock can keep up with demand.", "page": "forecast", "action": None})
    # category decline
    if c.prev is not None and c.has["category"]:
        a = group_table(c.cur, "category", oid).set_index("category")["revenue"]
        b = group_table(c.prev, "category", oid).set_index("category")["revenue"]
        tot = b.sum() or 1
        for cat in b.index:
            pv, cv = float(b[cat]), float(a.get(cat, 0))
            if pv / tot >= 0.05 and pv > 0 and (cv - pv) / pv <= -0.2:
                sig.append({"id": f"catdrop:{cat}", "type": "Category decline", "severity": "medium", "tone": "warn", "date": c.period["end"].strftime("%Y-%m-%d"), "value": r2(cv),
                            "title": f"{cat} sales are down {abs((cv - pv) / pv * 100):.0f}%", "detail": f"{m(cv)} versus {m(pv)} in the previous period.", "page": "insights",
                            "action": _act(f"Review category “{cat}”", f"{cat} fell from {m(pv)} to {m(cv)}.", "medium", f"catdrop:{cat}", f"{m(pv - cv)} lower")})
    # stock
    inv = inventory(c)
    if inv["available"]:
        for it in inv["items"]:
            st = it["status"]
            if st in ("out", "critical", "low"):
                left = "is out of stock" if st == "out" else f"has about {it['days_left']:.0f} day{'s' if it['days_left'] and it['days_left'] >= 1.5 else ''} of stock left"
                tail = f" Order about {it['reorder_qty']:,} units to cover the next {inv['settings']['lead_time_days'] + inv['settings']['safety_days'] + 14} days." if it["reorder_qty"] else ""
                sig.append({"id": f"stock:{it['product']}", "type": "Stock risk", "severity": "high" if st in ("out", "critical") else "medium", "tone": "bad" if st in ("out", "critical") else "warn",
                            "date": c.x["date"].max().strftime("%Y-%m-%d") if c.has["date"] else None, "value": it["stock"],
                            "title": f"{it['product']} {left}", "detail": f"Selling about {it['per_day']:.1f} per day; {num_s(it['stock'])} in stock." + tail, "page": "inventory",
                            "action": _act(f"Reorder {it['product']}", f"{it['product']} {left}. Sells about {it['per_day']:.1f}/day, stock {num_s(it['stock'])}. Suggested order: {it['reorder_qty']:,} units.", "high" if st != "low" else "medium",
                                           f"stock:{it['product']}", f"{c.m(it['revenue_at_risk'])} sales at risk" if it["revenue_at_risk"] else None)})
        dead = [i for i in inv["items"] if i["status"] == "dead"]
        if dead:
            sig.append({"id": "dead", "type": "Slow stock", "severity": "low", "tone": "info", "date": None, "value": len(dead),
                        "title": f"{len(dead)} item{'s' if len(dead) > 1 else ''} have not sold in 30 days", "detail": ", ".join(i["product"] for i in dead[:5]), "page": "inventory",
                        "action": _act("Clear slow-moving stock", f"No sales in 30 days: {', '.join(i['product'] for i in dead[:8])}. Consider a clearance offer.", "low", "dead-stock")})
    # margin
    if c.cost_mode and c.has["product"]:
        pt = group_table(c.cur, "product", oid)
        pt = pt[pt["profit"].notna() & (pt["profit"] < 0) & (pt["revenue"] > 0)].sort_values("profit").head(4)
        for r in pt.itertuples():
            sig.append({"id": f"loss:{r.product}", "type": "Margin risk", "severity": "high", "tone": "bad", "date": None, "value": r2(r.profit),
                        "title": f"{r.product} is selling below cost", "detail": f"It earned {m(r.revenue)} but cost more, a loss of {m(abs(r.profit))}.", "page": "insights",
                        "action": _act(f"Fix pricing for {r.product}", f"{r.product} lost {m(abs(r.profit))} in the selected period.", "high", f"loss:{r.product}", f"{m(abs(r.profit))} lost")})
    # returns
    gross = c.cur[c.cur["revenue"] > 0]["revenue"].sum()
    neg = abs(c.cur[c.cur["revenue"] < 0]["revenue"].sum())
    if gross and neg / gross > 0.05:
        sig.append({"id": "returns", "type": "Returns", "severity": "medium", "tone": "warn", "date": None, "value": r2(neg),
                    "title": f"Returns are {neg / gross * 100:.1f}% of sales", "detail": f"{m(neg)} refunded in this period.", "page": "insights", "action": None})
    # freshness
    if c.has["date"] and not c.ds.get("is_sample"):
        age = (pd.Timestamp(date.today()) - c.x["date"].max()).days
        if age > 7:
            sig.append({"id": "stale", "type": "Data freshness", "severity": "medium", "tone": "warn", "date": c.x["date"].max().strftime("%Y-%m-%d"), "value": age,
                        "title": f"Your latest data is {age} days old", "detail": "Upload recent sales so alerts and forecasts reflect today's business.", "page": "data", "action": None})
    # data quality
    q = c.info["quality"]
    if q["score"] < 70:
        sig.append({"id": "quality", "type": "Data quality", "severity": "medium", "tone": "warn", "date": None, "value": q["score"],
                    "title": f"Data quality is {q['score']}/100", "detail": "Open Data Studio to see which checks failed.", "page": "data", "action": None})
    order = {"high": 0, "medium": 1, "low": 2}
    sig.sort(key=lambda s: (order[s["severity"]], s.get("date") or "", ))
    return sig


def signals_payload(c: Ctx):
    s = build_signals(c)
    return {"signals": s, "summary": {"total": len(s), "high": sum(1 for x in s if x["severity"] == "high"),
                                      "medium": sum(1 for x in s if x["severity"] == "medium"), "low": sum(1 for x in s if x["severity"] == "low")},
            "period": period_public(c.period)}
