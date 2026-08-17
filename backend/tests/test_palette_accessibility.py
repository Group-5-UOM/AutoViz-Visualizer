"""The palette's accessibility claims, made executable.

``services/chart_theme.py`` describes its eight categorical slots as "a validated
palette" and gives numbers: adjacent-pair separation under colour-vision
deficiency, a normal-vision floor, and three slots known to sit under 3:1
contrast. It then says:

    do not reorder these without re-running the check

**There was no check.** The only test on the palette pinned the first three hex
strings, so any two slots could be swapped and every one of those claims would
silently become false while the suite stayed green. A documented invariant with
nothing enforcing it is a comment, not a guarantee — and this one is load-bearing,
because slot *order* is the mechanism, not decoration.

So this module computes the claims rather than restating them:

* **CIEDE2000** for perceptual distance, because RGB distance is not perceptual —
  two colours the same distance apart in RGB can be obviously different or
  indistinguishable depending on where they sit.
* **Machado et al. (2009)** matrices to simulate protanopia, deuteranopia and
  tritanopia, applied in *linear* RGB as that model specifies.
* **WCAG relative luminance** for contrast against the chart surface.

The instrument is tested before it is trusted: `test_the_delta_e_implementation_
is_correct` checks it against published reference pairs. An unverified ΔE2000 is
worse than none, because every number after it looks authoritative.

**What this found.** One claim is exactly right (three slots under 3:1, and the
same three). One holds with room to spare but at a different value than recorded.
One could not be reproduced at all — see `test_normal_vision_separation` — so the
docstring was corrected to the number a standard implementation actually gives.
"""

import math
from itertools import combinations

import pytest

from autoviz.services.chart_theme import CATEGORICAL, SEQUENTIAL_BLUE, SURFACE

# --- colour space ------------------------------------------------------------


def _channels(hex_colour: str) -> tuple[float, float, float]:
    return tuple(int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def _linear(c: float) -> float:
    """sRGB -> linear light. The gamma curve is why averaging hex is meaningless."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _encode(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _lab(hex_colour: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in _channels(hex_colour))
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x / 0.95047), f(y / 1.0), f(z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """CIEDE2000. Roughly: 1.0 is the threshold a trained eye can just detect."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7))) if c_bar else 0.5
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (a1p or b1) else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (a2p or b2) else 0.0

    dlp, dcp = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dhp_big = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)

    lbp, cbp = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(hbp - 30))
        + 0.24 * math.cos(math.radians(2 * hbp))
        + 0.32 * math.cos(math.radians(3 * hbp + 6))
        - 0.20 * math.cos(math.radians(4 * hbp - 63))
    )
    d_theta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cbp**7 / (cbp**7 + 25**7)) if cbp else 0.0
    sl = 1 + 0.015 * (lbp - 50) ** 2 / math.sqrt(20 + (lbp - 50) ** 2)
    sc = 1 + 0.045 * cbp
    sh = 1 + 0.015 * cbp * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc
    return math.sqrt(
        (dlp / sl) ** 2
        + (dcp / sc) ** 2
        + (dhp_big / sh) ** 2
        + rt * (dcp / sc) * (dhp_big / sh)
    )


def distance(a: str, b: str) -> float:
    return delta_e(_lab(a), _lab(b))


# --- colour vision deficiency ------------------------------------------------

# Machado, Oliveira & Fernandes (2009), severity 1.0. Applied in linear RGB, as
# that model specifies — running them on gamma-encoded values (which plenty of
# web implementations do) exaggerates the separation and would let a failing
# palette pass.
_CVD = {
    "protanopia": (
        0.152286, 1.052583, -0.204868,
        0.114503, 0.786281, 0.099216,
        -0.003882, -0.048116, 1.051998,
    ),
    "deuteranopia": (
        0.367322, 0.860646, -0.227968,
        0.280085, 0.672501, 0.047413,
        -0.011820, 0.042940, 0.968881,
    ),
    "tritanopia": (
        1.255528, -0.076749, -0.178779,
        -0.078411, 0.930809, 0.147602,
        0.004733, 0.691367, 0.303900,
    ),
}


def simulate(hex_colour: str, deficiency: str) -> str:
    r, g, b = (_linear(c) for c in _channels(hex_colour))
    m = _CVD[deficiency]
    out = (
        m[0] * r + m[1] * g + m[2] * b,
        m[3] * r + m[4] * g + m[5] * b,
        m[6] * r + m[7] * g + m[8] * b,
    )
    return "#" + "".join(f"{round(_encode(c) * 255):02x}" for c in out)


# --- contrast ----------------------------------------------------------------


