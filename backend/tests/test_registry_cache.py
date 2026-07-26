"""DatasetRegistry as a bounded, self-loading LRU cache.

Covers the two properties the plain dict never had: a memory ceiling, and the
ability to restore a frame it does not hold.
"""

import threading

import pandas as pd

from autoviz.services.registry import DatasetRecord, DatasetRegistry


def _record(dataset_id: str, rows: int = 1000) -> DatasetRecord:
    df = pd.DataFrame({"a": range(rows), "b": range(rows)})
    return DatasetRecord(
        dataset_id=dataset_id,
        source=f"{dataset_id}.csv",
        df=df,
        schema={"a": "number", "b": "number"},
    )


def _size_of(rows: int = 1000) -> int:
    return _record("probe", rows).nbytes()


# --- eviction ----------------------------------------------------------------


def test_evicts_least_recently_used_when_over_budget():
    one = _size_of()
    reg = DatasetRegistry(max_bytes=one * 2 + 1)  # room for exactly two

    reg.add(_record("ds_a"))
    reg.add(_record("ds_b"))
    reg.add(_record("ds_c"))

    assert reg.get("ds_a") is None  # oldest dropped
    assert reg.get("ds_b") is not None
    assert reg.get("ds_c") is not None


def test_get_refreshes_recency():
    one = _size_of()
    reg = DatasetRegistry(max_bytes=one * 2 + 1)

    reg.add(_record("ds_a"))
    reg.add(_record("ds_b"))
    reg.get("ds_a")  # ds_a is now the most recently used
    reg.add(_record("ds_c"))

    assert reg.get("ds_a") is not None
    assert reg.get("ds_b") is None  # ds_b became the oldest and was dropped


def test_never_evicts_the_only_record():
    """A dataset bigger than the whole budget must still be queryable."""
    reg = DatasetRegistry(max_bytes=1)
    reg.add(_record("ds_big"))
    assert reg.get("ds_big") is not None


def test_remove_frees_the_budget():
    one = _size_of()
    reg = DatasetRegistry(max_bytes=one * 2 + 1)

    reg.add(_record("ds_a"))
    reg.add(_record("ds_b"))
    reg.remove("ds_a")
    reg.add(_record("ds_c"))

    # Removing ds_a freed its bytes, so adding ds_c must not evict ds_b.
    assert reg.get("ds_b") is not None
    assert reg.get("ds_c") is not None


def test_re_adding_same_id_does_not_double_count():
    one = _size_of()
    reg = DatasetRegistry(max_bytes=one * 2 + 1)

    reg.add(_record("ds_a"))
    reg.add(_record("ds_a"))  # same id again
    reg.add(_record("ds_b"))

    assert reg.get("ds_a") is not None
    assert reg.get("ds_b") is not None


# --- loader ------------------------------------------------------------------


def test_loader_restores_on_miss_and_caches():
    calls: list[str] = []

    def loader(dataset_id: str):
        calls.append(dataset_id)
        return _record(dataset_id)

    reg = DatasetRegistry(loader=loader)

    assert reg.get("ds_x") is not None
    assert reg.get("ds_x") is not None
    assert calls == ["ds_x"]  # second hit served from cache


def test_loader_returning_none_is_a_miss():
    reg = DatasetRegistry(loader=lambda _id: None)
    assert reg.get("ds_gone") is None


def test_no_loader_keeps_pure_in_memory_behaviour():
    """The MCP server and offline services construct a bare registry."""
    reg = DatasetRegistry()
    assert reg.get("ds_anything") is None


def test_concurrent_misses_converge_on_one_record():
    """Threads racing on the same missing id must not end up with different frames."""
    barrier = threading.Barrier(8)

    def loader(dataset_id: str):
        barrier.wait()  # force the race
        return _record(dataset_id)

    reg = DatasetRegistry(loader=loader)
    results: list[DatasetRecord] = []
    lock = threading.Lock()

    def worker():
        record = reg.get("ds_race")
        with lock:
            results.append(record)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert all(r is not None for r in results)
    # Every caller holds the identical object — never divergent copies.
    assert len({id(r) for r in results}) == 1
