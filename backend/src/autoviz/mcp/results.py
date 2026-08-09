"""Typed output models for the MCP tool surface.

Without these every tool publishes ``{"type": "object", "additionalProperties":
true}`` — a schema that is technically valid and practically useless: the host
learns nothing about ``dataset_id``, ``provenance.sql``, ``vega_lite_spec`` or
``preprocessing_hash``, so it must hand the whole payload to an LLM instead of
branching on it. FastMCP derives ``outputSchema`` from these annotations and
validates every return against them, so a service that stops emitting a field
fails loudly here rather than silently degrading the host contract.

Two deliberate constraints:

* **Field names mirror the services exactly** (``result_table``, not ``rows``;
  ``sql`` nested inside ``provenance``). The same dicts are returned verbatim by
  the FastAPI routes (autoviz.api.schemas), so renaming here would split the two
  surfaces apart for no gain.
* **No top-level unions.** A bare ``A | B`` return annotation makes FastMCP set
  ``wrap_output``, and ``structuredContent`` arrives as ``{"result": {...}}`` —
  the host would read ``structuredContent.result.status``. Multi-state tools use
  one flat model with a ``status`` discriminator instead, which also matches the
  shape run_pipeline already returns.

Terminal failures never reach these models; they leave as ``isError: true`` via
autoviz.mcp.envelope.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# Free-form payloads stay dict[str, Any] on purpose: Vega-Lite specs, DuckDB
# summary stats and preprocessing reports are open-ended, and pinning them would
# make the schema lie. Everything with a fixed shape is modelled.


class _Strict(BaseModel):
    """Fixed-shape model: extra keys are a contract violation, not a warning.

    ``extra="forbid"`` is what emits ``additionalProperties: false`` into the
    published schema. It couples the model to its service — a service that grows
    a field must grow the model in the same change — which is the intent.
    """

    model_config = ConfigDict(extra="forbid")


# --- datasets ---------------------------------------------------------------


class ColumnSchema(_Strict):
    name: str
    type: str


class DatasetSummary(_Strict):
    dataset_id: str
    source: str
    row_count: int
    column_count: int


class MaterializeCleanedOutput(_Strict):
    """A cleaned copy promoted to a dataset of its own.

    ``dataset_id`` is a normal dataset from here on — previewable, chartable, and
    usable as the source of further analyses. ``parent_id`` and ``version_id``
    record where it came from; the parent is unchanged.
    """

    dataset_id: str
    parent_id: str
    version_id: str
    row_count: int
    column_count: int
    input_rows: int
    output_rows: int
    preprocessing: list[dict[str, Any]] = []
    # Set only by apply_cleaning_recipe: the dataset whose stored cleaning block
    # was reused. Distinct from parent_id, which is where these *rows* came from.
    recipe_from: str | None = None


class RegisterDatasetOutput(_Strict):
    dataset_id: str
    row_count: int
    column_count: int
    # How the file had to be read (services/ingest.py): encoding, delimiter, which
    # line the header sat on, and an `assumptions` list naming the choices that
    # were guesses. Present on the tool that does the reading so a host learns of
    # a mis-sniffed file at upload, not from a chart that looks odd later.
    ingest: dict[str, Any] = {}


class ListDatasetsOutput(_Strict):
    datasets: list[DatasetSummary]


class UnregisterDatasetOutput(_Strict):
    removed: bool
    dataset_id: str


class DatasetSchemaOutput(_Strict):
    columns: list[ColumnSchema]


class DatasetProfileOutput(_Strict):
    null_counts: dict[str, int]
    null_percentage: dict[str, float]
    unusable_columns: list[str]
    duplicate_count: int
    cardinality: dict[str, int]
    summary_stats: dict[str, dict[str, Any]]
    sample_values: dict[str, list[Any]]
    categorical_numeric: list[str]


class PreviewDatasetOutput(_Strict):
    rows: list[dict[str, Any]]


# --- validation -------------------------------------------------------------


class ValidatePlanOutput(_Strict):
    """A rejected plan is a *successful* validation call — isError stays false.

    The validator fulfilled its contract by determining the plan is invalid, so
    the host (or its LLM) can read ``errors`` and repair the plan rather than
    treating the tool as broken.
    """

    valid: bool
    errors: list[str] = []
    error_code: str | None = None
    repaired_plan: dict[str, Any] | None = None


# --- execution --------------------------------------------------------------


class Provenance(_Strict):
    """Everything needed to re-derive the numbers, including the exact SQL."""

    dataset_id: str
    source: str
    columns_used: list[str]
    filters: list[dict[str, Any]]
    aggregations: list[dict[str, Any]]
    chart_type: str | None = None
    preprocessing: list[dict[str, Any]] = []
    preprocessing_sql: list[str] = []
    # column -> rows the aggregate silently skipped, so the exclusion is stated
    # rather than hidden. Measured before cleaning, so imputing cannot erase it.
    # Empty when no null-skipping aggregate ran.
    implicit_null_exclusions: dict[str, int] = {}
    # Imputations big enough to move the answer: filling keeps every row, so it
    # never trips the row gate, but a mean over mostly-substituted values needs
    # to say so. Empty when nothing was imputed above the notice threshold.
    imputation_notices: list[dict[str, Any]] = []
    # The disclosure channel: the same cleaning facts as the fields above, written
    # as finished sentences with a severity saying how loudly to say each one.
    # Whoever composes the reply relays these rather than re-deriving them, so a
    # disclosure cannot be softened or dropped in paraphrase. See services/notices.py.
    notices: list[dict[str, Any]] = []
    # Logical id of the cleaned view these numbers came from — reproducible from
    # (source, preprocessing) without materialising a frame.
    preprocessing_version: str | None = None
    # The cleaning account in one place: columns inspected, per-step effect,
    # before/after row counts, whether a person approved it, and the parent
    # dataset when the source was itself a cleaned copy.
    cleaning: dict[str, Any] = {}
    sql: str


class ExecuteAnalysisOutput(_Strict):
    result_table: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float
    # Cleaning-stage row accounting, before analysis filters and limit.
    input_rows: int
    output_rows: int
    preprocessing: list[dict[str, Any]] = []
    provenance: Provenance


# --- charts -----------------------------------------------------------------


class RecommendChartOutput(_Strict):
    """A recommendation, or a reasoned refusal.

    ``recommended: false`` is a successful call, not a failure: the recommender
    inspected the result schema and correctly determined that nothing plottable
    is there. ``rationale`` says why, so the caller can aggregate a numeric
    column and ask again — the same contract as validate_analysis_plan
    returning ``valid: false``.
    """

    recommended: bool = True
    chart_type: str | None = None
    x: str | None = None
    y: str | None = None  # histogram has no y column
    color: str | None = None
    rationale: str


class GenerateChartOutput(_Strict):
    """``valid: false`` with a null spec is a successful call — the builder
    checked the spec against the result table and reports why it does not fit,
    in ``warnings``."""

    vega_lite_spec: dict[str, Any] | None = None
    valid: bool
    warnings: list[str] = []
    # Advisories about how the chart must be read — a log-scaled axis, or a
    # linear one dominated by a single value. Empty for an unremarkable chart.
    notices: list[dict[str, Any]] = []


class ExportChartOutput(_Strict):
    path: str
    filename: str


# --- pipeline ---------------------------------------------------------------


class PreprocessingImpact(_Strict):
    input_rows: int
    output_rows: int
    dropped: int
    fraction: float
    preprocessing: list[dict[str, Any]] = []


# --- data quality -------------------------------------------------------------


class QualityIssueOutput(_Strict):
    kind: str
    column: str | None = None
    affected: int
    fraction: float
    detail: dict[str, Any] = {}


class CleaningOptionOutput(_Strict):
    """One answer, phrased for someone who does not know the technique.

    ``label``/``detail`` are the offer; ``technique`` is the jargon, kept apart so
    a host can put it behind a disclosure rather than lead with it.
    """

    label: str
    detail: str
    technique: str
    recommended: bool = False


class CleaningProposalOutput(_Strict):
    slot: str
    question: str
    options: list[CleaningOptionOutput]
    issue: QualityIssueOutput


class DataQualityOutput(_Strict):
    """What is wrong, what can be fixed silently, and what needs a decision.

    ``auto_apply`` is a preprocessing block of semantics-preserving repairs, ready
    to merge into a plan. ``proposals`` are questions — every one of them alters
    values or row membership, so none may be applied without the user choosing.
    """

    row_count: int
    columns_inspected: list[str]
    issues: list[QualityIssueOutput] = []
    auto_apply: list[dict[str, Any]] = []
    proposals: list[CleaningProposalOutput] = []


class ConfirmationRequired(_Strict):
    question: str
    options: list[str]
    impact: PreprocessingImpact
    preprocessing_hash: str


class PipelineOutput(_Strict):
    """One flat model over the three non-terminal pipeline outcomes.

    ``ok``                    — result, chart_spec and vega_lite_spec are present.
    ``partial``               — the query succeeded and ``result`` is populated,
                                but the chart step failed. Emphatically not a
                                tool failure: the numbers are valid and traceable,
                                and the agent's own routing treats it as a chart
                                fallback rather than an error.
    ``confirmation_required`` — nothing ran; the caller must approve the cleaning
                                step by passing ``confirmation.preprocessing_hash``
                                back as ``approved_preprocessing_hash``.
    """

    status: Literal["ok", "partial", "confirmation_required"]
    result: ExecuteAnalysisOutput | None = None
    chart_spec: dict[str, Any] | None = None
    recommendation: RecommendChartOutput | None = None
    vega_lite_spec: dict[str, Any] | None = None
    warnings: list[str] = []
    # Both halves of the disclosure, merged: what cleaning did to the numbers and
    # what the chart had to do to make them legible. Pre-phrased with a severity —
    # relay these rather than re-deriving them. See services/notices.py.
    notices: list[dict[str, Any]] = []
    confirmation: ConfirmationRequired | None = None
    # Set on "partial" only: which chart step failed, and why.
    failed_step: str | None = None
    error_code: str | None = None
    errors: list[str] = []


# --- agent ------------------------------------------------------------------


class ChartResult(_Strict):
    task: str
    # Stable identity for this chart across the thread. A refinement returns the
    # id of the chart it changed, so a host can update that chart in place rather
    # than showing a near-duplicate beside it.
    chart_id: str | None = None
    status: Literal["ok", "partial", "error"]
    plan: dict[str, Any] | None = None
    attempts: int = 0
    result: ExecuteAnalysisOutput | None = None
    chart_spec: dict[str, Any] | None = None
    vega_lite_spec: dict[str, Any] | None = None
    warnings: list[str] = []
    # What the user must be told about how the data was cleaned or how the chart
    # has to be read — pre-written sentences with a severity. See
    # services/notices.py; a "disclosed" one is owed to the user every time.
    notices: list[dict[str, Any]] = []
    errors: list[str] = []


class AnalyzeOutput(_Strict):
    """The agent workflow's two non-terminal outcomes.

    A run that failed outright leaves as isError: true, so ``completed`` here
    means at least one chart is usable. ``waiting_for_user`` covers all three
    pause kinds; read ``pause_kind`` to tell a clarification question apart from
    a cleaning choice or a preprocessing confirmation, and answer any of them
    with ``answer_clarification``.

    Parallel workers can pause on several independent decisions at once. Only
    one is presented at a time: ``pending_count`` is how many are queued and
    ``interrupt_id`` names this one, so the answer lands where it was asked.
    """

    status: Literal["completed", "waiting_for_user"]
    thread_id: str
    answer: str | None = None
    charts: list[ChartResult] = []
    # waiting_for_user only.
    question: str | None = None
    # Plain strings for clarification/confirmation; cleaning choices carry their
    # row counts and recommendation on each option.
    options: list[str] | list[CleaningOptionOutput] = []
    pause_kind: Literal["clarification", "cleaning_choice", "confirmation"] | None = None
    preprocessing_hash: str | None = None
    impact: PreprocessingImpact | None = None
    # cleaning_choice only: which finding is being decided.
    slot: str | None = None
    issue: QualityIssueOutput | None = None
    # Pass interrupt_id back to answer_clarification; call again while
    # pending_count stays above 1.
    interrupt_id: str | None = None
    pending_count: int = 0
    # Set when the answered decision was already resolved: nothing was consumed
    # and the question below is what is actually pending.
    stale_answer: bool = False
