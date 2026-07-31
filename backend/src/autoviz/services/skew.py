"""Charts where one huge value squashes everything else, and what to do about it.

The symptom is familiar: one row is 500x the rest, every other mark collapses
into a hairline at the baseline, and a chart that is arithmetically correct shows
nothing. The instinct is to clean the outlier away. That instinct is wrong — an
extreme value is only *sometimes* an error, the data cannot say which, and
dropping it to improve a chart changes the number the chart reports. This module
treats the problem where it actually lives: the axis.

Two decisions, kept apart:

**Where to measure.** On the *plotted* values, never on the source column.
Aggregation both destroys and creates skew — a violently skewed `revenue` column
averages into twelve unremarkable regional means, and a tame column can produce
one enormous bar because one group holds most of the rows. The distribution that
compresses the chart is the one in the result table.

**Whether a scale may be changed.** This is a property of the *channel*, not of
the chart type. A channel that encodes by **position** (a line or scatter axis) or
by **colour** (a heatmap's measure) can be rescaled freely: the mark moves, or its
hue changes, and nothing else is claimed. A channel that encodes by **length or
area from a baseline** — a bar, an area — cannot, because a log-scaled bar length
is no longer proportional to its value. That is the same objection that makes a
truncated bar axis misleading, and the research there is unambiguous that the
distortion survives even when readers correctly read the axis labels. So bars,
areas and histograms are told about the problem and keep their honest scale,
while a heatmap's colour is rescaled like any axis. Boxplots are exempt outright:
extremes are their content.

The result is always disclosed, never silent. A log axis that nobody mentions is
its own way of misleading someone.
"""

from typing import Any

from autoviz.services.notices import ADVISORY, Notice
from autoviz.services.safety import neutralize_text

# max / median at which the typical value renders as a hairline. At 25 the median
# mark occupies 4% of the axis; well before that a chart is merely uneven rather
# than unreadable, which is not worth interrupting anyone over.
SKEW_DOMINANCE = 25.0

# Share of the axis occupied by the middle half of the points. Catches the case
# dominance misses — several extreme values rather than one — and works on data
# that crosses zero, where a ratio means nothing.
SKEW_OCCUPANCY = 0.03

# Below this there is no "typical value" to be squashed; three bars of wildly
# different heights is a finding about the data, not a defect in the chart.
MIN_POINTS = 4

# Marks whose *position* channels may be rescaled.
SCALABLE_TYPES = frozenset({"line", "scatter"})

# Marks that encode by length or area from a baseline. Told, never rescaled.
BASELINE_TYPES = frozenset({"bar", "grouped_bar", "area", "histogram"})

# Extremes are the point of the chart.
EXEMPT_TYPES = frozenset({"boxplot"})

# Channels that carry a quantity as a hue rather than a distance. Rescaling one
# is always safe — no length is being claimed — so the mark's own class does not
# get a vote. This is what lets a heatmap's measure be log-scaled while a bar's
# height, on the very same chart grammar, may not be.
COLOR_CHANNELS = frozenset({"color", "fill"})


def _numbers(values: list[Any]) -> list[float]:
    """Finite numeric values only. Booleans are ints in Python and are not data."""
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        f = float(v)
        if f == f and f not in (float("inf"), float("-inf")):  # NaN != NaN
            out.append(f)
    return out


def _quantile(ordered: list[float], p: float) -> float:
    """Linear-interpolated quantile of an already-sorted list."""
    if len(ordered) == 1:
        return ordered[0]
    pos = p * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _num(value: float) -> str:
    """Compact enough to sit in a sentence."""
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.4g}"


