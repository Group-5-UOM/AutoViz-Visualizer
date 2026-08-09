"""Disclosure: turning what the pipeline did into what the user is told.

Provenance already records every cleaning step in full, but provenance is an
audit artefact — nobody reads it mid-conversation. This module is the other half:
the short, finished sentences that belong in the answer itself, so a user who
never opens the SQL still learns that 40% of the column they just averaged was
filled in rather than measured.

The prose is built **here, in Python**, for the same reason the recommendations in
services/quality.py are: a disclosure the LLM paraphrases is a disclosure that can
drift, soften, or vanish. The composer is handed a finished sentence and told to
reuse it, never raw counts to phrase itself.

Three severities, which decide *how loudly* something is said — distinct from
``Risk``, which decides whether consent was needed in the first place:

* ``applied``  — semantics-preserving repair. Batched into one clause; the user
  is told it happened, not asked to care.
* ``disclosed`` — the number now means something different from the raw data.
  Must reach the user, in its own sentence.
* ``advisory`` — nothing was changed, but the chart cannot be read correctly
  without knowing this (a log-scaled axis). Also its own sentence.

Severity is *derived* from the op's declared ``Risk`` plus the existing
``ROW_DROP_NOTICE_FRACTION`` line, never declared a second time by hand — a
parallel judgement here would be one more thing to forget to update when an op
changes tier.
"""

from dataclasses import dataclass, field
from typing import Any, Union, get_args

from autoviz.schema.allowlists import ROW_DROP_NOTICE_FRACTION, Risk
from autoviz.schema.analysis_plan import PreprocessOp
from autoviz.services.safety import neutralize_text

APPLIED = "applied"
DISCLOSED = "disclosed"
ADVISORY = "advisory"

# Severity ordering for display: the things that change the answer lead.
_SEVERITY_RANK = {DISCLOSED: 0, ADVISORY: 1, APPLIED: 2}


def _op_risk_map() -> dict[str, Risk]:
    """op name -> declared risk, read off the models themselves.

    ``PreprocessOp`` is ``Annotated[Union[...], Field(discriminator=...)]``, so the
    members come out in two unwrapping steps. Deriving the map means a new op is
    covered the moment it joins the union, rather than the moment someone
    remembers to extend a list down here.
    """
    union = get_args(PreprocessOp)[0]
    out: dict[str, Risk] = {}
    for model in get_args(union):
        (name,) = get_args(model.model_fields["op"].annotation)
        out[name] = model.risk
    return out


_OP_RISK = _op_risk_map()


@dataclass(frozen=True)
class Notice:
    """One thing the user should be told, already written as a sentence."""

    kind: str
    severity: str
    note: str
    column: str | None = None
    # The jargon for this action, kept separate so it can sit behind a "how this
    # works" disclosure instead of leading — same split as quality.CleaningOption.
    technique: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "note": self.note,
            **({"column": self.column} if self.column else {}),
            **({"technique": self.technique} if self.technique else {}),
            **({"detail": self.detail} if self.detail else {}),
        }


def _pretty(column: str) -> str:
    """Column name as prose. Neutralized: header text is untrusted input, and
    these strings are bound for both an LLM prompt and the user's screen."""
    return neutralize_text(column).replace("_", " ").strip()


def _pct(fraction: float) -> str:
    return f"{round(fraction * 100, 1)}%"


def _severity_for(op_name: str, fraction: float) -> str:
    """How loudly to say it: risk tier first, size as the tie-breaker.

    A SAFE op never changes meaning, so it is ``applied`` at any size. A
    value-changing op is ``disclosed`` once it crosses the line the codebase
    already draws at ROW_DROP_NOTICE_FRACTION for "small enough to mention rather
    than ask about" — below it, the op is real but too small to spend a sentence
    on, so it joins the batched clause instead of leading the answer.
    """
    if _OP_RISK.get(op_name, Risk.VALUE_CHANGING) is Risk.SAFE:
        return APPLIED
    return DISCLOSED if fraction >= ROW_DROP_NOTICE_FRACTION else APPLIED


def _columns_phrase(cols: list[str]) -> str:
    pretty = [f"'{_pretty(c)}'" for c in cols]
    if not pretty:
        # These entries are read back from stored provenance as well as built
        # fresh, so a missing key must degrade to a vaguer sentence rather than
        # take the whole disclosure down with an IndexError.
        return "the affected column(s)"
    if len(pretty) == 1:
        return pretty[0]
    return f"{', '.join(pretty[:-1])} and {pretty[-1]}"


