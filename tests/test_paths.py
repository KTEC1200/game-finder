"""运行形态路径解析：开发 / 打包两种形态。

打包后最关键的一条：**可写数据必须在 exe 旁边**，不能落在 PyInstaller 的
只读临时解包目录里，否则用户的 config 改动、缓存库、Chrome profile 全部丢失。
"""
from __future__ import annotations

import sys

import pytest

from finder import paths


@pytest.fixture()
def frozen(monkeypatch, tmp_path):
    """模拟 PyInstaller 运行形态：exe 在 app/，只读资源在 bundle/。"""
    app = tmp_path / "app"
    bundle = tmp_path / "bundle"
    app.mkdir()
    bundle.mkdir()
    exe = app / "game-finder.exe"
    exe.write_bytes(b"MZ")
    (bundle / "config.yaml").write_text("proxy: {}\n", encoding="utf-8")
    (bundle / "sites.yaml").write_text("sites: []\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    return app, bundle


def test_dev_mode_roots_are_the_project_root():
    if paths.is_frozen():  # pragma: no cover - 正常跑 pytest 不会走到
        pytest.skip("running frozen")
    assert paths.bundle_root() == paths.app_root()
    assert (paths.app_root() / "config.yaml").exists()


def test_frozen_bundle_root_is_meipass(frozen):
    _, bundle = frozen
    assert paths.bundle_root() == bundle


def test_frozen_app_root_is_next_to_exe(frozen):
    app, _ = frozen
    assert paths.app_root() == app


def test_frozen_config_and_sites_are_next_to_exe(frozen):
    app, _ = frozen
    assert paths.config_path() == app / "config.yaml"
    assert paths.sites_path() == app / "sites.yaml"


def test_ensure_runtime_files_copies_templates_when_frozen(frozen):
    app, bundle = frozen
    root = paths.ensure_runtime_files()
    assert root == app
    assert (app / "config.yaml").read_text(encoding="utf-8") == \
        (bundle / "config.yaml").read_text(encoding="utf-8")
    assert (app / "sites.yaml").exists()


def test_ensure_runtime_files_never_overwrites_user_edits(frozen):
    """升级不能把用户改过的 config 冲掉。"""
    app, _ = frozen
    (app / "config.yaml").write_text("# my edits\n", encoding="utf-8")
    paths.ensure_runtime_files()
    assert (app / "config.yaml").read_text(encoding="utf-8") == "# my edits\n"


def test_ensure_runtime_files_is_idempotent(frozen):
    app, _ = frozen
    paths.ensure_runtime_files()
    first = (app / "config.yaml").stat().st_mtime_ns
    paths.ensure_runtime_files()
    assert (app / "config.yaml").stat().st_mtime_ns == first


def test_data_dir_is_created_under_app_root(frozen):
    app, _ = frozen
    d = paths.data_dir()
    assert d == app / "data"
    assert d.is_dir()


def test_static_dir_points_at_the_package():
    """前端资源跟着 Python 包走，不在 exe 旁边。"""
    static = paths.static_dir()
    assert static.name == "static"
    assert static.parent.name == "web"
    assert (static / "index.html").exists()


def test_describe_reports_both_roots(frozen):
    info = paths.describe()
    assert info["frozen"] == "True"
    assert info["bundle_root"] != info["app_root"]
    assert set(info) >= {"bundle_root", "app_root", "config", "sites",
                         "data", "static"}


def test_dev_mode_ensure_runtime_files_is_a_noop():
    """开发形态下源和目标同一个文件，绝不能自我复制。"""
    if paths.is_frozen():  # pragma: no cover
        pytest.skip("running frozen")
    before = (paths.app_root() / "config.yaml").read_text(encoding="utf-8")
    paths.ensure_runtime_files()
    assert (paths.app_root() / "config.yaml").read_text(encoding="utf-8") == before
