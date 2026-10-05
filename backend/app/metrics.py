"""Business metrics: KPIs, periods, insights, signals, inventory, customers, patterns."""
from __future__ import annotations

import math
from datetime import date as _date

import numpy as np
import pandas as pd

from . import ingest, store


class NoData(Exception):
    pass


# ───────────────────────── formatting ─────────────────────────
def _indian_group(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + out


def money(v, prof, compact=True):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    sym = prof.get("currency") or ""
    a = abs(v)
    sign = "-" if v < 0 else ""
    if prof.get("number_style") == "indian":
        if compact and a >= 1e7:
            return f"{sign}{sym}{a / 1e7:.2f} Cr"
        if compact and a >= 1e5:
            return f"{sign}{sym}{a / 1e5:.2f} L"
        return f"{sign}{sym}{_indian_group(round(a))}"
    if compact and a >= 1e9:
        return f"{sign}{sym}{a / 1e9:.2f}B"
    if compact and a >= 1e6:
        return f"{sign}{sym}{a / 1e6:.2f}M"
    if compact and a >= 1e4:
        return f"{sign}{sym}{a / 1e3:.1f}K"
    return f"{sign}{sym}{a:,.0f}"


def pct_s(v, signed=True):
    if v is None:
        return "—"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def pct_change(cur, prev):
    if prev is None or cur is None:
        return None
    if prev == 0:
        return None if cur == 0 else None
    return (cur - prev) / abs(prev) * 100


def num_s(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}".rstrip("0").rstrip(".")


def r2(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), 2)


# ───────────────────────── context ─────────────────────────
class Ctx:
    """Everything an analysis needs: data, profile, selected period."""

    def __init__(self, ds, period=None):
        self.ds = ds
        self.x, self.info = ingest.build_dataset(ds)
        self.prof = store.profile()
        self.has = self.info["has"]
        x = self.x
        pct = self.prof.get("assumed_cost_pct")
        try:
            pct = float(pct) if pct not in (None, "") else None
        except Exception:
            pct = None
        self.cost_mode = "actual" if self.has["cost"] else ("estimated" if pct else None)
        if "_cost" not in x.columns:
            if self.has["cost"]:
                x["_cost"] = x["cost"]
            elif pct:
                x["_cost"] = x["revenue"] * (pct / 100.0)
            else:
                x["_cost"] = np.nan
            x["_profit"] = x["revenue"] - x["_cost"]
            x["_rev_c"] = x["revenue"].where(x["_cost"].notna())
        self.period = resolve_period(x, period or self.prof.get("default_period") or "30d", self.prof, self.has["date"])
        p = self.period
        if p["start"] is not None:
            self.cur = x[(x["date"] >= p["start"]) & (x["date"] <= p["end"])]
            self.prev = x[(x["date"] >= p["prev_start"]) & (x["date"] <= p["prev_end"])] if p["prev_start"] is not None else None
        else:
            self.cur, self.prev = x, None

    def m(self, v, compact=True):
        return money(v, self.prof, compact)

    @property
    def sym(self):
        return self.prof.get("currency", "")


def get_ctx(period=None) -> Ctx:
    ds = store.active_dataset()
    if not ds:
        raise NoData("No data yet. Upload a sales file in Data Studio to begin.")
    return Ctx(ds, period)


# ───────────────────────── periods ─────────────────────────
PERIODS = [("7d", "Last 7 days"), ("30d", "Last 30 days"), ("90d", "Last 90 days"), ("mtd", "This month"),
           ("lastmonth", "Last month"), ("fytd", "This financial year"), ("365d", "Last 12 months"), ("all", "All time")]


