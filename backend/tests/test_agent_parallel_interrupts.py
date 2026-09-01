"""Concurrent interrupts: two workers pausing in the same superstep.

A fanned-out request runs its tasks as parallel subgraphs, so two of them can
call interrupt() in one superstep. LangGraph refuses a bare Command(resume=...)
in that situation, and the service used to send exactly that — which is how a
broad request over a mostly-null column ("complete analysis about deck") turned
into "you must specify the interrupt id when resuming".

The service now groups concurrent pauses by the *decision* they represent: the
same question asked by N workers is asked once and answered for all of them,
while genuinely different questions queue up one at a time.
"""

from autoviz.agent.service import AgentService
from autoviz.llm.client import IntentDecision
from autoviz.services import dataset

from tests.test_agent import FakePlanner

# nulls_id (conftest): 10 rows, drop_nulls(["cls","fare"]) removes 4 = 40%,
# over the confirmation threshold. Adding "age" removes 6 = 60% — a different
# block, so a different hash and therefore a different decision.
DROP_TWO = [{"op": "drop_nulls", "columns": ["cls", "fare"], "how": "any"}]
DROP_THREE = [{"op": "drop_nulls", "columns": ["cls", "fare", "age"], "how": "any"}]

FARE_TASK = "average fare by class"
AGE_TASK = "average age by class"


def _plan(preprocessing, column, alias):
    return {
        "intent": "comparison",
        "preprocessing": [dict(op) for op in preprocessing],
        "group_by": ["cls"],
        "aggregations": [{"column": column, "fn": "mean", "as": alias}],
    }


def _two_worker_agent(registry, fare_pre, age_pre):
    """Two tasks whose plans both gate, so both workers pause together."""
    decision = IntentDecision(intent="analysis", tasks=[FARE_TASK, AGE_TASK])
    plans = {
        FARE_TASK: _plan(fare_pre, "fare", "avg_fare"),
        AGE_TASK: _plan(age_pre, "age", "avg_age"),
    }
    return AgentService(
        planner=FakePlanner(decisions=[decision], plans=plans), registry=registry
    )


def _rows(resumed, task):
    chart = next(c for c in resumed["charts"] if c["task"] == task)
    return chart["result"]["output_rows"]


def _whose(pause):
    """Which task a confirmation belongs to, read off its impact.

    Interrupts do not arrive in Send order — LangGraph orders tasks by id — so a
    test that assumed "group 0 is the first task" would pass or fail on a hash.
    DROP_TWO removes 4 rows and DROP_THREE removes 6, which names them.
    """
    dropped = pause["impact"]["dropped"]
    assert dropped in (4, 6), pause
    return (FARE_TASK, 6) if dropped == 4 else (AGE_TASK, 4)


def test_parallel_gates_resume_without_an_interrupt_id(registry, nulls_id):
    """The original bug: two concurrent gates used to make resume() raise."""
    agent = _two_worker_agent(registry, DROP_TWO, DROP_TWO)
    out = agent.run("fare and age by cls, dropping missing", dataset_id=nulls_id)
    assert out["status"] == "waiting_for_user"

    resumed = agent.resume(out["thread_id"], "Proceed with cleaning")

    assert resumed["status"] == "completed", resumed
    assert len(resumed["charts"]) == 2
    assert _rows(resumed, FARE_TASK) == 6
    assert _rows(resumed, AGE_TASK) == 6


def test_one_decision_is_asked_once_for_both_workers(registry, nulls_id):
    """Identical preprocessing -> identical hash -> a single question."""
    agent = _two_worker_agent(registry, DROP_TWO, DROP_TWO)
    out = agent.run("fare and age by cls, dropping missing", dataset_id=nulls_id)

    assert out["pending_count"] == 1
    assert out["interrupt_id"]
    # Two workers really are paused behind that one question.
    config = {"configurable": {"thread_id": out["thread_id"]}}
    live = [
        i
        for task in agent._graph.get_state(config).tasks
        if task.result is None
        for i in task.interrupts
    ]
    assert len(live) == 2


def test_skip_reaches_every_worker_in_the_group(registry, nulls_id):
    agent = _two_worker_agent(registry, DROP_TWO, DROP_TWO)
    out = agent.run("fare and age by cls, dropping missing", dataset_id=nulls_id)

    resumed = agent.resume(out["thread_id"], "Skip cleaning (keep all rows)")

    assert resumed["status"] == "completed", resumed
    # Neither worker dropped rows, and neither kept the row-removal step.
    assert _rows(resumed, FARE_TASK) == 10
    assert _rows(resumed, AGE_TASK) == 10
    for chart in resumed["charts"]:
        ops = [s["operation"] for s in chart["result"]["provenance"]["preprocessing"]]
        assert "drop_nulls" not in ops


