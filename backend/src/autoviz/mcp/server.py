"""AutoViz MCP server — typed tools, resources, and prompts over the shared service layer.

Each tool is a thin adapter (Docs/06 §3); business logic lives in
autoviz.services so FastAPI routes can reuse the exact same functions. Two
concerns are handled here and nowhere else:

* **Typing** — every tool declares a Pydantic return model (autoviz.mcp.results),
  so the host gets a real ``outputSchema`` instead of "some object".
* **Failure signalling** — terminal failures leave as ``isError: true`` via
  autoviz.mcp.envelope; negative-but-successful results (invalid plan, pending
  confirmation, chart-only failure) stay ordinary successful calls.

Tools are registered at the bottom rather than by decorator so the exposed
surface can be narrowed by profile. Run: python -m autoviz.mcp  (stdio transport).
"""

import functools
import json
import os
import threading
from typing import Any, Callable

import anyio
from mcp.server.fastmcp import Context, FastMCP

from autoviz.errors import INVALID_PLAN, NO_CHART_FIT, make_error
from autoviz.mcp.envelope import unwrap
from autoviz.mcp.results import (
    AnalyzeOutput,
    DataQualityOutput,
    DatasetProfileOutput,
    DatasetSchemaOutput,
    ExecuteAnalysisOutput,
    ExportChartOutput,
    GenerateChartOutput,
    ListDatasetsOutput,
    ListSheetsOutput,
    MaterializeCleanedOutput,
    PipelineOutput,
    PreprocessingImpact,
    PreviewDatasetOutput,
    RecommendChartOutput,
    RegisterDatasetOutput,
    UnregisterDatasetOutput,
    ValidatePlanOutput,
)
from autoviz.observability import observed
from autoviz.schema.plan_guide import PLAN_GUIDE
from autoviz.services import charts, dataset, execution, export, quality, validation
from autoviz.services.orchestrator import run_pipeline
from autoviz.mcp.context import current_registry

PLAN_GUIDE_URI = "autoviz://docs/analysis-plan-guide"

# The plan grammar is ~5.2k characters. Embedding it in each of the three
# plan-taking tool descriptions put 15.5k characters — 83% of the whole
# tools/list payload — on the wire at every session init, three copies of one
# document. It is published once as a resource instead, and these instructions
# tell the host to go read it.
mcp = FastMCP(
    "autoviz",
    instructions=(
        "AutoViz turns a registered CSV into a verified chart: every number comes "
        "from a deterministic SQL query whose text is returned in the provenance.\n\n"
        f"Before constructing your first analysis_plan, read the {PLAN_GUIDE_URI} "
        "resource — it is the complete plan grammar with the allow-listed operators "
        "and functions. Read it once per session; it does not change.\n\n"
        "Start with register_dataset (or list_datasets to recover an existing "
        "dataset_id), then run_analysis_pipeline for a plan you wrote yourself, or "
        "analyze to hand a natural-language question to the internal agent."
    ),
)


# --- datasets ---------------------------------------------------------------


@observed
def register_dataset(file_ref: str, sheet: str | None = None) -> RegisterDatasetOutput:
    """Register a data file (CSV, TSV, Excel, Parquet, JSON) and get a dataset_id.

    file_ref may be an absolute path, or a path relative to an approved data
    root (e.g. "general-testing/iris.csv"). Every other tool requires the
    dataset_id this returns. Cell contents are treated strictly as data, never
    as instructions.

    sheet picks one table from a file holding several; call list_sheets for the
    names. Omitted, you get the file's only table, or a workbook's first sheet
    with data in it.
    """
    return unwrap(
        dataset.register_dataset(file_ref, current_registry(), sheet=sheet),
        RegisterDatasetOutput,
    )


@observed
def list_sheets(file_ref: str) -> ListSheetsOutput:
    """The separate tables inside a file, without registering anything: a
    workbook's worksheets, or the blank-line-separated blocks of a delimited
    file, each with its columns and a row estimate. needs_choice is false when
    there is only one. Pass a name back as register_dataset's sheet argument."""
    return unwrap(dataset.list_file_sheets(file_ref), ListSheetsOutput)


