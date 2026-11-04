"""테스트용 합성 현장 사진: 초록 배경 + 갈색 사다리꼴 길 + 그림자 띠 + 길 위 회색 원형 물체."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Scene:
    img: np.ndarray        # BGR uint8
    path: np.ndarray       # 길 마스크(물체 포함) uint8 0/255
    obj: np.ndarray        # 원형 물체 마스크
    shadow: np.ndarray     # 그림자 띠(길 안쪽) bool
    quad: np.ndarray       # (4,2) float32 좌하, 우하, 우상, 좌상
    road_pt: tuple         # 길 위(그림자·물체 아님) 터치 점 (x, y)
    far_pt: tuple          # 길 먼 쪽 터치 점
    obj_pt: tuple          # 물체 중심 (x, y)

    @property
    def path_wo_obj(self) -> np.ndarray:
        return np.where(self.obj > 0, 0, self.path).astype(np.uint8)


def make_scene(h: int = 900, w: int = 1200, seed: int = 0) -> Scene:
    rng = np.random.default_rng(seed)
    img = np.clip(np.full((h, w, 3), (60, 140, 70), np.float32) + rng.normal(0, 12, (h, w, 3)), 0, 255).astype(np.uint8)
    quad = np.array([[0.2 * w, h - 1], [0.8 * w, h - 1], [0.575 * w, 0.3 * h], [0.425 * w, 0.3 * h]], np.float32)
    path = np.zeros((h, w), np.uint8)
    cv2.fillPoly(path, [np.round(quad).astype(np.int32)], 255)
    road = np.clip(np.full((h, w, 3), (60, 100, 150), np.float32) + rng.normal(0, 15, (h, w, 3)), 0, 255).astype(np.uint8)
    img[path > 0] = road[path > 0]
    shadow = np.zeros((h, w), bool)
    shadow[int(0.633 * h):int(0.7 * h)] = True
    shadow &= path > 0
    img[shadow] = (img[shadow] * 0.55).astype(np.uint8)
    obj = np.zeros((h, w), np.uint8)
    c, r = (int(0.5 * w), int(0.833 * h)), max(2, int(0.03 * w))
    cv2.circle(obj, c, r, 255, -1)
    img[obj > 0] = (128, 128, 128)
    return Scene(img, path, obj, shadow, quad, (int(0.5 * w), int(0.933 * h)), (int(0.5 * w), int(0.45 * h)), c)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a > 0, b > 0
    return float((a & b).sum() / max(1, (a | b).sum()))
