"""Does the composed answer's arithmetic actually come from the results?

`compose` is the only one of the four `PlannerLLM` jobs whose output nothing
downstream checks (`Docs/16 §1.1`). `classify`, `generate_plan` and `style_patch`
all emit JSON that is validated before it can affect anyone; `compose` emits free
prose, and that prose is the part the user actually reads. Its system prompt says
"ground every number strictly in the provided result tables — never estimate,
extrapolate, or invent values", which is an instruction, not a guarantee. The
same reliance on instruction-following is what let a forecast request be answered
with a historical trend.

This module closes that asymmetry the way the rest of the system closes them:
deterministically, with no second LLM.

**A false positive is the expensive error here**, because it discards a correct
answer. The first version of this module had three, and they were only found by
running it over 32 real answers — it flagged a survival rate printed to six
decimals, a year taken from a truncated timestamp, and a figure at the end of a
sentence whose full stop it had swallowed. Each of those is now a named rule
below, and each has a regression test. The design principle that came out of it:

    Round the *data* to the precision the prose used.
    Never round the prose to a precision the data happens to have.

Anything still unmatched is a number with no visible source, which is the only
thing worth acting on.
"""

from __future__ import annotations

import re
from typing import Any

# ISO-ish timestamps are pulled out whole before number extraction, or
# "2012-01-01" arrives as three separate claims (2012, 1, 1) and the year gets
# checked against a fare.
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")

# 1,234.56 | 1234 | .5 — a decimal point only counts when digits follow it, or
# the full stop ending a sentence is swallowed and "2014." is read as a
# different number from the 2014 in the data.
_NUMBER = re.compile(r"-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)")

# Markdown table rules contribute dashes and colons, never claims.
_TABLE_RULE = re.compile(r"^[\s|:-]+$", re.MULTILINE)

# The scale changes a truthful sentence may apply to a stored value: none, a
# rate stated as a percentage, or a percentage stated as a rate.
_SCALES = (1.0, 100.0, 0.01)

# Above this many result cells the check is switched off, and it fails *open* —
# a large table is reported as grounded rather than as suspect.
#
# Both reasons are empirical. A 100,000-row result costs 5.7 s to build a
# grounded set for, which is not a price worth paying on every answer. More
# decisively, the check stops working long before that: by ~5,000 rows the set
# of admissible values is so dense that invented figures match it by
# coincidence, so it would return "grounded" anyway — while charging for the
# privilege. A check with no power that also costs seconds is worse than no
# check, and pretending otherwise would make this module theatre.
#
# The bound costs little in practice. Composers quote figures from *aggregate*
# results — a handful of rows — and that is exactly the regime where the set
# stays sparse and the check bites. `is_checkable` lets callers report coverage
# rather than assume it.
MAX_GROUNDABLE_CELLS = 2_000

# Decimal places beyond which two numbers are the same number.
_EPS = 1e-9