def resolve_period(x, key, prof, has_date):
    empty = {"key": "all", "label": "All data", "start": None, "end": None, "prev_start": None, "prev_end": None, "days": None, "has_prev": False}
    if not has_date:
        return empty
    d = x["date"].dropna()
    first, end = d.min().normalize(), d.max().normalize()
    D = pd.Timedelta(days=1)
    start = prev_s = prev_e = None
    label = dict(PERIODS).get(key, "All time")
    if key in ("7d", "30d", "90d", "365d"):
        n = int(key[:-1])
        start = end - (n - 1) * D
        prev_e = start - D
        prev_s = prev_e - (n - 1) * D
    elif key == "mtd":
        start = end.replace(day=1)
        span = (end - start).days
        prev_s = (start - pd.offsets.MonthBegin(1)).normalize()
        prev_e = prev_s + span * D
    elif key == "lastmonth":
        this_first = end.replace(day=1)
        end = this_first - D
        start = end.replace(day=1)
        prev_e = start - D
        prev_s = prev_e.replace(day=1)
    elif key == "fytd":
        fy = int(prof.get("fy_start_month") or 4)
        year = end.year if end.month >= fy else end.year - 1
        start = pd.Timestamp(year=year, month=fy, day=1)
        prev_s = start - pd.DateOffset(years=1)
        prev_e = end - pd.DateOffset(years=1)
    if start is None or start < first and key in ("7d", "30d", "90d", "365d", "mtd", "fytd", "lastmonth") and (end - first).days < 1:
        start, prev_s, prev_e, label = first, None, None, "All time"
    if start is not None and start < first:
        # data is shorter than the chosen period: use everything, no comparison unless prior window exists
        covered = (end - first).days + 1
        start = first
        label = f"All available data ({covered} days)"
        prev_s = prev_e = None
    if start is None:
        start, label = first, "All time"
    if prev_s is not None:
        # need at least 60% of the previous window to be inside the data
        overlap = (min(prev_e, end) - max(prev_s, first)).days + 1
        plen = (prev_e - prev_s).days + 1
        if prev_e < first or overlap < 0.6 * plen:
            prev_s = prev_e = None
    return {"key": key if key in dict(PERIODS) else "all", "label": label, "start": start, "end": end, "prev_start": prev_s, "prev_end": prev_e,
            "days": int((end - start).days) + 1, "has_prev": prev_s is not None,
            "text": f"{start:%d %b %Y} to {end:%d %b %Y}"}


def period_public(p):
    return {"key": p["key"], "label": p["label"], "days": p["days"], "has_prev": p["has_prev"], "text": p.get("text"),
            "start": p["start"].strftime("%Y-%m-%d") if p["start"] is not None else None,
            "end": p["end"].strftime("%Y-%m-%d") if p["end"] is not None else None}


# ───────────────────────── aggregation ─────────────────────────
def totals(df, has_order_id=False):
    if df is None or len(df) == 0:
        return {"revenue": 0.0, "units": 0.0, "orders": 0, "aov": None, "profit": None, "margin": None, "cost": None, "rows": 0}
    rev = float(df["revenue"].sum())
    units = float(df["units"].sum())
    orders = int(df["order_id"].nunique()) if has_order_id else int(len(df))
    cost_n = df["_cost"].notna().sum()
    profit = float(df["_profit"].sum()) if cost_n else None
    rc = float(df["_rev_c"].sum()) if cost_n else 0
    return {"revenue": rev, "units": units, "orders": orders, "aov": rev / orders if orders else None,
            "profit": profit, "margin": (profit / rc * 100) if (profit is not None and rc) else None,
            "cost": float(df["_cost"].sum()) if cost_n else None, "rows": int(len(df))}


def group_table(df, by, has_order_id=False):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=[by, "revenue", "units", "orders", "profit", "margin", "rows"])
    g = df.groupby(by, dropna=False)
    t = g.agg(revenue=("revenue", "sum"), units=("units", "sum"), rows=("revenue", "size"),
              profit=("_profit", lambda s: s.sum() if s.notna().any() else np.nan), rc=("_rev_c", "sum"))
    t["orders"] = g["order_id"].nunique() if has_order_id else t["rows"]
    t["margin"] = np.where(t["profit"].notna() & (t["rc"] > 0), t["profit"] / t["rc"].replace(0, np.nan) * 100, np.nan)
    t = t.drop(columns=["rc"]).reset_index()
    return t


