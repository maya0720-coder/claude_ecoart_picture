from pathlib import Path

import pytest

from app import config

ROOT = Path(__file__).resolve().parent.parent


def test_load_project_config():
    cfg = config.load_config(ROOT / "config.yaml")
    assert cfg["gemini"]["enabled"] is False
    assert cfg["render"]["max_preview_px"] == 1600
    assert cfg["gemini"]["max_send_px"] == 1536
    assert cfg["export"]["watermark"] is True and cfg["export"]["jpeg_quality"] == 92
    assert cfg["export"]["formats"] == ["after", "compare", "pdf", "settings"]
    assert cfg["gemini"]["model"] and cfg["gemini"]["timeout_s"] == 60


def test_partial_config_merged_with_defaults(tmp_path):
    p = tmp_path / "한글폴더" / "config.yaml"
    p.parent.mkdir()
    p.write_text("render:\n  max_preview_px: 800\n", encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg["render"]["max_preview_px"] == 800
    assert cfg["gemini"]["enabled"] is False
    assert cfg["export"]["jpeg_quality"] == 92


def test_defaults_not_mutated(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("export:\n  jpeg_quality: 50\n", encoding="utf-8")
    config.load_config(p)
    assert config.DEFAULTS["export"]["jpeg_quality"] == 92


def test_empty_file_gives_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("", encoding="utf-8")
    assert config.load_config(p) == config.DEFAULTS


def test_missing_explicit_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.load_config(tmp_path / "없음.yaml")


@pytest.mark.parametrize("text", [
    "- a\n- b\n",
    "render:\n  max_preview_px: -1\n",
    "export:\n  jpeg_quality: 101\n",
    "gemini:\n  enabled: \"yes\"\n",
])
def test_invalid_config_rejected(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config(p)


def test_user_data_dir_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config.user_data_dir() == tmp_path / "CorkWalkway"


def test_resource_paths():
    assert config.app_root() == ROOT
    assert config.resolve_resource("config.yaml") == ROOT / "config.yaml"
    assert (ROOT / "materials" / "cork" / "presets.yaml").exists()
