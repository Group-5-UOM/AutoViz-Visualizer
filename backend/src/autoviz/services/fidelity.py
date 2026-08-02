"""Did the answer do what was asked?

A request can name something specific — a log scale, a chart type, an ordering —
that the run then does not deliver, for reasons that are usually good: the chart
grammar forbids it, the planner chose otherwise, the data did not warrant it.
The failure is not the refusal. The failure is returning a finished chart and
saying nothing, because a user who asked for a log version and got a chart back
has no way to tell a considered refusal from a request that was dropped.

So this module compares the request against what came out and writes a sentence
for each thing that was asked for and is not there. It only ever produces
disclosure — nothing here changes a chart.

Each check is ``(request, outcome) -> Notice | None`` and is registered in
``_CHECKS``. Adding one means writing that function and appending it; the rule
for a new check is that it must be able to answer "was this asked for?" from the
request text alone, and "did it happen?" from the produced plan or spec alone.
A check that has to guess at either belongs in the planner, not here.

Detection is deliberately narrow — a missed disclosure is a quiet bug, but a
false one tells the user their request was refused when it never happened, and
that is the louder failure.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from autoviz.services.notices import ADVISORY, Notice
from autoviz.services.skew import BASELINE_TYPES

_LOG_SCALES = frozenset({"log", "symlog"})


@dataclass(frozen=True)
class ChartOutcome:
    """What a run actually produced, in the three forms the checks need."""

    chart_type: str
    vega_lite_spec: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)


def _mentions(request: str, phrases: tuple[str, ...]) -> bool:
    lowered = request.casefold()
    return any(p in lowered for p in phrases)


# --- log / logarithmic scale --------------------------------------------------

_LOG_PHRASES = (
    "log scale", "log-scale", "log scaled", "log-scaled", "log scaling",
    "logarithmic", "log axis", "log-axis", "log y", "log x",
)


def _iter_encodings(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Every encoding block in a spec, layered or not."""
    blocks = []
    if isinstance(spec.get("encoding"), dict):
        blocks.append(spec["encoding"])
    for layer in spec.get("layer") or []:
        if isinstance(layer, dict) and isinstance(layer.get("encoding"), dict):
            blocks.append(layer["encoding"])
    return blocks


def _has_log_scale(spec: dict[str, Any]) -> bool:
    for encoding in _iter_encodings(spec):
        for channel in encoding.values():
            if not isinstance(channel, dict):
                continue
            if (channel.get("scale") or {}).get("type") in _LOG_SCALES:
                return True
    return False


def _check_log_scale(request: str, outcome: ChartOutcome) -> Notice | None:
    if not _mentions(request, _LOG_PHRASES):
        return None
    if outcome.chart_type in BASELINE_TYPES:
        return Notice(
            kind="request_not_applied",
            severity=ADVISORY,
            note=(
                f"The scale is unchanged. A {outcome.chart_type} chart encodes "
                "each value as a length measured from zero, and a log axis breaks "
                "that — the bars would stop being comparable by size, which is the "
                "only thing a bar is for. Ask for the same figures as a line or "
                "scatter chart and the log scale can be applied there."
            ),
            technique="none — request declined",
            detail={"requested": "log scale", "chart_type": outcome.chart_type},
        )
    if _has_log_scale(outcome.vega_lite_spec):
        return None
    return Notice(
        kind="request_not_applied",
        severity=ADVISORY,
        note=(
            "The axis is still linear: these values are close enough together "
            "that a log scale would not change what the chart shows."
        ),
        technique="none — request had no effect",
        detail={"requested": "log scale", "chart_type": outcome.chart_type},
    )


# --- an explicitly named chart type -------------------------------------------

# Longest first, so "grouped bar" is not read as "bar" and "box plot" is not
# missed by a search for "plot".
_CHART_PHRASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            ("grouped bar", "grouped_bar"),
            ("side by side bar", "grouped_bar"),
            ("stacked bar", "bar"),
            ("bar chart", "bar"),
            ("bar graph", "bar"),
            ("line chart", "line"),
            ("line graph", "line"),
            ("scatter plot", "scatter"),
            ("scatterplot", "scatter"),
            ("scatter chart", "scatter"),
            ("pie chart", "pie"),
            ("donut chart", "donut"),
            ("doughnut chart", "donut"),
            ("area chart", "area"),
            ("histogram", "histogram"),
            ("heatmap", "heatmap"),
            ("heat map", "heatmap"),
            ("box plot", "boxplot"),
            ("boxplot", "boxplot"),
        ),
        key=lambda pair: -len(pair[0]),
    )
)

_PRETTY_TYPE = {
    "grouped_bar": "grouped bar",
    "boxplot": "box plot",
}


def _named_chart_type(request: str) -> str | None:
    lowered = request.casefold()
    for phrase, chart_type in _CHART_PHRASES:
        if phrase in lowered:
            return chart_type
    return None


def _check_chart_type(request: str, outcome: ChartOutcome) -> Notice | None:
    asked = _named_chart_type(request)
    if asked is None or asked == outcome.chart_type:
        return None
    got = _PRETTY_TYPE.get(outcome.chart_type, outcome.chart_type)
    want = _PRETTY_TYPE.get(asked, asked)
    return Notice(
        kind="request_not_applied",
        severity=ADVISORY,
        note=(
            f"This is a {got} chart, not the {want} chart that was asked for — "
            f"a {want} could not be built from these columns, so the closest "
            "readable option was used instead."
        ),
        technique=f"chart type {outcome.chart_type} substituted for {asked}",
        detail={"requested": asked, "produced": outcome.chart_type},
    )


# --- an explicitly requested ordering -----------------------------------------

_SORT_PHRASES = (
    "sort", "sorted", "descending", "ascending", "in order", "ordered by",
    "ranked", "rank them", "from highest", "from lowest", "largest first",
    "smallest first",
)


def _check_sort(request: str, outcome: ChartOutcome) -> Notice | None:
    if not _mentions(request, _SORT_PHRASES):
        return None
    plan = outcome.plan
    # A ranking plan sorts at render time even with no explicit sort block, so
    # the request is honoured either way.
    if plan.get("sort") or plan.get("intent") == "ranking":
        return None
    return Notice(
        kind="request_not_applied",
        severity=ADVISORY,
        note=(
            "The categories are in the order the data produced them, not sorted "
            "by value — the ordering asked for was not applied."
        ),
        technique="none — request not applied",
        detail={"requested": "sort"},
    )


_CHECKS: tuple[Callable[[str, ChartOutcome], Notice | None], ...] = (
    _check_log_scale,
    _check_chart_type,
    _check_sort,
)


def unmet_requests(request: str, outcome: ChartOutcome) -> list[Notice]:
    """Every specific thing this request asked for that the result does not have.

    Order follows ``_CHECKS`` rather than severity: they are all advisory, and a
    stable order keeps the wording of an answer reproducible across runs.
    """
    if not request:
        return []
    found = []
    for check in _CHECKS:
        notice = check(request, outcome)
        if notice is not None:
            found.append(notice)
    return found
