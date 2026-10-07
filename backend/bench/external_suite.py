"""The external benchmark: 100 nvBench and 100 VisEval queries, frozen.

    uv run python -m bench.external_suite build --nvbench path/to/NVBench.json   # once
    uv run python -m bench.external_suite check                                   # offline

The NL suite (`nl_suite.py`) was written by us over six tables we chose, so it
cannot say how the planner does on questions it was never shaped around. These
two published NL2VIS benchmarks can — with two limits stated up front:

* **Single-table only.** The plan grammar answers over one table, so a query
  whose gold SQL joins, nests a SELECT, or combines results (UNION / INTERSECT /
  EXCEPT) is not representable and is dropped *before* sampling, never scored
  as a failure. Each case is given only the one table its SQL reads; VisEval
  gives the model the whole database, so this is the easier setting.
* **The gold is the published ``vis_obj``** — the x values, y values and series
  each benchmark ships for its chart — never our own re-derivation. A chart is
  scored on whether its data matches that, the way VisEval's legality check
  does, never on SQL or specification equality.

**The two samples are disjoint.** VisEval was built from nvBench and shares its
keys, so every key VisEval uses (single or multiple) is removed from the
nvBench pool first. Both tables come from VisEval's CSV export of the Spider
databases, which carries every table the nvBench pool reads but six; those six
are dropped. To make sure the CSV export and the gold agree, every nvBench
candidate whose SQL can be replayed (no binning, no series) is run on its CSV
in SQLite and dropped if it does not reproduce the published ``vis_obj``.

**Frozen.** ``build`` draws 100 of each with a fixed seed, picks one of each
query's NL phrasings with the same generator, and writes
``external_cases.json``. It is run once; the file is committed, and a later
number is only comparable to an earlier one if this file is unchanged.
``meta.sha256`` in every result says which version it was.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASES_FILE = HERE / "external_cases.json"
CACHE = HERE / ".cache" / "external"

SEED = 20261006
PER_SOURCE = 100

# Pinned upstream data. The tables both samples read come from this zip only.
VISEVAL_COMMIT = "55162fac5765d8873180d962cce7e20e75b2c092"
VISEVAL_ZIP_URL = f"https://raw.githubusercontent.com/microsoft/VisEval/{VISEVAL_COMMIT}/viseval_dataset.zip"
VISEVAL_ZIP_SHA256 = "4d9490493880b37b9b7345b13403bd9d52edfd66577c5f696e1094b35a88b92a"
NVBENCH_COMMIT = "544fbc218a2c2fd5dac7591371e3e01ccd6afb93"
NVBENCH_JSON_URL = f"https://raw.githubusercontent.com/TsinghuaDatabaseGroup/nvBench/{NVBENCH_COMMIT}/NVBench.json"
NVBENCH_JSON_SHA256 = "8c85a9454fe1343074ba915bcbb379f170ab62bb1279b6a7aed23255e6eefbcf"

# Acceptable chart types for each benchmark chart. A stacked or grouped chart
# is a bar, line or scatter with a series field here, so the family is checked
# on the type and the series on the data.
FAMILIES: dict[str, frozenset[str]] = {
    "Bar": frozenset({"bar", "grouped_bar", "histogram"}),
    "Stacked Bar": frozenset({"bar", "grouped_bar"}),
    "Pie": frozenset({"pie", "donut"}),
    "Line": frozenset({"line", "area"}),
    "Grouping Line": frozenset({"line", "area"}),
    "Scatter": frozenset({"scatter"}),
    "Grouping Scatter": frozenset({"scatter"}),
}

_FROM = re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


# --------------------------------------------------------------------------
# value normalisation, shared by the build-time gold check and the scorer
# --------------------------------------------------------------------------

_WEEKDAYS = {"mon": "mon", "monday": "mon", "tue": "tue", "tues": "tue", "tuesday": "tue",
             "wed": "wed", "wednesday": "wed", "thu": "thu", "thur": "thu", "thurs": "thu",
             "thursday": "thu", "fri": "fri", "friday": "fri", "sat": "sat", "saturday": "sat",
             "sun": "sun", "sunday": "sun"}
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_NAMES = {m: m for m in _MONTHS} | {
    "january": "jan", "february": "feb", "march": "mar", "april": "apr", "june": "jun",
    "july": "jul", "august": "aug", "september": "sep", "sept": "sep", "october": "oct",
    "november": "nov", "december": "dec"}
# Matched against lower-cased text, so the separator is "t" and the zone "z".
_ISO = re.compile(
    r"^(\d{4})-(\d{2})(?:-(\d{2}))?(?:[t ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?(?:z|[+-]\d{2}:?\d{2})?$"
)


_DASHES = re.compile("[‐‑‒–—―−]")


def binning_unit(binning: str) -> str | None:
    """'BIN x BY YEAR' -> 'year'. None when the query is not binned."""
    m = re.search(r"\bBY\s+(YEAR|MONTH|WEEKDAY|DAY|TIME|INTERVAL)\b", binning or "", re.IGNORECASE)
    return m.group(1).lower() if m else None


def norm_x(value: Any, unit: str | None = None) -> str:
    """One canonical spelling for an x value or a series label.

    Numbers compare by value (3 == 3.0 == "3"), text without case or padding,
    and timestamps at the grain the gold was binned to — so a year bin drawn as
    "2018-01-01" matches the gold "2018", and "Thursday" matches "Thur".
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        f = float(value)
        if unit == "year" and f.is_integer():
            return str(int(f))
        # A weekday or month bin drawn from a date part is a number in the
        # chart's data (DuckDB: dow 0 = Sunday, month 1-12) and a name in the
        # gold chart; both name the same bin.
        if unit == "weekday" and f.is_integer() and 0 <= f <= 6:
            return ["sun", "mon", "tue", "wed", "thu", "fri", "sat"][int(f)]
        if unit == "month" and f.is_integer() and 1 <= f <= 12:
            return _MONTHS[int(f) - 1]
        return str(int(f)) if f.is_integer() else f"{round(f, 4):g}"
    # The gold charts and VisEval's CSV export spell the same value differently
    # ("9-1" against "9–1"), so text is compared after Unicode normalisation with
    # every dash folded to a hyphen.
    s = _DASHES.sub("-", unicodedata.normalize("NFKC", str(value))).strip().lower()
    m = _ISO.match(s)
    if m:
        year, month, day = m.group(1), m.group(2), m.group(3)
        if unit == "year":
            return year
        if unit == "month":
            return _MONTHS[int(month) - 1]
        if unit == "weekday" and day:
            import datetime as _dt
            return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][
                _dt.date(int(year), int(month), int(day)).weekday()]
        time = m.group(4) and f"{m.group(4)}:{m.group(5)}:{m.group(6) or '00'}"
        date = f"{year}-{month}-{day}" if day else f"{year}-{month}"
        return date if not time or time == "00:00:00" else f"{date} {time}"
    if unit == "weekday" and s in _WEEKDAYS:
        return _WEEKDAYS[s]
    if unit == "month" and s in _MONTH_NAMES:
        return _MONTH_NAMES[s]
    try:
        return norm_x(float(s), unit)
    except ValueError:
        return s


