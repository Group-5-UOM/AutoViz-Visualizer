"""Generate the synthetic data-quality / skew stress datasets.

Everything else in test-data/ is real, unmodified public data. These two files
are deliberately **not** — each column exists to trip exactly one code path in
the cleaning-disclosure and axis-scaling layers, at a size that lands on the
right side of the thresholds those layers use. Real data cannot be relied on to
do that, and a fixture whose defects are accidental is a fixture that stops
testing what you think it tests when someone regenerates it.

Deterministic: seeded, so a regenerated file is byte-identical and a diff means
a real change.

    python test-data/synthetic-quality/generate.py

Writes `messy_sales.csv` (240 rows, eyeball-able) and `messy_sales_large.csv`
(200,000 rows, for throughput). Both share a schema, so the same question can be
asked of each and only the timing should differ.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent

CHANNELS = ["Online", "Retail", "Partner", "Direct"]
PRODUCTS = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]

# Case + whitespace variants of four real regions. Folding merges them, which is
# what makes this `case_variants` (a SAFE auto-repair) rather than
# `high_cardinality` — the two findings are mutually exclusive in quality.scan.
REGION_VARIANTS = [
    "North", "north", "  North", "NORTH",
    "South", "south", "South  ",
    "East", "east", " East",
    "West", "WEST", "West ",
]

# 32 distinct, cleanly cased. Past HIGH_CARDINALITY (25) and with no case
# variants to merge, so this is the column that raises the grouping proposal.
REPS = [f"Rep {i:02d}" for i in range(1, 33)]

NOTES = ["ok", "follow up", "priority", "checked", "rush order"]

HEADER = [
    "order_id", "order_date", "region", "channel", "product_line", "sales_rep",
    "units", "revenue", "profit_delta", "discount_pct", "customer_note",
]

START = date(2026, 1, 1)


def build(n_rows: int, seed: int = 7) -> list[list]:
    rng = random.Random(seed)
    rows = []
    # 1 in 120 orders is an enterprise deal three orders of magnitude above the
    # rest. A *fixed* interval, not a fraction of n: the skew has to survive
    # aggregation, and what decides that is how far the max sits above the
    # median, which only holds if the extremes stay rare as the file grows.
    WHALE_EVERY = 120
    for i in range(n_rows):
        is_whale = i % WHALE_EVERY == WHALE_EVERY - 1
        revenue = (
            round(rng.uniform(600_000, 1_400_000), 2)
            if is_whale
            else round(rng.lognormvariate(6.4, 0.55), 2)  # ~200 - 3,000
        )
        # Crosses zero, with rare extremes in both directions: the case a log
        # domain cannot represent and symlog must pick up.
        if is_whale:
            profit_delta = round(rng.choice([-1, 1]) * rng.uniform(250_000, 480_000), 2)
        else:
            profit_delta = round(rng.gauss(40, 260), 2)

        # ~10% missing: over the 5% that earns a sentence, under the 30% that
        # demands confirmation before rows are removed.
        discount = "" if rng.random() < 0.10 else str(round(rng.uniform(0, 35), 1))

        # ~46% missing, split between true blanks and whitespace-only cells. The
        # true-blank half alone is 34%, so a bare drop_nulls on this column trips
        # the >30% confirmation gate without needing the cleaning steps to run
        # first; the whitespace half only becomes null after
        # empty_string_to_null, which is what makes the two halves worth having.
        draw = rng.random()
        if draw < 0.34:
            note = ""
        elif draw < 0.46:
            note = "   "
        else:
            note = rng.choice(NOTES)

        rows.append([
            1000 + i,
            (START + timedelta(days=i % 365)).isoformat(),
            rng.choice(REGION_VARIANTS),
            rng.choice(CHANNELS),
            rng.choice(PRODUCTS),
            rng.choice(REPS),
            rng.randint(1, 40),
            revenue,
            profit_delta,
            discount,
            note,
        ])

    # Exact duplicates, ~2.5%. Never auto-removed: repeated rows can be genuine
    # repeated events, so this is the finding that must arrive as a question.
    for src in rng.sample(range(len(rows)), max(2, n_rows // 40)):
        rows.append(list(rows[src]))
    rng.shuffle(rows)
    return rows


def write(path: Path, rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        w.writerow(HEADER)
        w.writerows(rows)
    print(f"{path.name}: {len(rows):,} rows, {path.stat().st_size / 1024:.0f} KiB")


if __name__ == "__main__":
    write(HERE / "messy_sales.csv", build(240))
    write(HERE / "messy_sales_large.csv", build(200_000, seed=11))
