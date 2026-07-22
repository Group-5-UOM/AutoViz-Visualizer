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

# export.py sits at backend/src/autoviz/services/; parents[3] is backend/.
EXPORT_DIR = Path(__file__).resolve().parents[3] / "exports"

_SLUG_PATTERN = re.compile(r"[^a-z0-9_-]+")

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AutoViz chart</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
</head>
<body>
  <div id="chart"></div>
  <script>
    vegaEmbed("#chart", {spec_json});
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
    if not isinstance(vega_lite_spec, dict) or "mark" not in vega_lite_spec:
        return {"error": "vega_lite_spec must be a Vega-Lite spec dict (missing 'mark')"}

    name = _slugify(filename or f"chart-{time.strftime('%Y%m%d-%H%M%S')}")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = (EXPORT_DIR / f"{name}.html").resolve()
    if not path.is_relative_to(EXPORT_DIR):
        return {"error": "Export filename escapes the exports directory"}

    # </script> inside JSON string values would terminate the inline script.
    spec_json = json.dumps(vega_lite_spec).replace("</", "<\\/")
    path.write_text(_HTML_TEMPLATE.replace("{spec_json}", spec_json), encoding="utf-8")
    return {"path": str(path), "filename": path.name}
