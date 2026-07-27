"""The automated cleaning pass inside the analysis worker.

This is the path a user who has never heard of imputation actually travels, so
the tests are about *when the tool speaks up* as much as what it does: safe
repairs happen silently, a misleading null gets one plain-language question, and
an explicit instruction is never second-guessed.
"""

from autoviz.agent.service import AgentService
from autoviz.services import dataset
from tests.test_agent import FakePlanner


def _register(registry, tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return dataset.register_dataset(p.as_posix(), registry)["dataset_id"]


# A grouping column with case variants AND padding, plus a null group key.
MESSY = (
    "dept,salary\n"
    "Eng ,100\n"
    "eng,200\n"
    "ENG,300\n"
    "Sales,400\n"
    " sales,500\n"
    ",600\n"
)


def _group_plan():
    return {
        "intent": "comparison",
        "group_by": ["dept"],
        "aggregations": [{"column": "salary", "fn": "mean", "as": "avg_salary"}],
    }


# --- safe repairs happen without asking ----------------------------------------


def test_safe_repairs_are_applied_silently(registry, tmp_path):
    """Whitespace and case variants would split one department into five bars.

    Fixing that changes no value's meaning, so it happens without a question —
    the run completes in one call.
    """
    ds = _register(registry, tmp_path, "messy.csv", MESSY)
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)

    # It pauses once — but for the null group key, not for the spelling.
    assert out["status"] == "waiting_for_user"
    assert out["pause_kind"] == "cleaning_choice"
    assert out["slot"] == "missing:dept"

    resumed = agent.resume(out["thread_id"], "Exclude those rows")
    assert resumed["status"] == "completed", resumed
    table = resumed["charts"][0]["result"]["result_table"]
    # Five spellings collapsed to two real departments, and the null group is gone.
    assert {r["dept"] for r in table} == {"eng", "sales"}


def test_applied_repairs_are_recorded_in_provenance(registry, tmp_path):
    ds = _register(registry, tmp_path, "prov.csv", MESSY)
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)
    resumed = agent.resume(out["thread_id"], "Exclude those rows")

    steps = resumed["charts"][0]["result"]["provenance"]["preprocessing"]
    operations = [s["operation"] for s in steps]
    assert "trim_whitespace" in operations and "normalize_case" in operations
    # The repairs run before the row-removal the user chose.
    assert operations.index("trim_whitespace") < operations.index("drop_nulls")


# --- when the tool speaks up ---------------------------------------------------


def test_a_null_dimension_is_asked_about(registry, tmp_path):
    """A null grouping key becomes a spurious category on the chart, so it is a
    real decision rather than a detail."""
    ds = _register(registry, tmp_path, "nulldim.csv", "dept,salary\neng,100\n,200\nsales,300\n")
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)
    assert out["pause_kind"] == "cleaning_choice"
    assert out["issue"]["kind"] == "missing_values"
    assert out["issue"]["column"] == "dept"


def test_a_null_measure_is_not_asked_about(registry, tmp_path):
    """Aggregates already skip nulls and the exclusion is stated in provenance —
    the default is correct and disclosed, so a question would add only friction."""
    ds = _register(registry, tmp_path, "nullmeasure.csv", "dept,salary\neng,100\neng,\nsales,300\n")
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)

    assert out["status"] == "completed", out
    prov = out["charts"][0]["result"]["provenance"]
    assert prov["implicit_null_exclusions"]["salary"] == 1  # stated, not hidden


def test_a_clean_dataset_asks_nothing(registry, iris_id):
    agent = AgentService(
        planner=FakePlanner(
            plans=[
                {
                    "intent": "comparison",
                    "group_by": ["species"],
                    "aggregations": [
                        {"column": "sepal_length", "fn": "mean", "as": "avg_sepal_length"}
                    ],
                }
            ]
        ),
        registry=registry,
    )
    out = agent.run("average sepal length by species", dataset_id=iris_id)
    assert out["status"] == "completed", out


def test_a_messy_unused_column_does_not_interrupt(registry, tmp_path):
    """Scoping in practice: the analysis never reads `notes`, so its problems are
    not the user's problem right now."""
    ds = _register(
        registry, tmp_path, "unused.csv",
        "dept,salary,notes\neng,100,  a  \neng,200,\nsales,300,   \n",
    )
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)
    assert out["status"] == "completed", out
    operations = [
        s["operation"]
        for s in out["charts"][0]["result"]["provenance"]["preprocessing"]
    ]
    assert operations == []  # nothing was applied to a column nobody asked about


# --- the user's answer is what happens -----------------------------------------


def test_choosing_to_keep_the_nulls_applies_nothing(registry, tmp_path):
    ds = _register(registry, tmp_path, "keep.csv", "dept,salary\neng,100\n,200\nsales,300\n")
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)
    resumed = agent.resume(out["thread_id"], "Keep them as they are")

    assert resumed["status"] == "completed", resumed
    table = resumed["charts"][0]["result"]["result_table"]
    assert None in {r["dept"] for r in table}  # the null group survives, as asked


def test_an_unreadable_answer_changes_nothing(registry, tmp_path):
    """A reply we cannot map to an option must not license a value-changing op.

    The recommendation is a default for someone who chose it, not a fallback for
    ambiguity — so an unparseable answer resolves to "do nothing".
    """
    ds = _register(registry, tmp_path, "gibberish.csv", "dept,salary\neng,100\n,200\nsales,300\n")
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)
    resumed = agent.resume(out["thread_id"], "asdfghjkl")

    assert resumed["status"] == "completed", resumed
    assert None in {r["dept"] for r in resumed["charts"][0]["result"]["result_table"]}


def test_options_carry_counts_and_one_recommendation(registry, tmp_path):
    ds = _register(registry, tmp_path, "opts.csv", "dept,salary\neng,100\n,200\nsales,300\n")
    agent = AgentService(planner=FakePlanner(plans=[_group_plan()]), registry=registry)
    out = agent.run("average salary by department", dataset_id=ds)

    options = out["options"]
    assert sum(1 for o in options if o["recommended"]) == 1
    assert any("2 of 3 rows" in o["detail"] for o in options)
    # Jargon is present but never the headline.
    assert all("imputation" not in o["label"].lower() for o in options)


# --- an explicit instruction wins ----------------------------------------------


def test_a_plan_that_already_handles_the_column_is_not_questioned(registry, tmp_path):
    """The planner turning "drop rows with no department" into an op is the user's
    instruction arriving. Asking again would re-litigate their decision."""
    # 1 null in 10 rows: under the 30% row-removal backstop, so the only thing
    # that could stop this run is a cleaning question — and there must not be one.
    rows = "\n".join(f"eng,{i}00" for i in range(9))
    ds = _register(registry, tmp_path, "explicit.csv", f"dept,salary\n{rows}\n,999\n")
    plan = {
        **_group_plan(),
        "preprocessing": [{"op": "drop_nulls", "columns": ["dept"], "how": "any"}],
    }
    agent = AgentService(planner=FakePlanner(plans=[plan]), registry=registry)
    out = agent.run("average salary by department, ignoring rows with no dept", dataset_id=ds)

    assert out["status"] == "completed", out
    assert None not in {r["dept"] for r in out["charts"][0]["result"]["result_table"]}
