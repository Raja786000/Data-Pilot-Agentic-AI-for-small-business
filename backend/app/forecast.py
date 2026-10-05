"""Forecasting (model comparison with backtest) and what-if scenarios."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from .metrics import Ctx, r2, pct_change, totals

SEASON = {"D": 7, "W": 4, "M": 12}
UNIT = {"D": "day", "W": "week", "M": "month"}
PERIOD_CODE = {"D": "D", "W": "W-SUN", "M": "MS"}
METRICS = {"revenue": "Sales", "units": "Items sold", "orders": "Orders", "profit": "Profit"}


def _series(c: Ctx, metric: str, freq: str):
    x = c.x[c.x["date"].notna()]
    if metric == "units":
        s = x.groupby("date")["units"].sum()
    elif metric == "orders":
        s = x.groupby("date")["order_id"].nunique() if c.has["order_id"] else x.groupby("date").size()
    elif metric == "profit":
        s = x.groupby("date")["_profit"].sum(min_count=1).fillna(0)
    else:
        s = x.groupby("date")["revenue"].sum()
    s = s.reindex(pd.date_range(x["date"].min(), x["date"].max(), freq="D"), fill_value=0.0)
    if freq == "W":
        s = s.resample("W-SUN").sum()
        if x["date"].max().dayofweek != 6 and len(s) > 3:
            s = s.iloc[:-1]  # drop incomplete trailing week
    elif freq == "M":
        s = s.resample("MS").sum()
        if x["date"].max().day < x["date"].max().days_in_month and len(s) > 3:
            s = s.iloc[:-1]
    return s.astype(float)


# ── models: each takes (y: ndarray, h: int, idx: DatetimeIndex of history, freq) and returns ndarray(h) ──
def m_naive(y, h, idx, freq):
    s = SEASON[freq] if len(y) >= 2 * SEASON[freq] else 1
    return np.resize(y[-s:], h)


def m_average(y, h, idx, freq):
    s = SEASON[freq] if len(y) >= SEASON[freq] else len(y)
    return np.full(h, y[-s:].mean())


def m_pattern(y, h, idx, freq):
    """Seasonal profile × recent level × damped trend."""
    s = SEASON[freq]
    if len(y) < 2 * s:
        return m_average(y, h, idx, freq)
    k = (len(y) // s) * s
    recent = y[-min(k, s * 8):]
    k2 = (len(recent) // s) * s
    recent = recent[-k2:]
    prof = recent.reshape(-1, s).mean(axis=0)
    prof = prof / (prof.mean() or 1)
    phase0 = (len(y) - len(recent)) % s
    # level = mean of last full cycles; trend = per-cycle slope of cycle means, damped
    means = recent.reshape(-1, s).mean(axis=1)
    slope = np.polyfit(np.arange(len(means)), means, 1)[0] if len(means) >= 3 else 0.0
    level = means[-1]
    out = []
    for i in range(h):
        pos = (len(y) + i - phase0) % s
        damp = sum(0.85 ** j for j in range(1, i // s + 2))
        out.append(max(0.0, (level + slope * damp * 0.5) * prof[pos]))
    return np.array(out)


def _feats(hist, i, idx_i, freq):
    s = SEASON[freq]
    l1 = hist[i - 1]
    ls = hist[i - s] if i - s >= 0 else hist[i - 1]
    roll = np.mean(hist[max(0, i - s):i])
    f = [l1, ls, roll]
    if freq == "D":
        dow = np.zeros(7)
        dow[idx_i.dayofweek] = 1
        f += list(dow)
    return f


def m_ridge(y, h, idx, freq):
    s = SEASON[freq]
    if len(y) < max(35, 3 * s):
        raise ValueError("not enough history")
    X, t = [], []
    start = s
    for i in range(start, len(y)):
        X.append(_feats(y, i, idx[i], freq))
        t.append(y[i])
    X, t = np.array(X), np.array(t)
    scale = max(np.mean(np.abs(t)), 1e-9)
    model = Ridge(alpha=1.0).fit(X / scale, t / scale)
    hist = list(y)
    fut = pd.date_range(idx[-1], periods=h + 1, freq=PERIOD_CODE[freq])[1:] if freq != "D" else pd.date_range(idx[-1] + pd.Timedelta(days=1), periods=h)
    out = []
    for j in range(h):
        i = len(hist)
        f = np.array([_feats(np.array(hist), i, fut[j], freq)])
        p = max(0.0, float(model.predict(f / scale)[0] * scale))
        hist.append(p)
        out.append(p)
    return np.array(out)


MODELS = {
    "pattern": ("Weekly pattern + trend" , m_pattern),
    "ridge": ("Machine learning (Ridge regression)", m_ridge),
    "naive": ("Same as last cycle", m_naive),
    "average": ("Recent average", m_average),
}


def _wape(a, f):
    d = np.sum(np.abs(a))
    return float(np.sum(np.abs(a - f)) / d * 100) if d > 0 else 100.0


_CACHE = {}


def forecast(c: Ctx, metric="revenue", horizon=None):
    if not c.has["date"]:
        return {"available": False, "reason": "Forecasts need a date column. Choose one in Data Studio → Column mapping."}
    if metric not in METRICS or (metric == "profit" and not c.cost_mode):
        metric = "revenue"
    freq = c.info["freq"] or "D"
    s = _series(c, metric, freq)
    if len(s) < 14:
        return {"available": False, "reason": f"Only {len(s)} {UNIT[freq]}s of history. At least 14 are needed for a reasonable forecast."}
    h = int(horizon or {"D": 14, "W": 8, "M": 6}[freq])
    h = max(3, min(h, {"D": 90, "W": 26, "M": 12}[freq]))
    key = (c.ds["id"], c.ds["version"], metric, h)
    if key in _CACHE:
        return _CACHE[key]
    y, idx = s.values, s.index
    hold = int(min(max(h, SEASON[freq]), max(4, len(y) // 4)))
    train_y, train_idx, test = y[:-hold], idx[:-hold], y[-hold:]
    table = []
    for k, (label, fn) in MODELS.items():
        try:
            pred = fn(train_y, hold, train_idx, freq)
            table.append({"id": k, "name": label, "wape": r2(_wape(test, pred)), "_pred": pred})
        except Exception:
            continue
    if not table:
        return {"available": False, "reason": "Could not fit a forecast on this data."}
    table.sort(key=lambda r: r["wape"])
    best = table[0]
    resid = test - best["_pred"]
    sigma = float(np.std(resid)) if len(resid) > 2 else float(np.std(y) * 0.3)
    fn = MODELS[best["id"]][1]
    pred = fn(y, h, idx, freq)
    fut_idx = pd.date_range(idx[-1] + pd.Timedelta(days=1), periods=h) if freq == "D" else pd.date_range(idx[-1], periods=h + 1, freq=PERIOD_CODE[freq])[1:]
    pts = []
    for i, (d, v) in enumerate(zip(fut_idx, pred)):
        w = 1.28 * sigma * (1 + 0.04 * i)
        pts.append({"date": d.strftime("%Y-%m-%d"), "value": r2(v), "lower": r2(max(0, v - w)), "upper": r2(v + w)})
    keep = {"D": 60, "W": 26, "M": 18}[freq]
    hist = [{"date": d.strftime("%Y-%m-%d"), "value": r2(v)} for d, v in list(zip(idx, y))[-keep:]]
    total_f = float(np.sum(pred))
    prev_actual = float(np.sum(y[-h:]))
    acc = max(0.0, 100 - best["wape"])
    out = {
        "available": True, "metric": metric, "metric_label": METRICS[metric], "freq": freq, "unit": UNIT[freq], "horizon": h,
        "history": hist, "forecast": pts, "model": {"id": best["id"], "name": best["name"]},
        "backtest": [{"id": t["id"], "name": t["name"], "wape": t["wape"], "accuracy": r2(max(0, 100 - t["wape"]))} for t in table],
        "holdout_periods": hold, "accuracy": r2(acc),
        "reliability": "good" if best["wape"] < 15 else "fair" if best["wape"] < 30 else "low",
        "summary": {"total": r2(total_f), "previous": r2(prev_actual), "change": r2(pct_change(total_f, prev_actual)), "average": r2(total_f / h),
                    "peak": max(pts, key=lambda p: p["value"])["date"], "low": min(pts, key=lambda p: p["value"])["date"]},
        "history_periods": int(len(y)),
    }
    if len(_CACHE) > 20:
        _CACHE.clear()
    _CACHE[key] = out
    return out


# ───────────────────────── scenarios ─────────────────────────
def estimate_elasticity(c: Ctx):
    """Rough price elasticity: within-product log-log slope of units vs price. Returns dict."""
    x = c.x
    if not c.has["units"] or not c.has["product"]:
        return {"value": None, "reason": "Needs quantity and product columns."}
    d = x[(x["units"] > 0) & (x["price"] > 0)][["product", "units", "price"]].copy()
    if len(d) < 200:
        return {"value": None, "reason": "Not enough rows to estimate price sensitivity."}
    d["lp"], d["lu"] = np.log(d["price"]), np.log(d["units"])
    d["lp"] -= d.groupby("product")["lp"].transform("mean")
    d["lu"] -= d.groupby("product")["lu"].transform("mean")
    v = float((d["lp"] ** 2).mean())
    if v < 0.0004:
        return {"value": None, "reason": "Your prices barely changed, so the data cannot show how demand reacts to price."}
    slope = float((d["lp"] * d["lu"]).mean() / v)
    if not np.isfinite(slope) or slope >= -0.05:
        return {"value": None, "reason": "No clear link between price and quantity was found in your data."}
    return {"value": r2(max(-3.0, slope)), "reason": f"Estimated from {len(d):,} rows. Treat as a rough guide."}


def scenario(c: Ctx, inp: dict):
    price = float(inp.get("price_change", 0)) / 100
    demand = float(inp.get("demand_change", 0)) / 100
    cost_ch = float(inp.get("cost_change", 0)) / 100
    disc = float(inp.get("discount", 0)) / 100
    extra = float(inp.get("extra_spend", 0) or 0)
    elas = inp.get("elasticity")
    notes = []
    if elas in (None, ""):
        est = estimate_elasticity(c)
        elas = est["value"] if est["value"] is not None else -1.0
        notes.append(f"Price sensitivity {'estimated from your data' if est['value'] is not None else 'assumed'} at {elas}. {est['reason']}")
    elas = float(elas)

    fc = forecast(c, "revenue") if c.has["date"] else {"available": False}
    if fc.get("available"):
        base_rev = fc["summary"]["total"]
        base_label = f"the next {fc['horizon']} {fc['unit']}s (forecast)"
        n_days = fc["horizon"] * {"day": 1, "week": 7, "month": 30}[fc["unit"]]
        recent = c.x[c.x["date"] > c.x["date"].max() - pd.Timedelta(days=30)]
    else:
        base_rev = float(c.x["revenue"].sum())
        base_label = "your whole data file"
        recent = c.x
        n_days = None
        notes.append("No dates, so the baseline is everything in the file.")
    t = totals(recent, c.has["order_id"])
    ratio_units = (t["units"] / t["revenue"]) if t["revenue"] else 0
    base_units = base_rev * ratio_units
    base_cost = None
    if c.cost_mode and t["cost"] is not None and t["revenue"]:
        base_cost = base_rev * (t["cost"] / t["revenue"])
    eff_price = (1 + price) * (1 - disc) - 1
    dem_mult = (1 + demand) * ((1 + eff_price) ** elas)
    rev_s = base_rev * (1 + eff_price) * dem_mult
    units_s = base_units * dem_mult
    cost_s = base_cost * dem_mult * (1 + cost_ch) if base_cost is not None else None
    profit_b = base_rev - base_cost if base_cost is not None else None
    profit_s = rev_s - cost_s - extra if cost_s is not None else None
    if profit_s is None and extra:
        notes.append("Extra spend is not subtracted because profit is unknown. Add costs to see profit impact.")
    curve = []
    for p in range(-20, 21, 5):
        ep = (1 + p / 100) * (1 - disc) - 1
        dm = (1 + demand) * ((1 + ep) ** elas)
        r = base_rev * (1 + ep) * dm
        pr = (r - base_cost * dm * (1 + cost_ch) - extra) if base_cost is not None else None
        curve.append({"price_change": p, "revenue": r2(r), "profit": r2(pr)})
    best = max(curve, key=lambda z: z["profit"] if z["profit"] is not None else z["revenue"])
    rows = [{"label": "Sales", "baseline": r2(base_rev), "scenario": r2(rev_s), "delta": r2(rev_s - base_rev), "change": r2(pct_change(rev_s, base_rev)), "money": True},
            {"label": "Items sold", "baseline": r2(base_units), "scenario": r2(units_s), "delta": r2(units_s - base_units), "change": r2(pct_change(units_s, base_units)), "money": False}]
    if profit_b is not None:
        rows.append({"label": "Profit", "baseline": r2(profit_b), "scenario": r2(profit_s), "delta": r2(profit_s - profit_b), "change": r2(pct_change(profit_s, profit_b)), "money": True})
    verdict = None
    if profit_s is not None:
        d = profit_s - profit_b
        verdict = ("This change is expected to raise profit by " if d >= 0 else "This change is expected to reduce profit by ") + c.m(abs(d)) + f" over {base_label}."
    else:
        d = rev_s - base_rev
        verdict = ("This change is expected to raise sales by " if d >= 0 else "This change is expected to reduce sales by ") + c.m(abs(d)) + f" over {base_label}."
    return {"baseline_label": base_label, "rows": rows, "verdict": verdict, "elasticity": elas, "curve": curve,
            "best_price_change": best["price_change"], "notes": notes + ["This is a what-if estimate, not a guarantee. It assumes everything else stays the same."],
            "inputs": inp}
