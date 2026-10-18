"""站点分级：tier = primary（主力站）/ backup（备用站）。

注册表里绝大多数站是主力站，只有实测体验/覆盖明显更弱的站才降到 backup
（gamer520 实测：中文能出结果，但站内搜索页对英文/日文查询基本无效）。
"""
from pathlib import Path

import pytest

from finder.models import SearchSpec, Site
from finder.sites import load_sites

PROJECT = Path(__file__).resolve().parent.parent


def _write_sites_yaml(tmp_path: Path, tier_line: str) -> Path:
    p = tmp_path / "sites.yaml"
    p.write_text(
        "sites:\n"
        "  - id: demo\n"
        "    name: Demo\n"
        '    homepage: "https://demo.example/"\n'
        "    kinds: [直链]\n"
        "    langs: [zh]\n"
        f"{tier_line}"
        "    search:\n"
        "      mode: url\n"
        '      url_template: "https://demo.example/?q={q}"\n',
        encoding="utf-8",
    )
    return p


def test_site_dataclass_defaults_to_primary():
    s = Site(
        id="x", name="X", homepage="https://x.example/", kinds=[],
        langs={"zh"}, url_searchable=True,
        search=SearchSpec(mode="url", url_template="https://x.example/?q={q}"),
    )
    assert s.tier == "primary"


def test_load_sites_defaults_missing_tier_to_primary(tmp_path):
    sites = load_sites(_write_sites_yaml(tmp_path, ""))
    assert [s.tier for s in sites] == ["primary"]


def test_load_sites_reads_explicit_backup(tmp_path):
    sites = load_sites(_write_sites_yaml(tmp_path, "    tier: backup\n"))
    assert [s.tier for s in sites] == ["backup"]


def test_load_sites_rejects_unknown_tier(tmp_path):
    with pytest.raises(ValueError, match="tier"):
        load_sites(_write_sites_yaml(tmp_path, "    tier: sometimes\n"))


def test_gamer520_is_the_only_backup_site():
    sites = load_sites(PROJECT / "sites.yaml")
    by_id = {s.id: s for s in sites}
    assert by_id["gamer520"].tier == "backup"
    others = {s.id: s.tier for s in sites if s.id != "gamer520"}
    assert set(others.values()) == {"primary"}, others
