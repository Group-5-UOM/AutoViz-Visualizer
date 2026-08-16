"""Clarification grammar — the canonical shapes for ambiguity resolution.

Direction B of the ambiguity-resolution feature: deterministic detectors (Day
2-3) emit `Ambiguity` objects; the agent surfaces one at a time as a wire-level
`{question, options}` payload (unchanged API contract); the user's answer is
bound back to the originating slot *deterministically* (`bind_answer`) instead of
being re-inferred by the LLM. `ClarificationState` tracks the bounded, multi-round
session so resolved slots accumulate and each round removes one ambiguity.

Kept separate from `llm.client.Clarification` (the current single-shot model) so
this can be introduced additively; the graph is rewired to it on Day 4.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The taxonomy this feature covers. Day 2-3 implement detectors for the first
# three; the fourth ("value_reference") is folded into the Day 3 detector.
AmbiguityType = Literal[
    "time_column",      # multiple plausible date/time columns for a temporal ask
    "missing_metric",   # a superlative/ranking ("best", "top") names no measure
    "column_reference", # a concept in the request maps to >1 real column
    "value_reference",  # a literal in the request matches values in >1 column
    # The request asks for something the closed grammar cannot express at all —
    # forecasting, statistical modelling, a join. Unlike the others this is not a
    # question about *which* of several readings was meant; it is a statement
    # that none of them exist, paired with the nearest thing that does.
    "unsupported_capability",
]

# The plan slot a resolution fills. Kept small and explicit so binding is total.
Slot = Literal["time_column", "metric", "dimension", "filter_value", "capability"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClarificationOption(_Strict):
    """One grounded, selectable answer.

    `label` is the human-facing button text; `resolves_to` is the structured
    resolution bound to the slot when this option is chosen — e.g.
    ``{"column": "signup_date"}`` for a time column, or
    ``{"aggregation": {"column": "fare", "fn": "mean"}}`` for a metric. Because
    options are generated from the real schema/profile, `resolves_to` always
    references columns/values that exist.
    """

    label: str
    resolves_to: dict[str, Any] = Field(default_factory=dict)


class Ambiguity(_Strict):
    """A single detected ambiguity plus how to ask about it."""

    type: AmbiguityType
    slot: Slot
    question: str
    options: list[ClarificationOption] = Field(default_factory=list)
    allow_free_text: bool = True
    # Optional machine detail for observability/tests (e.g. the candidate columns).
    detail: dict[str, Any] = Field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        """Reduce to the existing API/interrupt shape: {question, options:[str]}."""
        return {"question": self.question, "options": [o.label for o in self.options]}


class Resolution(_Strict):
    """The deterministic result of binding a user's answer to an ambiguity."""

    slot: Slot
    # "option": matched an offered option; "free_text": no option matched but the
    # ambiguity allowed free text; "unmatched": no option matched and free text
    # was not allowed (caller must re-ask or apply a default).
    source: Literal["option", "free_text", "unmatched"]
    value: dict[str, Any] = Field(default_factory=dict)
    matched_label: str | None = None

    @property
    def resolved(self) -> bool:
        return self.source != "unmatched"


class ClarificationState(_Strict):
    """Bounded, multi-round clarification session state for one run.

    `pending` is a FIFO queue of unresolved ambiguities; `resolved` maps each
    answered slot to its bound value; `rounds` counts questions already asked so
    the graph can cap the loop.
    """

    pending: list[Ambiguity] = Field(default_factory=list)
    resolved: dict[str, Any] = Field(default_factory=dict)
    rounds: int = 0

    def next_ambiguity(self) -> Ambiguity | None:
        return self.pending[0] if self.pending else None

    def record(self, resolution: Resolution) -> None:
        """Apply a resolution: store it under its slot and drop the front ambiguity."""
        if self.pending and self.pending[0].slot == resolution.slot:
            self.pending.pop(0)
        self.resolved[resolution.slot] = resolution.value
        self.rounds += 1


def bind_answer(ambiguity: Ambiguity, answer: str) -> Resolution:
    """Map a user's free-text answer to a structured resolution — deterministically.

    Resolution order (first match wins), all case/space-insensitive:
      1. exact match against an option label,
      2. match against a scalar inside an option's ``resolves_to`` (so typing the
         column name works even if the label was prettier),
      3. an option label that starts with, or is contained in, the answer,
      4. free text (when allowed) — carried through verbatim for the LLM/planner,
      5. otherwise "unmatched".

    Binding never calls the LLM: a clicked option (or a recognizable typed answer)
    resolves the exact slot that was asked, closing the "answer isn't bound to the
    ambiguity" gap in the old flow.
    """
    norm = _norm(answer)

    # 1. exact label match
    for opt in ambiguity.options:
        if _norm(opt.label) == norm:
            return Resolution(slot=ambiguity.slot, source="option",
                              value=opt.resolves_to, matched_label=opt.label)

    # 2. match a scalar value inside resolves_to (e.g. the column name)
    for opt in ambiguity.options:
        for v in opt.resolves_to.values():
            if isinstance(v, (str, int, float)) and not isinstance(v, bool) and _norm(str(v)) == norm:
                return Resolution(slot=ambiguity.slot, source="option",
                                  value=opt.resolves_to, matched_label=opt.label)

    # 3. label startswith / substring (guard against trivially short answers)
    if len(norm) >= 3:
        for opt in ambiguity.options:
            lbl = _norm(opt.label)
            if lbl.startswith(norm) or norm in lbl:
                return Resolution(slot=ambiguity.slot, source="option",
                                  value=opt.resolves_to, matched_label=opt.label)

    # 4. free text
    if ambiguity.allow_free_text and answer.strip():
        return Resolution(slot=ambiguity.slot, source="free_text",
                          value={"text": answer.strip()}, matched_label=None)

    # 5. nothing matched and free text not allowed
    return Resolution(slot=ambiguity.slot, source="unmatched")


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()