def test_different_decisions_queue_and_do_not_cross_apply(registry, nulls_id):
    """Distinct blocks are distinct questions; each answer binds to its own."""
    agent = _two_worker_agent(registry, DROP_TWO, DROP_THREE)
    first = agent.run("fare and age by cls, dropping missing", dataset_id=nulls_id)

    assert first["status"] == "waiting_for_user"
    assert first["pending_count"] == 2

    # Answering one leaves the other paused, with its own question.
    second = agent.resume(first["thread_id"], "Proceed with cleaning", first["interrupt_id"])
    assert second["status"] == "waiting_for_user", second
    assert second["pending_count"] == 1
    assert second["interrupt_id"] != first["interrupt_id"]
    assert second["preprocessing_hash"] != first["preprocessing_hash"]

    resumed = agent.resume(
        second["thread_id"], "Skip cleaning (keep all rows)", second["interrupt_id"]
    )
    assert resumed["status"] == "completed", resumed
    # Each worker got the answer meant for it, not the other's: the one told to
    # proceed dropped its rows, the one told to skip kept all of them.
    proceeded_task, proceeded_rows = _whose(first)
    skipped_task, _ = _whose(second)
    assert _rows(resumed, proceeded_task) == proceeded_rows
    assert _rows(resumed, skipped_task) == 10


def test_cleaning_choices_on_different_columns_queue_separately(registry, tmp_path):
    """Two workers, two dirty dimensions -> two slots, answered independently."""
    # 12 rows, 2 nulls in each dimension: above ROW_DROP_NOTICE_FRACTION (0.05)
    # so both are worth asking about, and 16.7% is under ROW_DROP_CONFIRM_FRACTION
    # (0.30) so excluding them does not go on to trip the row-removal gate.
    csv = tmp_path / "two_dims.csv"
    csv.write_text(
        "dept,region,salary\n"
        "eng,North,100\n"
        "eng,North,110\n"
        "eng,South,120\n"
        "sales,South,130\n"
        "sales,North,140\n"
        "sales,South,150\n"
        "ops,North,160\n"
        "ops,South,170\n"
        "eng,,180\n"
        "sales,,190\n"
        ",North,200\n"
        ",South,210\n"
    )
    ds = dataset.register_dataset(csv.as_posix(), registry)["dataset_id"]

    by_dept, by_region = "average salary by dept", "average salary by region"
    decision = IntentDecision(intent="analysis", tasks=[by_dept, by_region])
    plans = {
        by_dept: {
            "intent": "comparison",
            "group_by": ["dept"],
            "aggregations": [{"column": "salary", "fn": "mean", "as": "avg_salary"}],
        },
        by_region: {
            "intent": "comparison",
            "group_by": ["region"],
            "aggregations": [{"column": "salary", "fn": "mean", "as": "avg_salary"}],
        },
    }
    agent = AgentService(
        planner=FakePlanner(decisions=[decision], plans=plans), registry=registry
    )

    first = agent.run("salary by dept and by region", dataset_id=ds)
    assert first["pause_kind"] == "cleaning_choice"
    assert first["pending_count"] == 2

    second = agent.resume(first["thread_id"], "Exclude those rows", first["interrupt_id"])
    assert second["status"] == "waiting_for_user", second
    assert second["slot"] != first["slot"]

    resumed = agent.resume(
        second["thread_id"], "Keep them as they are", second["interrupt_id"]
    )
    assert resumed["status"] == "completed", resumed

    by_slot = {first["slot"]: "excluded", second["slot"]: "kept"}
    for chart in resumed["charts"]:
        column = chart["plan"]["group_by"][0]
        values = {r[column] for r in chart["result"]["result_table"]}
        if by_slot[f"missing:{column}"] == "excluded":
            assert None not in values
        else:
            assert None in values


def test_a_stale_interrupt_id_re_asks_instead_of_consuming_the_answer(registry, nulls_id):
    """An answer to a resolved question must not land on the next one."""
    agent = _two_worker_agent(registry, DROP_TWO, DROP_THREE)
    first = agent.run("fare and age by cls, dropping missing", dataset_id=nulls_id)
    stale = first["interrupt_id"]
    second = agent.resume(first["thread_id"], "Proceed with cleaning", stale)
    assert second["status"] == "waiting_for_user"

    replayed = agent.resume(second["thread_id"], "Proceed with cleaning", stale)

    assert replayed["status"] == "waiting_for_user"
    assert replayed["stale_answer"] is True
    # It re-presents what is actually pending rather than answering it.
    assert replayed["interrupt_id"] == second["interrupt_id"]
    assert replayed["question"] == second["question"]

    # And the surviving decision still takes its own answer.
    resumed = agent.resume(
        replayed["thread_id"], "Skip cleaning (keep all rows)", replayed["interrupt_id"]
    )
    assert resumed["status"] == "completed", resumed
    skipped_task, _ = _whose(second)
    assert _rows(resumed, skipped_task) == 10


def test_snapshot_interrupts_keeps_answered_entries(registry, nulls_id):
    """Guard on the LangGraph behaviour the grouping depends on.

    StateSnapshot.interrupts is rebuilt from pending writes, and an answered
    task's INTERRUPT write is never deleted — so it over-reports. Live pauses
    have to be read off the tasks instead. If a future upgrade fixes this, the
    filter in _live_from_snapshot becomes dead code and should be revisited.
    """
    agent = _two_worker_agent(registry, DROP_TWO, DROP_THREE)
    first = agent.run("fare and age by cls, dropping missing", dataset_id=nulls_id)
    agent.resume(first["thread_id"], "Proceed with cleaning", first["interrupt_id"])

    snapshot = agent._graph.get_state({"configurable": {"thread_id": first["thread_id"]}})
    live = [i for t in snapshot.tasks if t.result is None for i in t.interrupts]

    assert len(snapshot.interrupts) == 2  # stale: includes the answered one
    assert len(live) == 1