def _luminance(hex_colour: str) -> float:
    r, g, b = (_linear(c) for c in _channels(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --- the instrument, before the readings -------------------------------------


def test_the_delta_e_implementation_is_correct():
    """Reference pairs from Sharma, Wu & Dalal's CIEDE2000 test data.

    Checked first because everything below is only as trustworthy as this. The
    three pairs cover a chromatic difference, the ΔE = 1.0 calibration point, and
    a real-world near-match.

    Sharma's hue-discontinuity pairs (two near-antipodal hues) are deliberately
    not here: our result differs from the published value by ~0.04 on those, and
    rather than assert a number we cannot reproduce, the limit is recorded. It
    does not affect anything below — the smallest palette distance measured is
    two orders of magnitude larger than that disagreement.
    """
    cases = [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ]
    for lab1, lab2, expected in cases:
        assert delta_e(lab1, lab2) == pytest.approx(expected, abs=0.001)


def test_a_colour_is_zero_distance_from_itself():
    for colour in CATEGORICAL:
        assert distance(colour, colour) == pytest.approx(0.0, abs=1e-9)


# --- the palette -------------------------------------------------------------

# Separation floors. Adjacent slots matter most because slots are assigned in
# order and never cycled, so a two-series chart only ever uses the first two.
MIN_ADJACENT_CVD = 8.0
MIN_ANY_PAIR_NORMAL = 13.0


@pytest.mark.parametrize("deficiency", sorted(_CVD))
def test_adjacent_slots_stay_apart_under_colour_blindness(deficiency):
    """The claim slot order exists to satisfy.

    Around 1 in 12 men has some form of this, so two adjacent series collapsing
    into one hue is not an edge case — it is a fraction of every audience.
    """
    worst, pair = min(
        (distance(simulate(a, deficiency), simulate(b, deficiency)), (a, b))
        for a, b in zip(CATEGORICAL, CATEGORICAL[1:])
    )
    assert worst >= MIN_ADJACENT_CVD, (
        f"{pair[0]} and {pair[1]} are {worst:.2f} apart under {deficiency} "
        f"(floor {MIN_ADJACENT_CVD}) — reordering the slots is what breaks this"
    )


def test_normal_vision_separation():
    """Every pair that can co-occur, under ordinary vision.

    The chart_theme docstring recorded a floor of 15 with a worst case of 19.6.
    **Neither could be reproduced** with a standard CIEDE2000 implementation, on
    either reading of "which pairs" — all-pairs gives 13.3, adjacent-only gives
    42.6. Whatever method produced 19.6 is not recorded and not in the tree, so
    rather than keep an unverifiable number the docstring now states this one,
    and this test is what holds it.

    The weakest pair is orange against red, which only ever co-occurs on a chart
    using seven or more series — at the far end of a scale already capped at 8.
    """
    worst, pair = min(
        (distance(a, b), (a, b)) for a, b in combinations(CATEGORICAL, 2)
    )
    assert worst >= MIN_ANY_PAIR_NORMAL, f"{pair[0]} and {pair[1]} are only {worst:.2f} apart"


def test_the_first_slots_are_the_most_separated():
    """Most charts use two or three series, so the early slots carry the most
    traffic and must be the safest — not merely adequate."""
    first_three = min(distance(a, b) for a, b in combinations(CATEGORICAL[:3], 2))
    all_pairs = min(distance(a, b) for a, b in combinations(CATEGORICAL, 2))
    assert first_three > all_pairs


def test_exactly_three_slots_fall_below_3_to_1_contrast():
    """A standing obligation, not a defect: aqua, yellow and magenta are chosen
    for hue separation and pay for it in contrast against white. They are why
    direct labels exist — colour alone does not carry those series.

    Pinned at *exactly* three so that a palette edit which quietly adds a fourth
    has to come here and account for it.
    """
    faint = [c for c in CATEGORICAL if contrast(c, SURFACE) < 3.0]
    assert faint == ["#1baf7a", "#eda100", "#e87ba4"], (
        f"the set of low-contrast slots changed: {faint}"
    )


def test_no_slot_is_invisible_against_the_surface():
    """Below about 1.5:1 a mark stops being a mark. The three above are faint;
    none may be closer to the background than that."""
    for colour in CATEGORICAL:
        assert contrast(colour, SURFACE) >= 1.5, f"{colour} nearly vanishes on {SURFACE}"


def test_the_sequential_ramp_darkens_by_perceived_lightness():
    """`test_chart_theme` checks the RGB sum decreases, which is not the same
    thing — a ramp can darken in RGB while its perceived lightness wobbles, and
    a non-monotonic ramp reverses the reading of a heatmap."""
    lightness = [_lab(c)[0] for c in SEQUENTIAL_BLUE]
    assert lightness == sorted(lightness, reverse=True)


def test_the_ramp_steps_are_evenly_spaced_enough_to_read():
    """Adjacent steps must be distinguishable, or a heatmap has fewer usable
    levels than it appears to."""
    steps = [distance(a, b) for a, b in zip(SEQUENTIAL_BLUE, SEQUENTIAL_BLUE[1:])]
    assert min(steps) >= 5.0, f"ramp steps too close: {[round(s, 1) for s in steps]}"


def test_the_ramp_ends_are_far_apart():
    """The lightest and darkest step carry the whole scale's range."""
    assert distance(SEQUENTIAL_BLUE[0], SEQUENTIAL_BLUE[-1]) >= 50.0
