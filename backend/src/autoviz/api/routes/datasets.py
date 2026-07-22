"""Dataset routes (Week 3 — not yet implemented).

Thin adapters over `services.dataset`, identical behavior to MCP tools 1-6:

    POST   /datasets                      register_dataset(file_ref)
    POST   /datasets/upload               multipart CSV upload -> save under an
                                          approved data root -> register (the one
                                          route with no MCP equivalent; needed by
                                          the frontend file picker)
    GET    /datasets                      list_datasets()
    DELETE /datasets/{dataset_id}         unregister_dataset()
    GET    /datasets/{dataset_id}/schema  get_dataset_schema()
    GET    /datasets/{dataset_id}/profile get_dataset_profile()
    GET    /datasets/{dataset_id}/preview preview_dataset(limit)

Errors keep the services' structured `{error, hint?}` shape with an appropriate
HTTP status (404 unknown id, 400 bad file) — never a raised exception.
"""