def from_preprocessing(report: list[dict[str, Any]], input_rows: int) -> list[Notice]:
    """One notice per cleaning step that actually did something.

    A step with ``rows_affected == 0`` is dropped: it ran, it was a no-op, and
    "trimmed whitespace in 0 rows" is noise that pushes the real disclosure
    further down the answer.
    """
    if not input_rows:
        return []
    out: list[Notice] = []
    for entry in report:
        name = str(entry.get("operation") or "")
        affected = int(entry.get("rows_affected") or 0)
        if not affected:
            continue
        fraction = affected / input_rows
        severity = _severity_for(name, fraction)
        col = entry.get("column")
        cols = entry.get("columns") or ([col] if col else [])
        note: str | None = None
        technique: str | None = None

        if name == "fill_nulls":
            strategy = entry.get("strategy")
            within = entry.get("by") or []
            scope = f" within each {_columns_phrase(list(within))}" if within else ""
            note = (
                f"{affected} of {input_rows} values in '{_pretty(str(col))}' "
                f"({_pct(fraction)}) were filled in{scope}, not measured."
            )
            still = int(entry.get("rows_still_null") or 0)
            if still:
                # A group with no values at all has nothing to impute from, so
                # those rows stay missing. Silence here would let the reader
                # assume the column is now complete.
                note += (
                    f" {still} could not be filled — their group has no recorded "
                    f"{_pretty(str(col))} at all — and remain missing."
                )
            technique = f"{strategy} imputation on '{col}'" + (
                f" by {list(within)}" if within else ""
            )
        elif name == "drop_nulls":
            note = (
                f"{affected} row(s) with no {_columns_phrase(list(cols))} "
                f"({_pct(fraction)}) were excluded."
            )
            technique = f"drop_nulls on {list(cols)}"
        elif name == "drop_exact_duplicates":
            note = f"{affected} duplicate row(s) ({_pct(fraction)}) were counted only once."
            technique = "drop_exact_duplicates"
        elif name == "drop_empty_rows":
            note = f"{affected} completely empty row(s) were dropped."
            technique = "drop_empty_rows"
        elif name == "trim_whitespace":
            note = f"Stray spaces around values in {_columns_phrase(list(cols))} were removed."
            technique = f"trim_whitespace on {list(cols)}"
        elif name == "empty_string_to_null":
            note = f"Blank text in {_columns_phrase(list(cols))} was treated as missing."
            technique = f"empty_string_to_null on {list(cols)}"
        elif name == "normalize_case":
            note = (
                f"Values in {_columns_phrase(list(cols))} that differed only in "
                "capitalisation were merged, keeping the commonest spelling of each."
            )
            technique = f"normalize_case on {list(cols)}"
        elif name == "cast_column":
            note = f"'{_pretty(str(col))}' was read as {entry.get('to')}."
            technique = f"cast_column on '{col}'"
        elif name == "parse_number":
            note = (
                f"Currency symbols and separators were removed from "
                f"{_columns_phrase(list(cols))} so the values could be counted as numbers."
            )
            technique = f"parse_number on {list(cols)}"
        elif name == "nullify_values":
            shown = ", ".join(str(v) for v in (entry.get("values") or []))
            note = (
                f"{affected} value(s) in '{_pretty(str(col))}' ({_pct(fraction)}) were "
                f"the placeholder(s) {shown} and are now treated as missing rather "
                "than counted as numbers."
            )
            technique = f"nullify_values on '{col}'"
        elif name == "pivot_longer":
            # No percentage: this op multiplies rows, so "affected / input_rows"
            # is above 100% and reads as a bug rather than a reshape.
            before = int(entry.get("rows_before") or input_rows)
            note = (
                f"{len(cols)} columns ({_columns_phrase(list(cols))}) were folded into "
                f"rows, so '{_pretty(str(entry.get('names_to')))}' is now a value you "
                f"can group by. {before} row(s) became {affected}."
            )
            technique = f"pivot_longer on {list(cols)}"
        elif name == "split_column":
            note = (
                f"'{_pretty(str(col))}' was split on '{entry.get('separator')}' into "
                f"{_columns_phrase(list(entry.get('into') or []))}. "
                f"{affected} of {input_rows} row(s) contained the separator; the rest "
                "have no value for the new columns."
            )
            technique = f"split_column on '{col}'"
        elif name == "clean_categories":
            note = (
                f"{affected} value(s) in '{_pretty(str(col))}' ({_pct(fraction)}) "
                "were relabelled."
            )
            technique = f"clean_categories on '{col}'"
        elif name == "group_rare_categories":
            # Naming the ranking matters: "outside the top 10" is a different
            # claim depending on whether the top 10 was decided by row count or
            # by the measure on the axis, and a reader cannot tell which from a
            # bar labelled "Other".
            rank_by = entry.get("rank_by") or {}
            ranked = (
                f"the categories leading on {rank_by['fn']} of "
                f"'{_pretty(str(rank_by['column']))}'"
                if rank_by
                else "the commonest categories"
            )
            note = (
                f"{affected} row(s) in '{_pretty(str(col))}' ({_pct(fraction)}) fell "
                f"outside {ranked} and were grouped as "
                f"'{entry.get('other_label') or 'Other'}'."
            )
            technique = f"group_rare_categories on '{col}'"

        if note is None:
            continue
        out.append(
            Notice(
                kind=name,
                severity=severity,
                note=note,
                column=neutralize_text(str(col)) if col else None,
                technique=technique,
                detail={"rows_affected": affected, "fraction": round(fraction, 4)},
            )
        )
    return out


