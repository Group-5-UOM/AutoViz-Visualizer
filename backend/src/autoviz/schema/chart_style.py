"""User overrides layered on top of the baked-in chart theme (FR-15).

`services/chart_theme.py` is the single source of chart colour and chrome, and it
is deliberately not configurable — a validated palette in a fixed slot order. But
a user with a brand colour, or a chart whose default title reads badly, has to be
able to say so. This is the grammar for saying it.

**Why a separate block rather than fields on ChartSpec.** `ChartSpec` is part of
the analysis plan: a description of *what to compute*, written by the planner and
executed as SQL. Presentation is neither planned nor executed, and folding it in
would mean every style tweak re-ran the query. So the block travels beside the
spec and is applied to the finished Vega-Lite output.

**Cumulative, not incremental.** This is the widget's whole styling state, not a
diff. An edit merges into it and the entire block is re-applied to the chart, so
repeated edits cannot compound — applying the same block twice is applying it
once. That is also why every field is nullable: `None` is how a field says
"revert to the theme", which an absent field cannot express.

Colours are validated for *syntax* only. Nothing here measures contrast or
colour-vision separation: the theme's own palette carries those guarantees, and a
colour the user chose deliberately is the user's call to make.
"""

import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# #rgb or #rrggbb. Vega-Lite also accepts named CSS colours, but a free-text
# colour field is a place for a planner to hallucinate something unrenderable —
# a closed syntax fails loudly here instead of silently drawing nothing.
HEX_PATTERN = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"

HexColor = Annotated[str, StringConstraints(pattern=HEX_PATTERN)]

# A chart with more series than the theme has slots already folds into "Other";
# an override list longer than that is describing a chart that cannot exist.
MAX_SCHEME_COLORS = 20
# Bounded so an over-eager planner cannot turn one instruction into an unbounded
# map, and so a stored block stays a reasonable size in the chart_spec column.
MAX_SERIES_COLORS = 50

# Named stacks rather than a free-text family, for the same reason colours are
# closed hex — see services/chart_theme.FONT_STACKS, which holds the actual CSS
# these resolve to. Keep the two in step.
FontFamily = Literal["sans", "system", "serif", "mono"]

# The base tick-label size. The floor is where axis labels stop being readable;
# the ceiling is where a widget-sized chart is all text and no plot. Sizes above
# the base keep their offset from it, so the whole scale moves together.
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 28

# --- raw Vega-Lite config -----------------------------------------------------
#
# The fields above are the easy 80%. Everything else Vega-Lite can say about how
# a chart looks — gridlines, corner radius, label angle, background — lives in
# its top-level `config`, and a technical user may write that object by hand.
#
# `config` is chosen because it holds presentation and nothing else: no data, no
# encoding, no transform. A hand edit there cannot change a number. But it is
# still rendered in *other people's* browsers on a shared board, so the object is
# checked for the few places where Vega-Lite reaches beyond styling.

# Top-level keys a user may set: the Vega-Lite `Config` properties that describe
# appearance. Absent on purpose: `customFormatTypes` (routes formatting through
# registered code), `params`/`selection` (interaction, not look), `image` (its
# mark config carries a `url`), `projection`/`locale` (not appearance).
_CONFIG_KEYS = frozenset(
    {
        "arc", "area", "aria", "autosize", "background", "bar", "boxplot",
        "circle", "concat", "countTitle", "errorband", "errorbar", "facet",
        "font", "geoshape", "legend", "line", "lineBreak", "mark",
        "normalizedNumberFormat", "numberFormat", "padding", "point", "range",
        "rect", "rule", "scale", "square", "style", "text", "tick",
        "timeFormat", "title", "tooltipFormat", "trail", "view",
    }
)
# The axis* and header* families are open-ended (axisX, axisYBand, headerRow…).
_CONFIG_KEY_FAMILIES = re.compile(r"^(axis|header)[A-Za-z]*$")

# Keys refused at any depth. `expr`/`signal` and any `*Expr` (labelExpr, …) are
# Vega expressions — a language, and one with a history of sandbox escapes.
# `url`/`href` make a viewer's browser fetch or link somewhere. `test`/
# `condition` carry predicates, which are expressions again.
_FORBIDDEN_KEYS = frozenset({"expr", "signal", "url", "href", "test", "condition"})

# A style override, not a stylesheet. Bounded for the same reason as the colour
# maps: it is stored in chart_spec and shipped with every dashboard load.
MAX_CONFIG_BYTES = 16_000
MAX_CONFIG_DEPTH = 8


def _check_config_value(value: Any, path: str, depth: int) -> None:
    if depth > MAX_CONFIG_DEPTH:
        raise ValueError(f"config is nested too deeply at {path}")
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in _FORBIDDEN_KEYS or key.endswith("Expr"):
                raise ValueError(
                    f"config.{path}{key} is not allowed: expressions, signals and "
                    "links cannot be set here"
                )
            _check_config_value(inner, f"{path}{key}.", depth + 1)
    elif isinstance(value, list):
        for i, inner in enumerate(value):
            _check_config_value(inner, f"{path}{i}.", depth + 1)


def validate_vega_config(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a config that does more than describe appearance."""
    if len(json.dumps(config)) > MAX_CONFIG_BYTES:
        raise ValueError(f"config is larger than {MAX_CONFIG_BYTES:,} bytes")
    for key, value in config.items():
        if key not in _CONFIG_KEYS and not _CONFIG_KEY_FAMILIES.match(key):
            raise ValueError(f"config.{key} is not a styling option that can be set here")
        _check_config_value({key: value}, "", 0)
    return config


class ChartStyle(BaseModel):
    """Presentation overrides for one chart. Every field optional and nullable."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    x_title: str | None = Field(default=None, max_length=200)
    y_title: str | None = Field(default=None, max_length=200)
    # False hides the colour legend. Series stay distinguishable by direct label
    # or tooltip, so this is a presentation choice rather than a loss of meaning.
    legend: bool | None = None
    # Single-series charts have no colour scale, so their colour is the mark's.
    mark_color: HexColor | None = None
    # Series value -> colour, for a chart that does have a colour scale.
    series_colors: dict[str, HexColor] | None = Field(
        default=None, max_length=MAX_SERIES_COLORS
    )
    # Ordered replacement for the categorical range, when the user cares about the
    # palette rather than about which series got which colour.
    color_scheme: list[HexColor] | None = Field(
        default=None, max_length=MAX_SCHEME_COLORS
    )
    # Typography applies to every piece of text on the chart at once. There is no
    # per-element size here on purpose: the theme's hierarchy (axis titles a step
    # above tick labels) is a designed relationship, and letting it be set piece
    # by piece is how a chart ends up with a 9px title over 16px labels.
    font: FontFamily | None = None
    # The tick-label size; the rest of the scale shifts with it.
    font_size: int | None = Field(default=None, ge=MIN_FONT_SIZE, le=MAX_FONT_SIZE)
    # A raw Vega-Lite `config` object, applied last so it wins over the theme and
    # over the fields above. Written by hand in the style panel's advanced
    # editor; the natural-language path never authors it.
    config: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def _config_is_presentation_only(cls, value: dict[str, Any] | None):
        return None if value is None else validate_vega_config(value)

    def merged_with(self, patch: "ChartStyle") -> "ChartStyle":
        """This block with `patch` laid over it.

        Only fields the patch actually set are taken, so "make it orange" does
        not silently discard the title the user set three edits ago. A field set
        to None *is* set — that is how a revert is expressed.
        """
        return ChartStyle.model_validate(
            {**self.model_dump(), **patch.model_dump(exclude_unset=True)}
        )