def _is_compressed(ordered: list[float]) -> bool:
    """Whether the typical value is squashed against the baseline."""
    lo, hi = ordered[0], ordered[-1]
    span = hi - lo
    if span <= 0:
        return False
    # One dominant value. Only meaningful on strictly positive data, where the
    # baseline is zero and a ratio says what share of the axis the median gets.
    if lo > 0:
        median = _quantile(ordered, 0.5)
        if median > 0 and hi / median >= SKEW_DOMINANCE:
            return True
    # Several extremes, or data crossing zero: how much of the axis does the
    # middle half of the points actually occupy?
    iqr_span = _quantile(ordered, 0.75) - _quantile(ordered, 0.25)
    return iqr_span / span <= SKEW_OCCUPANCY


def assess(
    values: list[Any], column: str, chart_type: str, channel: str = "y"
) -> tuple[dict[str, Any] | None, Notice | None]:
    """Decide the scale for one quantitative channel, and what to say about it.

    Returns ``(scale, notice)``. ``scale`` is a Vega-Lite scale definition to
    merge into the encoding, or None to leave the channel alone; ``notice`` is the
    advisory to show the user, or None when there is nothing to report. A scale
    is never returned without a notice — a channel that silently stopped being
    linear is a trap, not a fix.
    """
    if chart_type in EXEMPT_TYPES:
        return None, None
    ordered = sorted(_numbers(values))
    if len(ordered) < MIN_POINTS or not _is_compressed(ordered):
        return None, None

    lo, hi = ordered[0], ordered[-1]
    median = _quantile(ordered, 0.5)
    pretty = neutralize_text(column).replace("_", " ").strip()
    detail = {
        "column": neutralize_text(column),
        "channel": channel,
        "min": lo,
        "max": hi,
        "median": median,
    }
    # A log domain must not include or cross zero, so anything touching zero or
    # going negative gets symlog — log-like, but defined at and below zero.
    scale_type = "log" if lo > 0 else "symlog"

    if channel in COLOR_CHANNELS:
        # Colour is the one channel where the linear version fails *worse* than a
        # squashed axis: one dominant cell takes the whole top of the ramp and
        # every other cell lands on an indistinguishable shade at the bottom, so
        # the chart reads as uniform rather than merely cramped.
        return (
            {"type": scale_type},
            Notice(
                kind="skewed_color",
                severity=ADVISORY,
                note=(
                    f"'{pretty}' spans {_num(lo)} to {_num(hi)}, so the colour "
                    f"scale is {scale_type}-scaled — on a linear ramp one value "
                    "would take the whole scale and the rest would be near-"
                    "identical shades. Equal steps in colour are equal ratios, "
                    "not equal amounts."
                ),
                column=neutralize_text(column),
                technique=f"{scale_type} colour scale on '{column}'",
                detail={**detail, "scale": scale_type},
            ),
        )

    if chart_type in SCALABLE_TYPES:
        return (
            {"type": scale_type},
            Notice(
                kind="skewed_axis",
                severity=ADVISORY,
                note=(
                    f"'{pretty}' spans {_num(lo)} to {_num(hi)}, so its axis is "
                    f"{scale_type}-scaled — on a linear axis the smaller values "
                    "would be flat against the baseline. Equal distances on that "
                    "axis are equal ratios, not equal amounts."
                ),
                column=neutralize_text(column),
                technique=f"{scale_type} scale on '{column}'",
                detail={**detail, "scale": scale_type},
            ),
        )

    if chart_type in BASELINE_TYPES:
        # Rescaling would break the length encoding, so the honest move is to say
        # what the chart is doing rather than quietly change what a bar means.
        times = int(hi / median) if median > 0 else None
        magnitude = f" — about {times}x the typical {_num(median)}" if times else ""
        return (
            None,
            Notice(
                kind="skewed_axis",
                severity=ADVISORY,
                note=(
                    f"'{pretty}' is dominated by one value, {_num(hi)}{magnitude}, "
                    "so the smaller values are compressed near the baseline. The "
                    "scale is left linear because bar length has to stay "
                    "proportional; a line or scatter of the same data can be "
                    "log-scaled instead."
                ),
                column=neutralize_text(column),
                technique="none — disclosure only",
                detail=detail,
            ),
        )

    return None, None