def from_null_exclusions(exclusions: dict[str, int], input_rows: int) -> list[Notice]:
    """Nulls an aggregate skipped on its own, with no cleaning op involved.

    This is the disclosure that is easiest to lose, because nothing "happened" —
    no step ran, no row was dropped by a plan. The average is simply over fewer
    rows than the user thinks. Below the notice threshold it is left to
    provenance; above it, it belongs in the answer.
    """
    if not input_rows:
        return []
    out: list[Notice] = []
    for col, count in sorted(exclusions.items()):
        if not count:
            continue
        fraction = count / input_rows
        if fraction < ROW_DROP_NOTICE_FRACTION:
            continue
        out.append(
            Notice(
                kind="implicit_null_exclusion",
                severity=DISCLOSED,
                note=(
                    f"{count} of {input_rows} row(s) ({_pct(fraction)}) have no "
                    f"'{_pretty(col)}' and were skipped by the calculation."
                ),
                column=neutralize_text(col),
                technique=f"null-skipping aggregate on '{col}'",
                detail={"rows_affected": count, "fraction": round(fraction, 4)},
            )
        )
    return out


# --- work the system decided not to do ------------------------------------------
# Three paths used to drop work silently: repairs cut by the step budget, cleaning
# questions cut by the prompt cap, and rows cut by the output ceiling. Each is a
# defensible limit and each was invisible, which in a tool built on disclosure is
# the one inconsistency that undermines the rest — the user cannot tell a decision
# that was made from one that was skipped.
#
# ADVISORY, not APPLIED: nothing happened, and that is exactly what has to be said.


def from_dropped_repairs(dropped: list[dict[str, Any]]) -> list[Notice]:
    """Safe repairs the step budget had no room for.

    The budget is real — a plan is capped at MAX_PREPROCESSING_STEPS — and a wide
    messy file can easily produce more repairs than that. Cutting them is right;
    cutting them without a word leaves a column half-cleaned and looking cleaned.
    """
    if not dropped:
        return []
    columns: list[str] = []
    kinds: set[str] = set()
    for op in dropped:
        kinds.add(str(op.get("op") or ""))
        if "columns" in op:
            columns.extend(str(c) for c in op["columns"])
        elif "column" in op:
            columns.append(str(op["column"]))
    unique = sorted(set(columns))
    where = f" in {_columns_phrase(unique)}" if unique else ""
    return [
        Notice(
            kind="repairs_not_applied",
            severity=ADVISORY,
            note=(
                f"{len(dropped)} routine cleanup step(s){where} were skipped: one "
                "analysis can only carry so many. Those values were left exactly as "
                "they are in the file."
            ),
            technique=f"step budget: {', '.join(sorted(kinds))} dropped",
            detail={"dropped": len(dropped), "columns": [neutralize_text(c) for c in unique]},
        )
    ]


