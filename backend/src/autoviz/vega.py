"""The Vega major versions AutoViz targets (Docs/13 §2.1).

These used to be written out in five places — the `$schema` stamp, the export
HTML template, the agent playground, the frontend mock specs and package.json —
and they drifted: specs were stamped v5 while the app rendered them through
Vega-Lite 6, so a chart could render differently in the app than in its own
exported HTML. One definition, one place to bump.

`tests/test_vega_version.py` asserts these still match `frontend/package.json`,
so bumping the npm dependency without bumping here fails the suite.
"""

VEGA_MAJOR = 6
VEGA_LITE_MAJOR = 6
VEGA_EMBED_MAJOR = 7

#: Stamped onto every generated spec.
VEGA_LITE_SCHEMA = f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_MAJOR}.json"

#: Script tags for standalone HTML (exports, playground) that load from a CDN.
#: Vega 6 is an ESM-only *package*, but all three still publish a UMD browser
#: bundle via their `jsdelivr` field, so plain script tags remain correct.
CDN_SCRIPT_TAGS = "\n".join(
    f'  <script src="https://cdn.jsdelivr.net/npm/{pkg}@{major}"></script>'
    for pkg, major in (
        ("vega", VEGA_MAJOR),
        ("vega-lite", VEGA_LITE_MAJOR),
        ("vega-embed", VEGA_EMBED_MAJOR),
    )
)
