"""真流式：`pipeline.run(..., on_result=cb)` 每站一出结果就回调。

用户诉求（m00001）：「搜索速度有点慢」。真正的痛点不是总耗时，而是旧实现
要等**全部**站点跑完（2026-10-23 实测 zh 35.5s / en 55.5s）才发出第一帧。
这里只锁契约本身：每个站一有结果就回调一次、返回顺序仍是传入顺序、
回调抛异常也不能带崩搜索。
"""
from finder import pipeline
from finder.models import GameDetail, SearchSpec, Site


def _site(sid: str) -> Site:
    return Site(
        id=sid, name=sid, homepage=f"https://{sid}.test/",
        kinds=[], langs={"zh"}, url_searchable=True,
        search=SearchSpec(mode="url", url_template=f"https://{sid}.test/?s={{q}}"),
    )


def _fake_run_one(config, root, site, query, timeout, store, cache_on,
                  profile_override=None, sess=None):
    return GameDetail(site_id=site.id, url=f"https://{site.id}.test/1", title=site.id)


def test_run_emits_each_site_as_it_finishes(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "_run_one_site", _fake_run_one)
    sites = [_site("a"), _site("b"), _site("c")]

    seen: list[str] = []
    out = pipeline.run({"search": {"workers": 1}}, sites, "x", tmp_path,
                       use_cache=False, on_result=lambda d: seen.append(d.site_id))

    assert [d.site_id for d in out] == ["a", "b", "c"], "返回顺序必须与传入一致"
    assert seen == ["a", "b", "c"], "每站一有结果就要回调（不是全部跑完再回调）"


def test_on_result_exception_does_not_break_search(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "_run_one_site", _fake_run_one)
    sites = [_site("a"), _site("b")]

    def boom(detail):
        raise RuntimeError("callback boom")

    out = pipeline.run({"search": {"workers": 1}}, sites, "x", tmp_path,
                       use_cache=False, on_result=boom)
    assert [d.site_id for d in out] == ["a", "b"]
    assert all(d.error is None for d in out)
