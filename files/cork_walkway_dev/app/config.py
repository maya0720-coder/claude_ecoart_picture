"""config.yaml 로드와 경로 계산."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import yaml

APP_NAME = "CorkWalkway"

DEFAULTS: dict = {
    "paths": {"models": "models", "materials": "materials/cork", "output_default": ""},
    "segmentation": {"encoder": "mobile_sam_image_encoder.onnx",
                     "decoder": "sam_mask_decoder_multi.onnx", "min_area_ratio": 0.002},
    "render": {"max_preview_px": 1600},
    "gemini": {"enabled": False, "model": "", "max_send_px": 1536, "timeout_s": 60},
    "export": {"watermark": True, "jpeg_quality": 92, "image_format": "jpg",
               "formats": ["after", "compare", "pdf", "settings"]},
}


def app_root() -> Path:
    """리소스 루트. PyInstaller 실행 시 sys._MEIPASS, 아니면 프로젝트 루트."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def exe_dir() -> Path:
    """실행 파일 폴더(배포본에서 사용자가 옆에 둔 config.yaml·models/ 우선)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return app_root()


def resolve_resource(rel: str) -> Path:
    """상대 경로를 exe 폴더 → 리소스 루트 순으로 찾는다. 없으면 리소스 루트 기준 경로."""
    p = Path(rel)
    if p.is_absolute():
        return p
    for base in (exe_dir(), app_root()):
        if (base / p).exists():
            return base / p
    return app_root() / p


def user_data_dir() -> Path:
    """사용자 설정·로그 폴더: %APPDATA%\\CorkWalkway"""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike | None = None) -> dict:
    """config.yaml을 읽어 기본값과 병합한다. 파일이 없으면 기본값."""
    p = Path(path) if path is not None else resolve_resource("config.yaml")
    if not p.exists():
        if path is not None:
            raise FileNotFoundError(f"설정 파일이 없습니다: {p}")
        return copy.deepcopy(DEFAULTS)
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"설정 파일 형식이 잘못되었습니다(최상위가 사전이 아님): {p}")
    cfg = _merge(DEFAULTS, data)
    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    mp = cfg["render"]["max_preview_px"]
    if not isinstance(mp, int) or mp <= 0:
        raise ValueError(f"render.max_preview_px는 양의 정수여야 합니다: {mp}")
    sp = cfg["gemini"]["max_send_px"]
    if not isinstance(sp, int) or sp <= 0:
        raise ValueError(f"gemini.max_send_px는 양의 정수여야 합니다: {sp}")
    q = cfg["export"]["jpeg_quality"]
    if not isinstance(q, int) or not 1 <= q <= 100:
        raise ValueError(f"export.jpeg_quality는 1~100이어야 합니다: {q}")
    if cfg["export"]["image_format"] not in ("jpg", "png"):
        raise ValueError("export.image_format은 jpg 또는 png여야 합니다")
    if not isinstance(cfg["export"]["formats"], list) or not cfg["export"]["formats"]:
        raise ValueError("export.formats는 저장할 항목 목록이어야 합니다")
    if not isinstance(cfg["gemini"]["enabled"], bool):
        raise ValueError("gemini.enabled는 true/false여야 합니다")

# ---- 사용자 설정(%APPDATA%\CorkWalkway\settings.json): 비밀이 아닌 선택값만. API 키는 secrets.py ----
USER_DEFAULTS: dict = {
    "gemini_enabled": False,
    "gemini_paid_key_confirmed": False,   # "Cloud Billing이 연결된 유료 키임을 확인함"
    "watermark": True,
    "hq_candidates": 1,                   # 고품질 후보 수(1~3)
    "last_folder": "",                    # 마지막으로 연 사진 폴더(최근 사진)
    "output_folder": "",                  # 마지막 저장 폴더
    "sidebar_width": 340,                 # 간편 화면 왼쪽 패널 폭(px, 사용자가 구분선을 끌어 조정)
    "clear_debris": True,                 # 길 위 나뭇가지·낙엽 정리 요청
    "edge_finish": True,                  # 길 가장자리 마감재(경계석 등) 시공 요청
}


def load_user_settings() -> dict:
    p = user_data_dir() / "settings.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = dict(USER_DEFAULTS)
    out.update({k: v for k, v in data.items() if k in USER_DEFAULTS and type(v) is type(USER_DEFAULTS[k])})
    return out


def save_user_settings(settings: dict) -> None:
    """알려진 항목만 저장(키 같은 다른 값이 섞여도 파일에 쓰지 않음)."""
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    clean = {k: settings[k] for k in USER_DEFAULTS if k in settings}
    tmp = d / "settings.json.tmp"
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(d / "settings.json")