def from_unasked_proposals(questions: list[str]) -> list[Notice]:
    """Cleaning decisions that were never put to the user.

    One question is asked per pass and the pass count is capped, so on a dirty
    dataset some findings never reach anyone. The unasked ones resolve to "leave
    it alone", which is the safe default and still a decision made on the user's
    behalf.
    """
    if not questions:
        return []
    return [
        Notice(
            kind="cleaning_not_asked",
            severity=ADVISORY,
            note=(
                f"{len(questions)} further data-quality decision(s) were not put to "
                f"you ({'; '.join(questions)}). Nothing was changed for them — the "
                "data was used as it is."
            ),
            technique="cleaning prompt budget reached",
            detail={"unasked": len(questions)},
        )
    ]


def from_quality_issues(issues: list[dict[str, Any]]) -> list[Notice]:
    """Findings that are worth reporting but that nothing can offer to fix.

    A column of email addresses with forty malformed entries is a real defect and
    there is no repair to propose: the grammar cannot invent the right address,
    and dropping the rows is a decision about the analysis, not about the data.
    So it is stated and left alone — which is also what Tableau's data roles do,
    minus the pretence that flagging is fixing.
    """
    out: list[Notice] = []
    for issue in issues:
        if issue.get("kind") != "invalid_domain_values":
            continue
        column = str(issue.get("column") or "")
        domain = str((issue.get("detail") or {}).get("domain") or "expected format")
        affected = int(issue.get("affected") or 0)
        if not affected:
            continue
        out.append(
            Notice(
                kind="invalid_domain_values",
                severity=ADVISORY,
                note=(
                    f"{affected} value(s) in '{_pretty(column)}' are not a valid "
                    f"{domain}, though the rest of the column is. They were left as "
                    "they are and still count toward any total of rows."
                ),
                column=neutralize_text(column),
                technique=f"domain check: {domain}",
                detail={"affected": affected, "domain": domain},
            )
        )
    return out


def from_row_ceiling(row_count: int, ceiling: int) -> list[Notice]:
    """The output ceiling was reached, so the table is a prefix of the answer."""
    if row_count < ceiling:
        return []
    return [
        Notice(
            kind="row_ceiling",
            severity=ADVISORY,
            note=(
                f"This result reached the {ceiling:,}-row ceiling. Any rows past that "
                "point are not included, so totals and extremes here describe the rows "
                "shown rather than the whole dataset."
            ),
            technique=f"HARD_ROW_CEILING={ceiling}",
            detail={"row_count": row_count, "ceiling": ceiling},
        )
    ]


# --- how the file had to be read ----------------------------------------------
# Reading is the one stage that happens before there is anything to disclose *about*
# — no op ran, no row moved, and yet a mis-sniffed delimiter or a swapped date order
# changes every number downstream. These are ADVISORY for exactly the reason the
# severity exists: nothing was altered, and the chart is still misread without them.
#
# Each check reads the wire form of an IngestReport (as stored on the profile)
# rather than the dataclass, so a dataset restored from a Parquet blob discloses
# the same things as one still in memory.

_ENCODING_NAMES = {
    "cp1252": "Windows-1252",
    "latin-1": "Latin-1",
    "utf-16": "UTF-16",
}


def _ingest_encoding(report: dict[str, Any]) -> Notice | None:
    encoding = str(report.get("encoding") or "")
    name = _ENCODING_NAMES.get(encoding, encoding)
    return Notice(
        kind="ingest_encoding",
        severity=ADVISORY,
        note=(
            f"This file is not UTF-8, so it was read as {name}. If any accented or "
            "non-English text looks wrong, that guess is why."
        ),
        technique=f"decoded as {encoding}",
        detail={"encoding": encoding},
    )


def _ingest_delimiter(report: dict[str, Any]) -> Notice | None:
    delimiter = str(report.get("delimiter") or ",")
    shown = {"\t": "a tab", ";": "a semicolon", "|": "a pipe"}.get(delimiter, f"'{delimiter}'")
    return Notice(
        kind="ingest_delimiter",
        severity=ADVISORY,
        note=f"Columns in this file are separated by {shown}, not a comma, and were split that way.",
        technique=f"delimiter {delimiter!r}",
        detail={"delimiter": delimiter},
    )


def _ingest_header_row(report: dict[str, Any]) -> Notice | None:
    skipped = int(report.get("header_row") or 0)
    return Notice(
        kind="ingest_header_row",
        severity=ADVISORY,
        note=(
            f"The first {skipped} line(s) of this file were a title or notes above the "
            "table rather than data, so the column names were taken from line "
            f"{skipped + 1}."
        ),
        technique=f"header on row {skipped}",
        detail={"header_row": skipped},
    )


