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
            note = (
                f"{affected} of {input_rows} values in '{_pretty(str(col))}' "
                f"({_pct(fraction)}) were filled in, not measured."
            )
            technique = f"{strategy} imputation on '{col}'"
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
                "capitalisation were merged."
            )
            technique = f"normalize_case on {list(cols)}"
        elif name == "cast_column":
            note = f"'{_pretty(str(col))}' was read as {entry.get('to')}."
            technique = f"cast_column on '{col}'"
        elif name == "clean_categories":
            note = (
                f"{affected} value(s) in '{_pretty(str(col))}' ({_pct(fraction)}) "
                "were relabelled."
            )
            technique = f"clean_categories on '{col}'"
        elif name == "group_rare_categories":
            note = (
                f"{affected} row(s) in '{_pretty(str(col))}' ({_pct(fraction)}) fell "
                "outside the commonest categories and were grouped as "
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
