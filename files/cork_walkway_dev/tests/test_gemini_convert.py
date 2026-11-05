"""간편 모드 Gemini 변환: 실제 SDK 경로를 가짜 통신(httpx.MockTransport)으로 오프라인 검증."""
import base64
import json
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

from app.ai import gemini_convert as gc
from app.ai.gemini_hq import HQError
from app.config import DEFAULTS
from app.core.compositor import verify_outside_unchanged
from app.core.cork_material import CorkPreset
from app.models import WorkSession
from app.security.privacy import SendConsent, TransferLog
from synth import iou, make_scene

KEY = "AIzaFAKEKEYFORTESTS0123456789abcd"
PRESET = CorkPreset("natural_brown", "내추럴 브라운", None, ["#C9A27F", "#B88F6C"], 3.0)


def b64dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jpeg_b64(img):
    return base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()).decode()


class FakeGemini:
    """받은 사진의 길(합성 장면 기준)만 코르크 색으로 칠해 돌려주는 가짜 서버."""

    def __init__(self, path_mask, mode="ok"):
        self.path_mask, self.mode, self.requests = path_mask, mode, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.mode == "quota":
            return httpx.Response(429, json={"error": {"code": 429, "message": "q", "status": "RESOURCE_EXHAUSTED"}})
        if self.mode == "prepay":          # 실제 응답 형식(2026-11-05 확인): 선불 크레딧 소진
            msg = ("Your prepayment credits are depleted. Please go to AI Studio to manage your project and billing.")
            return httpx.Response(402, json={"error": {"code": 402, "message": msg, "status": "RESOURCE_EXHAUSTED"}})
        if self.mode == "free":            # 실제 응답 형식: 무료 등급 프로젝트는 이미지 모델 할당량 0
            msg = ("You exceeded your current quota. * Quota exceeded for metric: generativelanguage.googleapis.com/"
                   "generate_content_free_tier_requests, limit: 0, model: gemini-nano-banana-2.1")
            return httpx.Response(429, json={"error": {"code": 429, "message": msg, "status": "RESOURCE_EXHAUSTED"}})
        parts = json.loads(request.content)["contents"][0]["parts"]
        photo = cv2.imdecode(np.frombuffer(b64dec(parts[1]["inlineData"]["data"]), np.uint8), cv2.IMREAD_COLOR)
        h, w = photo.shape[:2]
        m = cv2.resize(self.path_mask, (w, h), interpolation=cv2.INTER_NEAREST) > 0
        out = photo.astype(np.int16)
        if self.mode in ("ok", "drift"):
            rng = np.random.default_rng(0)
            out[m] = rng.normal((125, 160, 200), 10, (m.sum(), 3))           # 코르크 색 길
            out += 3                                                          # 모델이 전체 색을 살짝 바꿈
        if self.mode == "drift":                                              # 2px 밀림 → 정렬로 복구
            out = cv2.warpAffine(out.astype(np.float32), np.float32([[1, 0, 2], [0, 1, -1]]), (w, h),
                                 borderMode=cv2.BORDER_REPLICATE)
        if self.mode == "all":
            out = 255 - out                                                   # 사진 전체가 바뀜
        if self.mode == "crop":                                               # 비율이 다른 엉뚱한 결과
            out = out[: h // 2]
        img = np.clip(out, 0, 255).astype(np.uint8)
        body = {"candidates": [{"content": {"role": "model", "parts": [
            {"inlineData": {"mimeType": "image/jpeg", "data": jpeg_b64(img)}}]}, "finishReason": "STOP"}]}
        return httpx.Response(200, json=body)


def converter(fake, materials_dir=None, settings=None, confirmed=True):
    cfg = {"gemini": dict(DEFAULTS["gemini"], model="gemini-nano-banana-2.1")}
    st = {"gemini_enabled": True, "gemini_paid_key_confirmed": True} if settings is None else settings
    c = SendConsent()
    if confirmed:
        c.skip_for_this_run()
    return gc.GeminiConvert(cfg, c, TransferLog(), materials_dir=materials_dir, key_getter=lambda n: KEY,
                            settings_getter=lambda: st, network_check=lambda: True,
                            httpx_client=httpx.Client(transport=httpx.MockTransport(fake)))


@pytest.fixture
def scene():
    sc = make_scene(900, 1200)
    return sc, WorkSession(sc.img, "a.jpg")


@pytest.mark.parametrize("mode", ["ok", "drift"])
def test_convert_success_outside_unchanged(scene, mode):
    sc, s = scene
    fake = FakeGemini(sc.path, mode)
    conv = converter(fake)
    pkg = conv.prepare_full(s, PRESET)
    result, mask = conv.convert(s, pkg)
    assert result.shape == s.original.shape and mask.shape == s.original.shape[:2]
    assert iou(mask, sc.path) > 0.85                                   # 바뀐 영역 = 길
    assert verify_outside_unchanged(s.original, result, mask, gc.FEATHER_PX)
    outside = cv2.dilate(mask, np.ones((25, 25), np.uint8)) == 0
    assert np.array_equal(result[outside], s.original[outside])        # 전체 색 변화(+3)는 반영 안 됨
    inside = cv2.erode(sc.path, np.ones((25, 25), np.uint8)) > 0
    assert abs(result[inside].mean(0) - (125, 160, 200)).max() < 25     # 길은 코르크 색
    assert len(conv.transfer_log.entries()) == 1


def test_request_shape_no_reference(scene):
    sc, s = scene
    fake = FakeGemini(sc.path)
    conv = converter(fake)
    conv.convert(s, conv.prepare_full(s, PRESET))
    req = fake.requests[0]
    assert req.url.host == "generativelanguage.googleapis.com"
    assert "gemini-nano-banana-2.1:generateContent" in req.url.path
    body = json.loads(req.content)
    parts = body["contents"][0]["parts"]
    assert len(parts) == 2 and "text" in parts[0] and "inlineData" in parts[1]
    assert "fileData" not in req.content.decode()                      # Files API 금지
    assert "#" in parts[0]["text"]                                      # 프리셋 색이 프롬프트에 들어감
    sent = cv2.imdecode(np.frombuffer(b64dec(parts[1]["inlineData"]["data"]), np.uint8), cv2.IMREAD_COLOR)
    assert max(sent.shape[:2]) <= DEFAULTS["gemini"]["max_send_px"]
    assert sent.shape[1] / sent.shape[0] == pytest.approx(1200 / 900, rel=0.01)   # 사진 전체(크롭 아님)
    assert conv.transfer_log.entries()[0].images == 1


def test_reference_image_sent(scene, tmp_path):
    sc, s = scene
    d = tmp_path / "자재" / PRESET.id
    d.mkdir(parents=True)
    cv2.imencode(".jpg", np.full((300, 900, 3), (110, 150, 190), np.uint8))[1].tofile(str(d / gc.REFERENCE_NAME))
    fake = FakeGemini(sc.path)
    conv = converter(fake, materials_dir=tmp_path / "자재")
    pkg = conv.prepare_full(s, PRESET)
    assert pkg.guide_jpeg and "참고 사진" in pkg.description
    conv.convert(s, pkg)
    parts = json.loads(fake.requests[0].content)["contents"][0]["parts"]
    assert len(parts) == 3 and "Image 2" in parts[0]["text"]
    assert conv.transfer_log.entries()[0].images == 2


@pytest.mark.parametrize("mode, words", [("all", "전체"), ("crop", "구도"), ("quota", "한도"), ("same", "찾지 못"),
                                         ("free", "무료 등급.*결제"), ("prepay", "선불 크레딧.*충전")])
def test_convert_failures(scene, mode, words):
    sc, s = scene
    conv = converter(FakeGemini(sc.path, mode))
    with pytest.raises(HQError, match=words):
        conv.convert(s, conv.prepare_full(s, PRESET))


def test_needs_confirmation_and_availability(scene):
    sc, s = scene
    fake = FakeGemini(sc.path)
    conv = converter(fake, confirmed=False)
    pkg = conv.prepare_full(s, PRESET)
    with pytest.raises(HQError, match="확인"):
        conv.convert(s, pkg)
    off = converter(fake, settings={})
    with pytest.raises(HQError, match="꺼져"):
        off.convert(s, off.prepare_full(s, PRESET))
    assert fake.requests == []                                          # 아무것도 보내지 않음


def test_change_mask_fills_small_holes_only():
    h, w = 400, 600
    a = np.full((h, w, 3), 100, np.uint8)
    b = a.copy()
    b[100:300, 100:500] = (40, 120, 200)
    b[190:210, 290:310] = 100                       # 작은 구멍 → 메움
    b[120:280, 380:480] = 100                       # 큰 구멍(길 안 잔디밭) → 그대로
    m = gc.change_mask(a, b) > 0
    assert m[200, 300] and not m[200, 430] and m[150, 200]
    assert not m[50, 50]


def test_prompt_has_rules():
    p = gc.build_prompt(PRESET, False)
    for word in ("ONLY", "Do not add", "perspective"):
        assert word in p
    assert "Image 2" not in p and "Image 2" in gc.build_prompt(PRESET, True)


# ---- 결과 해상도·엉뚱한 결과 ----
def other_photo(h, w):
    """전혀 다른 사진(하늘·건물 색 띠 + 잡음)."""
    rng = np.random.default_rng(7)
    img = np.zeros((h, w, 3), np.float32)
    img[: h // 2] = (200, 160, 120)
    img[h // 2:] = (90, 90, 95)
    img[h // 4: h // 2, w // 3: 2 * w // 3] = (40, 40, 160)
    return np.clip(img + rng.normal(0, 10, img.shape), 0, 255).astype(np.uint8)


@pytest.mark.parametrize("size", [None, (1024, 768), (2048, 1536)])   # 모델이 다른 해상도로 돌려줘도 맞춘다
def test_merge_edited_any_resolution(size):
    sc = make_scene(900, 1200)
    m = sc.path > 0
    out = sc.img.astype(np.int16)
    out[m] = np.random.default_rng(0).normal((125, 160, 200), 10, (m.sum(), 3))
    edited = np.clip(out + 3, 0, 255).astype(np.uint8)
    if size:
        edited = cv2.resize(edited, size, interpolation=cv2.INTER_AREA)
    result, mask = gc.merge_edited(sc.img, edited)
    assert iou(mask, sc.path) > 0.85
    assert verify_outside_unchanged(sc.img, result, mask, gc.FEATHER_PX)


def test_merge_rejects_different_photo():
    sc = make_scene(900, 1200)
    with pytest.raises(HQError):
        gc.merge_edited(sc.img, other_photo(900, 1200))


# ---- 길 중간 깨짐(코르크·흙 색이 비슷해 덜 바뀐 얼룩) ----
def test_patchy_edit_mask_has_no_holes():
    sc = make_scene(900, 1200)
    m = sc.path > 0
    rng = np.random.default_rng(1)
    out = sc.img.astype(np.float32)
    cork = rng.normal((125, 160, 200), 10, (m.sum(), 3))
    out[m] = cork
    blobs = np.zeros(m.shape, np.uint8)
    # 덜 바뀐 곳(색차 작음): 길 가운데 큰 얼룩 + 길 가장자리에 걸친 얼룩(구멍이 아니라 움푹 팬 모양)
    for (x, y, r) in [(600, 610, 100), (385, 760, 70)]:
        cv2.circle(blobs, (x, y), r, 1, -1)
    same = np.zeros(m.shape, np.uint8)
    cv2.circle(same, (560, 450), 45, 1, -1)                                  # 전혀 안 바뀐 곳
    weak = (blobs > 0) & m
    out[weak] = 0.8 * sc.img[weak] + 0.2 * out[weak]
    out[(same > 0) & m] = sc.img[(same > 0) & m]
    edited = np.clip(out + 3, 0, 255).astype(np.uint8)                       # 모델 전체 톤 변화
    result, mask = gc.merge_edited(sc.img, edited)
    inner = cv2.erode(sc.path, np.ones((15, 15), np.uint8)) > 0
    assert (mask[inner] > 0).mean() > 0.995                                   # 길 안쪽에 구멍 없음
    assert iou(mask, sc.path) > 0.9
    assert verify_outside_unchanged(sc.img, result, mask, gc.feather_for(sc.img.shape))[0]


def test_change_mask_keeps_side_grass_touching_border():
    h, w = 400, 600
    a = np.full((h, w, 3), 100, np.uint8)
    b = a.copy()
    b[:, 200:400] = (40, 120, 200)                  # 위아래 테두리까지 이어진 길
    m = gc.change_mask(a, b) > 0
    assert not m[200, 50] and not m[200, 550] and m[200, 300]    # 길 옆 풀밭(테두리에 넓게 닿음)은 그대로


# ---- 사용자 소재·추가 요청 ----
def test_custom_material_and_note_sent(scene, tmp_path):
    from app.core.materials import add_custom
    sc, s = scene
    src = tmp_path / "샘플.png"
    cv2.imencode(".png", np.full((200, 300, 3), (90, 90, 90), np.uint8))[1].tofile(str(src))
    mat = add_custom(src, "화강석 블록", root=tmp_path / "mats")
    fake = FakeGemini(sc.path)
    conv = converter(fake)
    pkg = conv.prepare_full(s, mat, note='벤치 앞은  밝게\n"경계석" 유지' + "x" * 400)
    assert "소재 샘플" in pkg.description and "추가 요청" in pkg.description
    assert len(pkg.note) == gc.NOTE_MAX and "\n" not in pkg.note and '"' not in pkg.note
    conv.convert(s, pkg)
    parts = json.loads(fake.requests[0].content)["contents"][0]["parts"]
    text = parts[0]["text"]
    assert len(parts) == 3 and "paving material shown in Image 2" in text and "cork" not in text.lower()
    assert "벤치 앞은 밝게 '경계석' 유지" in text and "never override" in text
    assert "화강석" not in text                                          # 소재 이름은 보내지 않음


def test_prompt_without_note_has_no_user_section():
    assert "Additional instructions" not in gc.build_prompt(PRESET, False, "  \n ")
    assert gc.clean_note(None) == ""


def test_custom_material_requires_sample(scene, tmp_path):
    from app.core.materials import CustomMaterial
    sc, s = scene
    conv = converter(FakeGemini(sc.path))
    ghost = CustomMaterial("custom_00000000", "없음", tmp_path / "없음.jpg")
    with pytest.raises(ValueError, match="샘플"):
        conv.prepare_full(s, ghost)


# ---- 길 위 잔해(나뭇가지·낙엽) 정리 요청 ----
def test_prompt_clears_debris_by_default():
    p = gc.build_prompt(PRESET, False)
    assert "fallen branches" in p and "Apart from clearing debris" in p
    assert "Do not add, remove or move anything." not in p
    off = gc.build_prompt(PRESET, False, clear_debris=False, edge_finish=False)
    assert "branches" not in off and "Do not add, remove or move anything." in off


def test_debris_option_reaches_request(scene):
    sc, s = scene
    fake = FakeGemini(sc.path)
    conv = converter(fake)
    conv.convert(s, conv.prepare_full(s, PRESET, clear_debris=False))
    conv.convert(s, conv.prepare_full(s, PRESET))
    texts = [json.loads(r.content)["contents"][0]["parts"][0]["text"] for r in fake.requests]
    assert "branches" not in texts[0] and "branches" in texts[1]


# ---- 길 가장자리 마감재 ----
def test_prompt_edge_finish_option():
    on = gc.build_prompt(PRESET, False)
    assert "edging" in on and "installing the edging" in on and "clearing debris" in on
    only_edge = gc.build_prompt(PRESET, False, clear_debris=False)
    assert "edging" in only_edge and "branches" not in only_edge
    assert "Apart from installing the edging along the walkway edges, do not add" in only_edge
    off = gc.build_prompt(PRESET, True, edge_finish=False)
    assert "edging" not in off and "Image 2" in off


def test_edge_option_reaches_request(scene):
    sc, s = scene
    fake = FakeGemini(sc.path)
    conv = converter(fake)
    pkg = conv.prepare_full(s, PRESET, edge_finish=False)
    assert pkg.edge_finish is False
    conv.convert(s, pkg)
    assert "edging" not in json.loads(fake.requests[0].content)["contents"][0]["parts"][0]["text"]


def test_edging_band_outside_path_is_composited():
    """마감재가 길 바깥 풀밭 쪽 좁은 띠에 그려져도 길과 이어진 변경이므로 합성에 포함된다."""
    sc = make_scene(900, 1200)
    band = cv2.dilate(sc.path, np.ones((31, 31), np.uint8))
    m, b = sc.path > 0, (band > 0) & ~(sc.path > 0)
    out = sc.img.astype(np.int16)
    out[m] = np.random.default_rng(0).normal((125, 160, 200), 10, (m.sum(), 3))
    out[b] = (150, 150, 150)                                                  # 회색 경계석 띠
    result, mask = gc.merge_edited(sc.img, np.clip(out, 0, 255).astype(np.uint8))
    assert (mask[b] > 0).mean() > 0.9 and iou(mask, band) > 0.9
    assert verify_outside_unchanged(sc.img, result, mask, gc.feather_for(sc.img.shape))[0]
