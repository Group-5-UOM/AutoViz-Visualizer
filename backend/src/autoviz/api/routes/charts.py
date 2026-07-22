"""Chart routes (Week 3 — not yet implemented).

Thin adapters over `services.charts` / `services.export`, identical behavior to
MCP tools 9, 10, 12:

    POST /charts/recommend   recommend_chart_type(result_schema, intent)
    POST /charts/generate    generate_chart(result_table, chart_spec)
    POST /charts/export      export_chart(vega_lite_spec, filename?)
                             -> may later return the HTML file directly
                             (FileResponse) instead of a server path, so the
                             frontend can offer a download.
"""
