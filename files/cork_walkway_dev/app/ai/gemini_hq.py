"""Gemini 고품질 모드 (모듈 07, 선택 기능, 기본 꺼짐).

로컬 렌더 결과를 Gemini 이미지 모델로 사진처럼 다듬는다. 실패하면 로컬 결과를 그대로 쓴다.
모듈 10 규칙: 인라인 바이트만(Files API 금지), 캐싱·대화 세션·그라운딩·도구 금지,
요청마다 store=False(서버 기록 끄기), 대상은 generativelanguage.googleapis.com 하나.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.ai.align import align_to_original
from app.config import load_user_settings
from app.core.compositor import VerificationError, composite_verified
from app.models import WorkSession
from app.security.privacy import SendConsent, TransferLog, prepare_for_send
from app.security.secrets import GEMINI_KEY, get_key

log = logging.getLogger("corkwalkway")

BASE_URL = "https://generativelanguage.googleapis.com"      # 네트워크 허용 대상(모듈 10) 하나뿐

MAX_CANDIDATES = 3

PROMPT = (
    "You are given two images of the same scene. Image 1 is a real photo of an unpaved dirt walkway. "
    "Image 2 is the same photo where the walkway has been roughly replaced with a rubberized cork granule pavement. "
    "Produce a photorealistic version of Image 1 in which ONLY the walkway area is paved with the cork surface "
    "shown in Image 2: keep its color and granule texture. Keep the exact framing, size, perspective, lighting "
    "and shadows of Image 1. Do not change anything outside the walkway. Do not add, remove or move any objects, "
    "people, plants or structures. Output one image only."
)


class HQError(RuntimeError):
    """고품질 모드 실패. str(e)는 화면에 한 줄로 보여줄 사유."""


@dataclass
class SendPackage:
    """보낼 내용(확인 창 표시용). confirmed=True가 되어야 refine에서 보낸다."""
    original_jpeg: bytes
    guide_jpeg: bytes
    box: tuple[int, int, int, int]          # 원본에서 자른 영역 x, y, w, h
    sent_size: tuple[int, int]               # 보낼 이미지 (w, h)
    target: str = "Google Gemini API"
    confirmed: bool = False
    preview: np.ndarray | None = field(default=None, repr=False)   # 확인 창용 미리보기(BGR)
    description: str = ""                    # 확인 창에 보일 '보낼 이미지' 설명(비우면 고품질 모드 기본 문구)
    preset: object = field(default=None, repr=False)               # 간편 변환: 색상 프리셋·사용자 소재(프롬프트용)
    note: str = field(default="", repr=False)                      # 간편 변환: 사용자 추가 요청 글(정리된 것)
    clear_debris: bool = True                                      # 간편 변환: 길 위 나뭇가지·낙엽 등 정리 요청
    edge_finish: bool = True                                       # 간편 변환: 길 가장자리 마감재(경계석 등) 시공


class GeminiHQ:
    def __init__(self, config: dict, consent: SendConsent, transfer_log: TransferLog,
                 key_getter=get_key, settings_getter=load_user_settings,
                 network_check=None, httpx_client=None) -> None:
        g = config["gemini"]
        self.model: str = g.get("model", "")
        self.max_send_px: int = g.get("max_send_px", 1536)
        self.timeout_s: int = g.get("timeout_s", 60)
        self.config_enabled: bool = g.get("enabled", False)
        self.consent, self.transfer_log = consent, transfer_log
        self._key_getter, self._settings_getter = key_getter, settings_getter
        self._network_check = network_check or network_reachable
        self._httpx_client = httpx_client          # 테스트용 가짜 통신

    def available(self) -> tuple[bool, str]:
        """(사용 가능, 불가 사유)."""
        st = self._settings_getter()
        if not (self.config_enabled or st.get("gemini_enabled")):
            return False, "Gemini 사용이 꺼져 있습니다(설정에서 켤 수 있음)."
        if not st.get("gemini_paid_key_confirmed"):
            return False, "설정에서 'Cloud Billing이 연결된 유료 키임을 확인함'을 체크해야 사용할 수 있습니다."
        if not self.model:
            return False, "config.yaml에 gemini.model(모델 이름)이 비어 있습니다."
        if not self._key_getter(GEMINI_KEY):
            return False, "Gemini API 키가 없습니다. 설정에서 키를 입력하세요."
        if self._network_check() is False:
            return False, "인터넷에 연결되어 있지 않습니다. 로컬 결과를 사용하세요."
        try:
            import google.genai  # noqa: F401
        except ImportError:
            return False, "google-genai 라이브러리가 설치되어 있지 않습니다."
        return True, ""

    def prepare(self, session: WorkSession) -> SendPackage:
        """보낼 이미지 준비(UI 스레드에서 확인 창 표시 전에 호출)."""
        if session.mask is None or session.result_local is None:
            raise HQError("먼저 로컬 결과를 만들어야 합니다.")
        orig, box = prepare_for_send(session.original, session.mask, self.max_send_px)
        guide, box2 = prepare_for_send(session.result_local, session.mask, self.max_send_px)
        if box != box2:
            raise HQError("원본과 로컬 결과의 크기가 다릅니다. 로컬 결과를 다시 만들어 주세요.")
        prev = cv2.imdecode(np.frombuffer(orig, np.uint8), cv2.IMREAD_COLOR)
        return SendPackage(orig, guide, box, (prev.shape[1], prev.shape[0]), preview=prev)

    def refine(self, session: WorkSession, n: int = 1, package: SendPackage | None = None,
               cancel: threading.Event | None = None) -> list[np.ndarray]:
        """합성·검증 완료된 결과들(원본 해상도). 하나도 못 만들면 HQError(사유)."""
        ok, why = self.available()
        if not ok:
            raise HQError(why)
        if not 1 <= n <= MAX_CANDIDATES:
            raise ValueError(f"후보 수는 1~{MAX_CANDIDATES}개입니다")
        pkg = package or self.prepare(session)
        if self.consent.needs_confirmation() and not pkg.confirmed:
            raise HQError("보내기 전에 확인이 필요합니다.")
        client = self._client()
        x, y, w, h = pkg.box
        orig_crop = session.original[y:y + h, x:x + w]
        mask_crop = session.mask[y:y + h, x:x + w]
        results, reasons = [], []
        for i in range(n):
            if cancel is not None and cancel.is_set():
                reasons.append("취소됨")
                break
            t0 = time.perf_counter()
            # 전송 내역은 보내기 직전에 기록(실패한 요청도 사진은 이미 나갔을 수 있음)
            self.transfer_log.add(pkg.sent_size, (w, h), images=2)
            try:
                img = self._call(client, pkg)
                aligned, err = align_to_original(img, orig_crop, mask_crop)
                if aligned is None:
                    raise HQError(f"결과 정렬에 실패했습니다(오차 {err:.1f}px). 로컬 결과를 유지합니다.")
                layer = session.original.copy()
                layer[y:y + h, x:x + w] = aligned
                results.append(composite_verified(session.original, layer, session.mask, session.mask_feather_px))
                log.info("고품질 후보 %d 완료: 소요 %.1fs, 정렬 오차 %.2fpx", i + 1, time.perf_counter() - t0, err)
            except VerificationError:
                reasons.append("길 밖이 바뀐 결과라 버렸습니다. 로컬 결과를 유지합니다.")
                log.warning("고품질 후보 %d: 무변경 검증 실패", i + 1)
            except HQError as e:
                reasons.append(str(e))
                log.warning("고품질 후보 %d 실패: %s", i + 1, type(e).__name__)
        if not results:
            raise HQError(reasons[0] if reasons else "고품질 결과를 만들지 못했습니다.")
        return results

    # ---- 내부 ----
    def _client(self):
        from google import genai
        from google.genai import types
        opts = types.HttpOptions(base_url=BASE_URL, timeout=int(self.timeout_s * 1000),
                                 retry_options=types.HttpRetryOptions(attempts=1),
                                 httpx_client=self._httpx_client)
        # vertexai=False 고정: 환경 변수로 다른 서비스(Vertex)로 바뀌지 않게
        return genai.Client(api_key=self._key_getter(GEMINI_KEY), vertexai=False, http_options=opts)

    def _call(self, client, pkg: SendPackage) -> np.ndarray:
        from google.genai import errors, types
        config = types.GenerateContentConfig(response_modalities=["IMAGE"], store=False)
        contents = [PROMPT,
                    types.Part.from_bytes(data=pkg.original_jpeg, mime_type="image/jpeg"),
                    types.Part.from_bytes(data=pkg.guide_jpeg, mime_type="image/jpeg")]
        try:
            resp = client.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.APIError as e:
            raise HQError(_api_reason(e.code, e.message)) from None
        except Exception as e:  # 네트워크 계층 예외(httpx 등)는 종류가 많아 이름으로 분류
            name = type(e).__name__
            if "Timeout" in name:
                raise HQError(f"응답 시간({self.timeout_s}초)을 넘었습니다. 잠시 후 다시 시도하세요.") from None
            raise HQError("네트워크 오류로 보내지 못했습니다. 인터넷 연결을 확인하세요.") from None
        return _image_from_response(resp)


def _api_reason(code: int, message: str | None = "") -> str:
    """화면에 보일 한 줄 사유. 응답 원문은 화면·로그에 그대로 내보내지 않고 원인 분류에만 쓴다."""
    msg = (message or "").lower()
    if code == 429:
        if "free_tier" in msg and "limit: 0" in msg:
            return ("이 API 키의 Google 프로젝트가 무료 등급이라 이미지 모델을 쓸 수 없습니다(할당량 0). "
                    "Google AI Studio에서 이 키의 프로젝트에 결제(Billing)를 연결한 뒤 다시 시도하세요.")
        if "per day" in msg or "perday" in msg:
            return "오늘 사용 한도(할당량)를 모두 썼습니다. 내일 다시 시도하거나 AI Studio에서 한도를 확인하세요."
        return "사용 한도(할당량)를 넘었습니다. 1분쯤 뒤 다시 시도하세요."
    if code == 402:
        if "prepay" in msg or "credit" in msg:
            return ("Gemini API 선불 크레딧이 모두 소진되었습니다(잔액 없음). "
                    "AI Studio의 프로젝트 결제(Billing) 화면에서 크레딧을 충전한 뒤 다시 시도하세요.")
        return "Gemini API 결제 문제로 거절되었습니다. AI Studio에서 이 키의 프로젝트 결제 상태를 확인하세요."
    if code in (401, 403):
        return "API 키가 거부되었습니다. 설정에서 키와 결제 연결을 확인하세요."
    if code == 404:
        return "모델을 찾을 수 없습니다. config.yaml의 gemini.model을 확인하세요."
    if code == 400:
        return "요청이 거부되었습니다(지원하지 않는 모델·형식일 수 있음)."
    if code >= 500:
        return "Gemini 서버 오류입니다. 잠시 후 다시 시도하세요."
    return f"Gemini 오류(코드 {code})입니다. 잠시 후 다시 시도하고, 계속되면 AI Studio에서 프로젝트 상태를 확인하세요."


def _image_from_response(resp) -> np.ndarray:
    fb = getattr(resp, "prompt_feedback", None)
    if fb is not None and getattr(fb, "block_reason", None):
        raise HQError("Google 안전 필터에 의해 차단되었습니다. 사진 속 사람·글자가 원인일 수 있습니다.")
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content and cand.content.parts else []):
            blob = part.inline_data
            if blob is not None and blob.data and (blob.mime_type or "").startswith("image/"):
                img = cv2.imdecode(np.frombuffer(blob.data, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img
        reason = getattr(cand.finish_reason, "name", "") if cand.finish_reason else ""
        if reason in ("SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "IMAGE_PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
            raise HQError("Google 안전 필터에 의해 차단되었습니다. 사진 속 사람·글자가 원인일 수 있습니다.")
    raise HQError("응답에 이미지가 없습니다. 다시 시도하세요.")


def network_reachable() -> bool | None:
    """OS 네트워크 상태(데이터를 보내지 않음). 알 수 없으면 None."""
    try:
        from PySide6.QtNetwork import QNetworkInformation
        if QNetworkInformation.instance() is None and not QNetworkInformation.loadDefaultBackend():
            return None
        r = QNetworkInformation.instance().reachability()
        if r == QNetworkInformation.Reachability.Unknown:
            return None
        return r == QNetworkInformation.Reachability.Online
    except Exception:  # 백엔드가 없는 환경
        return None
