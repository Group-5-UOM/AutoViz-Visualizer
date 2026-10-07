"""What happens to the conversation around a question, not the question itself.

Each test here is a defect found by walking through the live app with a real
dataset (NYC Airbnb listings): the clarification and cleaning layers each worked
in isolation, and broke at the seams between one turn and the next.
"""

from autoviz.agent.nodes import CANCELLED_ANSWER
from autoviz.agent.service import AgentService
from autoviz.llm.client import IntentDecision, ProposedAmbiguity, ProposedOption
from autoviz.services import dataset
from tests.test_agent import GOOD_IRIS_PLAN, FakePlanner

# Two listings priced 9999 among ordinary prices: the placeholder-code detector's
# exact shape, and the reason the demo asked about "999, 9999" on every question.
LISTINGS = "borough,room,price\n" + "".join(
    f"{b},{r},{p}\n"
    for b, r, p in [
        ("Bronx", "Private", 60), ("Bronx", "Entire", 120), ("Bronx", "Private", 70),
        ("Brooklyn", "Entire", 150), ("Brooklyn", "Private", 80), ("Brooklyn", "Shared", 40),
        ("Manhattan", "Entire", 220), ("Manhattan", "Private", 110), ("Manhattan", "Entire", 9999),
        ("Queens", "Private", 65), ("Queens", "Entire", 130), ("Queens", "Shared", 9999),
        ("Bronx", "Entire", 115), ("Brooklyn", "Entire", 160), ("Manhattan", "Shared", 90),
        ("Queens", "Private", 75),
    ]
)

AVG_PRICE_BY_BOROUGH = {
    "intent": "comparison",
    "group_by": ["borough"],
    "aggregations": [{"column": "price", "fn": "mean", "as": "avg_price"}],
}
MAX_PRICE_BY_ROOM = {
    "intent": "comparison",
    "group_by": ["room"],
    "aggregations": [{"column": "price", "fn": "max", "as": "max_price"}],
}
COUNT_BY_ROOM = {
    "intent": "comparison",
    "group_by": ["room"],
    "aggregations": [{"column": "room", "fn": "count", "as": "n"}],
}


def _listings(registry, tmp_path, name="listings.csv"):
    path = tmp_path / name
    path.write_text(LISTINGS)
    return dataset.register_dataset(path.as_posix(), registry)["dataset_id"]


def _ops(out):
    return [op["op"] for op in out["charts"][0]["plan"].get("preprocessing") or []]


# --- cancel means cancel -------------------------------------------------------


def test_cancelling_a_refused_request_ends_the_run(registry, iris_id):
    """"Nothing — cancel this request" used to resolve the slot and carry on, so
    the forecast the user had just declined was planned and charted anyway."""
    fake = FakePlanner(plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)

    out = agent.run("Forecast sepal length for next year", dataset_id=iris_id)
    assert out["status"] == "waiting_for_user"
    assert "Nothing — cancel this request" in out["options"]

    done = agent.resume(out["thread_id"], "Nothing — cancel this request")
    assert done["status"] == "completed", done
    assert done["charts"] == []
    assert done["answer"] == CANCELLED_ANSWER
    assert fake.plan_calls == []


def test_the_alternative_on_offer_still_runs(registry, iris_id):
    fake = FakePlanner(plans=[GOOD_IRIS_PLAN])
    agent = AgentService(planner=fake, registry=registry)
    out = agent.run("Forecast sepal length for next year", dataset_id=iris_id)
    done = agent.resume(out["thread_id"], "Show what the data does say, over time")
    assert done["status"] == "completed", done
    assert len(done["charts"]) == 1


# --- a new request is not an answer -------------------------------------------


def test_a_new_request_on_a_paused_thread_starts_fresh(registry, tmp_path):
    """The frontend now sends a new question as a new run on the same thread when
    a cleaning question is pending. That must start over, not resume the pause."""
    ds = _listings(registry, tmp_path)
    fake = FakePlanner(plans=[AVG_PRICE_BY_BOROUGH, COUNT_BY_ROOM])
    agent = AgentService(planner=fake, registry=registry)

    paused = agent.run("average price by borough", dataset_id=ds)
    assert paused["status"] == "waiting_for_user"
    assert paused["slot"] == "suspect:price"

    fresh = agent.run("how many listings of each room type", dataset_id=ds,
                      thread_id=paused["thread_id"])
    assert fresh["status"] == "completed", fresh
    assert fake.plan_calls[-1]["task"] == "how many listings of each room type"
    rooms = {row["room"] for row in fresh["charts"][0]["result"]["result_table"]}
    assert rooms == {"Private", "Entire", "Shared"}


# --- a cleaning answer is remembered -------------------------------------------


def test_a_cleaning_answer_is_not_asked_again_in_the_same_conversation(registry, tmp_path):
    ds = _listings(registry, tmp_path)
    fake = FakePlanner(plans=[AVG_PRICE_BY_BOROUGH, MAX_PRICE_BY_ROOM])
    agent = AgentService(planner=fake, registry=registry)

    first = agent.run("average price by borough", dataset_id=ds)
    assert first["slot"] == "suspect:price"
    answered = agent.resume(first["thread_id"], "Treat them as missing")
    assert answered["status"] == "completed", answered

    second = agent.run("highest price per room type", dataset_id=ds,
                       thread_id=first["thread_id"])
    assert second["status"] == "completed", second
    # Applied, not merely skipped: the remembered choice still changes the numbers.
    assert "nullify_values" in _ops(second)
    table = {r["room"]: r["max_price"] for r in second["charts"][0]["result"]["result_table"]}
    assert table["Entire"] == 220


