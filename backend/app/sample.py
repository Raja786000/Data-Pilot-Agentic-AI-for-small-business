"""Creates a realistic sample shop so every feature can be explored before real data is added."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

TEMPLATE_CSV = """Date,Bill No,Category,Product,Quantity,Unit Price,Sales Amount,Cost,Stock,Customer
2026-09-01,B1001,Grocery,Atta 5kg,2,260,520,430,38,C001
2026-09-01,B1002,Dairy,Milk 1L,3,66,198,180,90,C002
2026-09-02,B1003,Snacks,Biscuits,5,10,50,41,300,C003
"""


def make_sample() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    end = date.today() - timedelta(days=1)
    days = pd.date_range(end - timedelta(days=179), end)
    # product: (category, price, cost, base daily units)
    prods = {
        "Atta 5kg": ("Grocery", 260, 215, 14), "Basmati Rice 5kg": ("Grocery", 610, 520, 8), "Toor Dal 1kg": ("Grocery", 165, 138, 12),
        "Sugar 1kg": ("Grocery", 48, 44, 20), "Cooking Oil 1L": ("Grocery", 150, 134, 11), "Amul Butter 500g": ("Dairy", 285, 255, 6),
        "Milk 1L": ("Dairy", 66, 60, 34), "Paneer 200g": ("Dairy", 95, 78, 9), "Parle-G": ("Snacks", 10, 8.2, 80), "Maggi 4-pack": ("Snacks", 56, 47, 18),
        "Namkeen 400g": ("Snacks", 120, 92, 7), "Surf Excel 1kg": ("Household", 210, 172, 5), "Dettol Soap": ("Household", 48, 38, 9),
        "Phenyl 1L": ("Household", 95, 101, 4),  # sold below cost on purpose
    }
    stock = {p: int(v[3] * rng.integers(5, 10)) for p, v in prods.items()}
    custs = [f"C{n:03d}" for n in range(1, 161)]
    cust_w = rng.dirichlet(np.ones(len(custs)) * 0.35)
    rows, bill = [], 2000
    n_days = len(days)
    for i, d in enumerate(days):
        wk = {0: .9, 1: .85, 2: .95, 3: 1.0, 4: 1.1, 5: 1.35, 6: 1.25}[d.weekday()]
        trend = 1 + 0.0012 * i
        if i >= n_days - 21:
            trend *= 0.82   # recent slowdown
        promo = 1.5 if i in (60, 61, 120) else 1.0
        month_end = 1.12 if d.day >= 28 or d.day <= 2 else 1.0
        for p, (cat, price, cost, base) in prods.items():
            mult = wk * trend * promo * month_end
            if p == "Toor Dal 1kg" and i >= n_days - 21:
                mult *= 1.25
            q = int(rng.poisson(max(0.1, base * mult / 5)))
            if q == 0:
                continue
            skip = p == "Toor Dal 1kg" and i >= n_days - 25  # supplier delay → stock-out risk
            if stock[p] < base * 2.2 and rng.random() < 0.3 and not skip:
                stock[p] += int(base * rng.integers(6, 11))     # supplier delivery arrives
            if stock[p] <= 0:
                stock[p] = 0 if skip else int(base * 4)
            sold = min(q, stock[p])
            if sold == 0:
                continue
            stock[p] -= sold
            bill += 1
            rows.append([d.strftime("%Y-%m-%d"), f"B{bill}", cat, p, sold, price, round(price * sold, 2), round(cost * sold, 2), stock[p], rng.choice(custs, p=cust_w)])
    df = pd.DataFrame(rows, columns=["Date", "Bill No", "Category", "Product", "Quantity", "Unit Price", "Sales Amount", "Cost", "Stock", "Customer"])
    return df
