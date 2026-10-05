"""Reading messy real-world files and mapping their columns to business roles."""
from __future__ import annotations

import csv
import io
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from . import store

ROLES = ["date", "revenue", "units", "price", "unit_cost", "cost", "inventory",
         "product", "category", "customer", "order_id", "discount"]
NUMERIC_ROLES = {"revenue", "units", "price", "unit_cost", "cost", "inventory"}
TEXT_ROLES = {"product", "category", "customer", "order_id"}

ROLE_LABELS = {
    "date": "Date of sale", "revenue": "Sales amount", "units": "Quantity sold", "price": "Selling price per unit",
    "unit_cost": "Cost per unit", "cost": "Total cost / expenses", "inventory": "Stock on hand",
    "product": "Product or item", "category": "Category", "customer": "Customer", "order_id": "Order / bill number",
    "discount": "Discount",
}
ROLE_HELP = {
    "date": "When the sale happened. Needed for trends, forecasts and comparisons.",
    "revenue": "How much money each row brought in.",
    "units": "How many items were sold. If missing, each row counts as one item.",
    "price": "Price of one unit. Used to work out sales if there is no sales column.",
    "unit_cost": "What one unit costs you. Used to calculate profit.",
    "cost": "Total cost for the row (purchase cost, expenses). Used to calculate profit.",
    "inventory": "Items currently in stock. Used for low-stock and reorder alerts.",
    "product": "Name of the product, dish or service sold.",
    "category": "Group the product belongs to.",
    "customer": "Customer name or ID. Used for repeat-customer analysis.",
    "order_id": "Bill or invoice number. Used to count real orders.",
    "discount": "Whether a discount was given (Yes/No) or how much.",
}

# (substring/token, score). Matching is done on normalised snake_case names.
NAME_HINTS = {
    "date": [("order_date", 10), ("sale_date", 10), ("invoice_date", 10), ("transaction_date", 10), ("purchase_date", 10),
             ("bill_date", 10), ("date", 8), ("timestamp", 8), ("datetime", 8), ("created_at", 6), ("day", 4), ("time", 3), ("month", 2)],
    "revenue": [("net_sales", 10), ("total_sales", 10), ("sales_amount", 10), ("revenue", 10), ("gmv", 9), ("turnover", 9),
                ("order_value", 9), ("line_total", 9), ("grand_total", 9), ("purchase_amount", 9), ("total_amount", 9),
                ("invoice_amount", 9), ("bill_amount", 9), ("sale_amount", 9), ("net_amount", 8), ("sales", 8), ("amount", 7),
                ("income", 6), ("total", 5), ("value", 3), ("paid", 4)],
    "units": [("units_sold", 10), ("quantity_sold", 10), ("qty_sold", 10), ("quantity", 9), ("qty", 9), ("units", 9),
              ("pieces", 7), ("pcs", 7), ("volume", 5), ("sold", 4), ("count", 3)],
    "price": [("unit_price", 10), ("selling_price", 10), ("sale_price", 10), ("price_per_unit", 10), ("mrp", 7), ("price", 8), ("rate", 5)],
    "unit_cost": [("unit_cost", 10), ("cost_price", 10), ("cost_per_unit", 10), ("purchase_price", 8), ("buying_price", 8), ("cogs_per_unit", 9)],
    "cost": [("total_cost", 10), ("cogs", 9), ("expenses", 9), ("expense", 9), ("cost", 8), ("spend", 6), ("purchase_cost", 8)],
    "inventory": [("inventory", 10), ("stock_level", 10), ("stock_on_hand", 10), ("on_hand", 10), ("closing_stock", 10),
                  ("stock_qty", 9), ("stock_quantity", 9), ("in_stock", 8), ("stock", 8), ("available", 5), ("balance", 3)],
    "product": [("product_name", 10), ("item_name", 10), ("item_purchased", 10), ("product", 9), ("item", 8), ("sku_name", 9),
                ("menu_item", 9), ("dish", 8), ("sku", 7), ("description", 5), ("article", 6), ("service", 5), ("name", 3)],
    "category": [("product_category", 10), ("category", 10), ("department", 8), ("segment", 5), ("section", 5),
                 ("class", 5), ("group", 5), ("type", 4), ("vertical", 5), ("brand", 3)],
    "customer": [("customer_id", 10), ("customer_name", 10), ("customer", 9), ("client", 8), ("buyer", 8), ("member", 5),
                 ("cust_id", 9), ("user_id", 7), ("phone", 5), ("mobile", 5), ("email", 5)],
    "order_id": [("order_id", 10), ("invoice_no", 10), ("invoice_number", 10), ("bill_no", 10), ("transaction_id", 10),
                 ("order_no", 10), ("order_number", 10), ("receipt", 8), ("txn_id", 9), ("invoice", 7), ("order", 4)],
    "discount": [("discount_applied", 10), ("discount", 9), ("promo_code_used", 8), ("promo", 6), ("coupon", 7), ("offer", 4)],
}
# words that make a column a poor match for a role
PENALTIES = {
    "revenue": {"discount", "tax", "gst", "shipping", "cost", "cogs", "expense", "unit", "price", "id", "rate", "previous", "count",
                "qty", "quantity", "profit", "margin", "rating", "age", "frequency"},
    "units": {"price", "cost", "stock", "inventory", "hand", "previous", "amount", "revenue", "sales", "rating", "age"},
    "price": {"total", "amount", "discount", "cost", "sales", "revenue", "previous", "rating", "age"},
    "unit_cost": {"total", "amount", "revenue"},
    "cost": {"price", "unit", "revenue", "sales", "per"},
    "inventory": {"price", "cost", "sold", "sales"},
    "product": {"category", "id", "type", "group", "customer", "payment", "shipping"},
    "category": {"id", "customer", "payment", "shipping", "age"},
    "customer": {"type", "segment", "category", "age", "gender", "location"},
    "order_id": {"date", "amount", "value", "total", "status"},
    "date": {"update", "birth", "dob", "expiry", "expire"},
    "discount": {"price", "total"},
}