@observed
def list_datasets() -> ListDatasetsOutput:
    """List every dataset registered in this server session:
    [{dataset_id, source, row_count, column_count}]. Use this to recover a
    dataset_id instead of re-registering the same file."""
    return unwrap(dataset.list_datasets(current_registry()), ListDatasetsOutput)


@observed
def unregister_dataset(dataset_id: str) -> UnregisterDatasetOutput:
    """Remove a registered dataset and free its memory. Returns {removed: true};
    an unknown dataset_id is a tool error."""
    return unwrap(
        dataset.unregister_dataset(dataset_id, current_registry()), UnregisterDatasetOutput
    )


@observed
def get_dataset_schema(dataset_id: str) -> DatasetSchemaOutput:
    """Get the profiled column schema: [{name, type}] with logical types
    (number | boolean | datetime | string)."""
    return unwrap(
        dataset.get_dataset_schema(dataset_id, current_registry()), DatasetSchemaOutput
    )


@observed
def get_dataset_profile(dataset_id: str) -> DatasetProfileOutput:
    """Get the dataset profile: null_counts, duplicate_count, per-column
    cardinality, and numeric summary_stats."""
    return unwrap(
        dataset.get_dataset_profile(dataset_id, current_registry()), DatasetProfileOutput
    )


@observed
def preview_dataset(dataset_id: str, limit: int = 10) -> PreviewDatasetOutput:
    """Preview the first rows of a registered dataset as sanitized records."""
    return unwrap(
        dataset.preview_dataset(dataset_id, limit, current_registry()), PreviewDatasetOutput
    )


# --- long-running work ------------------------------------------------------


async def _run_cancellable(
    ctx: Context,
    work: Callable[[Callable[[int, int, str], None], threading.Event], dict[str, Any]],
) -> dict[str, Any]:
    """Run a blocking pipeline in a worker thread, wired to the MCP request.

    Two things the host gets that a plain synchronous tool cannot give it:

    * **Progress.** The pipeline reports stage boundaries through a plain
      callback; ``anyio.from_thread.run`` hands each one back to the event loop
      as an MCP progress notification, so "Executing query — step 3 of 5"
      replaces an opaque spinner on a slow CSV.
    * **Cancellation.** When the host cancels the request, anyio cancels this
      await. ``abandon_on_cancel`` lets us return immediately, and setting the
      event interrupts the running DuckDB query rather than leaving it to burn
      CPU to completion with nobody waiting for the answer.
    """
    cancel_event = threading.Event()

    def on_progress(step: int, total: int, message: str) -> None:
        try:
            anyio.from_thread.run(ctx.report_progress, step, total, message)
        except Exception:
            pass  # progress is advisory; never fail the analysis over it

    try:
        return await anyio.to_thread.run_sync(
            functools.partial(work, on_progress, cancel_event),
            abandon_on_cancel=True,
        )
    except anyio.get_cancelled_exc_class():
        cancel_event.set()
        raise


# --- analysis ---------------------------------------------------------------

_VALIDATE_DESC = (
    "Validate an analysis_plan against the dataset's profiled schema and the closed "
    "operator/function allow-lists. Returns {valid, errors, repaired_plan?}. A plan "
    "that fails validation is a successful call with valid=false — read the errors, "
    "repair the plan, and call again. "
    f"See {PLAN_GUIDE_URI} for the plan structure."
)

_EXECUTE_DESC = (
    "Deterministically execute a validated analysis_plan via read-only DuckDB. Returns "
    "{result_table, row_count, execution_time_ms, provenance}; the provenance carries the "
    "exact SQL, so every number is traceable. Prefer run_analysis_pipeline unless you "
    "specifically want the numbers without a chart. A plan whose cleaning step would "
    "remove a large fraction of rows fails with CONFIRMATION_REQUIRED until you pass the "
    "returned confirmation.preprocessing_hash back as approved_preprocessing_hash — the "
    "same rule the pipeline applies, enforced here too. "
    f"See {PLAN_GUIDE_URI} for the plan structure."
)

