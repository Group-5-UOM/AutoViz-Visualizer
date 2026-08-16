"""Two users, two MCP sessions, one process — and no way to see across.

This is the acceptance gate for serving MCP over HTTP (`Docs/26 §3`). Over stdio
the process *is* the user, so every tool reading the global ``REGISTRY`` was
correct. Over HTTP that same code would let **any caller read any dataset any
other caller had touched**, because the registry is a process-wide cache and
`dataset_id`s are not secrets.

The tests below are written against the MCP tool functions themselves rather
than against `ScopedRegistry` in isolation, because the property that matters is
"the tool refuses", not "the wrapper has a method". A future tool that forgets to
call `current_registry()` must fail here.
"""

import json

import pandas as pd
import pytest

from mcp.server.fastmcp.exceptions import ToolError

from autoviz.core.database import get_sessionmaker
from autoviz.mcp import server
from autoviz.mcp.context import McpCaller, ScopedRegistry, caller_scope, current_registry
from autoviz.services import dataset as dataset_svc
from autoviz.services.registry import REGISTRY
from autoviz.storage import repository


@pytest.fixture()
def two_users(api_db):
    """Two real users in the throwaway database."""
    session = get_sessionmaker()()
    try:
        a = repository.create_user(session, "alice@example.com", "x")
        b = repository.create_user(session, "bob@example.com", "x")
        return a.id, b.id
    finally:
        session.close()


def _register_frame(user_id: str, label: str) -> str:
    """Register a small frame as `user_id` through the scoped registry."""
    frame = pd.DataFrame({"k": [label, label], "v": [1.0, 2.0]})
    with caller_scope(McpCaller(user_id=user_id)):
        registry = current_registry()
        record = dataset_svc.build_record(frame, f"{label}.csv", registry)
        registry.add(record)
        return record.dataset_id


# --- the gate ----------------------------------------------------------------


def test_a_user_cannot_read_another_users_dataset(two_users):
    alice, bob = two_users
    bob_ds = _register_frame(bob, "bob-secret")

    # Surfaces as the ordinary unknown-dataset failure: Alice learns nothing
    # about whether the id exists, only that it is not hers to read.
    with caller_scope(McpCaller(user_id=alice)):
        with pytest.raises(ToolError, match="[Uu]nknown dataset"):
            server.get_dataset_schema(bob_ds)


def test_a_user_cannot_preview_another_users_dataset(two_users):
    alice, bob = two_users
    bob_ds = _register_frame(bob, "bob-secret")

    with caller_scope(McpCaller(user_id=alice)):
        with pytest.raises(ToolError):
            server.preview_dataset(bob_ds)


def test_list_datasets_shows_only_your_own(two_users):
    alice, bob = two_users
    alice_ds = _register_frame(alice, "alice-one")
    bob_ds = _register_frame(bob, "bob-one")

    with caller_scope(McpCaller(user_id=alice)):
        listed = server.list_datasets()
    ids = {d.dataset_id for d in listed.datasets}

    assert alice_ds in ids
    assert bob_ds not in ids, "another user's dataset was enumerated"


def test_a_user_cannot_query_another_users_dataset(two_users):
    """The one that actually moves data — execution must be gated too."""
    alice, bob = two_users
    bob_ds = _register_frame(bob, "bob-secret")
    plan = {
        "dataset_id": bob_ds,
        "intent": "comparison",
        "group_by": ["k"],
        "aggregations": [{"column": "v", "fn": "sum", "as": "total"}],
    }

    with caller_scope(McpCaller(user_id=alice)):
        with pytest.raises(ToolError):
            server.execute_analysis(bob_ds, plan)


def test_a_user_cannot_delete_another_users_dataset(two_users):
    alice, bob = two_users
    bob_ds = _register_frame(bob, "bob-secret")

    with caller_scope(McpCaller(user_id=alice)):
        with pytest.raises(ToolError):
            server.unregister_dataset(bob_ds)

    # Still Bob's, still readable by Bob.
    with caller_scope(McpCaller(user_id=bob)):
        assert server.get_dataset_schema(bob_ds).columns


def test_the_owner_can_still_do_all_of_it(two_users):
    """The gate must not be a wall — the whole flow works for the owner."""
    alice, _bob = two_users
    ds = _register_frame(alice, "alice-one")

    with caller_scope(McpCaller(user_id=alice)):
        assert server.get_dataset_schema(ds).columns
        assert server.preview_dataset(ds).rows
        out = server.execute_analysis(
            ds,
            {
                "dataset_id": ds,
                "intent": "comparison",
                "group_by": ["k"],
                "aggregations": [{"column": "v", "fn": "sum", "as": "total"}],
            },
        )
    assert out.result_table[0]["total"] == 3.0


def test_resources_are_scoped_too(two_users):
    """`autoviz://datasets` is a second way to enumerate, and needs the same gate."""
    alice, bob = two_users
    bob_ds = _register_frame(bob, "bob-one")

    with caller_scope(McpCaller(user_id=alice)):
        listed = json.loads(server.datasets_resource())

    assert bob_ds not in {d["dataset_id"] for d in listed["datasets"]}


# --- the unscoped path must be untouched -------------------------------------


def test_no_caller_means_the_global_registry(registry):
    """stdio behaviour is the reason this seam exists rather than a rewrite."""
    assert current_registry() is REGISTRY


def test_scoped_registry_shares_the_process_cache(two_users):
    """Scoping must not duplicate frames — the LRU and memory budget stay global."""
    alice, _ = two_users
    ds = _register_frame(alice, "alice-one")
    assert REGISTRY.get(ds) is ScopedRegistry(alice).get(ds)


def test_an_unattributed_dataset_is_invisible_to_a_scoped_caller(two_users, registry):
    """Fail closed: no ownership row means nobody remote can read it.

    A dataset registered by a local stdio session has no owner. Treating that as
    "unowned, therefore public" would leak it to every HTTP caller in the process.
    """
    alice, _ = two_users
    orphan = dataset_svc.build_record(
        pd.DataFrame({"a": [1]}), "orphan.csv", REGISTRY
    )
    REGISTRY.add(orphan)
    try:
        assert ScopedRegistry(alice).get(orphan.dataset_id) is None
    finally:
        REGISTRY.remove(orphan.dataset_id)
