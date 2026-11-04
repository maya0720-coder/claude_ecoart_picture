"""흙길 마스크 (모듈 02): SAM 계열 ONNX 자동 지정 + 수동 보정 도구."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# 기본 모델 파일(MobileSAM ViT-T 인코더 + SAM 마스크 디코더, Apache-2.0). README에 출처 안내.
DEFAULT_ENCODER = "mobile_sam_image_encoder.onnx"
DEFAULT_DECODER = "sam_mask_decoder_multi.onnx"
ENCODER_SIDE = 1024            # 인코더 입력 긴 변
UNDO_STEPS = 20

_DECODER_INPUTS = {"image_embeddings", "point_coords", "point_labels",
                   "mask_input", "has_mask_input", "orig_im_size"}


class PathSegmenter:
    """터치 점으로 흙길 마스크를 만든다. 모델이 없으면 available()이 False(수동 도구만 사용)."""

    def __init__(self, model_dir: str, encoder_name: str = DEFAULT_ENCODER,
                 decoder_name: str = DEFAULT_DECODER) -> None:
        self.reason = ""
        self._enc = self._dec = None
        self._emb: np.ndarray | None = None
        self._img_shape: tuple[int, int] | None = None
        self._scale = 1.0
        enc_p, dec_p = Path(model_dir) / encoder_name, Path(model_dir) / decoder_name
        missing = [p.name for p in (enc_p, dec_p) if not p.is_file()]
        if missing:
            self.reason = f"길 자동 지정 모델이 없습니다({', '.join(missing)}). 브러시로 길을 칠해 주세요."
            return
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            # 한글 경로 대응: 파일 바이트를 직접 넘긴다.
            enc = ort.InferenceSession(enc_p.read_bytes(), opts, providers=["CPUExecutionProvider"])
            dec = ort.InferenceSession(dec_p.read_bytes(), opts, providers=["CPUExecutionProvider"])
        except Exception as e:  # onnxruntime 로드 실패는 형식이 다양함
            self.reason = f"길 자동 지정 모델을 불러오지 못했습니다({type(e).__name__}). 모델 파일을 다시 받아 주세요."
            return
        enc_in = enc.get_inputs()
        if [i.name for i in enc_in] != ["input_image"] or len(enc_in[0].shape) != 3:
            self.reason = "인코더 모델 형식이 맞지 않습니다(input_image (H, W, 3) 필요)."
            return
        if {i.name for i in dec.get_inputs()} != _DECODER_INPUTS:
            self.reason = "디코더 모델 형식이 맞지 않습니다(SAM ONNX 디코더 형식 필요)."
            return
        self._enc, self._dec = enc, dec

    def available(self) -> bool:
        return self._enc is not None

    def set_image(self, img_bgr: np.ndarray) -> None:
        """인코더 실행·임베딩 캐시(약 1~2초, 작업 스레드에서 호출)."""
        if not self.available():
            raise RuntimeError(self.reason)
        h, w = img_bgr.shape[:2]
        s = ENCODER_SIDE / max(h, w)
        small = cv2.resize(img_bgr, (max(1, round(w * s)), max(1, round(h * s))),
                           interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        # 확인 결과: 입력은 긴 변 1024로 줄인 RGB 0~255 float. 정규화·패딩은 모델 안에서 처리.
        x = np.ascontiguousarray(small[:, :, ::-1], dtype=np.float32)
        self._emb = self._enc.run(None, {"input_image": x})[0]
        self._img_shape, self._scale, self._small_hw = (h, w), s, small.shape[:2]

    def predict(self, pos_pts: list[tuple[int, int]], neg_pts: list[tuple[int, int]]) -> np.ndarray:
        """원본 좌표 (x, y) 점 → uint8 0/255 마스크(원본 크기). 포함 점이 없으면 빈 마스크."""
        if self._emb is None:
            raise RuntimeError("set_image()를 먼저 호출해야 합니다")
        h, w = self._img_shape
        for x, y in list(pos_pts) + list(neg_pts):
            if not (0 <= x < w and 0 <= y < h):
                raise ValueError(f"점 좌표가 사진 밖입니다: ({x}, {y})")
        if not pos_pts:
            return np.zeros((h, w), np.uint8)
        s = self._scale
        pts = [(x * s, y * s) for x, y in pos_pts] + [(x * s, y * s) for x, y in neg_pts]
        labels = [1] * len(pos_pts) + [0] * len(neg_pts)
        coords = np.array([pts + [(0.0, 0.0)]], np.float32)       # 상자 없음 → 패딩 점(-1)
        lab = np.array([labels + [-1]], np.float32)
        sh, sw = self._small_hw
        masks, scores, _ = self._dec.run(None, {
            "image_embeddings": self._emb, "point_coords": coords, "point_labels": lab,
            "mask_input": np.zeros((1, 1, 256, 256), np.float32),
            "has_mask_input": np.zeros(1, np.float32),
            "orig_im_size": np.array([sh, sw], np.float32)})
        best = int(np.argmax(scores[0]))
        logits = cv2.resize(masks[0, best], (w, h), interpolation=cv2.INTER_LINEAR)
        return np.where(logits > 0, 255, 0).astype(np.uint8)


def clean_mask(mask: np.ndarray, min_area_ratio: float = 0.002,
               keep_pts: list[tuple[int, int]] = ()) -> np.ndarray:
    """작은 조각 제거 + 작은 구멍 채우기(면적 < 전체 × min_area_ratio).

    keep_pts(제외 점)가 들어 있는 구멍은 채우지 않는다(길 위 사람·물체 원본 유지).
    """
    m = (mask > 0).astype(np.uint8)
    thr = m.size * min_area_ratio
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    small = np.where(stats[:, cv2.CC_STAT_AREA] < thr)[0]
    small = small[small != 0]
    if small.size:
        m[np.isin(lab, small)] = 0

    inv = 1 - m
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    h, w = m.shape
    keep = {int(lab[y, x]) for x, y in keep_pts if 0 <= x < w and 0 <= y < h}
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    fill = [i for i in range(1, n)
            if stats[i, cv2.CC_STAT_AREA] < thr and i not in border and i not in keep]
    if fill:
        m[np.isin(lab, fill)] = 1
    return m * 255


def feather_alpha(mask: np.ndarray, px: int) -> np.ndarray:
    """마스크 경계 중심 페더 알파(float32 0~1). 마스크 밖 px 이상 떨어진 곳은 정확히 0."""
    if px < 1:
        raise ValueError(f"페더 폭은 1 이상이어야 합니다: {px}")
    inside = (mask > 0).astype(np.uint8)
    d_in = cv2.distanceTransform(inside, cv2.DIST_L2, 5)        # 안쪽: 밖까지 거리(≥1)
    d_out = cv2.distanceTransform(1 - inside, cv2.DIST_L2, 5)   # 바깥: 안까지 거리(≥1)
    signed = d_in - d_out
    return np.clip((signed + px) / (2.0 * px), 0.0, 1.0).astype(np.float32)


class MaskEditor:
    """수동 보정: 브러시(추가)·지우개·다각형, 실행 취소/다시 실행 20단계.

    좌표는 원본 픽셀 기준. 되돌리기 기록은 바뀐 영역만 비트 압축해 저장(12MP에서도 가벼움).
    """

    def __init__(self, shape: tuple[int, int], mask: np.ndarray | None = None) -> None:
        self.mask = np.zeros(shape, np.uint8) if mask is None else (mask > 0).astype(np.uint8) * 255
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []

    def set_mask(self, new: np.ndarray) -> None:
        """자동 지정 결과 등으로 전체 교체."""
        if new.shape != self.mask.shape:
            raise ValueError("마스크 크기가 다릅니다")
        def replace(region):
            region[...] = (new > 0) * 255
        self._apply((0, 0, self.mask.shape[1], self.mask.shape[0]), replace)

    def brush(self, points: list[tuple[int, int]], radius: int, add: bool = True) -> None:
        """한 번의 붓질(점 목록을 잇는 선). add=False면 지우개."""
        if radius < 1 or not points:
            raise ValueError("브러시 크기는 1 이상, 점은 1개 이상이어야 합니다")
        pts = np.array(points, np.int32)
        bbox = self._bbox(pts, radius)
        val = 255 if add else 0

        def draw(region):
            p = pts - (bbox[0], bbox[1])
            if len(p) == 1:
                cv2.circle(region, tuple(int(v) for v in p[0]), radius, val, -1)
            else:
                cv2.polylines(region, [p], False, val, thickness=2 * radius, lineType=cv2.LINE_8)
                for q in (p[0], p[-1]):
                    cv2.circle(region, tuple(int(v) for v in q), radius, val, -1)
        self._apply(bbox, draw)

    def polygon(self, points: list[tuple[int, int]], add: bool = True) -> None:
        if len(points) < 3:
            raise ValueError("다각형은 점이 3개 이상이어야 합니다")
        pts = np.array(points, np.int32)
        bbox = self._bbox(pts, 0)
        self._apply(bbox, lambda region: cv2.fillPoly(region, [pts - (bbox[0], bbox[1])], 255 if add else 0))

    def undo(self) -> bool:
        return self._swap(self._undo, self._redo)

    def redo(self) -> bool:
        return self._swap(self._redo, self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    # 내부
    def _bbox(self, pts: np.ndarray, r: int) -> tuple[int, int, int, int]:
        h, w = self.mask.shape
        x0, y0 = np.clip(pts.min(0) - r - 1, 0, None)
        x1, y1 = pts.max(0) + r + 2
        return int(x0), int(y0), int(min(x1, w)), int(min(y1, h))

    def _snap(self, bbox):
        x0, y0, x1, y1 = bbox
        region = self.mask[y0:y1, x0:x1]
        return (bbox, region.shape, np.packbits(region > 0))

    def _restore(self, snap) -> None:
        (x0, y0, x1, y1), shape, bits = snap
        n = shape[0] * shape[1]
        self.mask[y0:y1, x0:x1] = np.unpackbits(bits, count=n).reshape(shape) * 255

    def _apply(self, bbox, fn) -> None:
        x0, y0, x1, y1 = bbox
        if x1 <= x0 or y1 <= y0:
            return
        self._undo.append(self._snap(bbox))
        del self._undo[:-UNDO_STEPS]
        self._redo.clear()
        region = np.ascontiguousarray(self.mask[y0:y1, x0:x1])
        fn(region)
        self.mask[y0:y1, x0:x1] = region

    def _swap(self, src: list, dst: list) -> bool:
        if not src:
            return False
        snap = src.pop()
        dst.append(self._snap(snap[0]))
        self._restore(snap)
        return True
