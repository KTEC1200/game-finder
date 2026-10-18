"""Environment sanity: the three things every later task assumes."""
from pathlib import Path
import yaml

PROJECT = Path(__file__).resolve().parent.parent


def test_project_importable():
    import finder
    assert finder.__file__.endswith("__init__.py")


def test_config_yaml_has_required_keys():
    cfg = yaml.safe_load((PROJECT / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["proxy"]["server"] == "http://127.0.0.1:6234"
    assert cfg["browser"]["headless"] is True
    assert Path(cfg["browser"]["chrome_path"]).exists()
    assert cfg["search"]["timeout_ms"] > 0
    assert cfg["cache"]["ttl_hours"] > 0


def test_playwright_importable():
    import playwright  # noqa: F401
