"""고품질 모드: 실제 SDK(google-genai) 경로를 가짜 통신(httpx.MockTransport)으로 오프라인 검증."""
import base64
import json
import re
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

from app.ai import gemini_hq as gh
from app.ai.align import align_to_original
from app.config import DEFAULTS
from app.core.compositor import verify_outside_unchanged
from app.models import WorkSession
from app.security.privacy import SendConsent, TransferLog
from synth import make_scene

APP = Path(__file__).resolve().parent.parent / "app"
KEY = "AIzaFAKEKEYFORTESTS0123456789abcd"


def make_session():
    sc = make_scene(600, 800)
    local = sc.img.copy()
    rng = np.random.default_rng(1)
    m = sc.path_wo_obj > 0
    local[m] = np.clip(rng.normal((40, 80, 140), 12, (m.sum(), 3)), 0, 255).astype(np.uint8)   # 대충 칠한 로컬 결과
    return WorkSession(sc.img, "a.jpg", mask=sc.path_wo_obj, quad=sc.quad, result_local=local), sc


def b64dec(s):
    """SDK는 URL-safe base64(패딩 생략 가능)로 보낸다."""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jpeg_b64(img):
    return base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()).decode()


def ok_body(img):
    return {"candidates": [{"content": {"role": "model", "parts": [
        {"inlineData": {"mimeType": "image/jpeg", "data": jpeg_b64(img)}}]}, "finishReason": "STOP"}]}


