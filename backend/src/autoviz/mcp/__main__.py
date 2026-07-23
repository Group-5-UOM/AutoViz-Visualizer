"""Entrypoint: python -m autoviz.mcp"""

from autoviz.mcp.server import mcp
from autoviz.observability import configure_logging

configure_logging()  # stderr + rotating file; never stdout (reserved for JSON-RPC)
mcp.run()