def _as_float(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def _places(token: str) -> int:
    """Decimal places the prose actually wrote, which sets the comparison."""
    _, _, frac = token.partition(".")
    return len(frac)


def _years(text: str) -> set[float]:
    """Years named by any timestamp in `text`.

    A trend grouped by `year_start` stores `2012-01-01T00:00:00` and the
    composer writes "2012". That is the same fact, and the first version of this
    module called it fabrication.
    """
    return {float(stamp[:4]) for stamp in _DATE.findall(text)}


def _collect(text: str) -> tuple[set[float], set[str]]:
    """Numbers and whole date stamps asserted by, or stored in, a piece of text."""
    numbers = {v for t in _NUMBER.findall(text or "") if (v := _as_float(t)) is not None}
    return numbers, set(_DATE.findall(text or ""))


def result_cells(results: list[dict[str, Any]]) -> int:
    """Total cells across every result table — what the budget is spent on."""
    total = 0
    for r in results:
        table = (r.get("result") or {}).get("result_table") or []
        for row in table:
            total += len(row) if isinstance(row, dict) else 1
    return total


def is_checkable(results: list[dict[str, Any]]) -> bool:
    """Is this result set small enough for grounding to mean anything?

    See ``MAX_GROUNDABLE_CELLS``. Callers should report coverage with this
    rather than assuming every answer was verified.
    """
    return result_cells(results) <= MAX_GROUNDABLE_CELLS


def grounded_values(results: list[dict[str, Any]]) -> tuple[set[float], set[str], int]:
    """Everything the answer may draw on: (raw values, date stamps, count ceiling).

    Values are kept **raw**. Rounding happens at comparison time against the
    precision the prose chose, because no fixed set of roundings can anticipate
    a composer printing a rate to six decimal places.

    `ceiling` is the largest count anything on screen could legitimately be, so
    ordinals and "N categories" phrasing do not read as fabrication.
    """
    numbers: set[float] = set()
    dates: set[str] = set()
    ceiling = len(results)

    for r in results:
        result = r.get("result") or {}
        table = result.get("result_table") or []
        ceiling = max(ceiling, len(table))

        for row in table:
            if not isinstance(row, dict):
                continue
            for value in row.values():
                if isinstance(value, bool) or value is None:
                    continue
                if isinstance(value, (int, float)):
                    numbers.add(float(value))
                    continue
                text = str(value)
                dates.update(_DATE.findall(text))
                numbers |= _years(text)
                # A category label that is itself a number ("2015", "3") is as
                # much a grounded value as a measure is.
                if (parsed := _as_float(text)) is not None:
                    numbers.add(parsed)

        # Row accounting: the counts a truthful summary quotes about scope.
        for key in ("row_count", "input_rows", "output_rows"):
            if isinstance(value := result.get(key), int):
                numbers.add(float(value))
                ceiling = max(ceiling, value)
        for step in result.get("preprocessing") or []:
            for key in ("rows_affected", "rows_still_null", "rows_before"):
                if isinstance(value := step.get(key), int):
                    numbers.add(float(value))

        # Notices are prose *we* wrote and their figures came from the same
        # counts, so anything they state is grounded by construction.
        for notice in r.get("notices") or []:
            if note := notice.get("note"):
                found, stamps = _collect(note)
                numbers |= found | _years(note)
                dates |= stamps

        # The user's own constraints. "passengers who paid more than 100" puts
        # 100 in the answer without it ever appearing in a result cell, and a
        # date-range filter is how "in 2014" usually reaches the plan.
        plan = r.get("plan") or {}
        for f in plan.get("filters") or []:
            raw = f.get("value")
            for item in raw if isinstance(raw, list) else [raw]:
                if isinstance(item, bool) or item is None:
                    continue
                if isinstance(item, (int, float)):
                    numbers.add(float(item))
                    continue
                text = str(item)
                dates.update(_DATE.findall(text))
                numbers |= _years(text)
                if (parsed := _as_float(text)) is not None:
                    numbers.add(parsed)
        if isinstance(plan.get("limit"), int):
            numbers.add(float(plan["limit"]))

    return numbers, dates, ceiling


def _supported(claim: float, places: int, values: set[float]) -> bool:
    """Could any stored value be written as `claim` at `places` decimal places?

    The rounding runs on the data, not on the claim — a value of
    0.9680851063829787 supports "0.97", "0.968" and "0.968085" alike, and no
    fixed expansion of the value could have covered all three.
    """
    for scale in _SCALES:
        for value in values:
            scaled = value * scale
            if abs(scaled - claim) < _EPS or round(scaled, places) == claim:
                return True
    return False


def ungrounded_numbers(answer: str, results: list[dict[str, Any]]) -> list[str]:
    """Numbers the answer asserts that nothing in `results` supports.

    Returns the offending tokens as written, which is what makes a rejection
    explainable. An empty list means every figure in the prose traces to the
    analysis — **or** that the result set was too large to check, which
    `is_checkable` distinguishes.
    """
    if not answer or not is_checkable(results):
        return []

    values, dates, ceiling = grounded_values(results)
    year_set = {float(stamp[:4]) for stamp in dates}
    text = _TABLE_RULE.sub(" ", answer)

    offenders: list[str] = []

    # Dates first and whole, then removed so their parts are not re-read as
    # standalone claims. Compared on the calendar day: a stored timestamp and a
    # written date are the same assertion.
    stored_days = {d.split("T")[0].split(" ")[0] for d in dates}
    for stamp in _DATE.findall(text):
        if stamp.split("T")[0].split(" ")[0] not in stored_days:
            offenders.append(stamp)
    text = _DATE.sub(" ", text)

    for token in _NUMBER.findall(text):
        claim = _as_float(token)
        if claim is None:
            continue
        if _supported(claim, _places(token), values):
            continue
        # A year the data covers, written bare.
        if claim in year_set:
            continue
        # A whole number no larger than what is on screen can only be a count,
        # an ordinal, or a "top N" — never a measurement worth challenging.
        if claim == int(claim) and 0 <= claim <= max(ceiling, 12):
            continue
        offenders.append(token)

    return offenders


def is_grounded(answer: str, results: list[dict[str, Any]]) -> bool:
    return not ungrounded_numbers(answer, results)