def _ingest_decimal_comma(report: dict[str, Any]) -> Notice | None:
    return Notice(
        kind="ingest_decimal_comma",
        severity=ADVISORY,
        note=(
            "Numbers in this file are written the European way (1.234,56), so a comma "
            "was read as the decimal point and a full stop as the thousands separator."
        ),
        technique="decimal=',' thousands='.'",
        detail={"decimal": ","},
    )


def _ingest_ambiguous_dates(report: dict[str, Any]) -> Notice | None:
    return Notice(
        kind="ingest_ambiguous_dates",
        severity=ADVISORY,
        note=(
            "Dates in this file are written like 01/02/2024, which could mean 1 February "
            "or 2 January — the file does not say which. They were read month-first."
        ),
        technique="dayfirst=False (undetermined)",
        detail={"dayfirst": False},
    )


def _ingest_na_exclusion(report: dict[str, Any]) -> Notice | None:
    exclusions = report.get("na_exclusions") or {}
    if not exclusions:
        return None
    cols = sorted(exclusions)
    return Notice(
        kind="ingest_na_exclusion",
        severity=ADVISORY,
        note=(
            f"'NA' in {_columns_phrase(cols)} was kept as a value rather than read as "
            "missing: the column holds two-letter codes, where NA is Namibia."
        ),
        column=neutralize_text(cols[0]) if len(cols) == 1 else None,
        technique="na_values exclusion",
        detail={"columns": [neutralize_text(c) for c in cols]},
    )


def _ingest_extra_sheets(report: dict[str, Any]) -> Notice | None:
    others = report.get("other_sheets") or []
    if not others:
        return None
    sheet = report.get("sheet") or "the first sheet"
    rest = ", ".join(f"'{s}'" for s in others)
    return Notice(
        kind="ingest_extra_sheets",
        severity=ADVISORY,
        note=(
            f"This workbook has {len(others)} other sheet(s) — only '{sheet}' was read. "
            f"The rest ({rest}) are not in this analysis."
        ),
        technique=f"read sheet '{sheet}'",
        detail={"sheet": sheet, "other_sheets": list(others)},
    )


_INGEST_CHECKS = {
    "encoding": _ingest_encoding,
    "delimiter": _ingest_delimiter,
    "header_row": _ingest_header_row,
    "decimal_comma": _ingest_decimal_comma,
    "ambiguous_dates": _ingest_ambiguous_dates,
    "na_exclusion": _ingest_na_exclusion,
    "extra_sheets": _ingest_extra_sheets,
}


def from_ingest(report: dict[str, Any] | None) -> list[Notice]:
    """Advisories for the reading decisions a user could reasonably dispute.

    Driven off ``report["assumptions"]``, which the probe leaves **empty** for a
    well-formed UTF-8 comma CSV. That emptiness is the point: an advisory attached
    to every upload is one nobody reads by the time it matters.
    """
    if not report:
        return []
    out: list[Notice] = []
    for kind in report.get("assumptions") or []:
        check = _INGEST_CHECKS.get(str(kind))
        if check is None:
            continue
        notice = check(report)
        if notice is not None:
            out.append(notice)
    return out


def order(notices: list[Notice]) -> list[Notice]:
    """Most consequential first, largest effect first within a severity."""
    return sorted(
        notices,
        key=lambda n: (
            _SEVERITY_RANK.get(n.severity, 99),
            -float(n.detail.get("fraction") or 0),
        ),
    )


def render_summary(notices: list[Notice]) -> str:
    """Deterministic prose for the whole set, for callers with no LLM.

    Used by the composer's fallback path. Disclosures and advisories keep their
    own sentences; the safe repairs collapse into one trailing clause, because a
    wide messy CSV can produce a dozen of them and a paragraph of throat-clearing
    in front of the answer is its own kind of unhelpful.
    """
    if not notices:
        return ""
    ordered = order(notices)
    lead = [n.note for n in ordered if n.severity in (DISCLOSED, ADVISORY)]
    applied = [n.note for n in ordered if n.severity == APPLIED]
    parts = list(lead)
    if applied:
        joined = " ".join(applied)
        parts.append(f"Routine cleanup was also applied: {joined}")
    return " ".join(parts)


def to_wire(notices: list[Notice]) -> list[dict[str, Any]]:
    return [n.to_wire() for n in order(notices)]