def ts_points(df, start, end, gran="D", col="revenue"):
    if df is None or len(df) == 0 or start is None:
        return []
    s = df.groupby("date")[col].sum()
    idx = pd.date_range(start, end, freq="D")
    s = s.reindex(idx, fill_value=0.0)
    if gran == "W":
        s = s.resample("W-SUN").sum()
    elif gran == "M":
        s = s.resample("MS").sum()
    return [{"date": d.strftime("%Y-%m-%d"), "value": r2(v)} for d, v in s.items()]


def pick_gran(days):
    return "D" if days <= 75 else "W" if days <= 420 else "M"


# ───────────────────────── KPI + dashboard ─────────────────────────
def kpi_cards(c: Ctx):
    oid = c.has["order_id"]
    cur, prev = totals(c.cur, oid), totals(c.prev, oid) if c.prev is not None else None
    ch = lambda k: pct_change(cur[k], prev[k]) if prev else None
    cards = [
        {"key": "revenue", "label": "Sales", "value": r2(cur["revenue"]), "display": c.m(cur["revenue"]), "change": r2(ch("revenue")), "tone": "money"},
        {"key": "orders", "label": "Orders" if oid else "Transactions", "value": cur["orders"], "display": f"{cur['orders']:,}", "change": r2(ch("orders")), "tone": "count"},
        {"key": "aov", "label": "Average bill", "value": r2(cur["aov"]), "display": c.m(cur["aov"]) if cur["aov"] else "—", "change": r2(ch("aov")), "tone": "money"},
    ]
    if cur["profit"] is not None:
        est = c.cost_mode == "estimated"
        cards.append({"key": "profit", "label": "Profit (estimated)" if est else "Profit", "value": r2(cur["profit"]), "display": c.m(cur["profit"]),
                      "change": r2(ch("profit")), "tone": "money", "sub": f"{cur['margin']:.1f}% margin" if cur["margin"] is not None else None, "estimated": est})
    else:
        cards.append({"key": "profit", "label": "Profit", "value": None, "display": "Add costs", "change": None, "tone": "missing",
                      "sub": "No cost data yet", "missing": "cost"})
    if c.has["units"]:
        cards.insert(2, {"key": "units", "label": "Items sold", "value": cur["units"], "display": num_s(cur["units"]), "change": r2(ch("units")), "tone": "count"})
    return cards, cur, prev


def dashboard(c: Ctx):
    cards, cur, prev = kpi_cards(c)
    p = c.period
    out = {"period": period_public(p), "kpis": cards, "totals": {k: r2(v) if isinstance(v, float) else v for k, v in cur.items()}}
    if c.has["date"]:
        gran = pick_gran(p["days"])
        out["trend"] = {"granularity": gran, "current": ts_points(c.cur, p["start"], p["end"], gran)}
        if c.prev is not None:
            pr = ts_points(c.prev, p["prev_start"], p["prev_end"], gran)
            out["trend"]["previous"] = pr
    else:
        out["trend"] = None
    by_cat = group_table(c.cur, "category", c.has["order_id"]).sort_values("revenue", ascending=False)
    by_prod = group_table(c.cur, "product", c.has["order_id"]).sort_values("revenue", ascending=False)
    prev_prod = group_table(c.prev, "product", c.has["order_id"]).set_index("product")["revenue"] if c.prev is not None else None
    prev_cat = group_table(c.prev, "category", c.has["order_id"]).set_index("category")["revenue"] if c.prev is not None else None

    def rows(t, key, prevs, n):
        res = []
        tot = t["revenue"].sum() or 1
        for r in t.head(n).itertuples():
            name = getattr(r, key)
            pv = float(prevs.get(name, 0)) if prevs is not None else None
            res.append({"name": name, "revenue": r2(r.revenue), "units": r2(r.units), "profit": r2(r.profit), "share": r2(r.revenue / tot * 100),
                        "change": r2(pct_change(r.revenue, pv)) if pv else None})
        return res
    out["categories"] = rows(by_cat, "category", prev_cat, 8) if c.has["category"] else []
    out["products"] = rows(by_prod, "product", prev_prod, 8) if c.has["product"] else []
    out["headline"] = headline(c, cur, prev)
    out["setup"] = setup_tips(c)
    return out


