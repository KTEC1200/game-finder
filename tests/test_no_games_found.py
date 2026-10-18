"""ankergames 的空结果文案。

实测依据（2026-10-18）：`https://ankergames.net/search/制服カノジョ` 页面正文
只有 733 字符，明确写着
`No games found / Try different filters or browse the full catalogue.`
——该站是英文库，查日文游戏名确实 0 条。少了这条标记就会掉进
"NO_RESULTS: pick_best returned None"，看不出是站点真的没有。
"""
from __future__ import annotations

from finder.pipeline import looks_no_results

BODY = (
    'Search results for "制服カノジョ" Filter Newest Action 1256 games '
    "Adventure 1131 games Horror 274 games No games found\n\n"
    "Try different filters or browse the full catalogue.\n\nBrowse all games"
)
HTML = f"<div>{BODY}</div>"


def test_ankergames_empty_catalogue_is_recognised():
    assert looks_no_results(HTML)
