"""Deterministic data-quality scan and cleaning recommendations.

The point of this module is that a user who has never heard of median imputation
should still get a correct chart. It is deliberately **not** an LLM: what is wrong
with a column, and what the sensible repair is, are computable from the data, and
computing them means the recommendation is reproducible and can be tested against
exact counts rather than reviewed by eye.

Two outputs, split by who is allowed to decide:

* **auto_ops** — SAFE repairs, applied without asking and reported in provenance.
  Nothing here changes what a value means (see ``Risk`` in schema/allowlists.py).
* **proposals** — everything that alters values or row membership. These are
  questions, phrased in plain language with exact counts, carrying a recommended
  answer so the novice case is one click rather than a statistics lesson.

Everything is **scoped to the columns the current analysis needs**. A filthy
`comments` column is not a reason to interrupt a question about revenue, and
scanning the whole frame every time would make the interruption rate a function
of the dataset rather than of the request.
"""

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from autoviz.schema.allowlists import (
    MAX_PREPROCESSING_STEPS,
    ROW_DROP_CONFIRM_FRACTION,
    ROW_DROP_NOTICE_FRACTION,
)
from autoviz.services.registry import DatasetRecord
from autoviz.services.safety import neutralize_text

# A categorical column with more distinct values than this makes an unreadable
# chart, so it is worth mentioning. Not a defect — just not plottable as-is.
HIGH_CARDINALITY = 25

# Codes conventionally used to mean "not recorded". Flagged only when the value
# also sits far outside the column's real distribution (see _numeric_sentinels),
# because 999 is a placeholder in a column of ages and an ordinary reading in a
# column of prices — the number alone cannot tell you which.
SENTINEL_NUMBERS = (-1, -9, -99, -999, -9999, 999, 9999, 99999, -111111)

# Text standing in for absence. The obvious ones ("NA", "null", "none") are
# already nulled at read time by services/ingest.py; these are the ones that
# survive it, and they survive precisely because no CSV reader treats them as
# missing.
SENTINEL_TEXT = frozenset(
    {"unknown", "missing", "not available", "not applicable", "tbd", "n.a.",
     "-", "--", "---", "?", "??", "none given", "no data", "unspecified"}
)

# A sentinel has to appear at least this often to be worth raising. One stray -1
# is more likely a typo than a coding convention, and a question about a single
# row costs more attention than it saves.
MIN_SENTINEL_ROWS = 2

# How far outside the interquartile range a numeric sentinel must sit. 3x is the
# conventional "far out" fence — wide enough that a legitimate extreme reading is
# not mistaken for a code.
SENTINEL_IQR_MULTIPLE = 3.0

# Domain shapes worth validating. Deliberately only the two that are decidable
# from the value alone: an address either has the shape of an email or it does
# not. Anything needing a reference list (countries, currencies) is a judgement
# about the world, not about the string, and belongs to a user-supplied list.
DOMAIN_PATTERNS = {
    "email address": re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),
    "web address": re.compile(r"^(https?://|www\.)\S+$"),
}

# What share of a column must match a domain before the rest count as errors
# rather than the column simply not being of that kind.
DOMAIN_MAJORITY = 0.8

# How many categories to keep when offering to bucket the long tail. Chosen to sit
# well under HIGH_CARDINALITY so accepting the offer actually solves the problem,
# and to stay inside the legible-series ceilings in schema/allowlists.py.
DEFAULT_TOP_CATEGORIES = 10


@dataclass(frozen=True)
class QualityIssue:
    """One problem found in one column."""

    kind: str
    column: str | None
    # Rows the issue affects, and that count as a share of the frame.
    affected: int
    fraction: float
    detail: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "column": self.column,
            "affected": self.affected,
            "fraction": round(self.fraction, 4),
            **({"detail": self.detail} if self.detail else {}),
        }


@dataclass(frozen=True)
class CleaningOption:
    """One answer to a proposal, in the user's language.

    ``label`` says what happens, ``detail`` says what it costs in this dataset's
    actual numbers, and ``technique`` is the jargon — kept separate so it can go
    behind a "how this works" disclosure instead of leading.
    """

    label: str
    detail: str
    technique: str
    # The preprocessing op this answer applies; None means "do nothing".
    op: dict[str, Any] | None
    recommended: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "detail": self.detail,
            "technique": self.technique,
            "recommended": self.recommended,
        }


