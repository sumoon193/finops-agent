"""FO-08 结果、缓存、审计与血缘：缓存绑定 RLS/语义/watermark 且结果可追溯。"""

from app.finops.results.store import FO08Input, FO08Result, QueryIntent, ResultCache


def _input(**overrides):
    defaults = {
        "query_hash": "q1",
        "tenant_id": "acme",
        "semantic_version": "2024-07",
        "watermark": "w1",
        "compute": lambda: "value",
    }
    defaults.update(overrides)
    return FO08Input(**defaults)


def test_cache_key_binds_rls_semantic_and_watermark():
    cache = ResultCache()
    ctx = QueryIntent(cache=cache)
    calls = []

    def compute():
        calls.append(1)
        return "value"

    ctx.execute(_input(compute=compute))
    ctx.execute(_input(tenant_id="globex", compute=compute))
    ctx.execute(_input(semantic_version="2023-01", compute=compute))
    ctx.execute(_input(watermark="w2", compute=compute))
    assert len(calls) == 4  # all four dimensions differ -> distinct cache entries


def test_cache_hit_returns_same_result_without_recompute():
    cache = ResultCache()
    ctx = QueryIntent(cache=cache)
    calls = []

    def compute():
        calls.append(1)
        return {"rows": [1]}

    first = ctx.execute(_input(compute=compute))
    second = ctx.execute(_input(compute=compute))
    assert first.artifact.cache_status == "computed"
    assert second.artifact.cache_status == "cache-hit"
    assert second.artifact.value == first.artifact.value
    assert len(calls) == 1


def test_cache_miss_computes_and_stores():
    cache = ResultCache()
    ctx = QueryIntent(cache=cache)
    calls = []

    def compute():
        calls.append(1)
        return "fresh"

    result = ctx.execute(_input(compute=compute))
    assert isinstance(result, FO08Result)
    assert result.artifact.cache_status == "computed"
    assert result.artifact.value == "fresh"
    assert len(calls) == 1
    assert cache.contains(_input(compute=compute))


def test_result_carries_traceable_provenance():
    ctx = QueryIntent(cache=ResultCache())
    result = ctx.execute(_input(compute=lambda: "value"))
    provenance = result.artifact.provenance
    assert any(item == "query:q1" for item in provenance)
    assert any(item == "semantic:2024-07" for item in provenance)
    assert any(item == "watermark:w1" for item in provenance)
    assert any(item == "tenant:acme" for item in provenance)