CURRENCY_RE = re.compile(r"[₹$€£¥]|rs\.?|inr|usd|eur|gbp|\s", re.I)


def norm(name) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def to_number(s: pd.Series) -> pd.Series:
    """Convert strings like '₹1,23,456.50', '(120)', '12%' into numbers."""
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    t = s.astype(str).str.strip()
    neg = t.str.match(r"^\(.*\)$")
    t = t.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    t = t.str.replace(CURRENCY_RE, "", regex=True).str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    t = t.replace({"": np.nan, "nan": np.nan, "None": np.nan, "-": np.nan, "NA": np.nan, "N/A": np.nan, "null": np.nan})
    out = pd.to_numeric(t, errors="coerce")
    out[neg.fillna(False)] = -out[neg.fillna(False)].abs()
    return out


def _dayfirst_guess(sample: pd.Series) -> bool:
    first_gt12 = second_gt12 = 0
    for v in sample.dropna().astype(str).head(400):
        m = re.match(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", v)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            first_gt12 += a > 12
            second_gt12 += b > 12
    if first_gt12 and not second_gt12:
        return True
    if second_gt12 and not first_gt12:
        return False
    return True  # Indian and most world formats are day-first when ambiguous


def to_dates(s: pd.Series):
    """Return (datetime Series, note|None). Handles text dates, Excel serials and epoch."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce"), None
    if pd.api.types.is_numeric_dtype(s):
        v = pd.to_numeric(s, errors="coerce")
        med = v.dropna().median() if v.notna().any() else 0
        if 20000 < med < 80000:
            return pd.to_datetime(v, unit="D", origin="1899-12-30", errors="coerce"), "Dates were stored as Excel serial numbers and were converted."
        if med > 1e12:
            return pd.to_datetime(v, unit="ms", errors="coerce"), None
        if med > 1e9:
            return pd.to_datetime(v, unit="s", errors="coerce"), None
        return pd.Series(pd.NaT, index=s.index), None
    # 1) ISO dates (2026-10-03, 2026-10-03 14:20) are unambiguous: never apply day-first rules to them.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        iso = pd.to_datetime(s, format="ISO8601", errors="coerce")
        rest = iso.isna() & s.notna()
        out = iso
        note = None
        if rest.any():
            dayfirst = _dayfirst_guess(s[rest])
            try:
                other = pd.to_datetime(s[rest], errors="coerce", dayfirst=dayfirst, format="mixed")
            except Exception:
                other = pd.to_datetime(s[rest], errors="coerce", dayfirst=dayfirst)
            out = iso.copy()
            out[rest] = other
            if other.notna().any() and s[rest].astype(str).str.contains(r"^\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}", regex=True).any():
                note = "Dates like 03/04/2026 were read as day/month/year." if dayfirst else "Dates like 03/04/2026 were read as month/day/year."
    return out, note


# ───────────────────────── file reading ─────────────────────────
def read_table(path: Path) -> pd.DataFrame:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            return pd.read_excel(path, sheet_name=0)
        except ImportError:
            raise ValueError("Excel support needs the 'openpyxl' package. Run: pip install openpyxl")
    if ext == ".xls":
        raise ValueError("Old .xls files are not supported. Save the sheet as .xlsx or .csv and upload again.")
    raw = path.read_bytes()
    if not raw.strip():
        raise ValueError("The file is empty.")
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:8192]
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        sep = "\t" if ext == ".tsv" else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, skipinitialspace=True, low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed: \d+$")]
    if df.shape[1] < 2:
        raise ValueError("Only one column was found. Check that the file is a table with a header row.")
    return df


# ───────────────────────── detection ─────────────────────────
def _name_score(role, name):
    n = norm(name)
    toks = set(n.split("_"))
    best = 0
    for hint, sc in NAME_HINTS[role]:
        h_toks = hint.split("_")
        if n == hint:
            best = max(best, sc + 2)
        elif all(t in toks for t in h_toks) or (len(hint) > 4 and hint in n):
            best = max(best, sc)
    if best:
        pen = PENALTIES.get(role, set()) & toks
        best -= 6 * len(pen)
    return best


def _profile_col(s: pd.Series):
    nn = s.dropna()
    n = max(len(nn), 1)
    numeric = to_number(nn) if len(nn) else nn
    num_rate = float(numeric.notna().mean()) if len(nn) else 0
    is_text = not pd.api.types.is_numeric_dtype(s)
    date_rate = 0.0
    if len(nn):
        if is_text and num_rate < 0.5:
            d, _ = to_dates(nn.head(300))
            date_rate = float(d.notna().mean())
        elif pd.api.types.is_datetime64_any_dtype(s):
            date_rate = 1.0
    return {"num_rate": num_rate, "date_rate": date_rate, "unique": int(nn.nunique()), "n": len(nn),
            "unique_ratio": nn.nunique() / n, "is_text": is_text}


def detect(raw: pd.DataFrame) -> dict:
    """Guess which column plays which business role. Returns {'roles': {...}, 'candidates': {...}}."""
    profiles = {c: _profile_col(raw[c]) for c in raw.columns}
    scores = {r: {} for r in ROLES}
    for role in ROLES:
        for c in raw.columns:
            p = profiles[c]
            s = _name_score(role, c)
            if role == "date":
                if p["date_rate"] < 0.8:
                    continue
                s = max(s, 0) + (5 if s <= 0 else 0)
                if p["num_rate"] > 0.9 and not pd.api.types.is_datetime64_any_dtype(raw[c]):
                    continue
            elif role in NUMERIC_ROLES:
                if p["num_rate"] < 0.8 or s <= 0:
                    continue
                if pd.api.types.is_datetime64_any_dtype(raw[c]):
                    continue
            elif role in ("product", "category"):
                if s <= 0:
                    continue
                if p["unique_ratio"] > 0.9 and p["n"] > 20:
                    continue
                if role == "category" and p["unique"] > 120:
                    continue
            elif role == "discount":
                if s <= 0:
                    continue
            else:
                if s <= 0:
                    continue
            if s >= (1 if role == "date" else 4):
                scores[role][c] = s
    chosen, used = {}, set()
    # fixed order: most specific roles claim columns first
    for role in ["date", "order_id", "unit_cost", "revenue", "cost", "inventory", "price", "units", "customer", "discount", "product", "category"]:
        ranked = sorted(scores[role].items(), key=lambda kv: -kv[1])
        pick = next(((c, s) for c, s in ranked if c not in used), None)
        if pick:
            c, s = pick
            chosen[role] = {"column": c, "confidence": "high" if s >= 8 else "medium" if s >= 5 else "low", "score": s}
            used.add(c)
        else:
            chosen[role] = {"column": None, "confidence": None, "score": 0}
    candidates = {r: [c for c, _ in sorted(scores[r].items(), key=lambda kv: -kv[1])[:4]] for r in ROLES}
    return {"roles": chosen, "candidates": candidates}


# ───────────────────────── applying a mapping ─────────────────────────
def apply_mapping(raw: pd.DataFrame, mapping: dict, opts: dict | None = None):
    """Build the canonical frame. mapping: role -> column name or None."""
    opts = opts or {}
    notes, x = [], pd.DataFrame(index=raw.index)
    used = set()

    def col(role):
        c = mapping.get(role)
        if c and c in raw.columns:
            used.add(c)
            return raw[c]
        return None

    # date
    mode = opts.get("date_mode", "column")
    d = col("date") if mode == "column" else None
    if d is not None:
        dates, note = to_dates(d)
        if note:
            notes.append(note)
        bad = int(dates.isna().sum() - d.isna().sum())
        if bad > 0:
            notes.append(f"{bad} date value(s) could not be read and those rows were left out of time-based charts.")
        x["date"] = dates.dt.normalize()
    elif mode == "sequence":
        per = max(1, int(opts.get("rows_per_period") or 1))
        start = pd.to_datetime(opts.get("sequence_start") or "2026-01-01", errors="coerce")
        start = start if pd.notna(start) else pd.Timestamp("2026-01-01")
        x["date"] = start + pd.to_timedelta(np.arange(len(raw)) // per, unit="D")
        notes.append(f"No date column: dates were created from row order ({per} row(s) per day) because you chose that option.")
    else:
        x["date"] = pd.NaT

    for r in ("revenue", "units", "price", "unit_cost", "cost", "inventory"):
        s = col(r)
        x[r] = to_number(s) if s is not None else np.nan

    # derive missing pieces
    if x["revenue"].isna().all() and x["units"].notna().any() and x["price"].notna().any():
        x["revenue"] = x["units"] * x["price"]
        notes.append("Sales amount was calculated as quantity × price.")
    units_assumed = False
    if x["units"].isna().all():
        x["units"] = 1.0
        units_assumed = True
        notes.append("No quantity column: each row is counted as one item sold.")
    if x["price"].isna().all() and x["revenue"].notna().any():
        x["price"] = x["revenue"] / x["units"].replace(0, np.nan)
    if x["cost"].isna().all() and x["unit_cost"].notna().any():
        x["cost"] = x["unit_cost"] * x["units"]
        notes.append("Total cost was calculated as cost per unit × quantity.")

    for r, default in (("product", "All products"), ("category", "Uncategorised")):
        s = col(r)
        if s is None:
            x[r] = default
            if r == "product":
                notes.append("No product column was chosen: all sales are grouped as 'All products'.")
        else:
            x[r] = s.astype(str).str.strip().replace({"nan": default, "": default, "None": default})
    s = col("customer")
    x["customer"] = s.astype(str).str.strip().replace({"nan": np.nan, "": np.nan}) if s is not None else np.nan
    s = col("order_id")
    x["order_id"] = s.astype(str).str.strip().replace({"nan": np.nan, "": np.nan}) if s is not None else np.nan

    s = col("discount")
    x["discount"] = np.nan
    if s is not None:
        if pd.api.types.is_numeric_dtype(s) or to_number(s).notna().mean() > 0.9:
            x["discount"] = (to_number(s).fillna(0) > 0).astype(float)
        else:
            low = s.astype(str).str.strip().str.lower()
            x["discount"] = low.isin(["yes", "y", "true", "1", "applied", "used"]).astype(float)

    # extras: every other column becomes an optional breakdown dimension
    extras = []
    for c in raw.columns:
        if c in used:
            continue
        name = c if c not in x.columns else f"{c} (original)"
        x[name] = raw[c]
        extras.append(name)

    miss_rev = int(x["revenue"].isna().sum())
    x["revenue"] = x["revenue"].fillna(0.0)
    x["_revenue_missing"] = x["revenue"].eq(0) & (miss_rev > 0)
    if opts.get("drop_duplicates"):
        before = len(x)
        x = x.drop_duplicates().reset_index(drop=True)
        if before - len(x):
            notes.append(f"{before - len(x)} exact duplicate row(s) were removed.")
    return x, {"notes": notes, "units_assumed": units_assumed, "extras": extras, "revenue_missing": miss_rev}


# ───────────────────────── dataset build + cache ─────────────────────────
_CACHE: dict = {}


def _merge_overrides(raw, detection, overrides):
    roles = {r: detection["roles"][r]["column"] for r in ROLES}
    for r, c in (overrides.get("mapping") or {}).items():
        if r not in ROLES:
            continue
        if c in (None, "", "__none__"):
            roles[r] = None
        elif c in raw.columns:
            roles[r] = c
    return roles


def build_dataset(ds: dict):
    """Return (frame, info) for a dataset record. Cached by (id, version)."""
    key = (ds["id"], ds["version"])
    if key in _CACHE:
        return _CACHE[key]
    overrides = ds.get("overrides") or {}
    opts = {k: overrides.get(k) for k in ("date_mode", "rows_per_period", "sequence_start", "drop_duplicates")}
    frames, notes, detections, all_extras, columns = [], [], [], [], []
    units_assumed = False
    rev_missing = 0
    d = store.dataset_dir(ds["id"])
    for f in ds["files"]:
        p = d / f["stored"]
        raw = read_table(p)
        det = detect(raw)
        roles = _merge_overrides(raw, det, overrides)
        fo = dict(opts)
        if fo.get("date_mode") in (None, ""):
            fo["date_mode"] = "column" if roles.get("date") else "none"
        frame, meta = apply_mapping(raw, roles, fo)
        frame["_source"] = f["name"]
        frames.append(frame)
        detections.append({"file": f["name"], "roles": det["roles"], "candidates": det["candidates"], "columns": list(raw.columns), "used": roles})
        notes += [f"{f['name']}: {n}" if len(ds["files"]) > 1 else n for n in meta["notes"]]
        units_assumed = units_assumed or meta["units_assumed"]
        rev_missing += meta["revenue_missing"]
        all_extras += [e for e in meta["extras"] if e not in all_extras]
        columns += [c for c in raw.columns if c not in columns]
    if not frames:
        raise ValueError("This dataset has no files.")
    x = pd.concat(frames, ignore_index=True, sort=False)
    x = x.sort_values("date", kind="stable").reset_index(drop=True) if x["date"].notna().any() else x
    info = _profile_frame(x, ds, detections, notes, all_extras, units_assumed, rev_missing, overrides, columns)
    _CACHE.clear() if len(_CACHE) > 6 else None
    _CACHE[key] = (x, info)
    return x, info


def invalidate(ds_id=None):
    for k in list(_CACHE):
        if ds_id is None or k[0] == ds_id:
            _CACHE.pop(k, None)


def _profile_frame(x, ds, detections, notes, extras, units_assumed, rev_missing, overrides, columns):
    has = {
        "date": bool(x["date"].notna().any()),
        "revenue": bool((x["revenue"] != 0).any()),
        "cost": bool(x["cost"].notna().any()),
        "inventory": bool(x["inventory"].notna().any()),
        "units": not units_assumed,
        "product": bool((x["product"] != "All products").any()),
        "category": bool((x["category"] != "Uncategorised").any()),
        "customer": bool(x["customer"].notna().any()),
        "order_id": bool(x["order_id"].notna().any()),
        "discount": bool(x["discount"].notna().any()),
    }
    dims = []
    for name in ["category", "product"] + extras:
        if name not in x.columns:
            continue
        if name in ("category", "product") and not has[name]:
            continue
        s = x[name]
        nun = s.nunique(dropna=True)
        if name in ("category", "product") or (2 <= nun <= 60 and not pd.api.types.is_float_dtype(s) and nun < len(x) * 0.5):
            if pd.api.types.is_numeric_dtype(s) and nun > 15:
                continue
            dims.append(name)
    num_extras = [e for e in extras if e in x.columns and pd.api.types.is_numeric_dtype(x[e]) and x[e].nunique() > 8]
    dr = None
    if has["date"]:
        dd = x["date"].dropna()
        dr = {"start": dd.min().strftime("%Y-%m-%d"), "end": dd.max().strftime("%Y-%m-%d"), "days": int((dd.max() - dd.min()).days) + 1}
    quality = _quality(x, has, rev_missing, notes, len(x))
    merged_roles = detections[0]["used"] if detections else {}
    return {
        "rows": int(len(x)), "columns": len(columns), "has": has, "dims": dims, "numeric_extras": num_extras,
        "date_range": dr, "notes": notes, "quality": quality, "detections": detections, "roles": merged_roles,
        "all_columns": columns, "overrides": overrides, "units_assumed": units_assumed,
        "freq": infer_freq(x) if has["date"] else None,
    }


def infer_freq(x):
    d = x["date"].dropna().drop_duplicates().sort_values()
    if len(d) < 3:
        return "D"
    gap = d.diff().dt.days.dropna().median()
    return "M" if gap >= 25 else "W" if gap >= 6 else "D"


def _quality(x, has, rev_missing, notes, n):
    checks, penalty = [], 0

    def add(label, status, detail, pen=0):
        nonlocal penalty
        checks.append({"label": label, "status": status, "detail": detail})
        penalty += pen

    if n == 0:
        return {"score": 0, "checks": [{"label": "Rows", "status": "bad", "detail": "No rows were found."}], "rows": 0}
    add("Rows loaded", "ok", f"{n:,} rows ready for analysis.")
    if has["revenue"]:
        pct = rev_missing / n * 100
        if rev_missing:
            add("Sales amounts", "warn" if pct < 10 else "bad", f"{rev_missing:,} rows ({pct:.1f}%) have no sales amount and count as 0.", min(25, pct * 1.5))
        else:
            add("Sales amounts", "ok", "Every row has a sales amount.")
    else:
        add("Sales amounts", "bad", "No sales amount column found. Choose one in Column mapping.", 40)
    if has["date"]:
        bad = int(x["date"].isna().sum())
        if bad:
            pct = bad / n * 100
            add("Dates", "warn" if pct < 10 else "bad", f"{bad:,} rows ({pct:.1f}%) have no usable date.", min(25, pct * 1.5))
        else:
            add("Dates", "ok", "Every row has a valid date.")
    else:
        add("Dates", "warn", "No date column. Trends, forecasts and period comparisons are switched off until you map one.", 15)
    neg = int((x["revenue"] < 0).sum())
    if neg:
        add("Refunds / negatives", "info", f"{neg:,} rows have negative sales and are treated as returns.")
    dup = int(x.drop(columns=[c for c in ("_source", "_revenue_missing") if c in x.columns]).duplicated().sum())
    if dup:
        pct = dup / n * 100
        add("Duplicate rows", "warn" if pct < 5 else "bad", f"{dup:,} rows are exact duplicates. Remove them in Column mapping if they are mistakes.", min(10, pct))
    else:
        add("Duplicate rows", "ok", "No exact duplicate rows.")
    add("Costs", "ok" if has["cost"] else "info",
        "Cost data found, so profit is calculated." if has["cost"] else "No cost column. Profit is unknown until you add costs or set a typical cost % in Settings.")
    add("Stock levels", "ok" if has["inventory"] else "info",
        "Stock data found, so low-stock alerts work." if has["inventory"] else "No stock column. Low-stock and reorder alerts need one.")
    if has["revenue"]:
        r = x["revenue"]
        med, mad = r.median(), (r - r.median()).abs().median()
        if mad > 0:
            out = int(((r - med).abs() > 12 * mad * 1.4826).sum())
            if out > max(3, n * 0.01):
                add("Unusual amounts", "warn", f"{out:,} rows have amounts far from normal. Check for typing mistakes.", 5)
    return {"score": int(max(0, min(100, round(100 - penalty)))), "checks": checks, "rows": n}
