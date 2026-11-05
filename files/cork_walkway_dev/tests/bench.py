"""성능 측정(모듈 12): 12MP 합성 이미지로 단계별 소요 시간을 재고 MAIN.md 6장 목표와 비교.

실행: .venv\\Scripts\\python tests\\bench.py   (pytest 수집 대상 아님)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ai.gemini_convert import merge_edited  # noqa: E402
from app.core import render_local as rl  # noqa: E402
from app.core.compositor import composite_verified  # noqa: E402
from app.core.cork_material import load_presets  # noqa: E402
from app.core.export import export_result  # noqa: E402
from app.core.image_io import load_image, make_preview, save_image  # noqa: E402
from app.core.perspective import estimate_quad  # noqa: E402
from app.core.segmentation import MaskEditor, PathSegmenter, clean_mask  # noqa: E402
from app.models import WorkSession  # noqa: E402
from synth import iou, make_scene  # noqa: E402

TARGETS = {  # MAIN.md 6장
    "사진 읽기(12MP JPG)": 3.0,
    "Gemini 결과 정렬·영역 검출·합성(12MP)": 5.0,
    "저장(시공후·비교·PDF·설정 4종)": 5.0,
    "사진 불러오기 + 마스크 준비": 5.0,
    "터치 1회당 마스크 갱신": 1.0,
    "로컬 렌더링(12MP)": 10.0,
    "코르크 색상 프리셋 변경(캐시)": 2.0,
}


def timed(fn, *a, **k):
    t = time.perf_counter()
    r = fn(*a, **k)
    return r, time.perf_counter() - t


def main() -> int:
    _app = QApplication.instance() or QApplication([])  # 내보내기 글자 그리기에 필요
    rows = []
    sc = make_scene(3000, 4000)
    presets = load_presets(str(ROOT / "materials" / "cork" / "presets.yaml"))
    with tempfile.TemporaryDirectory() as td:
        photo = Path(td) / "현장 사진.jpg"
        save_image(str(photo), sc.img)

        img, t_load = timed(load_image, str(photo))
        (_, _), t_prev = timed(make_preview, img, 1600)
        seg, t_model = timed(PathSegmenter, str(ROOT / "models"))
        if seg.available():
            _, t_enc = timed(seg.set_image, img)
        else:
            t_enc = 0.0
        rows.append(("사진 읽기(12MP JPG)", t_load, TARGETS["사진 읽기(12MP JPG)"]))

        # 간편 화면: Gemini가 보낸 크기(긴 변 1536)로 길만 바꿔 돌려준 경우의 후처리(네트워크 제외)
        sent = cv2.resize(img, (1536, 1152), interpolation=cv2.INTER_AREA)
        m_small = cv2.resize(sc.path, (1536, 1152), interpolation=cv2.INTER_NEAREST) > 0
        edited = sent.copy()
        edited[m_small] = np.random.default_rng(0).normal((125, 160, 200), 10, (m_small.sum(), 3)).clip(0, 255)
        _, t_merge = timed(merge_edited, img, edited, sent)
        rows.append(("Gemini 결과 정렬·영역 검출·합성(12MP)", t_merge, TARGETS["Gemini 결과 정렬·영역 검출·합성(12MP)"]))
        rows.append(("미리보기 축소", t_prev, None))
        rows.append(("길 인식 모델 로드(시작 시 1회, 뒤에서)", t_model, None))
        rows.append(("길 인식 인코더", t_enc, None))
        rows.append(("사진 불러오기 + 마스크 준비", t_load + t_prev + t_enc, TARGETS["사진 불러오기 + 마스크 준비"]))

        if seg.available():
            def touch():
                # 실제 사용 흐름: 길 2회 터치 + 길 위 물체 제외 1회(모듈 02 참고)
                m = clean_mask(seg.predict([sc.road_pt, sc.far_pt], [sc.obj_pt]), keep_pts=[sc.obj_pt])
                ed = MaskEditor(m.shape, m)
                ed.brush([(100, 100), (300, 120)], 20)            # 브러시 기록 1개 다시 적용 포함
                return ed.mask
            mask, t_touch = timed(touch)
            note = f" (IoU {iou(mask, sc.path_wo_obj):.3f})"
        else:
            mask, t_touch, note = sc.path_wo_obj, 0.0, " (모델 없음)"
        rows.append(("터치 1회당 마스크 갱신" + note, t_touch, TARGETS["터치 1회당 마스크 갱신"]))

        quad, t_quad = timed(estimate_quad, mask)
        rows.append(("원근 4점 추정", t_quad, None))
        s = WorkSession(img, "현장 사진.jpg", mask=mask, quad=quad)

        rl.clear_cache()
        layer, t_r1 = timed(rl.render_local, s, presets[0])
        out, t_c = timed(composite_verified, img, layer, mask, s.mask_feather_px)
        rows.append(("로컬 렌더링(12MP, 첫 렌더: 텍스처 생성 포함)", t_r1, None))
        rows.append(("합성 + 무변경 검증(12MP)", t_c, None))
        rows.append(("로컬 렌더링(12MP)", t_r1 + t_c, TARGETS["로컬 렌더링(12MP)"]))

        _, t_p1 = timed(rl.render_local, s, presets[0], preview=True)
        _, t_p2 = timed(rl.render_local, s, presets[1], preview=True)
        _, t_p3 = timed(rl.render_local, s, presets[0], preview=True)
        rows.append(("미리보기 렌더(1600px, 첫 기하 계산)", t_p1, None))
        rows.append(("프리셋 변경(새 텍스처, 화면은 뒤에서 미리 만들기)", t_p2, None))
        rows.append(("코르크 색상 프리셋 변경(캐시)", t_p3, TARGETS["코르크 색상 프리셋 변경(캐시)"]))

        s.result_local, s.verified = out, True
        _, t_save = timed(export_result, s, td, "벤치", preset_name=presets[0].name)
        rows.append(("저장(시공후·비교·PDF·설정 4종)", t_save, TARGETS["저장(시공후·비교·PDF·설정 4종)"]))

    w = max(len(r[0]) for r in rows) + 2
    print(f"{'단계':<{w}} {'시간(초)':>8}  목표")
    slow = []
    for name, t, target in rows:
        mark = ""
        if target is not None:
            ok = t <= target
            mark = f"{target:.0f}초 이내 {'O' if ok else 'X'}"
            if not ok:
                slow.append(name)
        print(f"{name:<{w}} {t:8.2f}  {mark}")
    if slow:
        print("목표 미달: " + ", ".join(slow))
    return 1 if slow else 0


if __name__ == "__main__":
    sys.exit(main())