_PIPELINE_DESC = (
    "Orchestrated validate -> execute -> recommend -> generate in one call — the preferred "
    "tool for going from a plan to a render-ready Vega-Lite chart. Returns status 'ok', or "
    "'partial' when the query succeeded but no chart could be built (the result is still "
    "returned), or 'confirmation_required' when the plan's cleaning step would drop a large "
    "fraction of rows — nothing executes until you call again passing that "
    "confirmation.preprocessing_hash as approved_preprocessing_hash. "
    f"See {PLAN_GUIDE_URI} for the plan structure."
)


@observed
def validate_analysis_plan(dataset_id: str, analysis_plan: dict[str, Any]) -> ValidatePlanOutput:
    return unwrap(
        validation.validate_analysis_plan(dataset_id, analysis_plan, current_registry()),
        ValidatePlanOutput,
    )


@observed
def execute_analysis(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    approved_preprocessing_hash: str | None = None,
) -> ExecuteAnalysisOutput:
    return unwrap(
        execution.execute_analysis(
            dataset_id,
            analysis_plan,
            current_registry(),
            approved_preprocessing_hash=approved_preprocessing_hash,
        ),
        ExecuteAnalysisOutput,
    )


_QUALITY_DESC = (
    "Inspect a dataset for data-quality problems and get back a cleaning proposal. "
    "Read-only: nothing is applied. Pass `columns` with just the columns your analysis "
    "needs — a problem in an unrelated column is not a reason to interrupt. Returns "
    "{issues, auto_apply, proposals}: `auto_apply` is a ready-to-use preprocessing block "
    "of semantics-preserving repairs (whitespace, blank-as-text, case variants) you can "
    "merge into a plan without asking; `proposals` are questions you MUST put to the user, "
    "because each one changes values or drops rows. Every proposal carries plain-language "
    "options with exact row counts and one marked `recommended` — offer that as the default."
)

_PREVIEW_PREPROCESSING_DESC = (
    "Measure what a preprocessing block would do before committing to it. Read-only: "
    "counts rows through the cleaning chain without running the analysis or touching the "
    "source. Returns {input_rows, output_rows, dropped, fraction, preprocessing} with the "
    "per-step effect. Use it to show a user the cost of a cleaning step in real numbers."
)


@observed
def analyze_data_quality(
    dataset_id: str, columns: list[str] | None = None
) -> DataQualityOutput:
    registry = current_registry()
    record = registry.get(dataset_id)
    if record is None:
        return unwrap(
            dataset.get_dataset_profile(dataset_id, registry), DataQualityOutput
        )  # reuse the UNKNOWN_DATASET error shape
    scope = set(columns) if columns else None
    return unwrap(quality.analyze_data_quality(record, scope), DataQualityOutput)


@observed
def preview_preprocessing(
    dataset_id: str, analysis_plan: dict[str, Any]
) -> PreprocessingImpact:
    registry = current_registry()
    record = registry.get(dataset_id)
    if record is None:
        return unwrap(
            dataset.get_dataset_profile(dataset_id, registry), PreprocessingImpact
        )  # reuse the UNKNOWN_DATASET error shape
    verdict = validation.validate_analysis_plan(dataset_id, analysis_plan, registry)
    if not verdict["valid"]:
        return unwrap(verdict, PreprocessingImpact)
    try:
        return unwrap(
            execution.preprocessing_impact(record, analysis_plan), PreprocessingImpact
        )
    except execution.PreprocessError as exc:
        return unwrap(make_error(INVALID_PLAN, str(exc)), PreprocessingImpact)
    except execution.GovernedFailure as exc:
        return unwrap(make_error(exc.code, str(exc)), PreprocessingImpact)