@dataclass(frozen=True)
class CleaningProposal:
    """A question the user must answer before a value-changing op is applied."""

    slot: str
    question: str
    options: list[CleaningOption]
    issue: QualityIssue

    def to_wire(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "question": self.question,
            "options": [o.to_wire() for o in self.options],
            "issue": self.issue.to_wire(),
        }


def _pretty(column: str) -> str:
    return column.replace("_", " ").strip()


def _numeric_sentinels(series: "pd.Series") -> list[Any]:
    """Placeholder codes in a numeric column, or [] if none are convincing.

    Two conditions, and both are needed. The value must be a **known code**, and
    it must sit **far outside the column's own distribution**. Either test alone
    is wrong in a way that matters: 999 is a placeholder among ages and a real
    reading among prices, so the code list cannot decide on its own; and plenty
    of genuine outliers are not codes, so distance cannot either.
    """
    clean = series.dropna()
    if len(clean) < 4:  # too few rows for a quartile to mean anything
        return []
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        # A column with no spread has no "far outside". Anything that is not the
        # single repeated value would be, which flags ordinary data.
        return []
    low = q1 - SENTINEL_IQR_MULTIPLE * iqr
    high = q3 + SENTINEL_IQR_MULTIPLE * iqr
    counts = clean.value_counts()
    found = []
    for candidate in SENTINEL_NUMBERS:
        n = int(counts.get(candidate, 0))
        if n >= MIN_SENTINEL_ROWS and (candidate < low or candidate > high):
            found.append(candidate)
    return found


def _text_sentinels(values: "pd.Series") -> list[str]:
    """Placeholder words in a text column, matched case- and space-insensitively.

    No distribution test here: unlike a number, "unknown" cannot also be a real
    observation, so its presence is sufficient on its own.
    """
    folded = values.str.strip().str.casefold()
    counts = folded.value_counts()
    found = []
    for token, n in counts.items():
        if token in SENTINEL_TEXT and int(n) >= MIN_SENTINEL_ROWS:
            # Report the spelling the file actually uses, not the folded form —
            # it is what the user will search for and what the op must match.
            original = values[folded == token].iloc[0]
            found.append(str(original).strip())
    return found


def _domain_failures(values: "pd.Series") -> tuple[str, int] | None:
    """(domain name, failing count) when a column is mostly one shape but not all.

    This is Tableau's data role, minus the fixer. A column that is 96% email
    addresses is an email column with 4% broken rows; a column that is 30%
    email addresses is a notes field, and flagging the other 70% would be noise.
    """
    total = len(values)
    if total < 5:
        return None
    for name, pattern in DOMAIN_PATTERNS.items():
        matches = int(values.str.strip().str.match(pattern).sum())
        if matches == total:
            return None  # a clean column of that kind: nothing to say
        if matches / total >= DOMAIN_MAJORITY:
            return name, total - matches
    return None


# --- scan ---------------------------------------------------------------------


def scan(record: DatasetRecord, columns: set[str] | None = None) -> list[QualityIssue]:
    """Find quality issues in `columns` (default: every column).

    Reads the frame directly rather than the cached profile for the string-level
    checks, because whitespace and case variants are not in the profile — but
    reuses the profile's null and duplicate counts, which are already computed at
    registration and would otherwise be a second full pass.

    Memoized per column scope on the record. The agent scans once per pass and
    re-enters the node for every cleaning question it asks, so the same work was
    being repeated several times a turn — a third of a second each on a 200k-row
    frame. Sound because the frame is immutable; see ``DatasetRecord.scan_cache``.
    """
    key = None if columns is None else frozenset(columns)
    cached = record.scan_cache.get(key)
    if cached is not None:
        return list(cached)
    found = _scan_uncached(record, columns)
    record.scan_cache[key] = found
    # Copied out so a caller that mutates the list cannot corrupt the next
    # caller's findings.
    return list(found)


