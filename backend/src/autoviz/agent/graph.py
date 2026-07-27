"""Graph assembly: bounded workflow, not an unconstrained agent.

START -> load_context -> classify_intent -> (clarify | Send fan-out | fail)
Each analysis worker: plan -> assess_quality -> execute -> [repair loop |
preprocessing-confirmation | chart fallback] -> finalize. Workers join at
compose_response. Three interrupts require the checkpointer: clarify (an ambiguous
request), assess_quality (a cleaning choice), and the large-row-removal gate.
"""

from functools import partial

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from autoviz.agent import nodes, routing
from autoviz.agent.state import AutoVizState, WorkerOutput, WorkerState
from autoviz.llm.client import GeminiPlanner, PlannerLLM
from autoviz.services.registry import REGISTRY, DatasetRegistry


def build_graph(
    planner: PlannerLLM | None = None,
    registry: DatasetRegistry = REGISTRY,
    checkpointer: BaseCheckpointSaver | None = None,
):
    planner = planner or GeminiPlanner()

    worker = StateGraph(WorkerState, output_schema=WorkerOutput)
    worker.add_node("plan", partial(nodes.plan_node, planner=planner))
    worker.add_node("assess_quality", partial(nodes.assess_quality, registry=registry))
    worker.add_node("execute", partial(nodes.execute_node, registry=registry))
    worker.add_node("confirm_preprocessing", nodes.confirm_preprocessing)
    worker.add_node("chart_fallback", nodes.chart_fallback)
    worker.add_node("finalize", nodes.finalize_worker)
    worker.add_edge(START, "plan")
    worker.add_conditional_edges(
        "plan",
        routing.route_after_plan,
        {
            "plan": "plan",
            "assess_quality": "assess_quality",
            "execute": "execute",
            "finalize": "finalize",
        },
    )
    # One cleaning question per pass, looping until the queue empties or the budget
    # runs out — the same shape as the clarification loop in the parent graph.
    worker.add_conditional_edges(
        "assess_quality",
        routing.route_after_assess,
        {"assess_quality": "assess_quality", "execute": "execute"},
    )
    worker.add_conditional_edges(
        "execute",
        routing.route_after_execute,
        {
            "plan": "plan",
            "confirm_preprocessing": "confirm_preprocessing",
            "chart_fallback": "chart_fallback",
            "finalize": "finalize",
        },
    )
    # After the user answers the row-removal gate, re-run execute (now approved, or
    # with the row-dropping steps skipped).
    worker.add_edge("confirm_preprocessing", "execute")
    worker.add_edge("chart_fallback", "finalize")
    worker.add_edge("finalize", END)

    graph = StateGraph(AutoVizState)
    graph.add_node("load_context", partial(nodes.load_context, registry=registry))
    graph.add_node("detect_ambiguity", nodes.detect_ambiguity)
    graph.add_node("classify_intent", partial(nodes.classify_intent, planner=planner))
    graph.add_node("clarify", nodes.clarify)
    graph.add_node("analysis_worker", worker.compile())
    graph.add_node("compose_response", partial(nodes.compose_response, planner=planner))
    graph.add_node("record_failure", nodes.record_failure)

    graph.add_edge(START, "load_context")
    graph.add_conditional_edges(
        "load_context",
        routing.route_after_context,
        {"detect_ambiguity": "detect_ambiguity", "record_failure": "record_failure"},
    )
    graph.add_conditional_edges(
        "detect_ambiguity",
        routing.route_after_detect,
        ["clarify", "classify_intent"],
    )
    graph.add_conditional_edges(
        "classify_intent",
        routing.route_after_classify,
        ["clarify", "analysis_worker"],
    )
    graph.add_conditional_edges(
        "clarify",
        routing.route_after_clarify,
        ["detect_ambiguity", "classify_intent"],
    )
    graph.add_edge("analysis_worker", "compose_response")
    graph.add_edge("compose_response", END)
    graph.add_edge("record_failure", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())