_MATERIALIZE_DESC = (
    "Apply a cleaning block once and keep the result as a new dataset. Use this only when the "
    "user wants to go on working from cleaned data — for a single chart, put the same "
    "preprocessing in the analysis_plan instead and nothing needs storing. The source dataset "
    "is never modified; the new one records parent_id and version_id. Subject to the same "
    "approval rule as execution: a block removing a large share of rows needs "
    "approved_preprocessing_hash. Returns the new dataset_id, which behaves like any other."
)


@observed
def materialize_cleaned_dataset(
    dataset_id: str,
    preprocessing: list[dict[str, Any]],
    approved_preprocessing_hash: str | None = None,
) -> MaterializeCleanedOutput:
    return unwrap(
        execution.materialize_cleaned_dataset(
            dataset_id,
            preprocessing,
            current_registry(),
            approved_preprocessing_hash=approved_preprocessing_hash,
        ),
        MaterializeCleanedOutput,
    )


_APPLY_RECIPE_DESC = (
    "Clean a new file the way an earlier one was cleaned. recipe_dataset_id is a dataset "
    "materialize_cleaned_dataset produced; its stored block is reapplied to target_dataset_id. "
    "Refuses if the new file lacks a column the recipe names. Approval never carries over — a "
    "removal that was small before re-gates here."
)


@observed
def apply_cleaning_recipe(
    recipe_dataset_id: str,
    target_dataset_id: str,
    approved_preprocessing_hash: str | None = None,
) -> MaterializeCleanedOutput:
    return unwrap(
        execution.apply_cleaning_recipe(
            recipe_dataset_id,
            target_dataset_id,
            current_registry(),
            approved_preprocessing_hash=approved_preprocessing_hash,
        ),
        MaterializeCleanedOutput,
    )


@observed
async def run_analysis_pipeline(
    dataset_id: str,
    analysis_plan: dict[str, Any],
    ctx: Context,
    approved_preprocessing_hash: str | None = None,
) -> PipelineOutput:
    return unwrap(
        await _run_cancellable(
            ctx,
            lambda on_progress, cancel_event, _r=current_registry(): run_pipeline(
                dataset_id,
                analysis_plan,
                _r,
                approved_preprocessing_hash=approved_preprocessing_hash,
                on_progress=on_progress,
                cancel_event=cancel_event,
            ),
        ),
        PipelineOutput,
    )


# --- charts -----------------------------------------------------------------


@observed
def recommend_chart_type(result_schema: list[dict[str, str]], intent: str) -> RecommendChartOutput:
    """Rule-based chart recommendation from the result schema
    ([{name, type}]) and analytical intent. Returns {recommended, chart_type, x,
    y, color?, rationale}. If no column can carry a chart the call still
    succeeds with recommended=false and a rationale."""
    out = charts.recommend_chart_type(result_schema, intent)
    # "Nothing here is plottable" is an answer, not a failure — the recommender
    # did its job. Translate it into the negative result rather than isError.
    if out.get("error_code") == NO_CHART_FIT:
        out = {"recommended": False, "rationale": out["error"]}
    return unwrap(out, RecommendChartOutput)


@observed
def generate_chart(
    result_table: list[dict[str, Any]], chart_spec: dict[str, Any]
) -> GenerateChartOutput:
    """Build and structurally validate a Vega-Lite spec from a result table and
    chart spec {type, x, y, color?}. Returns {vega_lite_spec, valid, warnings}."""
    return unwrap(charts.generate_chart(result_table, chart_spec), GenerateChartOutput)


@observed
def export_chart(vega_lite_spec: dict[str, Any], filename: str | None = None) -> ExportChartOutput:
    """Save a Vega-Lite spec as a self-contained HTML file in the server's
    exports directory (rendered with vega-embed; open it in any browser).
    Returns {path, filename}. filename is optional and slug-sanitized."""
    return unwrap(export.export_chart(vega_lite_spec, filename), ExportChartOutput)


# --- agent ------------------------------------------------------------------

_agent_service = None


def _get_agent():
    """Lazy: importing the server must not require LangGraph/an API key."""
    global _agent_service
    if _agent_service is None:
        from autoviz.agent.service import AgentService

        _agent_service = AgentService()
    return _agent_service


