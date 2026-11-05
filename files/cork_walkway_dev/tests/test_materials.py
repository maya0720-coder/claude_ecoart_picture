"""사용자 추가 소재 저장소: 입력 검증, 메타데이터 제거, 경로 조작 차단."""
import json

import cv2
import numpy as np
import pytest
from PIL import Image

from app.core import materials as mt


def _png(path, h=200, w=300):
    cv2.imencode(".png", np.full((h, w, 3), 120, np.uint8))[1].tofile(str(path))
    return path


def test_add_list_remove(tmp_path):
    root = tmp_path / "소재"
    m = mt.add_custom(_png(tmp_path / "돌.png"), "  화강석\t블록  ", root=root)
    assert m.name == "화강석 블록" and mt._ID_RE.match(m.id) and m.reference.is_file()
    assert [x.id for x in mt.list_custom(root)] == [m.id]
    mt.remove_custom(m.id, root=root)
    assert mt.list_custom(root) == [] and not (root / m.id).exists()


def test_sample_resized_and_exif_removed(tmp_path):
    src = tmp_path / "big.jpg"
    exif = Image.Exif()
    exif[0x010F] = "CameraMaker"
    Image.fromarray(np.full((1500, 3000, 3), 90, np.uint8)).save(src, exif=exif)
    m = mt.add_custom(src, "타일", root=tmp_path / "r")
    with Image.open(m.reference) as im:
        assert max(im.size) == mt.SAMPLE_MAX_PX and not im.getexif()


@pytest.mark.parametrize("name", ["", "   ", "\n\t"])
def test_name_required(tmp_path, name):
    with pytest.raises(ValueError, match="이름"):
        mt.add_custom(_png(tmp_path / "a.png"), name, root=tmp_path / "r")


def test_name_trimmed_to_limit():
    assert len(mt.clean_name("가" * 100)) == mt.NAME_MAX


def test_bad_files_rejected(tmp_path):
    bad = tmp_path / "fake.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="읽을 수 없는"):
        mt.add_custom(bad, "x", root=tmp_path / "r")
    with pytest.raises(ValueError, match="찾을 수 없"):
        mt.add_custom(tmp_path / "없음.jpg", "x", root=tmp_path / "r")
    with pytest.raises(ValueError, match="작습니다"):
        mt.add_custom(_png(tmp_path / "tiny.png", 20, 20), "x", root=tmp_path / "r")


def test_too_large_file_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(mt, "MAX_FILE_MB", 0)
    with pytest.raises(ValueError, match="너무 큽니다"):
        mt.add_custom(_png(tmp_path / "a.png"), "x", root=tmp_path / "r")


def test_limit_count(tmp_path, monkeypatch):
    monkeypatch.setattr(mt, "MAX_CUSTOM", 1)
    root = tmp_path / "r"
    mt.add_custom(_png(tmp_path / "a.png"), "a", root=root)
    with pytest.raises(ValueError, match="개까지"):
        mt.add_custom(_png(tmp_path / "b.png"), "b", root=root)


@pytest.mark.parametrize("bad", ["..", "../x", "custom_../../etc", "custom_ABCDEFGH", "", "natural_brown"])
def test_remove_rejects_bad_ids(tmp_path, bad):
    with pytest.raises(ValueError):
        mt.remove_custom(bad, root=tmp_path)


def test_list_skips_foreign_and_broken_folders(tmp_path):
    root = tmp_path / "r"
    good = mt.add_custom(_png(tmp_path / "a.png"), "좋음", root=root)
    (root / "other").mkdir()
    _png(root / "other" / mt.SAMPLE_NAME)
    broken = root / "custom_0badc0de"
    broken.mkdir()
    _png(broken / mt.SAMPLE_NAME)
    (broken / mt.META_NAME).write_text("{bad json", encoding="utf-8")
    empty_name = root / "custom_12345678"
    empty_name.mkdir()
    _png(empty_name / mt.SAMPLE_NAME)
    (empty_name / mt.META_NAME).write_text(json.dumps({"name": ""}), encoding="utf-8")
    assert [m.id for m in mt.list_custom(root)] == [good.id]
    assert mt.list_custom(tmp_path / "없는폴더") == []