def _scan_uncached(
    record: DatasetRecord, columns: set[str] | None = None
) -> list[QualityIssue]:
    df = record.df
    total = len(df)
    if total == 0:
        return []
    targets = [c for c in df.columns if columns is None or c in columns]
    profile = record.profile or {}
    null_counts: dict[str, int] = profile.get("null_counts", {})
    issues: list[QualityIssue] = []

    for col in targets:
        logical = record.schema.get(col)
        series = df[col]

        nulls = int(null_counts.get(col, series.isna().sum()))
        if nulls:
            issues.append(
                QualityIssue(
                    kind="missing_values",
                    column=col,
                    affected=nulls,
                    fraction=nulls / total,
                    detail={"column_type": logical},
                )
            )

        if logical == "number":
            # Codes standing in for "not recorded". Worth finding before anything
            # else: a null is skipped by every aggregate and disclosed when it
            # matters, while a 999 meaning "unknown" is averaged in and the answer
            # is wrong with nothing to show for it.
            sentinels = _numeric_sentinels(series)
            if sentinels:
                affected = int(series.isin(sentinels).sum())
                issues.append(
                    QualityIssue(
                        kind="suspect_values", column=col, affected=affected,
                        fraction=affected / total,
                        detail={"values": sentinels, "column_type": "number"},
                    )
                )

        if logical != "string":
            continue

        text = series.dropna().astype(str)
        if text.empty:
            continue

        placeholders = _text_sentinels(text)
        if placeholders:
            affected = int(text.str.strip().str.casefold().isin(
                {p.casefold() for p in placeholders}
            ).sum())
            issues.append(
                QualityIssue(
                    kind="suspect_values", column=col, affected=affected,
                    fraction=affected / total,
                    detail={"values": placeholders, "column_type": "string"},
                )
            )

        domain = _domain_failures(text)
        if domain is not None:
            role, failing = domain
            issues.append(
                QualityIssue(
                    kind="invalid_domain_values", column=col, affected=failing,
                    fraction=failing / total, detail={"domain": role},
                )
            )

        padded = int((text != text.str.strip()).sum())
        if padded:
            issues.append(
                QualityIssue(
                    kind="untrimmed_whitespace", column=col, affected=padded,
                    fraction=padded / total,
                )
            )

        stripped = text.str.strip()
        blanks = int((stripped == "").sum())
        if blanks:
            issues.append(
                QualityIssue(
                    kind="blank_as_text", column=col, affected=blanks, fraction=blanks / total,
                )
            )

        # Case variants: only a finding when folding actually merges groups. Two
        # spellings of one category are two bars on a chart, which is the concrete
        # harm — a column that is merely mixed-case but unambiguous is left alone.
        #
        # The two findings below are independent, not alternatives. A column can
        # easily have both, and when this was an `elif` the case-variant finding
        # masked the other: normalize_case then quietly repaired the spellings, no
        # grouping proposal was ever offered, and the user got an unreadable chart
        # of 300 categories with nothing having gone visibly wrong.
        non_blank = stripped[stripped != ""]
        if not non_blank.empty:
            distinct = non_blank.nunique()
            folded_values = non_blank.str.lower()
            folded = folded_values.nunique()
            if folded < distinct:
                affected = int((non_blank != folded_values).sum())
                issues.append(
                    QualityIssue(
                        kind="case_variants", column=col, affected=affected,
                        fraction=affected / total,
                        detail={"distinct": int(distinct), "after_folding": int(folded)},
                    )
                )
            # Judged on the *folded* count, because normalize_case is a SAFE repair
            # that runs first: the number of categories the chart actually has to
            # draw is the count after merging, not before.
            if folded > HIGH_CARDINALITY:
                issues.append(
                    QualityIssue(
                        kind="high_cardinality", column=col, affected=int(folded),
                        fraction=0.0, detail={"distinct": int(folded)},
                    )
                )

    # Whole-row issues are properties of the *row*, so they are only findings when
    # the scan actually covers the whole row. Reporting them from a scoped scan
    # would put "9 duplicate rows" in front of a user who asked about one column,
    # where the duplication may be entirely explained by the columns not examined.
    if columns is None or set(df.columns) <= set(targets):
        empty_rows = int(df.isna().all(axis=1).sum())
        if empty_rows:
            issues.append(
                QualityIssue(
                    kind="empty_rows", column=None, affected=empty_rows,
                    fraction=empty_rows / total,
                )
            )
        duplicates = int((record.profile or {}).get("duplicate_count", 0))
        if duplicates:
            issues.append(
                QualityIssue(
                    kind="duplicate_rows", column=None, affected=duplicates,
                    fraction=duplicates / total,
                )
            )
    return issues


# --- recommend ----------------------------------------------------------------