class FakeGemini:
    """요청을 기록하고 정해진 방식으로 응답하는 가짜 서버."""

    def __init__(self, mode="shift"):
        self.mode, self.requests = mode, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.mode == "network":
            raise httpx.ConnectError("no route", request=request)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if self.mode == "quota":
            return httpx.Response(429, json={"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        if self.mode == "safety":
            return httpx.Response(200, json={"candidates": [{"finishReason": "IMAGE_SAFETY"}]})
        if self.mode == "blocked":
            return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        guide = cv2.imdecode(np.frombuffer(b64dec(parts[2]["inlineData"]["data"]), np.uint8), cv2.IMREAD_COLOR)
        h, w = guide.shape[:2]
        if self.mode == "shift":           # 모델이 2px 밀린 그림을 돌려준 경우 → 정렬로 복구
            out = cv2.warpAffine(guide, np.float32([[1, 0, 2], [0, 1, -1]]), (w, h), borderMode=cv2.BORDER_REPLICATE)
        elif self.mode == "rotated":       # 구도가 크게 바뀐 경우 → 정렬 실패
            out = cv2.warpAffine(guide, cv2.getRotationMatrix2D((w / 2, h / 2), 12, 1.0), (w, h))
        else:
            out = guide
        return httpx.Response(200, json=ok_body(out))


def hq_for(fake, settings=None, key=KEY, model="gemini-nano-banana-2.1", online=True, consent=None):
    cfg = {"gemini": dict(DEFAULTS["gemini"], model=model)}
    st = {"gemini_enabled": True, "gemini_paid_key_confirmed": True} if settings is None else settings
    c = consent or SendConsent()
    c.skip_for_this_run()
    return gh.GeminiHQ(cfg, c, TransferLog(), key_getter=lambda name: key, settings_getter=lambda: st,
                       network_check=lambda: online, httpx_client=httpx.Client(transport=httpx.MockTransport(fake)))


def test_success_request_shape_and_result():
    fake = FakeGemini("shift")
    hq = hq_for(fake)
    s, sc = make_session()
    out = hq.refine(s, n=1)
    assert len(out) == 1 and out[0].shape == s.original.shape
    ok, n = verify_outside_unchanged(s.original, out[0], s.mask, s.mask_feather_px)
    assert ok and n == 0
    inner = cv2.erode(s.mask, np.ones((9, 9), np.uint8)) > 0
    assert np.abs(out[0][inner].astype(int) - s.original[inner]).mean() > 10    # 길 안은 바뀜

    req = fake.requests[0]
    assert req.url.host == "generativelanguage.googleapis.com"
    assert "gemini-nano-banana-2.1:generateContent" in req.url.path
    assert req.headers.get("x-goog-api-key") == KEY
    body = json.loads(req.content)
    assert body["store"] is False                                 # 서버 기록 끄기
    assert body["generationConfig"]["responseModalities"] == ["IMAGE"]
    for banned in ("tools", "toolConfig", "cachedContent", "systemInstruction"):
        assert banned not in body
    assert len(body["contents"]) == 1                             # 대화 이력 없음(1회성)
    parts = body["contents"][0]["parts"]
    assert "text" in parts[0]
    imgs = [p["inlineData"] for p in parts[1:]]
    assert len(imgs) == 2 and all(i.get("mimeType", i.get("mime_type")) == "image/jpeg" for i in imgs)
    assert "fileData" not in json.dumps(body)                    # Files API 참조 없음
    for i in imgs:
        raw = b64dec(i["data"])
        assert b"Exif" not in raw
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        assert max(im.shape[:2]) <= DEFAULTS["gemini"]["max_send_px"]
        assert im.shape[0] * im.shape[1] < s.original.shape[0] * s.original.shape[1]   # 전체 사진 아님
    assert "a.jpg" not in req.content.decode(errors="ignore")    # 파일명 전송 안 함
    rec = hq.transfer_log.entries()
    assert len(rec) == 1 and rec[0].images == 2


def test_multiple_candidates():
    fake = FakeGemini("shift")
    s, _ = make_session()
    out = hq_for(fake).refine(s, n=2)
    assert len(out) == 2 and len(fake.requests) == 2


@pytest.mark.parametrize("mode, words", [
    ("quota", "할당량"), ("safety", "안전 필터"), ("blocked", "안전 필터"),
    ("network", "네트워크"), ("timeout", "응답 시간"), ("rotated", "정렬"),
])
def test_failures_fall_back_with_reason(mode, words):
    s, _ = make_session()
    with pytest.raises(gh.HQError) as e:
        hq_for(FakeGemini(mode)).refine(s)
    assert words in str(e.value)
    assert KEY not in str(e.value)


@pytest.mark.parametrize("kw, words", [
    ({"settings": {"gemini_enabled": False, "gemini_paid_key_confirmed": True}}, "꺼져"),
    ({"settings": {"gemini_enabled": True, "gemini_paid_key_confirmed": False}}, "유료 키"),
    ({"key": None}, "키가 없습니다"),
    ({"model": ""}, "gemini.model"),
    ({"online": False}, "인터넷"),
])
def test_unavailable_reasons(kw, words):
    fake = FakeGemini()
    hq = hq_for(fake, **kw)
    ok, why = hq.available()
    assert not ok and words in why
    s, _ = make_session()
    with pytest.raises(gh.HQError):
        hq.refine(s)
    assert fake.requests == []                                    # 아무것도 보내지 않음


def test_consent_required_before_send():
    fake = FakeGemini()
    cfg = {"gemini": dict(DEFAULTS["gemini"], model="m")}
    hq = gh.GeminiHQ(cfg, SendConsent(), TransferLog(), key_getter=lambda n: KEY,
                     settings_getter=lambda: {"gemini_enabled": True, "gemini_paid_key_confirmed": True},
                     network_check=lambda: True, httpx_client=httpx.Client(transport=httpx.MockTransport(fake)))
    s, _ = make_session()
    pkg = hq.prepare(s)
    assert pkg.preview is not None and pkg.sent_size == (pkg.preview.shape[1], pkg.preview.shape[0])
    with pytest.raises(gh.HQError, match="확인"):
        hq.refine(s, package=pkg)
    assert fake.requests == []
    pkg.confirmed = True                                          # 확인 창에서 [보내기]
    assert len(hq.refine(s, package=pkg)) == 1


def test_prepare_needs_local_result():
    s, _ = make_session()
    s.result_local = None
    with pytest.raises(gh.HQError):
        hq_for(FakeGemini()).prepare(s)


def test_network_check_returns_bool_or_none(qapp):
    assert gh.network_reachable() in (True, False, None)


# ---- 정렬 ----
def test_align_recovers_small_shift():
    s, _ = make_session()
    orig, m = s.original, s.mask
    shifted = cv2.warpAffine(orig, np.float32([[1, 0, 3], [0, 1, 2]]), (800, 600), borderMode=cv2.BORDER_REPLICATE)
    aligned, err = align_to_original(shifted, orig, m)
    assert aligned is not None and err < 2.0
    outside = cv2.dilate(m, np.ones((21, 21), np.uint8)) == 0
    outside[:10], outside[-10:], outside[:, :10], outside[:, -10:] = False, False, False, False
    assert np.abs(aligned[outside].astype(int) - orig[outside]).mean() < 4


def test_align_rejects_flat_or_wrong():
    s, _ = make_session()
    flat = np.full_like(s.original, 128)
    assert align_to_original(flat, flat, s.mask)[0] is None       # 특징점 없음
    other = np.random.default_rng(3).integers(0, 255, s.original.shape, dtype=np.uint8)
    assert align_to_original(other, s.original, s.mask)[0] is None


# ---- 정적 검사: 금지 API ----
def test_no_forbidden_gemini_features_in_code():
    banned = [r"\.files\.", r"\.caches\.", r"cached_content", r"\.chats\.", r"start_chat", r"GoogleSearch",
              r"google_search", r"GoogleMaps", r"google_maps", r"\.interactions\.", r"\.live\.", r"tools\s*=",
              r"upload\(", r"store\s*=\s*True"]
    for p in APP.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for pat in banned:
            assert not re.search(pat, text), f"{p.name}: {pat}"
    src = (APP / "ai" / "gemini_hq.py").read_text(encoding="utf-8")
    assert "store=False" in src and "vertexai=False" in src


def test_base_url_is_allowed_host():
    from app.security.privacy import ALLOWED_HOST
    assert gh.BASE_URL == f"https://{ALLOWED_HOST}"


@pytest.mark.parametrize("mode", ["quota", "safety", "rotated"])
def test_failed_requests_still_logged(mode):
    hq = hq_for(FakeGemini(mode))
    s, _ = make_session()
    with pytest.raises(gh.HQError):
        hq.refine(s)
    assert len(hq.transfer_log.entries()) == 1                      # 사진이 나간 시도는 실패해도 기록
