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

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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

    def merged_with(self, patch: "ChartStyle") -> "ChartStyle":
        """This block with `patch` laid over it.

        Only fields the patch actually set are taken, so "make it orange" does
        not silently discard the title the user set three edits ago. A field set
        to None *is* set — that is how a revert is expressed.
        """
        return ChartStyle.model_validate(
            {**self.model_dump(), **patch.model_dump(exclude_unset=True)}
        )