@observed
async def analyze(
    request: str,
    ctx: Context,
    dataset_id: str | None = None,
    file_ref: str | None = None,
    thread_id: str | None = None,
    chart_id: str | None = None,
) -> AnalyzeOutput:
    """One-shot agentic analysis: the internal LangGraph workflow interprets a
    natural-language request, generates and repairs a validated analysis plan,
    executes it deterministically, and returns charts plus a grounded summary.

    Pass dataset_id (from register_dataset) or file_ref (a CSV to register).
    Multi-part requests fan out into up to 6 charts. Reuse thread_id to refine a
    result ("same but only 2015"); pass the chart_id you mean, or the newest
    chart is the one refined. If the result
    is {status: "waiting_for_user"}, answer with answer_clarification — check
    pause_kind to see whether you are answering a clarifying question or
    approving a data-cleaning step, and pass back interrupt_id so the answer
    reaches the right one when pending_count is above 1.
    Requires a planner LLM key (GOOGLE_API_KEY); the granular tools remain the
    host-LLM path and need none.
    """
    await ctx.info(f"Planning analysis for: {request[:120]}")
    result = await anyio.to_thread.run_sync(
        functools.partial(
            _get_agent().run,
            request,
            dataset_id=dataset_id,
            file_ref=file_ref,
            thread_id=thread_id,
            chart_id=chart_id,
        ),
        abandon_on_cancel=True,
    )
    return unwrap(result, AnalyzeOutput)


@observed
def answer_clarification(
    thread_id: str, answer: str, interrupt_id: str | None = None
) -> AnalyzeOutput:
    """Resume an analyze() run that paused with {status: "waiting_for_user"},
    supplying the user's answer to its clarification, cleaning or confirmation
    question.

    Pass back the interrupt_id from the pause you are answering. When
    pending_count is above 1 the run is paused on several independent decisions:
    answer them one at a time, calling again with each new interrupt_id until
    the status is no longer "waiting_for_user"."""
    return unwrap(_get_agent().resume(thread_id, answer, interrupt_id), AnalyzeOutput)


# --- resources and prompts --------------------------------------------------


@mcp.resource(PLAN_GUIDE_URI)
def analysis_plan_guide() -> str:
    """The complete AnalysisPlan grammar: required fields, allow-listed operators
    and functions, preprocessing steps, and worked examples. Read once per
    session before building a plan."""
    return PLAN_GUIDE


@mcp.resource("autoviz://datasets")
def datasets_resource() -> str:
    """JSON list of every dataset registered in this server session."""
    return json.dumps(dataset.list_datasets(current_registry()), indent=2)


@mcp.resource("autoviz://datasets/{dataset_id}/schema")
def dataset_schema_resource(dataset_id: str) -> str:
    """JSON column schema ([{name, type}]) of a registered dataset."""
    return json.dumps(dataset.get_dataset_schema(dataset_id, current_registry()), indent=2)


@mcp.resource("autoviz://datasets/{dataset_id}/profile")
def dataset_profile_resource(dataset_id: str) -> str:
    """JSON profile (null_counts, duplicate_count, cardinality, summary_stats)
    of a registered dataset."""
    return json.dumps(dataset.get_dataset_profile(dataset_id, current_registry()), indent=2)


@mcp.prompt()
def analyze_dataset(file_ref: str, question: str) -> str:
    """Guided flow: register a CSV, understand it, answer a question with a chart."""
    return f"""Analyze the dataset at "{file_ref}" to answer: {question}

Follow this flow with the autoviz tools:
1. register_dataset("{file_ref}") — note the dataset_id.
2. get_dataset_schema and get_dataset_profile — learn column names, types, and nulls.
3. Read the {PLAN_GUIDE_URI} resource, then build an analysis_plan in that
   closed grammar.
4. run_analysis_pipeline(dataset_id, analysis_plan) — it validates, executes via
   DuckDB, recommends a chart if you omitted one, and returns a Vega-Lite spec.
   If the plan is rejected, read the errors, fix the plan, and retry.
5. Offer export_chart(vega_lite_spec) so the user gets an HTML file they can open.

Report the numbers from result_table (they come from a deterministic SQL query —
the provenance field shows the exact SQL) and describe the chart."""


