"""Export a Vega-Lite spec as a self-contained HTML file the user can open.

The spec is inlined as JSON and rendered with vega-embed from a CDN. Filenames
are slug-sanitized and always written inside EXPORT_DIR — a caller can never
escape it.
"""

import json
import re
import time
from pathlib import Path
from typing import Any

from autoviz.errors import FORBIDDEN_PATH, INVALID_SPEC, make_error
from autoviz.vega import CDN_SCRIPT_TAGS

# export.py sits at backend/src/autoviz/services/; parents[3] is backend/.
EXPORT_DIR = Path(__file__).resolve().parents[3] / "exports"

_SLUG_PATTERN = re.compile(r"[^a-z0-9_-]+")

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AutoViz chart</title>
{cdn_script_tags}
  <style>
    /* Specs size themselves from their container, so #chart needs a definite
       height here — without one the chart would render zero pixels tall. */
    html, body { height: 100%; margin: 0; }
    body { padding: 24px; box-sizing: border-box;
           font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
    #chart, #chart .vega-embed, #chart .vega-embed .chart-wrapper {
      width: 100%; height: 100%;
    }
  </style>
</head>
<body>
  <div id="chart"></div>
  <script>
    vegaEmbed("#chart", {spec_json}, {actions: false, tooltip: true});
  </script>
</body>
</html>
"""


def _slugify(filename: str) -> str:
    slug = _SLUG_PATTERN.sub("-", filename.lower()).strip("-")
    return slug or f"chart-{time.strftime('%Y%m%d-%H%M%S')}"


def export_chart(
    vega_lite_spec: dict[str, Any], filename: str | None = None
) -> dict[str, Any]:
    # Three shapes count as a renderable top level: a bare unit spec, a layered
    # one (direct labels, error bands, jitter overlays), and a faceted one, where
    # small multiples put the chart itself under `spec`.
    if not isinstance(vega_lite_spec, dict) or not (
        "mark" in vega_lite_spec or "layer" in vega_lite_spec or "facet" in vega_lite_spec
    ):
        return make_error(
            INVALID_SPEC,
            "vega_lite_spec must be a Vega-Lite spec dict (missing 'mark', 'layer' or 'facet')",
        )

    name = _slugify(filename or f"chart-{time.strftime('%Y%m%d-%H%M%S')}")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = (EXPORT_DIR / f"{name}.html").resolve()
    if not path.is_relative_to(EXPORT_DIR):
        return make_error(FORBIDDEN_PATH, "Export filename escapes the exports directory")

    # </script> inside JSON string values would terminate the inline script.
    spec_json = json.dumps(vega_lite_spec).replace("</", "<\\/")
    html = _HTML_TEMPLATE.replace("{cdn_script_tags}", CDN_SCRIPT_TAGS).replace(
        "{spec_json}", spec_json
    )
    path.write_text(html, encoding="utf-8")
    return {"path": str(path), "filename": path.name}