def _missing_value_proposal(issue: QualityIssue, total: int) -> CleaningProposal | None:
    """Offer fill / exclude / keep for a column with missing values.

    The recommendation is not a statistical judgement so much as a
    least-surprise one: with few rows missing, dropping them barely moves the
    answer and invents nothing, so that leads. With many rows missing, dropping
    them would throw away most of the dataset, so filling leads instead — and
    either way the third option is always "leave it alone".
    """
    col = issue.column
    assert col is not None
    kept = total - issue.affected
    col_type = issue.detail.get("column_type")
    pct = round(issue.fraction * 100, 1)

    fill_op: dict[str, Any] | None = None
    fill_label = ""
    fill_detail = ""
    technique = ""
    if col_type == "number":
        fill_op = {"op": "fill_nulls", "column": col, "strategy": "median"}
        fill_label = f"Use the typical {_pretty(col)} value"
        fill_detail = (
            f"Fills {issue.affected} missing value(s) with the middle {_pretty(col)}."
        )
        technique = f"median imputation on '{col}'"
    elif col_type in ("string", "boolean"):
        fill_op = {"op": "fill_nulls", "column": col, "strategy": "mode"}
        fill_label = f"Use the most common {_pretty(col)}"
        fill_detail = f"Fills {issue.affected} missing value(s) with the commonest value."
        technique = f"mode imputation on '{col}'"

    # Filling is the lead only when excluding would cost most of the data.
    prefer_fill = fill_op is not None and issue.fraction > ROW_DROP_CONFIRM_FRACTION
    options = [
        CleaningOption(
            label="Exclude those rows",
            detail=f"Calculates the result using {kept} of {total} rows.",
            technique=f"drop_nulls on '{col}'",
            op={"op": "drop_nulls", "columns": [col], "how": "any"},
            recommended=not prefer_fill,
        ),
        CleaningOption(
            label="Keep them as they are",
            detail="Some groups may have incomplete results.",
            technique="no preprocessing",
            op=None,
        ),
    ]
    if fill_op is not None:
        options.insert(
            0,
            CleaningOption(
                label=fill_label, detail=fill_detail, technique=technique,
                op=fill_op, recommended=prefer_fill,
            ),
        )
    return CleaningProposal(
        slot=f"missing:{col}",
        question=(
            f"{issue.affected} of {total} rows ({pct}%) have no "
            f"{_pretty(col)}. What should AutoViz do?"
        ),
        options=options,
        issue=issue,
    )


def _high_cardinality_proposal(
    issue: QualityIssue, measure: tuple[str, str] | None = None
) -> CleaningProposal:
    """Offer to bucket the long tail of a column with too many categories.

    Value-changing, so it is asked rather than applied: folding categories into
    "Other" is usually what makes the chart readable, but it also erases whichever
    small category the user might have been looking for.

    ``measure`` is the plan's ``(column, fn)`` when it aggregates, and it decides
    which categories survive. Ranking by row frequency instead is a trap whenever
    volume and value disagree: on a revenue chart it can bury the top earner in
    "Other" while keeping a rep who ranks near-last, because who logged the most
    orders is a different question from who brought in the most money.
    """
    col = issue.column
    assert col is not None
    distinct = int(issue.detail.get("distinct", issue.affected))
    op: dict[str, Any] = {
        "op": "group_rare_categories",
        "column": col,
        "top_n": DEFAULT_TOP_CATEGORIES,
        "other_label": "Other",
    }
    if measure is not None:
        m_col, m_fn = measure
        op["rank_by"] = {"column": m_col, "fn": m_fn}
        kept = f"the {DEFAULT_TOP_CATEGORIES} highest by {m_fn} of {_pretty(m_col)}"
    else:
        kept = f"the {DEFAULT_TOP_CATEGORIES} commonest values"
    return CleaningProposal(
        slot=f"cardinality:{col}",
        question=(
            f"{_pretty(col)} has {distinct} different values — too many to read on "
            "one chart. What should AutoViz do?"
        ),
        options=[
            CleaningOption(
                label=f"Show the top {DEFAULT_TOP_CATEGORIES} and group the rest as Other",
                detail=(
                    f"Keeps {kept}; the other "
                    f"{distinct - DEFAULT_TOP_CATEGORIES} are combined."
                ),
                technique=f"group_rare_categories(top_n={DEFAULT_TOP_CATEGORIES}) on '{col}'",
                op=op,
                recommended=True,
            ),
            CleaningOption(
                label="Show every value",
                detail=f"The chart will have {distinct} categories.",
                technique="no preprocessing",
                op=None,
            ),
        ],
        issue=issue,
    )