# --- tool registration ------------------------------------------------------

# A host's LLM must choose between these tools on every turn, and overlapping
# levels of abstraction ("should I call execute_analysis, run_analysis_pipeline,
# or analyze?") make that choice noisier. The default profile exposes one
# coherent path; "advanced" adds the granular per-step tools for orchestration
# and testing. Set AUTOVIZ_MCP_PROFILE to switch.
_DEFAULT_TOOLS = [
    (register_dataset, None),
    # Ships with register_dataset in every profile, for the same reason
    # answer_clarification ships with analyze: register_dataset's `sheet`
    # argument is unusable without a way to learn the names, and a host that
    # cannot see a workbook's other sheets will silently analyse the wrong one.
    (list_sheets, None),
    (list_datasets, None),
    # In the default profile because a host that cannot see a dataset's problems
    # will plan around them badly, and this is the tool that makes the cleaning
    # decision explicit rather than guessed. Read-only, so it is safe everywhere.
    (analyze_data_quality, _QUALITY_DESC),
    (run_analysis_pipeline, _PIPELINE_DESC),
    # analyze and answer_clarification are one feature and must ship together: a
    # run that returns {status: "waiting_for_user"} can only be finished by the
    # resume tool, so exposing analyze without it strands the host on a pause it
    # was told to answer.
    (analyze, None),
    (answer_clarification, None),
    (export_chart, None),
]

_ADVANCED_ONLY_TOOLS = [
    (unregister_dataset, None),
    (get_dataset_schema, None),
    (get_dataset_profile, None),
    (preview_dataset, None),
    (preview_preprocessing, _PREVIEW_PREPROCESSING_DESC),
    (materialize_cleaned_dataset, _MATERIALIZE_DESC),
    (apply_cleaning_recipe, _APPLY_RECIPE_DESC),
    (validate_analysis_plan, _VALIDATE_DESC),
    (execute_analysis, _EXECUTE_DESC),
    (recommend_chart_type, None),
    (generate_chart, None),
]

# The surface offered to a *foreign* host over the network (`Docs/26 §4.4`).
#
# It is `default` minus `analyze`/`answer_clarification`, and the omission is the
# point. Those two run AutoViz's own LangGraph agent and its own planner LLM, so
# calling them from inside Gemini is Gemini asking AutoViz to ask Gemini —
# double the latency and cost, with the host's model reduced to a passthrough.
#
# Without them the division of labour is the one MCP exists for: the host's model
# plans, and AutoViz validates and computes deterministically. That extends the
# invariant from Docs/09 — *the LLM only plans, it never computes a number* —
# across the network to someone else's LLM, which is a stronger claim than the
# project could previously make.
_HOST_TOOLS = [
    (register_dataset, None),
    (list_sheets, None),
    (list_datasets, None),
    (get_dataset_schema, None),
    (get_dataset_profile, None),
    (preview_dataset, None),
    (analyze_data_quality, _QUALITY_DESC),
    (validate_analysis_plan, _VALIDATE_DESC),
    (execute_analysis, _EXECUTE_DESC),
    (recommend_chart_type, None),
    (generate_chart, None),
    (export_chart, None),
]

PROFILES = {
    "host": _HOST_TOOLS,
    "default": _DEFAULT_TOOLS,
    "advanced": _DEFAULT_TOOLS + _ADVANCED_ONLY_TOOLS,
}

# "advanced" is the default so an upgrade never silently removes a tool a host
# was already calling.
ACTIVE_PROFILE = os.getenv("AUTOVIZ_MCP_PROFILE", "advanced").strip().lower()
if ACTIVE_PROFILE not in PROFILES:
    ACTIVE_PROFILE = "advanced"

for _fn, _desc in PROFILES[ACTIVE_PROFILE]:
    mcp.add_tool(_fn, description=_desc)


if __name__ == "__main__":
    mcp.run()
