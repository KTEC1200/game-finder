"""结果分档 + 排序（后端），以及结果卡片的跳转/图例（静态结构断言）。

用户要求（原文，m00620）：
  「找到連結的排前面（直鏈優先，然後網盤），然後是找到結果但沒有連結的，
    最後是什麼都沒有的。」

分档只在后端做（`server.outcome_of` / `server.order_results`），前端只按 result
帧里的 `outcome` 上色分组，**不解析错误字串**。index.html 是单文件内联 JS（没有
构建、没有 JS 测试运行器），所以 UI 侧沿用 `tests/test_ui_hint.py` 的静态结构
断言做法；真实点击跳转由 lead 在 live 服务上统一验。

关键事实（lead 已查证）：`NO_RESULTS` 的结果实测是 `url=None, title=''`
（例：acggw），所以卡片必须有站点名/首页兜底；`NEEDS_LOGIN` 有两种语意，靠
`extra["search_login_wall"]` 分开，不靠比对中文文案。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import get_args

import pytest

from finder.models import Download, DownloadKind, GameDetail
from finder.web.server import DIRECT_KIND, outcome_of, order_results

HTML = Path(__file__).resolve().parent.parent / "finder" / "web" / "static" / "index.html"
ALL_KINDS = get_args(DownloadKind)


@pytest.fixture(scope="module")
def src() -> str:
    return HTML.read_text(encoding="utf-8")


def gd(site_id="site-a", *, url="https://site-a.example/game/1", title="Some Game",
       downloads=(), error=None, extra=None) -> GameDetail:
    return GameDetail(site_id=site_id, url=url, title=title,
                      downloads=list(downloads), error=error, extra=dict(extra or {}))


def dl(kind, url="https://site-a.example/dl/1") -> Download:
    return Download(kind=kind, url=url)


# ---------------------------------------------------------------------------
# outcome_of：四档各自的真/假边界
# ---------------------------------------------------------------------------

def test_direct_kind_is_a_real_downloadkind_literal():
    """排序认的「直链」字面值必须真的存在于 models.DownloadKind。"""
    assert DIRECT_KIND in ALL_KINDS


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_every_download_kind_lands_in_direct_or_pan(kind):
    """有 downloads 时：kind == direct → direct，其余（pan/magnet/filehost/unknown）→ pan。"""
    expected = "direct" if kind == DIRECT_KIND else "pan"
    assert outcome_of(gd(downloads=[dl(kind)])) == expected


def test_one_direct_among_many_downloads_is_still_direct():
    d = gd(downloads=[dl("pan"), dl("magnet"), dl("direct"), dl("unknown")])
    assert outcome_of(d) == "direct"


def test_downloads_beat_a_stale_error_string():
    """顺序不能反过来：只要抽到了链接就按链接分档。"""
    assert outcome_of(gd(downloads=[dl("direct")], error="NO_DOWNLOADS")) == "direct"


def test_no_downloads_and_no_error_is_no_links():
    assert outcome_of(gd()) == "no_links"


def test_empty_error_string_counts_as_no_error():
    """done 帧是用 `not d.error` 计 ok 的，空串属于「没出错」，分档口径要一致。"""
    assert outcome_of(gd(error="")) == "no_links"


@pytest.mark.parametrize("error", [
    "NO_DOWNLOADS",
    "NO_DOWNLOADS: page says unavailable",
    "NEEDS_GATE: detail page only has in-site jump links",
    "NEEDS_COMMENT: comment required to reveal",
])
def test_detail_level_errors_are_no_links(error):
    assert outcome_of(gd(error=error)) == "no_links"


@pytest.mark.parametrize("error", [
    "NO_RESULTS: nothing matched",
    "WRONG_GAME: no query evidence in page",
    "FORM_FAILED: TimeoutError: boom",
    "QUERY_TOO_LONG: 41 > 40",
    "BLOCKED_SEARCH: cloudflare challenge",
    "SOMETHING_NEW: an unlisted prefix",
])
def test_not_found_errors(error):
    assert outcome_of(gd(error=error)) == "not_found"


def test_no_results_typical_shape_is_not_found():
    """NO_RESULTS 的实测形状：url=None, title=''（例：acggw）。"""
    d = GameDetail(site_id="acggw", url=None, title="",
                   error="NO_RESULTS: no content")
    assert outcome_of(d) == "not_found"


# ---------------------------------------------------------------------------
# NEEDS_LOGIN 的两种语意：搜索页级 vs 详情页级
# ---------------------------------------------------------------------------

def test_needs_login_search_page_level_is_not_found():
    """搜索页被重定向到登录页 == 根本没搜到；pipeline 会写 extra 的墙 URL。"""
    d = gd(error="NEEDS_LOGIN: search page redirected to login",
           extra={"search_login_wall": "https://site-a.example/login"})
    assert outcome_of(d) == "not_found"


def test_needs_login_detail_page_level_is_no_links():
    """详情页级登录墙（隐藏内容门槛）不写 search_login_wall → 找到但没链接。"""
    assert outcome_of(gd(error="NEEDS_LOGIN: hidden content gate")) == "no_links"


@pytest.mark.parametrize("wall", [None, "", False, 0])
def test_falsy_search_login_wall_is_not_a_search_wall(wall):
    d = gd(error="NEEDS_LOGIN: x", extra={"search_login_wall": wall})
    assert outcome_of(d) == "no_links"


# ---------------------------------------------------------------------------
# order_results
# ---------------------------------------------------------------------------

def _mixed() -> tuple[list[GameDetail], dict[str, str]]:
    """混合输入：四档都有，且每档尽量带 primary/backup，外加一个未登记 tier 的站。"""
    items = [
        gd("s-not-found", error="NO_RESULTS: nope"),            # not_found, primary
        gd("s-pan", downloads=[dl("pan")]),                      # pan, primary
        gd("s-direct-backup", downloads=[dl("direct")]),         # direct, backup
        gd("s-direct", downloads=[dl("direct")]),                # direct, primary
        gd("s-no-links", error="NO_DOWNLOADS"),                  # no_links, primary
        gd("s-no-links-backup", error="NEEDS_GATE: x"),          # no_links, backup
        gd("s-pan-backup", downloads=[dl("magnet")]),            # pan, backup
        gd("s-unlisted", downloads=[dl("unknown")]),             # pan, tier 未登记
    ]
    tiers = {
        "s-not-found": "primary", "s-pan": "primary",
        "s-direct-backup": "backup", "s-direct": "primary",
        "s-no-links": "primary", "s-no-links-backup": "backup",
        "s-pan-backup": "backup",
    }
    return items, tiers


def test_order_results_full_mixed_ordering():
    items, tiers = _mixed()
    got = [d.site_id for d in order_results(items, tiers)]
    assert got == [
        "s-direct",           # direct, primary
        "s-direct-backup",    # direct, backup
        "s-pan",              # pan, primary
        "s-unlisted",         # pan, tier 未登记 == primary，保持原相对顺序
        "s-pan-backup",       # pan, backup
        "s-no-links",         # no_links, primary
        "s-no-links-backup",  # no_links, backup
        "s-not-found",        # not_found
    ]


def test_backup_sorts_after_primary_within_the_same_outcome():
    prim = gd("p", downloads=[dl("direct")])
    back = gd("b", downloads=[dl("direct")])
    out = order_results([back, prim], {"p": "primary", "b": "backup"})
    assert [d.site_id for d in out] == ["p", "b"]


def test_unknown_site_id_is_treated_as_primary():
    a = gd("unlisted", downloads=[dl("direct")])
    b = gd("b", downloads=[dl("direct")])
    assert [d.site_id for d in order_results([a, b], {"b": "backup"})] == ["unlisted", "b"]


def test_same_key_keeps_original_relative_order():
    a, b, c = (gd(f"s{i}", downloads=[dl("pan")]) for i in range(3))
    tiers = {d.site_id: "primary" for d in (a, b, c)}
    # 输入 c(=s2), a(=s0), b(=s1)：三把键完全相同，必须原样保持
    assert [d.site_id for d in order_results([c, a, b], tiers)] == ["s2", "s0", "s1"]


def test_input_list_is_not_mutated_and_result_is_a_new_list():
    items, tiers = _mixed()
    snapshot = list(items)
    out = order_results(items, tiers)
    assert items == snapshot, "order_results 不许就地改输入"
    assert out is not items
    assert sorted(map(id, out)) == sorted(map(id, items))


def test_empty_input_is_fine():
    assert order_results([], {}) == []


def test_no_results_object_does_not_break_ordering():
    """url=None / title='' 的 NO_RESULTS 也要能排到最后而不炸。"""
    n = GameDetail(site_id="acggw", url=None, title="",
                   error="NO_RESULTS: no content")
    good = gd("good", downloads=[dl("direct")])
    out = order_results([n, good], {"acggw": "primary", "good": "primary"})
    assert [d.site_id for d in out] == ["good", "acggw"]


# ---------------------------------------------------------------------------
# /api/search 真的按排序发帧，且每帧带 outcome
# ---------------------------------------------------------------------------

def _result_frames(body: str) -> list[dict]:
    frames = []
    for blk in body.split("\n\n"):
        lines = blk.split("\n")
        ev = next((l[6:].strip() for l in lines if l.startswith("event:")), None)
        data = next((l[5:].strip() for l in lines if l.startswith("data:")), None)
        if ev == "result" and data:
            frames.append(json.loads(data))
    return frames


def test_search_frames_carry_outcome_and_arrive_sorted(monkeypatch):
    from fastapi.testclient import TestClient

    from finder.web import server as srv

    def fake(config, sites, query, root, use_cache=True):
        # 故意反着给：未找到 / 网盘 / 直链
        return [
            GameDetail(site_id="nf", url=None, title="", error="NO_RESULTS: nope"),
            GameDetail(site_id="pan", url="https://pan.example/1", title="P",
                       downloads=[Download(kind="pan", url="https://pan.example/f")]),
            GameDetail(site_id="direct", url="https://direct.example/1", title="D",
                       downloads=[Download(kind="direct", url="https://direct.example/f")]),
        ]

    monkeypatch.setattr(srv, "_run_pipeline", fake)
    client = TestClient(srv.create_app())
    with client.stream("POST", "/api/search", json={"query": "abc"}) as r:
        body = "".join(r.iter_text())

    frames = _result_frames(body)
    assert [f["site_id"] for f in frames] == ["direct", "pan", "nf"]
    assert [f["outcome"] for f in frames] == ["direct", "pan", "not_found"]
    # 既有字段一个都不许少（UI 仍在用）
    assert {"site_id", "url", "title", "downloads", "error", "extra"} <= set(frames[0])
    assert frames[0]["downloads"][0]["kind"] == "direct"


def test_api_sites_exposes_homepage_and_tier():
    from fastapi.testclient import TestClient

    from finder.web import server as srv

    client = TestClient(srv.create_app())
    r = client.get("/api/sites")
    assert r.status_code == 200
    data = r.json()
    assert data, "站点表不该为空"
    for s in data:
        assert s["homepage"].startswith("http"), s["id"]
        assert s["tier"] in ("primary", "backup"), s["id"]
    # 既有字段不许被删掉
    assert {"id", "name", "langs", "mode", "url_searchable",
            "needs_login", "max_query_len", "kinds"} <= set(data[0])


# ---------------------------------------------------------------------------
# index.html 的静态结构断言（没有 JS 测试运行器，沿用 test_ui_hint.py 的做法）
# ---------------------------------------------------------------------------

def test_html_defines_four_distinct_outcome_styles(src):
    for name in ("direct", "pan", "no_links", "not_found"):
        assert f".card.outcome-{name} " in src, f"缺少 {name} 档的卡片样式"
        assert f".badge.{name} " in src, f"缺少 {name} 档的 badge 样式"


def test_html_has_legend_explaining_the_sort_order(src):
    m = re.search(r'<div class="legend" id="legend">(.*?)</div>', src, re.S)
    assert m, "结果区上方必须有 #legend 图例"
    legend = m.group(1)
    for name in ("direct", "pan", "no_links", "not_found"):
        assert f'class="badge {name}"' in legend, f"图例缺 {name}"
    assert "排序" in legend
    assert "备用站" in legend


def test_html_marks_backup_sites_and_dims_them(src):
    assert "badge backup" in src and "备用站" in src
    assert ".card.backup { opacity" in src, "备用站卡片要淡化"


def test_html_card_link_opens_new_tab_with_noreferrer(src):
    assert "a.target = '_blank'" in src
    assert "a.rel = 'noopener noreferrer'" in src
    assert "'cardlink'" in src


def test_html_card_link_only_accepts_http_and_https(src):
    """站点返回的 URL 直接进 href，必须挡掉 javascript: 之类的值。"""
    assert "/^https?:\\/\\//i" in src


def test_html_title_falls_back_to_site_name_then_site_id(src):
    """NO_RESULTS 的 title 是空串，卡片标题要退回站点名 / site_id。"""
    assert "d.title || site.name || d.site_id" in src
    # 实际跳转目标要用小字亮出来（「定位问题」时要看得到到底开了哪一页）
    assert "跳转：" in src


def test_html_loads_the_site_table_once_for_names_and_homepages(src):
    assert "fetch('/api/sites')" in src
    assert "SITES[s.id] = " in src
    assert "site.homepage" in src


def test_html_does_not_parse_error_prefixes(src):
    """分档只认后端给的 d.outcome —— JS 里不许出现解析错误字串的逻辑。"""
    assert "d.outcome" in src
    assert "error.startsWith" not in src
    assert ".split(':')" not in src


def test_html_keeps_existing_controls(src):
    """既有功能不得回归：强制刷新按钮 / 缓存计数 / 换名提示 / 常驻提示 / 语种行。"""
    for anchor in ('id="refresh"', 'id="hint"', 'id="note"', 'id="langLine"'):
        assert anchor in src
    assert "站来自缓存" in src


# ---------------------------------------------------------------------------
# 上面全是「字串在不在」；下面把内联 JS 真的跑一遍（桩 DOM + node）
# ---------------------------------------------------------------------------
NODE = shutil.which("node")

# 桩 DOM + 只碰 renderCard / safeUrl：验证跳转优先级（详情页 → 站点首页 → 不生成
# 链接）、NO_RESULTS 形状的标题兜底、备用站标签，以及 http(s) 白名单真的挡得住
# javascript: / data: / //evil.example。
_HARNESS = r'''
const fs = require('fs');
function mkEl(tag, cls, text) {
  return { tag, className: cls || '', textContent: text == null ? '' : text,
           title: '', href: '', target: '', rel: '', src: '',
           dataset: {}, style: {}, children: [],
           appendChild(n) { this.children.push(n); return n; },
           remove() {}, addEventListener() {} };
}
global.document = { getElementById: () => mkEl('div'), createElement: t => mkEl(t) };
global.fetch = () => Promise.reject(new Error('no network in harness'));
const src = fs.readFileSync('ui.js', 'utf8');
const api = new Function(src + '\n; return { safeUrl, renderCard, SITES };')();

function find(node, pred, acc = []) {
  if (pred(node)) acc.push(node);
  (node.children || []).forEach(c => find(c, pred, acc));
  return acc;
}
const fails = [];
function check(name, cond, extra) { if (!cond) fails.push(name + ' -> ' + JSON.stringify(extra)); }

api.SITES['acg'] = { name: 'ACG', homepage: 'https://acg.example/', tier: 'primary' };
api.SITES['gamer520'] = { name: 'Gamer520', homepage: 'https://g520.example/', tier: 'backup' };
api.SITES['evil'] = { name: 'Evil', homepage: 'data:text/html,x', tier: 'primary' };
const link = c => find(c, n => n.tag === 'a' && n.className === 'cardlink')[0];

let c = api.renderCard({ site_id: 'acg', url: 'https://acg.example/g/1', title: 'Game A',
                         outcome: 'direct', downloads: [] });
check('detail link', link(c) && link(c).href === 'https://acg.example/g/1', link(c));
check('target/rel', link(c) && link(c).target === '_blank'
                    && link(c).rel === 'noopener noreferrer');
check('direct class', c.className === 'card outcome-direct', c.className);

// NO_RESULTS 实测形状：url=None, title='' → 标题用站点名、链接退回站点首页
c = api.renderCard({ site_id: 'acg', url: null, title: '', outcome: 'not_found',
                     error: 'NO_RESULTS: x', downloads: [] });
check('fallback label', link(c) && link(c).textContent === 'ACG', link(c));
check('fallback href', link(c) && link(c).href === 'https://acg.example/', link(c));
const tgt = find(c, n => n.className === 'target')[0];
check('target url shown', tgt && tgt.textContent === '跳转：https://acg.example/', tgt);

// 恶意 URL：url 与 homepage 都不合法 → 退化成纯文本，一个链接都不生成
c = api.renderCard({ site_id: 'evil', url: 'javascript:alert(1)', title: 'Evil',
                     outcome: 'pan', downloads: [] });
check('no javascript: link', !link(c), link(c));
check('plain title', find(c, n => n.tag === 'h3')[0].textContent === 'Evil');

// site_id 也不在站点表里 → 标题退回 site_id
c = api.renderCard({ site_id: 'ghost', url: null, title: '', outcome: 'not_found', downloads: [] });
check('ghost label', find(c, n => n.tag === 'h3')[0].textContent === 'ghost');

// 备用站：backup class + 「备用站」标签
c = api.renderCard({ site_id: 'gamer520', url: 'https://g520.example/g/2', title: 'Game B',
                     outcome: 'pan', downloads: [] });
check('backup class', c.className.includes('backup'), c.className);
check('backup badge', find(c, n => n.textContent === '备用站').length === 1);

// 缺 outcome 的帧（error 帧就是）→ 退到 not_found，不炸
c = api.renderCard({ site_id: 'system', title: 'x', error: 'boom', downloads: [] });
check('missing outcome', c.className === 'card outcome-not_found', c.className);

for (const [name, want] of [['http://x/y', 'http://x/y'], ['HTTPS://X/y', 'HTTPS://X/y']]) {
  check('safeUrl ' + name, api.safeUrl(name) === want, api.safeUrl(name));
}
for (const bad of ['javascript:alert(1)', 'data:text/html,x', '//evil.example/x', null, '']) {
  check('safeUrl rejects ' + bad, api.safeUrl(bad) === null, api.safeUrl(bad));
}

if (fails.length) { console.log(fails.join('\n')); process.exit(1); }
console.log('js checks passed');
'''


@pytest.mark.skipif(NODE is None, reason="没装 node，跳过内联 JS 的行为检查")
def test_card_jump_logic_actually_runs(tmp_path, src):
    js = re.search(r"<script>([\s\S]*?)</script>", src).group(1)
    (tmp_path / "ui.js").write_text(js, encoding="utf-8")
    (tmp_path / "harness.js").write_text(_HARNESS, encoding="utf-8")
    r = subprocess.run([NODE, "harness.js"], cwd=tmp_path, capture_output=True,
                       text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, f"node 退出码 {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert "js checks passed" in r.stdout
