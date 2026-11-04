import ast
import base64
import logging
import re
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app import config
from app.core.image_io import load_image
from app.security import privacy as pv

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


@pytest.fixture
def appdirs(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    yield tmp_path
    for h in logging.getLogger("corkwalkway").handlers:
        h.close()
    logging.getLogger("corkwalkway").handlers.clear()


def scene_with_gps(tmp_path):
    img = np.zeros((600, 800, 3), np.uint8)
    img[:] = (60, 140, 70)
    mask = np.zeros((600, 800), np.uint8)
    mask[300:600, 300:500] = 255
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (37.0, 30.0, 0.0)
    p = tmp_path / "현장.jpg"
    Image.fromarray(img[:, :, ::-1]).save(p, exif=exif)
    return load_image(str(p)), mask


def test_prepare_for_send_no_exif_and_limits(tmp_path):
    img, mask = scene_with_gps(tmp_path)
    data, (x, y, w, h) = pv.prepare_for_send(img, mask, max_px=150)
    assert data[:2] == b"\xff\xd8"
    assert b"Exif" not in data and b"PhoneMaker" not in data
    dec = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert max(dec.shape[:2]) <= 150                      # 최대 해상도 이하
    assert dec.shape[0] <= h and dec.shape[1] <= w        # 잘린 영역 이하
    # 마스크 외접 사각형 x 300~500, y 300~600 + 10% 여유, 사진 경계에서 자름
    assert (x, y, w, h) == (280, 270, 240, 330)
    assert w * h < img.shape[0] * img.shape[1]            # 전체 사진 전송 아님
    with Image.open(BytesIO(data)) as im:
        assert len(im.getexif()) == 0


def test_prepare_for_send_small_crop_not_upscaled():
    img = np.zeros((100, 100, 3), np.uint8)
    mask = np.zeros((100, 100), np.uint8)
    mask[40:60, 40:60] = 255
    data, (x, y, w, h) = pv.prepare_for_send(img, mask, max_px=1536)
    dec = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert dec.shape[:2] == (h, w) == (24, 24)


def test_prepare_for_send_errors():
    img = np.zeros((10, 10, 3), np.uint8)
    with pytest.raises(ValueError):
        pv.prepare_for_send(img, np.zeros((10, 10), np.uint8), 100)
    with pytest.raises(ValueError):
        pv.prepare_for_send(img, np.full((5, 5), 255, np.uint8), 100)
    with pytest.raises(ValueError):
        pv.prepare_for_send(img, np.full((10, 10), 255, np.uint8), 0)


def test_log_has_no_base64_or_key(appdirs):
    path = pv.setup_logging()
    log = logging.getLogger("corkwalkway")
    blob = base64.b64encode(np.random.default_rng(0).bytes(3000)).decode()
    log.info("응답: %s", blob)
    log.info("data:image/jpeg;base64," + blob[:500])
    log.warning("키 AIzaSyD-abcdefghijklmnopqrstuvwxyz012345 사용")
    try:
        raise RuntimeError("server said " + blob[:300])
    except RuntimeError:
        log.exception("Gemini 호출 실패")
    pv.TransferLog().add((1024, 768), (2000, 1500))
    for h in log.handlers:
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z0-9+/]{64,}", text)
    assert "AIza" not in text
    assert "Gemini 호출 실패" in text and "RuntimeError" in text
    assert "1024x768" in text
    assert str(path).startswith(str(appdirs / "Roaming"))


def test_transfer_log_records_metadata_only():
    tl = pv.TransferLog()
    r = tl.add((1024, 768), (2000, 1500), images=2)
    assert tl.entries() == [r]
    assert r.target == pv.SEND_TARGET and r.sent_size == (1024, 768) and r.images == 2
    assert not any(isinstance(v, (bytes, np.ndarray)) for v in r.__dict__.values())


def test_send_consent_only_this_run():
    c = pv.SendConsent()
    assert c.needs_confirmation()
    c.skip_for_this_run()
    assert not c.needs_confirmation()
    assert pv.SendConsent().needs_confirmation()          # 새 실행 = 다시 묻는다
    assert not any("confirm" in k and "paid" not in k for k in config.USER_DEFAULTS)   # 영구 생략 설정 없음


def test_cleanup_temp(appdirs):
    d = pv.temp_dir()
    assert d == appdirs / "Local" / "CorkWalkway" / "temp"
    (d / "a.jpg").write_bytes(b"x")
    (d / "하위").mkdir()
    (d / "하위" / "b.png").write_bytes(b"y")
    pv.cleanup_temp()
    assert list(d.iterdir()) == []


def test_user_settings_roundtrip(appdirs):
    s = config.load_user_settings()
    assert s["gemini_enabled"] is False and s["gemini_paid_key_confirmed"] is False
    s["gemini_paid_key_confirmed"] = True
    s["api_key"] = "AIza-should-not-be-saved"
    config.save_user_settings(s)
    f = appdirs / "Roaming" / "CorkWalkway" / "settings.json"
    assert "AIza" not in f.read_text(encoding="utf-8")
    assert config.load_user_settings()["gemini_paid_key_confirmed"] is True
    f.write_text("{broken", encoding="utf-8")
    assert config.load_user_settings() == config.USER_DEFAULTS
    f.write_text('{"gemini_enabled": "yes"}', encoding="utf-8")   # 형식이 다른 값은 무시
    assert config.load_user_settings()["gemini_enabled"] is False


# ---- 정적 검사: 네트워크·키 ----
def py_files():
    return list(APP.rglob("*.py"))


def test_only_allowed_host_in_code():
    urls = []
    for p in py_files():
        urls += re.findall(r"https?://[^\s\"')]+", p.read_text(encoding="utf-8"))
    assert all(pv.ALLOWED_HOST in u for u in urls), urls


def test_no_direct_network_modules():
    banned = {"requests", "urllib", "http", "socket", "httpx", "aiohttp", "websockets", "ftplib", "smtplib"}
    for p in py_files():
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for n in names:
                assert n.split(".")[0] not in banned, f"{p.name}: {n}"


def test_no_key_literals_in_code_or_config():
    for p in py_files() + [ROOT / "config.yaml"]:
        assert not re.search(r"AIza[0-9A-Za-z_-]{20,}", p.read_text(encoding="utf-8")), p.name
