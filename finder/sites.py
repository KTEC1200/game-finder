"""载入并校验站点注册表。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import SearchSpec, Site

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "sites.yaml"


def load_sites(path: Path | str | None = None) -> list[Site]:
    p = Path(path) if path else DEFAULT_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    out: list[Site] = []
    for item in raw["sites"]:
        s = item["search"]
        spec = SearchSpec(
            mode=s["mode"],
            url_template=s.get("url_template"),
            form_url=s.get("form_url"),
            input_selector=s.get("input_selector"),
            open_selector=s.get("open_selector"),
            submit_selector=s.get("submit_selector"),
            result_link_selector=s.get("result_link_selector"),
            title_selector=s.get("title_selector"),
            index_url=s.get("index_url"),
            detail_open_selector=s.get("detail_open_selector"),
            detail_follow_pattern=s.get("detail_follow_pattern"),
            torrent_selector=s.get("torrent_selector"),
            download_flow=s.get("download_flow"),
            download_open_selector=s.get("download_open_selector"),
        )
        out.append(
            Site(
                id=item["id"],
                name=item["name"],
                homepage=item["homepage"],
                kinds=list(item.get("kinds") or []),
                langs=set(item.get("langs") or []),
                url_searchable=(spec.mode == "url"),
                search=spec,
                tags=set(item.get("tags") or []),
                needs_login=bool(item.get("needs_login", False)),
                max_query_len=item.get("max_query_len"),
                adapter_status=item.get("adapter_status", "untested"),
                force_headful=bool(item.get("force_headful", False)),
            )
        )
    return out


def filter_sites_by_lang(
    all_sites: list[Site], lang: str
) -> tuple[list[Site], list[Site]]:
    """按语种分流。返回 (参与搜索的站点, 被跳过的站点)。"""
    part = [s for s in all_sites if lang in s.langs]
    skipped = [s for s in all_sites if lang not in s.langs]
    return part, skipped
