"""缺陷 5：WRONG_GAME 时不能把错游戏的标题留在卡片上。

真站现场（2026-10-18，ankergames 查 `summer clover`）：
    hits=28，pick_best 选中 **Castlevania**（完全无关），`_query_evidence = 0`
    → 旧代码回 `WRONG_GAME: no query evidence in page`，
    但卡片仍然显示 **Castlevania** 的标题、match=strong —— 用户看起来像「找到了」。

修法：产生 WRONG_GAME 的地方清空 `card.title`，原值留进
`extra["wrong_game_title"]` / `extra["wrong_game_url"]` 供诊断。
`pick_best` 的选择逻辑一个字都不动。
"""
from finder.models import SearchSpec, Site
from finder.pipeline import search_one

SEARCH_HTML = (
    "<html><body><h2>搜索结果</h2>"
    '<a href="/game/castlevania-sotn">Castlevania: Symphony of the Night</a>'
    "</body></html>"
)
DETAIL_HTML = (
    '<html><head><meta property="og:title" content="Castlevania: Symphony of the Night">'
    "</head><body><p>Dracula's castle, Alucard, Belmont</p>"
    '<a href="https://pan.baidu.com/s/WRONGGAME">下载</a></body></html>'
)


class _FakePage:
    def __init__(self, pages):
        self._pages = pages
        self.url = "about:blank"

    def goto(self, url, **kw):
        self.url = url
        return type("_R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def content(self):
        return (self._pages.get(self.url) or self._pages["*"])["html"]

    def title(self):
        return (self._pages.get(self.url) or self._pages["*"]).get("title", "")

    def evaluate(self, script):
        return (self._pages.get(self.url) or self._pages["*"]).get("text", "")


def _ankergames() -> Site:
    return Site(
        id="ankergames",
        name="AnkerGames",
        homepage="https://ankergames.test/",
        kinds=["直链"],
        langs={"en"},
        url_searchable=True,
        search=SearchSpec(mode="url", url_template="https://ankergames.test/search?q={q}"),
    )


def _page() -> _FakePage:
    return _FakePage(
        {
            "https://ankergames.test/search?q=summer%20clover": {
                "html": SEARCH_HTML,
                "title": "搜索",
            },
            "https://ankergames.test/game/castlevania-sotn": {
                "html": DETAIL_HTML,
                "title": "Castlevania: Symphony of the Night",
                "text": "Dracula's castle, Alucard, Belmont",
            },
            "*": {"html": "", "title": "", "text": ""},
        }
    )


def test_wrong_game_clears_card_title_and_keeps_original_in_extra():
    card = search_one(_page(), _ankergames(), "summer clover", timeout_ms=500)
    # 先确认真的走了「选错游戏」这条路径
    assert card.extra["best_url"] == "https://ankergames.test/game/castlevania-sotn"
    assert card.extra["evidence"] == 0
    assert card.error is not None and card.error.startswith("WRONG_GAME")
    assert card.title == "", "WRONG_GAME 时不能把错游戏的标题显示给用户"
    assert card.extra["wrong_game_title"] == "Castlevania: Symphony of the Night"
    assert card.extra["wrong_game_url"] == "https://ankergames.test/game/castlevania-sotn"
    assert card.downloads == []


def test_wrong_game_title_is_the_raw_picked_title_even_when_empty():
    """选中的页面连标题都抽不到时，extra 里也要有键（值为空串），不要炸。"""
    page = _page()
    page._pages["https://ankergames.test/game/castlevania-sotn"]["html"] = (
        "<html><body><p>nothing here</p></body></html>"
    )
    page._pages["https://ankergames.test/game/castlevania-sotn"]["title"] = ""
    card = search_one(page, _ankergames(), "summer clover", timeout_ms=500)
    assert card.error.startswith("WRONG_GAME")
    assert "wrong_game_title" in card.extra
    assert card.title == ""


def test_good_card_keeps_its_title():
    """有证据时标题照旧保留（不能因为本修复被清空）。"""
    page = _page()
    page._pages["https://ankergames.test/game/castlevania-sotn"]["html"] = (
        '<html><head><meta property="og:title" content="Summer Clover"></head>'
        "<body><p>summer clover</p>"
        '<a href="https://pan.baidu.com/s/GOOD">下载</a></body></html>'
    )
    page._pages["https://ankergames.test/game/castlevania-sotn"]["title"] = "Summer Clover"
    card = search_one(page, _ankergames(), "summer clover", timeout_ms=500)
    assert card.error is None
    assert "Summer Clover" in card.title
    assert "wrong_game_title" not in card.extra
