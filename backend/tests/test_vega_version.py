"""The backend's Vega target must match what the frontend actually loads.

These drifted once already (Docs/13 §2.1): specs were stamped `vega-lite/v5.json`
and exports pulled vega@5 from CDN while the app rendered through Vega-Lite 6, so
the same chart could render differently in the app than in its own export. The
failure was silent — Vega-Lite does not validate the `$schema` it is handed.
"""

import json
import pathlib
import re

from autoviz.services.charts import generate_chart
from autoviz.services.export import _HTML_TEMPLATE
from autoviz.vega import (
    CDN_SCRIPT_TAGS,
    VEGA_EMBED_MAJOR,
    VEGA_LITE_MAJOR,
    VEGA_LITE_SCHEMA,
    VEGA_MAJOR,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _npm_major(dep: str) -> int:
    package_json = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    pinned = package_json["dependencies"][dep]
    match = re.search(r"(\d+)", pinned)
    assert match, f"could not read a major version out of {dep}@{pinned}"
    return int(match.group(1))


def test_backend_targets_the_vega_the_frontend_installs():
    assert _npm_major("vega") == VEGA_MAJOR
    assert _npm_major("vega-lite") == VEGA_LITE_MAJOR
    assert _npm_major("vega-embed") == VEGA_EMBED_MAJOR


def test_generated_specs_are_stamped_with_that_schema():
    out = generate_chart([{"a": "x", "b": 1.0}], {"type": "bar", "x": "a", "y": "b"})
    assert out["vega_lite_spec"]["$schema"] == VEGA_LITE_SCHEMA
    assert f"/v{VEGA_LITE_MAJOR}.json" in VEGA_LITE_SCHEMA


def test_export_template_loads_the_same_majors():
    tags = CDN_SCRIPT_TAGS
    assert f"vega@{VEGA_MAJOR}" in tags
    assert f"vega-lite@{VEGA_LITE_MAJOR}" in tags
    assert f"vega-embed@{VEGA_EMBED_MAJOR}" in tags
    # The template must actually interpolate them rather than hardcoding a copy.
    assert "{cdn_script_tags}" in _HTML_TEMPLATE
    assert "cdn.jsdelivr.net" not in _HTML_TEMPLATE


def test_no_source_file_hardcodes_a_vega_version():
    # The whole point of autoviz.vega is that the version lives in one place.
    pattern = re.compile(r"vega(?:-lite|-embed)?@\d|schema/vega-lite/v\d")
    offenders = []
    for path in (REPO_ROOT / "backend" / "src").rglob("*.py"):
        if path.name == "vega.py":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"hardcoded Vega version in: {offenders}"
