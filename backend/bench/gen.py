"""Deterministic synthetic table generator for the performance benchmark.

One schema at many scales, so a latency curve measures *size* and nothing else.
The column mix is chosen to exercise every part of the plan grammar the product
actually ships: low/mid/high-cardinality dimensions, a datetime for the trend
shape, several measures, and one column with real nulls so imputation can be
timed against the same rows as everything else.

Seeded, so two runs on two machines describe the same table.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Cardinalities are fixed, not proportional to row count: a group-by over 5
# regions has to stay a group-by over 5 regions at every scale, or the curve
# would be measuring output size instead of input size. `customer_id` is the
# one deliberate exception — it grows with the table, which is what makes it a
# high-cardinality case worth timing.
REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = [
    "Electronics", "Furniture", "Office Supplies", "Clothing", "Grocery",
    "Sports", "Toys", "Books", "Beauty", "Automotive", "Garden", "Pet",
]
CHANNELS = ["Online", "Retail", "Partner"]
N_PRODUCTS = 200

NULL_FRACTION = 0.08  # discount_pct — the imputation target


def make_frame(rows: int, seed: int = 20260816) -> pd.DataFrame:
    """A sales-shaped table of `rows` rows and 11 columns."""
    rng = np.random.default_rng(seed)

    # Three years of daily-resolution timestamps, deliberately unsorted so a
    # trend query has to do real work rather than reading an already-ordered
    # column.
    start = np.datetime64("2023-01-01")
    offsets = rng.integers(0, 1095, size=rows).astype("timedelta64[D]")
    seconds = rng.integers(0, 86400, size=rows).astype("timedelta64[s]")
    order_date = start + offsets + seconds

    quantity = rng.integers(1, 21, size=rows)
    unit_price = np.round(rng.gamma(shape=2.0, scale=45.0, size=rows) + 1.0, 2)

    discount = np.round(rng.beta(2, 8, size=rows) * 40, 2)
    # Missing at random, at a rate that is worth disclosing but not fatal.
    discount[rng.random(rows) < NULL_FRACTION] = np.nan

    frame = pd.DataFrame(
        {
            "order_id": [f"ORD-{i:09d}" for i in range(rows)],
            "order_date": order_date,
            "region": rng.choice(REGIONS, size=rows),
            "category": rng.choice(CATEGORIES, size=rows),
            "product": rng.choice([f"SKU-{i:04d}" for i in range(N_PRODUCTS)], size=rows),
            "customer_id": [f"CUST-{i:07d}" for i in rng.integers(0, max(1, rows // 8), size=rows)],
            "channel": rng.choice(CHANNELS, size=rows),
            "quantity": quantity,
            "unit_price": unit_price,
            "discount_pct": discount,
            "revenue": np.round(quantity * unit_price * (1 - np.nan_to_num(discount) / 100), 2),
        }
    )
    return frame


def make_dimension(kind: str, seed: int = 20260816) -> pd.DataFrame:
    """A dimension table for the join-headroom measurement.

    `small` is the 200-product lookup a real star-schema join uses; `large` is a
    customer table sized to the fact table, which is the case that actually
    costs something.
    """
    rng = np.random.default_rng(seed + 1)
    if kind == "small":
        return pd.DataFrame(
            {
                "product": [f"SKU-{i:04d}" for i in range(N_PRODUCTS)],
                "supplier": rng.choice([f"SUP-{i:03d}" for i in range(25)], size=N_PRODUCTS),
                "cost": np.round(rng.uniform(1, 80, size=N_PRODUCTS), 2),
            }
        )
    n = 125_000  # 1M fact rows / 8
    return pd.DataFrame(
        {
            "customer_id": [f"CUST-{i:07d}" for i in range(n)],
            "segment": rng.choice(["SMB", "Mid-Market", "Enterprise"], size=n),
            "signup_year": rng.integers(2015, 2026, size=n),
        }
    )
