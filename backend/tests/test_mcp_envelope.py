"""The MCP protocol contract: isError signalling and published output schemas.

These assert on the real ``CallToolResult`` envelope, not on the service dicts
the other suites cover. That distinction is the whole point: AutoViz previously
returned failures as ordinary dicts with ``isError: false``, so a host that
branches on ``isError`` — to stop a chain, retry, or record a failure — could not
see them. Testing the service return value would not have caught that.
"""

import asyncio

import mcp.types as T
import pytest

from autoviz.mcp.server import PROFILES, mcp
from autoviz.services import dataset
from autoviz.services.registry import REGISTRY
from autoviz.services.charts import primary_layer


async def _call(name: str, **arguments):
    """Invoke a tool through the real request handler and return the result."""
    req = T.CallToolRequest(
        method="tools/call", params={"name": name, "arguments": arguments}
    )
    return (await mcp._mcp_server.request_handlers[T.CallToolRequest](req)).root


def call(name: str, **arguments):
    return asyncio.run(_call(name, **arguments))


@pytest.fixture
def iris_id():
    out = dataset.register_dataset("general-testing/iris.csv", REGISTRY)
    yield out["dataset_id"]
    REGISTRY.remove(out["dataset_id"])


@pytest.fixture
def titanic_id():
    out = dataset.register_dataset("general-testing/titanic.csv", REGISTRY)
    yield out["dataset_id"]
    REGISTRY.remove(out["dataset_id"])


def _plan(dataset_id: str) -> dict:
    return {
        "dataset_id": dataset_id,
        "intent": "comparison",
        "group_by": ["species"],
        "aggregations": [{"column": "sepal_length", "fn": "mean", "as": "avg_len"}],
    }


# --- isError: true — the tool could not fulfil its contract ------------------


def test_unknown_dataset_is_a_tool_error(iris_id):
    res = call("execute_analysis", dataset_id="ds_nope", analysis_plan=_plan(iris_id))
    assert res.isError is True
    # The code must survive into the message: it is the only channel available on
    # the failure path, and the host's LLM reads it to decide whether to retry.
    assert "UNKNOWN_DATASET" in res.content[0].text


def test_missing_file_is_a_tool_error():
    res = call("register_dataset", file_ref="definitely/not/here.csv")
    assert res.isError is True
    assert "FILE_ERROR" in res.content[0].text


def test_malformed_export_spec_is_a_tool_error():
    res = call("export_chart", vega_lite_spec={"not": "a spec"})
    assert res.isError is True
    assert "INVALID_SPEC" in res.content[0].text


def test_tool_error_message_carries_remediation(iris_id):
    res = call("execute_analysis", dataset_id="ds_nope", analysis_plan=_plan(iris_id))
    assert "Register the dataset first" in res.content[0].text


# --- isError: false — the tool worked and reported a negative result ---------


def test_invalid_plan_is_a_successful_call(iris_id):
    """The validator fulfilled its contract by rejecting the plan."""
    bad = {
        "dataset_id": iris_id,
        "intent": "comparison",
        "aggregations": [{"column": "species", "fn": "mean", "as": "x"}],
    }
    res = call("validate_analysis_plan", dataset_id=iris_id, analysis_plan=bad)
    assert res.isError is False
    assert res.structuredContent["valid"] is False
    assert res.structuredContent["error_code"] in ("TYPE_MISMATCH", "INVALID_PLAN")
    assert res.structuredContent["errors"]


def test_confirmation_required_is_a_successful_call(titanic_id):
    """A paused workflow is not a failure; the host must be able to branch on it."""
    plan = {
        "dataset_id": titanic_id,
        "intent": "comparison",
        "group_by": ["pclass"],
        "aggregations": [{"column": "fare", "fn": "mean", "as": "avg_fare"}],
        # 'deck' is ~77% null, well over the confirmation threshold.
        "preprocessing": [{"op": "drop_nulls", "columns": ["deck"]}],
    }
    res = call("run_analysis_pipeline", dataset_id=titanic_id, analysis_plan=plan)
    assert res.isError is False
    body = res.structuredContent
    assert body["status"] == "confirmation_required"
    assert body["confirmation"]["preprocessing_hash"]
    assert body["confirmation"]["impact"]["dropped"] > 0
    assert body["result"] is None  # nothing executed

    # And the hash round-trips: approving it lets the same call through.
    approved = call(
        "run_analysis_pipeline",
        dataset_id=titanic_id,
        analysis_plan=plan,
        approved_preprocessing_hash=body["confirmation"]["preprocessing_hash"],
    )
    assert approved.isError is False
    assert approved.structuredContent["status"] == "ok"