def headline(c: Ctx, cur, prev):
    if not c.has["revenue"]:
        return ["We could not find a sales amount column yet. Open Data Studio → Column mapping and choose it."]
    lines = []
    ch = pct_change(cur["revenue"], prev["revenue"]) if prev else None
    if ch is not None:
        verb = "up" if ch >= 0 else "down"
        lines.append(f"Sales are {verb} {abs(ch):.1f}% versus the previous period: {c.m(cur['revenue'])} compared with {c.m(prev['revenue'])}.")
    else:
        lines.append(f"{c.m(cur['revenue'])} in sales across {cur['orders']:,} {'orders' if c.has['order_id'] else 'transactions'} ({c.period['label'].lower()}).")
    if cur["profit"] is not None and cur["margin"] is not None:
        lines.append(f"{'Estimated profit' if c.cost_mode == 'estimated' else 'Profit'} is {c.m(cur['profit'])}, a {cur['margin']:.1f}% margin.")
    return lines


def setup_tips(c: Ctx):
    tips = []
    if not c.has["date"]:
        tips.append({"id": "date", "title": "Add a date column to unlock trends and forecasts", "text": "Without dates, DataPilot can compare products and groups but cannot show growth, seasonality or forecasts.", "cta": "Fix in Column mapping", "page": "data"})
    if not c.has["cost"] and not c.prof.get("assumed_cost_pct"):
        tips.append({"id": "cost", "title": "Add cost data to see real profit", "text": "Upload a cost column, or set a typical cost % in Settings to get an estimated profit.", "cta": "Open Settings", "page": "settings"})
    if not c.has["inventory"]:
        tips.append({"id": "stock", "title": "Add stock levels for low-stock alerts", "text": "A 'stock' or 'closing stock' column lets DataPilot warn you before items run out.", "cta": "Add data", "page": "data"})
    return tips


# ───────────────────────── explore ─────────────────────────
def explore(c: Ctx, dim, metric="revenue", limit=30):
    if dim not in c.x.columns:
        raise ValueError(f"'{dim}' is not a column in this dataset.")
    oid = c.has["order_id"]
    cur = group_table(c.cur, dim, oid)
    prev = group_table(c.prev, dim, oid).set_index(dim) if c.prev is not None else None
    cur["aov"] = cur["revenue"] / cur["orders"].replace(0, np.nan)
    extras = {}
    for e in c.info["numeric_extras"][:6]:
        extras[e] = c.cur.groupby(dim)[e].mean()
    total_rev = cur["revenue"].sum() or 1
    metric = metric if metric in ("revenue", "units", "orders", "profit", "aov", "margin") and (metric not in ("profit", "margin") or c.cost_mode) else "revenue"
    cur = cur.sort_values(metric, ascending=False, na_position="last")
    cum, rows = 0.0, []
    for r in cur.head(limit).itertuples():
        name = getattr(r, dim) if dim in cur.columns and dim.isidentifier() else r[1]
        name = r[1]
        pv = float(prev["revenue"].get(name, 0)) if prev is not None else None
        cum += r.revenue / total_rev * 100
        row = {"name": str(name), "revenue": r2(r.revenue), "units": r2(r.units), "orders": int(r.orders), "profit": r2(r.profit),
               "margin": r2(r.margin), "aov": r2(r.aov), "share": r2(r.revenue / total_rev * 100),
               "change": r2(pct_change(r.revenue, pv)) if prev is not None and pv else None,
               "abc": "A" if cum - r.revenue / total_rev * 100 < 80 else "B" if cum - r.revenue / total_rev * 100 < 95 else "C"}
        for e, ser in extras.items():
            row["avg_" + e] = r2(ser.get(name))
        rows.append(row)
    return {"dim": dim, "metric": metric, "rows": rows, "total_groups": int(len(cur)), "extras": list(extras),
            "can_profit": bool(c.cost_mode), "period": period_public(c.period)}