def test_remembering_keep_them_also_stops_the_question(registry, tmp_path):
    ds = _listings(registry, tmp_path)
    fake = FakePlanner(plans=[AVG_PRICE_BY_BOROUGH, MAX_PRICE_BY_ROOM])
    agent = AgentService(planner=fake, registry=registry)
    first = agent.run("average price by borough", dataset_id=ds)
    agent.resume(first["thread_id"], "Treat them as real values")

    second = agent.run("highest price per room type", dataset_id=ds,
                       thread_id=first["thread_id"])
    assert second["status"] == "completed", second
    assert "nullify_values" not in _ops(second)


def test_a_remembered_answer_is_per_dataset(registry, tmp_path):
    ds = _listings(registry, tmp_path)
    other = _listings(registry, tmp_path, "other.csv")
    fake = FakePlanner(plans=[AVG_PRICE_BY_BOROUGH, AVG_PRICE_BY_BOROUGH])
    agent = AgentService(planner=fake, registry=registry)
    first = agent.run("average price by borough", dataset_id=ds)
    agent.resume(first["thread_id"], "Treat them as missing")

    again = agent.run("average price by borough", dataset_id=other,
                      thread_id=first["thread_id"])
    assert again["status"] == "waiting_for_user"
    assert again["slot"] == "suspect:price"


def test_a_filter_that_excludes_the_codes_asks_nothing(registry, tmp_path):
    """"Prices under $500" cannot be changed by how 9999 is read."""
    ds = _listings(registry, tmp_path)
    under_500 = {**AVG_PRICE_BY_BOROUGH, "filters": [{"column": "price", "op": "lt", "value": 500}]}
    agent = AgentService(planner=FakePlanner(plans=[under_500]), registry=registry)
    out = agent.run("average price under $500 by borough", dataset_id=ds)
    assert out["status"] == "completed", out


# --- pointing at a chart ---------------------------------------------------------


def test_pointing_at_a_chart_plans_from_the_users_words(registry, iris_id):
    """The classifier's rewrite borrowed the previous question's filter; with a
    chart pointed at, the task is the user's request and the plan is that chart's."""
    rewritten = IntentDecision(
        intent="refinement",
        tasks=["average sepal length by species for flowers under 5cm as a line chart"],
    )
    fake = FakePlanner(
        decisions=[IntentDecision(intent="analysis", tasks=["average sepal length by species"]),
                   rewritten],
        plans=[GOOD_IRIS_PLAN, GOOD_IRIS_PLAN],
    )
    agent = AgentService(planner=fake, registry=registry)
    first = agent.run("average sepal length by species", dataset_id=iris_id)
    chart_id = first["charts"][0]["chart_id"]

    second = agent.run("show this as a line chart", dataset_id=iris_id,
                       thread_id=first["thread_id"], chart_id=chart_id)
    assert second["status"] == "completed", second
    call = fake.plan_calls[-1]
    assert call["task"] == "show this as a line chart"
    assert call["prior_plan"]["group_by"] == ["species"]
    assert second["charts"][0]["chart_id"] == chart_id


def test_pointing_at_a_chart_skips_asking_how_to_group_it(registry, iris_id):
    ask = IntentDecision(
        intent="clarification",
        ambiguity=ProposedAmbiguity(
            type="semantic",
            slot="metric",
            question="Which measurement should the bars show?",
            options=[
                ProposedOption(label="Sepal length",
                               resolves_to={"column": "sepal_length", "fn": "mean"}),
                ProposedOption(label="Petal length",
                               resolves_to={"column": "petal_length", "fn": "mean"}),
            ],
        ),
    )
    fake = FakePlanner(
        decisions=[IntentDecision(intent="analysis", tasks=["average sepal length by species"]),
                   ask],
        plans=[GOOD_IRIS_PLAN, GOOD_IRIS_PLAN],
    )
    agent = AgentService(planner=fake, registry=registry)
    first = agent.run("average sepal length by species", dataset_id=iris_id)

    second = agent.run("show this as a grouped bar chart", dataset_id=iris_id,
                       thread_id=first["thread_id"],
                       chart_id=first["charts"][0]["chart_id"])
    assert second["status"] == "completed", second


def test_without_a_pointed_chart_the_same_question_is_still_asked(registry, iris_id):
    ask = IntentDecision(
        intent="clarification",
        ambiguity=ProposedAmbiguity(
            type="semantic",
            slot="metric",
            question="Which measurement should the bars show?",
            options=[
                ProposedOption(label="Sepal length",
                               resolves_to={"column": "sepal_length", "fn": "mean"}),
                ProposedOption(label="Petal length",
                               resolves_to={"column": "petal_length", "fn": "mean"}),
            ],
        ),
    )
    agent = AgentService(planner=FakePlanner(decisions=[ask], plans=[GOOD_IRIS_PLAN]),
                         registry=registry)
    out = agent.run("show the bars for each species", dataset_id=iris_id)
    assert out["status"] == "waiting_for_user"