def norm_y(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def gold_points(vis_obj: dict[str, Any], unit: str | None) -> list[tuple[str, str | None, float | None]]:
    """The published chart as (x, series, y) triples. A chart with no series
    has series None; one x list shared by several series is expanded."""
    xs, ys, series = vis_obj["x_data"], vis_obj["y_data"], vis_obj.get("classify") or []
    out = []
    for i, ycol in enumerate(ys):
        xcol = xs[i] if len(xs) > 1 else xs[0]
        label = norm_x(series[i]) if series else None
        out.extend((norm_x(x, unit), label, norm_y(y)) for x, y in zip(xcol, ycol))
    return out


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, sha256: str) -> Path:
    if not dest.exists() or _sha256(dest) != sha256:
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[external] downloading {url}", flush=True)
        urllib.request.urlretrieve(url, dest)
    got = _sha256(dest)
    if got != sha256:
        raise SystemExit(f"{dest.name}: sha256 {got} != pinned {sha256}")
    return dest


def databases_dir() -> Path:
    """VisEval's CSV export of the Spider databases, fetched once and cached."""
    root = CACHE / f"viseval-{VISEVAL_COMMIT[:7]}"
    db = root / "visEval_dataset" / "databases"
    if not db.is_dir():
        z = _download(VISEVAL_ZIP_URL, CACHE / "viseval_dataset.zip", VISEVAL_ZIP_SHA256)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(root)
    return db


