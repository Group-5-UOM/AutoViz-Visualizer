"""One question should not fan out into several charts unless the user asked to."""

from autoviz.agent.nodes import collapse_tasks, looks_multipart


def test_single_relationship_is_not_multipart():
    assert not looks_multipart("how post length change with the language")
    assert not looks_multipart("show fare by class")
    assert not looks_multipart("average tip by smoker")


def test_explicit_multi_part_cues():
    assert looks_multipart(
        "Show average fare by class, and separately the survival count by sex."
    )
    assert looks_multipart("Plot tips by day and also show party size by smoker")
    assert looks_multipart("Two charts: average fare by class; survival by sex")
    assert looks_multipart("1. average fare by class\n2. survival count by sex")


def test_collapse_keeps_multipart_tasks():
    request = "Show average fare by class, and separately the survival count by sex."
    tasks = ["average fare by class", "survival count by sex"]
    assert collapse_tasks(request, tasks) == tasks


def test_collapse_reduces_over_split_to_original_request():
    request = "how post length change with the language"
    tasks = [
        "average post length by language",
        "count of posts by language",
        "max post length by language",
        "min post length by language",
        "median post length by language",
    ]
    assert collapse_tasks(request, tasks) == [request]