# ───────────────────────── patterns ─────────────────────────
def patterns(c: Ctx):
    if not c.has["date"]:
        return {"available": False, "reason": "Time patterns need a date column."}
    x = c.x[c.x["date"].notna()]
    span = (x["date"].max() - x["date"].min()).days + 1
    daily = x.groupby("date").agg(revenue=("revenue", "sum"), units=("units", "sum"), n=("revenue", "size"))
    idx = pd.date_range(x["date"].min(), x["date"].max(), freq="D")
    daily = daily.reindex(idx, fill_value=0)
    daily["dow"] = daily.index.dayofweek
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    wk = daily.groupby("dow").agg(avg_revenue=("revenue", "mean"), avg_units=("units", "mean"), days=("revenue", "size"))
    weekday = [{"day": names[i], "avg_revenue": r2(wk.loc[i, "avg_revenue"]) if i in wk.index else 0, "avg_units": r2(wk.loc[i, "avg_units"]) if i in wk.index else 0} for i in range(7)]
    monthly = x.set_index("date").resample("MS").agg(revenue=("revenue", "sum"), units=("units", "sum"), orders=("revenue", "size"))
    months = []
    prev_v = None
    for d, r in monthly.iterrows():
        months.append({"month": d.strftime("%b %Y"), "revenue": r2(r.revenue), "units": r2(r.units), "orders": int(r.orders), "change": r2(pct_change(r.revenue, prev_v)) if prev_v else None})
        prev_v = r.revenue
    # last month may be partial
    partial = len(monthly) > 0 and x["date"].max().day < pd.Timestamp(x["date"].max()).days_in_month
    return {"available": span >= 14, "weekday": weekday, "monthly": months, "last_month_partial": bool(partial), "span_days": int(span),
            "reason": None if span >= 14 else "Need at least two weeks of data to show patterns."}


# ───────────────────────── inventory ─────────────────────────
def inventory(c: Ctx):
    if not c.has["inventory"]:
        return {"available": False, "reason": "No stock column was found. Add a column such as 'Closing Stock' to get low-stock and reorder alerts.", "items": [], "summary": {}}
    x = c.x
    prof = c.prof
    lead, safety = int(prof.get("lead_time_days") or 7), int(prof.get("safety_days") or 3)
    low_days = float(prof.get("low_stock_days") or 7)
    xs = x[x["inventory"].notna()]
    xs = xs.sort_values("date", kind="stable") if c.has["date"] else xs
    latest = xs.groupby("product")["inventory"].last()
    if c.has["date"]:
        end = x["date"].max()
        win = 30
        start = max(end - pd.Timedelta(days=win - 1), x["date"].min())
        days = max(1, (end - start).days + 1)
        recent = x[(x["date"] >= start)]
        sold = recent.groupby("product")["units"].sum()
        rev = recent.groupby("product")["revenue"].sum()
        ever = x.groupby("product")["units"].sum()
        last_sale = x[x["units"] > 0].groupby("product")["date"].max()
    else:
        days, sold, rev, ever, last_sale = None, x.groupby("product")["units"].sum(), x.groupby("product")["revenue"].sum(), x.groupby("product")["units"].sum(), None
    items = []
    for prod, stock in latest.items():
        s30 = float(sold.get(prod, 0))
        rate = s30 / days if days else None
        price = float(rev.get(prod, 0)) / s30 if s30 else None
        cover = (stock / rate) if rate and rate > 0 else None
        if stock <= 0:
            status = "out"
        elif rate is None:
            status = "ok"
        elif rate == 0:
            status = "dead" if float(ever.get(prod, 0)) >= 0 else "ok"
        elif cover < min(3, low_days):
            status = "critical"
        elif cover < low_days:
            status = "low"
        elif cover < low_days * 2:
            status = "watch"
        elif cover > 120:
            status = "over"
        else:
            status = "ok"
        need = max(0.0, math.ceil((rate or 0) * (lead + safety + 14) - stock)) if rate else 0
        short = max(0.0, lead - cover) if cover is not None else (lead if status == "out" and rate else 0)
        items.append({"product": str(prod), "stock": r2(stock), "sold_30d": r2(s30), "per_day": r2(rate), "days_left": r2(cover),
                      "status": status, "reorder_qty": int(need) if need else 0, "avg_price": r2(price),
                      "revenue_at_risk": r2((rate or 0) * (price or 0) * short) if status in ("out", "critical", "low") else 0,
                      "last_sale": last_sale.get(prod).strftime("%Y-%m-%d") if last_sale is not None and prod in last_sale.index else None})
    order = {"out": 0, "critical": 1, "low": 2, "watch": 3, "dead": 4, "over": 5, "ok": 6}
    items.sort(key=lambda i: (order[i["status"]], i["days_left"] if i["days_left"] is not None else 1e9))
    cnt = {k: sum(1 for i in items if i["status"] == k) for k in order}
    return {"available": True, "items": items, "settings": {"lead_time_days": lead, "safety_days": safety, "low_stock_days": low_days},
            "summary": {**cnt, "needs_action": cnt["out"] + cnt["critical"] + cnt["low"], "revenue_at_risk": r2(sum(i["revenue_at_risk"] or 0 for i in items)), "total": len(items)},
            "reason": None}