def _suspect_values_proposal(issue: QualityIssue, total: int) -> CleaningProposal:
    """Offer to read placeholder codes as missing.

    Recommended, unusually for a value-changing op, and the asymmetry is the
    point: if 999 really is a code, counting it as a number corrupts every
    average that touches the column, while treating a genuine 999 as missing
    costs a handful of rows from an aggregate that already discloses its
    exclusions. The cheap mistake is the one to default to.
    """
    col = issue.column
    assert col is not None
    values = list(issue.detail.get("values") or [])
    shown = ", ".join(str(v) for v in values)
    pct = round(issue.fraction * 100, 1)
    return CleaningProposal(
        slot=f"suspect:{col}",
        question=(
            f"{_pretty(col)} contains {issue.affected} row(s) ({pct}%) with the "
            f"value {shown}, which sits well outside the rest of the column. "
            "Codes like this usually mean 'not recorded'. What should AutoViz do?"
        ),
        options=[
            CleaningOption(
                label="Treat them as missing",
                detail=(
                    f"{issue.affected} row(s) stop counting toward totals and "
                    f"averages of {_pretty(col)}."
                ),
                technique=f"nullify_values({shown}) on '{col}'",
                op={"op": "nullify_values", "column": col, "values": values},
                recommended=True,
            ),
            CleaningOption(
                label="Treat them as real values",
                detail=f"{shown} will be counted in totals and averages.",
                technique="no preprocessing",
                op=None,
            ),
        ],
        issue=issue,
    )


def _duplicate_proposal(issue: QualityIssue, total: int) -> CleaningProposal:
    """Duplicates are never removed by default.

    Identical rows are frequently legitimate — two sales of the same item at the
    same price on the same day — so the recommendation is to keep them. This is the
    clearest case where "obviously dirty" and "actually wrong" come apart.
    """
    return CleaningProposal(
        slot="duplicates",
        question=(
            f"{issue.affected} of {total} rows are exact copies of another row. "
            "What should AutoViz do?"
        ),
        options=[
            CleaningOption(
                label="Keep them",
                detail="Repeated rows can be genuine repeated events.",
                technique="no preprocessing",
                op=None,
                recommended=True,
            ),
            CleaningOption(
                label="Count each row only once",
                detail=f"Calculates the result using {total - issue.affected} of {total} rows.",
                technique="drop_exact_duplicates",
                op={"op": "drop_exact_duplicates"},
            ),
        ],
        issue=issue,
    )