def test_unplottable_result_is_a_successful_refusal():
    """The recommender answered the question — nothing here is plottable."""
    res = call(
        "recommend_chart_type",
        result_schema=[{"name": "species", "type": "string"}],
        intent="comparison",
    )
    assert res.isError is False
    assert res.structuredContent["recommended"] is False
    assert res.structuredContent["rationale"]


def test_structurally_invalid_chart_is_a_successful_call():
    res = call(
        "generate_chart",
        result_table=[{"a": 1}],
        chart_spec={"type": "bar", "x": "missing_col", "y": "a"},
    )
    assert res.isError is False
    assert res.structuredContent["valid"] is False


# --- success ----------------------------------------------------------------


def test_pipeline_success_publishes_provenance(iris_id):
    res = call("run_analysis_pipeline", dataset_id=iris_id, analysis_plan=_plan(iris_id))
    assert res.isError is False
    body = res.structuredContent
    assert body["status"] == "ok"
    assert body["result"]["row_count"] == 3
    # The traceability claim: the exact SQL comes back with the numbers.
    assert body["result"]["provenance"]["sql"].lower().startswith("with")
    assert primary_layer(body["vega_lite_spec"])["mark"]


def test_register_returns_typed_structured_content():
    res = call("register_dataset", file_ref="general-testing/iris.csv")
    assert res.isError is False
    body = res.structuredContent
    assert isinstance(body["dataset_id"], str)
    assert body["row_count"] == 150
    assert body["column_count"] == 5
    REGISTRY.remove(body["dataset_id"])


# --- published schemas ------------------------------------------------------


def _schemas():
    return {t.name: t.outputSchema for t in asyncio.run(mcp.list_tools())}


def test_no_tool_publishes_a_vacuous_schema():
    """`dict[str, Any]` returns publish {"additionalProperties": true} — a schema
    that tells the host nothing. Guard against a refactor regressing to it."""
    for name, schema in _schemas().items():
        assert schema is not None, name
        assert schema.get("additionalProperties") is not True, name
        assert schema.get("properties"), name


def test_execute_analysis_schema_names_its_fields():
    schema = _schemas()["execute_analysis"]
    assert schema["additionalProperties"] is False
    assert "provenance" in schema["properties"]
    for field in ("result_table", "row_count", "execution_time_ms", "provenance"):
        assert field in schema["required"], field
    prov = schema["$defs"]["Provenance"]
    assert "sql" in prov["required"]


def test_pipeline_schema_declares_its_states():
    schema = _schemas()["run_analysis_pipeline"]
    states = schema["properties"]["status"]["enum"]
    assert set(states) == {"ok", "partial", "confirmation_required"}
    assert "confirmation" in schema["properties"]


def test_pipeline_output_is_not_wrapped(iris_id):
    """A top-level union return type would make FastMCP wrap structuredContent as
    {"result": {...}}, silently moving every field one level down for the host."""
    res = call("run_analysis_pipeline", dataset_id=iris_id, analysis_plan=_plan(iris_id))
    assert "status" in res.structuredContent
    assert set(res.structuredContent) != {"result"}


def test_tool_descriptions_stay_small():
    """PLAN_GUIDE lives in a resource, not in three tool descriptions. Inlining it
    again would put ~15.5k characters back on every session's tools/list."""
    tools = asyncio.run(mcp.list_tools())
    total = sum(len(t.description or "") for t in tools)
    assert total < 6000, f"tool descriptions grew to {total} chars"


def test_plan_guide_is_published_as_a_resource():
    uris = {str(r.uri) for r in asyncio.run(mcp.list_resources())}
    assert "autoviz://docs/analysis-plan-guide" in uris


# --- profiles ---------------------------------------------------------------


def test_advanced_profile_exposes_every_tool():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {fn.__name__ for fn, _ in PROFILES["advanced"]}
    assert len(names) == 14