# ───────────────────────── customers ─────────────────────────
def customers(c: Ctx):
    if not c.has["customer"]:
        return {"available": False, "reason": "No customer column was found."}
    x = c.x[c.x["customer"].notna()]
    n_cust = x["customer"].nunique()
    if n_cust > len(x) * 0.97:
        return {"available": False, "reason": "Every row has a different customer ID, so repeat-customer analysis is not possible with this data."}
    oid = c.has["order_id"]
    g = x.groupby("customer")
    t = g.agg(revenue=("revenue", "sum"), rows=("revenue", "size"), last=("date", "max"), first=("date", "min"))
    t["orders"] = g["order_id"].nunique() if oid else t["rows"]
    repeat = float((t["orders"] >= 2).mean() * 100)
    top_n = max(1, int(len(t) * 0.1))
    top = t.sort_values("revenue", ascending=False)
    share_top = float(top.head(top_n)["revenue"].sum() / max(t["revenue"].sum(), 1) * 100)
    anchor = x["date"].max() if c.has["date"] else None
    segs = {}
    if anchor is not None:
        t["recency"] = (anchor - t["last"]).dt.days
        f_hi, r_med, r_late = t["orders"].quantile(.75), t["recency"].median(), t["recency"].quantile(.75)

        def seg(r):
            if r.orders >= f_hi and r.recency <= r_med and f_hi >= 2:
                return "Champions"
            if r.orders >= 2 and r.recency > r_late:
                return "At risk"
            if r.orders >= 2:
                return "Loyal"
            if r.recency <= r_med:
                return "New"
            return "One-time"
        t["segment"] = t.apply(seg, axis=1)
        segs = {k: int(v) for k, v in t["segment"].value_counts().items()}
    rows = []
    for name, r in top.head(15).iterrows():
        rows.append({"customer": str(name), "revenue": r2(r.revenue), "orders": int(r.orders),
                     "last_seen": r["last"].strftime("%Y-%m-%d") if pd.notna(r["last"]) else None,
                     "segment": t.loc[name, "segment"] if "segment" in t else None})
    return {"available": True, "total": int(n_cust), "repeat_rate": r2(repeat), "avg_orders": r2(t["orders"].mean()), "avg_spend": r2(t["revenue"].mean()),
            "top10_share": r2(share_top), "segments": segs, "top": rows, "reason": None}