def table_csv(db_id: str, table: str, db_root: Path | None = None) -> Path | None:
    folder = (db_root or databases_dir()) / db_id
    if not folder.is_dir():
        return None
    for f in folder.iterdir():
        if f.suffix.lower() == ".csv" and f.stem.lower() == table.lower():
            return f
    return None


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def cases_sha256() -> str:
    """Hash of the frozen cases with line endings normalised, so a Windows
    (CRLF) checkout and a Linux one report the same version."""
    return hashlib.sha256(CASES_FILE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# --------------------------------------------------------------------------
# build (run once)
# --------------------------------------------------------------------------

def _phrasings(entry: dict[str, Any]) -> list[str]:
    """The entry's NL questions, without the blank ones nvBench ships for ten."""
    return [q.strip() for q in entry["nl_queries"] if q.strip()]


def _base(key: str) -> str:
    """'372@x_name@ASC' -> '372': the query a sort variant was derived from."""
    return key.split("@", 1)[0]


def single_table(sql: str) -> str | None:
    """The one table a query reads, or None if it reads more than one."""
    s = f" {sql.upper()} "
    if " JOIN " in s or s.count("SELECT") != 1 or any(k in s for k in (" UNION ", " INTERSECT ", " EXCEPT ")):
        return None
    tables = _FROM.findall(sql)
    if len(tables) != 1:
        return None
    after = sql[sql.upper().index("FROM") + 4:].strip()
    if re.match(r"[A-Za-z_][A-Za-z0-9_]*\s*(AS\s+\w+\s*)?,", after, re.IGNORECASE):  # FROM a, b
        return None
    return tables[0]


def _replays(entry: dict[str, Any], csv_path: Path, table: str) -> bool:
    """Does the gold SQL, run on our CSV, give the published chart data?"""
    import pandas as pd

    con = sqlite3.connect(":memory:")
    try:
        pd.read_csv(csv_path, encoding_errors="replace").to_sql(table, con, index=False)
        rows = con.execute(entry["vis_query"]["data_part"]["sql_part"]).fetchall()
    except Exception:
        return False
    finally:
        con.close()
    if not rows or len(rows[0]) != 2:
        return False
    got = sorted((norm_x(x), norm_y(y)) for x, y in rows)
    want = sorted((x, y) for x, _, y in gold_points(entry["vis_obj"], None))
    return got == want


def _case(source: str, key: str, entry: dict[str, Any], table: str, rng: random.Random) -> dict[str, Any]:
    dp = entry["vis_query"]["data_part"]
    return {
        "id": f"{'NV' if source == 'nvbench' else 'VE'}-{key}",
        "source": source,
        "key": key,
        "db_id": entry["db_id"],
        "table": table,
        "prompt": rng.choice(_phrasings(entry)),
        "chart": entry["chart"],
        "hardness": entry["hardness"],
        "sql": dp["sql_part"],
        "binning": dp["binning"],
        "vis_obj": {k: entry["vis_obj"][k] for k in ("x_name", "y_name", "x_data", "y_data", "classify")},
    }


def build(nvbench_json: Path) -> dict[str, Any]:
    if _sha256(nvbench_json) != NVBENCH_JSON_SHA256:
        raise SystemExit(f"{nvbench_json} is not the pinned NVBench.json ({NVBENCH_JSON_URL})")
    db_root = databases_dir()
    vis_root = db_root.parent
    nv = json.loads(nvbench_json.read_text(encoding="utf-8"))
    ve = json.loads((vis_root / "visEval_single.json").read_text(encoding="utf-8"))
    vm = json.loads((vis_root / "visEval_multiple.json").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    counts: dict[str, Any] = {}

    ve_pool = {}
    for k, e in ve.items():
        t = single_table(e["vis_query"]["data_part"]["sql_part"])
        if t and table_csv(e["db_id"], t, db_root) and _phrasings(e):
            ve_pool[k] = t
    counts["viseval"] = {"published": len(ve), "single_table_with_csv": len(ve_pool)}

    nv_pool, dropped_replay = {}, 0
    used_by_viseval = {_base(k) for k in (*ve, *vm)}
    for k, e in nv.items():
        if _base(k) in used_by_viseval:
            continue
        t = single_table(e["vis_query"]["data_part"]["sql_part"])
        path = t and table_csv(e["db_id"], t, db_root)
        if not path or not _phrasings(e):
            continue
        replayable = not e["vis_query"]["data_part"]["binning"] and not e["vis_obj"].get("classify")
        if replayable and not _replays(e, path, t):
            dropped_replay += 1
            continue
        nv_pool[k] = t
    counts["nvbench"] = {"published": len(nv),
                         "not_in_viseval": sum(1 for k in nv if _base(k) not in used_by_viseval),
                         "single_table_with_csv_and_replaying": len(nv_pool),
                         "dropped_gold_not_reproduced": dropped_replay}

    # Sampled by base query, then one variant of it: "372" and "372@x_name@ASC"
    # are the same question with a sort added, and drawing both would count one
    # query twice.
    cases = []
    for source, pool, data in (("nvbench", nv_pool, nv), ("viseval", ve_pool, ve)):
        by_base: dict[str, list[str]] = {}
        for key in pool:
            by_base.setdefault(_base(key), []).append(key)
        for base in rng.sample(sorted(by_base, key=int), PER_SOURCE):
            key = rng.choice(sorted(by_base[base]))
            cases.append(_case(source, key, data[key], pool[key], rng))
    return {
        "meta": {"seed": SEED, "per_source": PER_SOURCE,
                 "viseval": {"commit": VISEVAL_COMMIT, "zip_sha256": VISEVAL_ZIP_SHA256},
                 "nvbench": {"commit": NVBENCH_COMMIT, "json_sha256": NVBENCH_JSON_SHA256},
                 "pools": counts},
        "cases": cases,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="draw the frozen sample (run once)")
    b.add_argument("--nvbench", type=Path, required=True, help=f"NVBench.json from {NVBENCH_JSON_URL}")
    b.add_argument("--force", action="store_true", help="overwrite an existing external_cases.json")
    sub.add_parser("check", help="every frozen case has its table")
    args = ap.parse_args()

    if args.cmd == "build":
        if CASES_FILE.exists() and not args.force:
            raise SystemExit(f"{CASES_FILE.name} exists and is frozen; --force only if you mean to replace it")
        suite = build(args.nvbench)
        CASES_FILE.write_text(json.dumps(suite, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(suite["meta"]["pools"], indent=2))
        print(f"wrote {len(suite['cases'])} cases to {CASES_FILE}")
    else:
        missing = [c["id"] for c in load_cases() if not table_csv(c["db_id"], c["table"])]
        print(f"{len(load_cases())} cases, sha256 {cases_sha256()[:12]}, missing tables: {missing or 'none'}")
        sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