def recommend(
    issues: list[QualityIssue],
    total_rows: int,
    measure: tuple[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[CleaningProposal]]:
    """Split findings into repairs to apply and questions to ask.

    Returns ``(auto_ops, proposals)``. ``auto_ops`` is a preprocessing block ready
    to merge into a plan; ``proposals`` are unanswered questions, most impactful
    first, so a caller that can only ask once asks about the thing that matters.

    ``measure`` is the ``(column, fn)`` the plan aggregates by, when it has one.
    It only affects the high-cardinality proposal, which uses it to keep the
    categories that lead on the quantity being charted rather than the ones with
    the most rows.
    """
    auto_ops: list[dict[str, Any]] = []
    proposals: list[CleaningProposal] = []

    # Safe repairs, grouped so one op covers every column with the same problem —
    # a plan with eight separate trim steps would burn the step budget for nothing.
    trim = sorted({i.column for i in issues if i.kind == "untrimmed_whitespace" if i.column})
    blanks = sorted({i.column for i in issues if i.kind == "blank_as_text" if i.column})
    if trim:
        auto_ops.append({"op": "trim_whitespace", "columns": trim})
    if blanks:
        auto_ops.append({"op": "empty_string_to_null", "columns": blanks})
    for issue in issues:
        if issue.kind == "case_variants" and issue.column:
            auto_ops.append({"op": "normalize_case", "column": issue.column})
        elif issue.kind == "empty_rows":
            auto_ops.append({"op": "drop_empty_rows"})

    for issue in issues:
        if issue.kind == "missing_values":
            proposal = _missing_value_proposal(issue, total_rows)
            if proposal is not None:
                proposals.append(proposal)
        elif issue.kind == "duplicate_rows":
            proposals.append(_duplicate_proposal(issue, total_rows))
        elif issue.kind == "high_cardinality":
            proposals.append(_high_cardinality_proposal(issue, measure))
        elif issue.kind == "suspect_values":
            proposals.append(_suspect_values_proposal(issue, total_rows))

    proposals.sort(key=lambda p: p.issue.fraction, reverse=True)
    return auto_ops, proposals


# --- which findings are worth interrupting for ---------------------------------


def dimension_columns(plan: Any) -> set[str]:
    """Columns a plan uses as a *dimension* — a grouping key or a colour series.

    Takes a validated ``AnalysisPlan``; typed loosely to keep this module free of
    a schema import cycle.
    """
    dims = set(plan.group_by)
    if plan.chart is not None and plan.chart.color:
        dims.add(plan.chart.color)
    return dims


def plan_measure(plan: Any) -> tuple[str, str] | None:
    """The ``(column, fn)`` this plan charts, or None if it doesn't aggregate.

    Prefers the aggregation the chart actually plots — a plan can compute several
    and show one, and it is the shown one that a "top N" should be ranked by.
    Falls back to the first aggregation when the chart names something else (a
    derived column, say), which is still closer to the truth than row counts.
    """
    if not plan.aggregations:
        return None
    if plan.chart is not None and plan.chart.y:
        for agg in plan.aggregations:
            if agg.as_ == plan.chart.y:
                return agg.column, agg.fn
    first = plan.aggregations[0]
    return first.column, first.fn


def is_worth_asking(proposal: CleaningProposal, dimensions: set[str]) -> bool:
    """Whether a finding justifies stopping to ask, given how the plan uses it.

    Every proposal is a *legitimate* decision, but not every one changes what the
    user would see, and a question that cannot change the answer is just friction.
    Missing values behave differently by role:

    * **Dimension** (group_by / colour) — nulls become a visible "null" category
      sitting alongside the real ones. That is a wrong-looking chart, so ask.
    * **Measure** — aggregates already skip nulls, and the exclusion is stated in
      ``provenance.implicit_null_exclusions``. The default is both correct and
      disclosed; asking adds nothing.
    * **Selected, not aggregated** (a histogram, a scatter) — nulls are not
      plotted, so dropping them yields an identical chart. Nothing to decide.

    High cardinality is judged the same way and for the same reason: 200 distinct
    values make an unreadable chart when they are the *axis*, and are irrelevant
    when the column is only being filtered on.

    Duplicates are always asked about: whether repeated rows are real events is
    not something the data can answer.

    **For missing values, magnitude is judged before role.** A dimension with 2
    missing values in 891 rows (0.2%) draws a null category too small to read,
    and stopping the whole analysis to ask about it costs the user more than the
    defect does. Below ``ROW_DROP_NOTICE_FRACTION`` — the project's existing
    "small enough to mention rather than ask about" line — the finding is
    disclosed instead of asked: unasked proposals already reach the user through
    ``notices.from_unasked_proposals``, so nothing is hidden, only de-escalated.
    Found by ``bench/nl_suite.py`` T05, which this rule turns from an
    interruption into an answer.

    The floor is deliberately *not* applied to high cardinality, whose
    ``fraction`` is 0.0 by construction — it counts distinct values, not a share
    of rows, so comparing it to a row fraction would silence every one of them.
    """
    if proposal.issue.kind == "missing_values":
        if proposal.issue.fraction < ROW_DROP_NOTICE_FRACTION:
            return False
        return proposal.issue.column in dimensions
    if proposal.issue.kind == "high_cardinality":
        return proposal.issue.column in dimensions
    return True


# --- merging recommendations into a plan the planner already wrote -------------


def _op_columns(op: dict[str, Any]) -> set[str]:
    """Columns a raw op dict names, without needing the model."""
    if "columns" in op:
        return set(op["columns"])
    if "column" in op:
        return {op["column"]}
    return set()


def merge_auto_ops(
    existing: list[dict[str, Any]], auto: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fold safe repairs into a plan's preprocessing block.

    Two rules, both about not overriding a person:

    * A repair is dropped for any column the plan **already applies the same kind
      of op to**. Same *kind*, not same column — an explicit ``drop_nulls`` on
      `age` says nothing about whether `age` should be trimmed, and treating any
      mention of a column as "hands off" would silently disable most repairs.
    * Repairs are **prepended**. They fix how values are written, so they have to
      run before the ops that decide which rows survive: trimming after a
      ``drop_nulls`` on the same column would be too late to matter.

    The result is capped at ``MAX_PREPROCESSING_STEPS``, and the cap falls on
    *suggestions* only. A messy wide dataset can produce a ``normalize_case`` per
    column, and letting those push the block over the limit would fail validation
    on a plan the user wrote correctly — the system's own helpfulness breaking
    their request. The planner's ops are always kept in full.

    Returns ``(merged, dropped)``. ``dropped`` is the repairs the budget had no
    room for, and it is returned rather than discarded because a half-cleaned
    column looks cleaned: the values are still wrong and nothing about the output
    says so. The caller turns it into an advisory notice.
    """
    taken: dict[str, set[str]] = {}
    for op in existing:
        taken.setdefault(op.get("op", ""), set()).update(_op_columns(op))

    merged: list[dict[str, Any]] = []
    for op in auto:
        claimed = taken.get(op["op"], set())
        cols = _op_columns(op)
        if not cols:
            # Whole-row repair (drop_empty_rows): only skip an exact duplicate.
            if any(e.get("op") == op["op"] for e in existing):
                continue
            merged.append(op)
            continue
        remaining = sorted(cols - claimed)
        if not remaining:
            continue
        if "columns" in op:
            merged.append({**op, "columns": remaining})
        else:
            merged.append(op)

    budget = MAX_PREPROCESSING_STEPS - len(existing)
    if budget <= 0:
        return list(existing), merged
    return merged[:budget] + list(existing), merged[budget:]


def suppressed_slots(existing: list[dict[str, Any]]) -> set[str]:
    """Proposal slots the plan has already answered explicitly.

    An LLM plan that says "fill missing age with the median" is the user's
    instruction reaching the planner. Asking them again about missing `age` would
    be re-litigating a decision they already made.
    """
    slots: set[str] = set()
    for op in existing:
        if op.get("op") in ("fill_nulls", "drop_nulls"):
            for col in _op_columns(op):
                slots.add(f"missing:{col}")
        elif op.get("op") == "drop_exact_duplicates":
            slots.add("duplicates")
        elif op.get("op") == "nullify_values":
            for col in _op_columns(op):
                slots.add(f"suspect:{col}")
        elif op.get("op") == "group_rare_categories":
            # A refinement carries the prior plan's preprocessing forward, so
            # without this the cardinality slot is unsuppressable and every
            # follow-up re-asks a question the user already answered.
            for col in _op_columns(op):
                slots.add(f"cardinality:{col}")
    return slots


def bind_cleaning_answer(
    proposal: CleaningProposal, answer: str
) -> CleaningOption:
    """Map a user's reply onto one of the offered options, deterministically.

    An answer that matches nothing resolves to the **do-nothing** option, not to
    the recommended one. The recommendation is a default for someone who clicked
    it, not a licence to apply a value-changing op off a reply we could not read.
    """
    norm = str(answer).strip().casefold()
    for option in proposal.options:
        if option.label.casefold() == norm:
            return option
    if norm:
        matches = [o for o in proposal.options if o.label.casefold().startswith(norm)]
        if len(matches) == 1:
            return matches[0]
    inert = [o for o in proposal.options if o.op is None]
    if inert:
        return inert[0]
    return proposal.options[-1]


def analyze_data_quality(
    record: DatasetRecord, columns: set[str] | None = None
) -> dict[str, Any]:
    """Read-only quality report: what is wrong, what to fix, what to ask about.

    Nothing here mutates anything or runs a query — it is safe to call before
    every analysis, which is the point: the caller decides what to do with
    ``auto_apply`` and ``proposals``, and the gate still applies to whatever they
    put in a plan.
    """
    issues = scan(record, columns)
    total = len(record.df)
    auto_ops, proposals = recommend(issues, total)
    return {
        "row_count": total,
        "columns_inspected": sorted(
            neutralize_text(c)
            for c in (columns if columns is not None else set(record.df.columns))
        ),
        "issues": [i.to_wire() for i in issues],
        "auto_apply": auto_ops,
        "proposals": [p.to_wire() for p in proposals],
    }
