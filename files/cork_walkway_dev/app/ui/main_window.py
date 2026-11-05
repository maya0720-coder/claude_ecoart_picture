"""메인 창 (모듈 08): 현장 모드 ① 사진 → ② 길 지정 → ③ 확인 → ④ 결과.

무거운 작업(사진 읽기, 길 인식, 렌더, 저장, 고품질)은 모두 작업 스레드(Runner)에서 실행한다.
작업 결과에는 '세대(gen)'를 붙여, 그 사이 사용자가 마스크·설정을 바꿨으면 오래된 결과를 버린다.
"""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSlider, QSpinBox, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from app.ai.gemini_hq import GeminiHQ
from app.config import load_user_settings, resolve_resource, save_user_settings
from app.core import image_io
from app.core.compositor import composite_verified
from app.core.export import export_result
from app.core.cork_material import load_presets
from app.core.perspective import DEFAULT_PATH_WIDTH_M, estimate_quads, update_quad
from app.core.render_local import render_local
from app.core.segmentation import MaskEditor, PathSegmenter, clean_mask
from app.models import RenderParams, WorkSession
from app.security.privacy import SendConsent, TransferLog
from app.ui.canvas import ImageCanvas
from app.ui.compare_view import CompareView
from app.ui.presentation import PresentationWindow
from app.ui.settings_dialog import SendConfirmDialog, SettingsDialog, TransferLogDialog
from app.ui.widgets import STYLE, PresetChips, bgr_to_pixmap, big_button, flow_row
from app.ui.workers import Runner

log = logging.getLogger("corkwalkway")

STEPS = ("① 사진", "② 길 지정", "③ 확인", "④ 결과")
GUIDE = {
    1: "현장 사진을 찍거나 불러오세요. 사진 파일을 창에 끌어다 놓아도 됩니다.",
    2: "흙길을 한 번 눌러 주세요. 길이 덜 잡히면 길을 한 번 더, 길 위 사람·물체는 [제외 점 모드]로 눌러 빼세요."
       " (마우스 오른쪽 클릭·길게 누름 = 제외 점)",
    3: "파란 격자가 길 방향과 맞는지 확인하세요. 어긋나면 [4점 조정]으로 모서리를 끌어 맞춥니다.",
    4: "가운데 선을 끌어 시공 전·후를 비교하세요.",
}
HISTORY_STEPS = 20


class MainWindow(QMainWindow):
    def __init__(self, config: dict, segmenter: PathSegmenter | None = None, runner: Runner | None = None) -> None:
        super().__init__()
        self.config = config
        self.settings = load_user_settings()
        self.setWindowTitle("시공 시뮬레이터 — 단계별 화면")
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self.resize(1280, 800)
        self.runner = runner or Runner()
        self.presets = load_presets(str(resolve_resource(config["paths"]["materials"]) / "presets.yaml"))
        self.preset_by_id = {p.id: p for p in self.presets}
        self.consent, self.transfer_log = SendConsent(), TransferLog()
        self.hq = GeminiHQ(config, self.consent, self.transfer_log)
        self.max_prev = config["render"]["max_preview_px"]

        self.segmenter = segmenter
        self.session: WorkSession | None = None
        self.preview_img = None
        self.prev_scale = 1.0
        self.pos, self.neg, self.strokes = [], [], []
        self.history: deque = deque(maxlen=HISTORY_STEPS)
        self.redo_stack: list = []                 # 되돌린 작업 (종류, 항목)
        self.pred_cache: dict = {}
        self.enc_ready = False
        self.gen = 0                       # 마스크·설정이 바뀔 때마다 증가
        self.previews: dict[str, np.ndarray] = {}
        self.hq_preview = None             # (preset_id, 미리보기)
        self.presentation: PresentationWindow | None = None
        self.step = 1
        self.last_saved: list[str] = []

        self._build_ui()
        self._shortcuts()
        self.go_step(1)
        if self.segmenter is None:
            m = config["paths"]["models"]
            s = config["segmentation"]
            self.runner.start("load_model", PathSegmenter, str(resolve_resource(m)), s["encoder"], s["decoder"],
                              on_done=self._model_loaded, on_fail=lambda msg: self._banner(msg))

    # ================= 화면 구성 =================
    def _build_ui(self) -> None:
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)

        # 상단 단계 표시 + 설정
        top = QHBoxLayout()
        self.step_btns = []
        for i, name in enumerate(STEPS, start=1):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, n=i: self._step_clicked(n))
            top.addWidget(b)
            self.step_btns.append(b)
        top.addStretch(1)
        self.btn_log = QToolButton(text="전송 내역")
        self.btn_log.clicked.connect(lambda: TransferLogDialog(self.transfer_log, self).exec())
        self.btn_settings = QToolButton(text="설정")
        self.btn_settings.clicked.connect(self._open_settings)
        for b in (self.btn_log, self.btn_settings):
            b.setMinimumHeight(40)
            top.addWidget(b)
        lay.addLayout(top)

        # 가운데 보기: 0=시작 화면(최근 사진) 1=캔버스 2=비교
        self.view_stack = QStackedWidget()
        self.home = QWidget()
        hl = QVBoxLayout(self.home)
        self.home_title = QLabel("코르크 포장 시공 예상도를 만들 현장 사진을 준비하세요.")
        self.home_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_title.setObjectName("guide")
        self.recent_box = QWidget()
        self.recent_layout = QHBoxLayout(self.recent_box)
        hl.addStretch(1)
        hl.addWidget(self.home_title)
        hl.addWidget(self.recent_box, alignment=Qt.AlignmentFlag.AlignCenter)
        hl.addStretch(1)
        self.canvas = ImageCanvas()
        self.canvas.pointAdded.connect(self.on_point)
        self.canvas.strokeFinished.connect(self.on_stroke)
        self.canvas.polygonFinished.connect(self.on_polygon)
        self.canvas.quadChanged.connect(self.on_quad_changed)
        self.compare = CompareView()
        for w in (self.home, self.canvas, self.compare):
            self.view_stack.addWidget(w)
        lay.addWidget(self.view_stack, 1)

        # 안내·알림·진행
        self.guide = QLabel(objectName="guide")
        self.guide.setWordWrap(True)
        self.banner = QLabel(objectName="banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        busy = QHBoxLayout()
        self.busy_label = QLabel("")
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(200)
        self.btn_cancel = big_button("취소")
        self.btn_cancel.clicked.connect(self._cancel_busy)
        busy.addWidget(self.busy_label, 1)
        busy.addWidget(self.busy_bar)
        busy.addWidget(self.btn_cancel)
        self.busy_row = QWidget()
        self.busy_row.setLayout(busy)
        self.busy_row.hide()
        self._busy_kind = None
        lay.addWidget(self.guide)
        lay.addWidget(self.banner)
        lay.addWidget(self.busy_row)

        # 하단 단계별 조작: 현재 단계 페이지만 보이게(숨긴 페이지는 높이를 차지하지 않음)
        self.pages = [self._page_photo(), self._page_mask(), self._page_check(), self._page_result()]
        for pg in self.pages:
            lay.addWidget(pg)
        self.setCentralWidget(root)

    def _page_photo(self) -> QWidget:
        self.btn_camera = big_button("카메라로 촬영")
        self.btn_camera.clicked.connect(self.take_photo)
        self.btn_open = big_button("사진 열기", primary=True)
        self.btn_open.clicked.connect(self.open_dialog)
        self.btn_recent = big_button("최근 사진")
        self.btn_recent.clicked.connect(self.show_recent)
        from app.ui.camera_dialog import has_camera
        self.btn_camera.setVisible(has_camera())
        return flow_row(self.btn_camera, self.btn_open, self.btn_recent)

    def _page_mask(self) -> QWidget:
        self.btn_pos = big_button("길 점(포함)", checkable=True)
        self.btn_neg = big_button("제외 점 모드", checkable=True)
        self.btn_brush = big_button("브러시", checkable=True)
        self.btn_erase = big_button("지우개", checkable=True)
        self.btn_poly = big_button("다각형", checkable=True)
        self.btn_poly_done = big_button("다각형 완료")
        self.btn_poly_done.clicked.connect(lambda: self.canvas.finish_polygon())
        self.btn_poly_done.hide()
        self.mode_btns = {"point": self.btn_pos, "neg": self.btn_neg, "brush": self.btn_brush, "erase": self.btn_erase,
                          "polygon": self.btn_poly}
        for m, b in self.mode_btns.items():
            b.clicked.connect(lambda _=False, mm=m: self.set_tool(mm))
        self.brush_size = QSlider(Qt.Orientation.Horizontal)
        self.brush_size.setRange(5, 80)
        self.brush_size.setValue(30)
        self.brush_size.setMinimumWidth(120)
        self.brush_size.setMinimumHeight(40)
        self.brush_size.valueChanged.connect(lambda v: setattr(self.canvas, "brush_px", v))
        self.btn_undo = big_button("되돌리기")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = big_button("다시 실행")
        self.btn_redo.clicked.connect(self.redo)
        self.btn_next2 = big_button("다음 →", primary=True)
        self.btn_next2.clicked.connect(lambda: self.go_step(3))
        size = QWidget()
        sl = QHBoxLayout(size)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(QLabel("브러시 크기"))
        sl.addWidget(self.brush_size)
        return flow_row(self.btn_pos, self.btn_neg, self.btn_brush, self.btn_erase, self.btn_poly, self.btn_poly_done,
                        size, self.btn_undo, self.btn_redo, self.btn_next2)

    def _page_check(self) -> QWidget:
        self.btn_back3 = big_button("← 길 다시 지정")
        self.btn_back3.clicked.connect(lambda: self.go_step(2))
        self.btn_quad = big_button("4점 조정", checkable=True)
        self.btn_quad.clicked.connect(lambda on: self.canvas.set_mode("quad" if on else "view"))
        self.btn_auto_quad = big_button("자동 4점")
        self.btn_auto_quad.clicked.connect(lambda: self._estimate_quad(force=True))
        self.segments = QComboBox()
        self.segments.addItems(["곧은 길", "굽은 길(3구간)", "굽은 길(4구간)", "굽은 길(5구간)"])
        self.segments.setMinimumHeight(44)
        self.segments.currentIndexChanged.connect(lambda _: self._estimate_quad(force=True))
        self.width_real = QCheckBox("실제 길 폭 입력")
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.3, 20.0)
        self.width_spin.setSingleStep(0.1)
        self.width_spin.setValue(DEFAULT_PATH_WIDTH_M)
        self.width_spin.setSuffix(" m")
        self.width_spin.setMinimumHeight(44)
        self.width_note = QLabel(f"가정값 {DEFAULT_PATH_WIDTH_M:.1f}m")
        self.width_real.toggled.connect(self._width_changed)
        self.width_spin.valueChanged.connect(self._width_changed)
        self.chips3 = PresetChips(self.presets)
        self.chips3.presetChosen.connect(self._set_preset)
        self.btn_next3 = big_button("결과 보기 →", primary=True)
        self.btn_next3.clicked.connect(lambda: self.go_step(4))

        # 고급 설정(접힘)
        self.adv = QGroupBox("고급 설정")
        self.adv.setCheckable(True)
        self.adv.setChecked(False)
        self.adv_body = QWidget()
        f = QFormLayout(self.adv_body)
        self.s_shade = self._slider(0, 100, 80)
        self.s_color = self._slider(0, 100, 30)
        self.s_granule = self._slider(50, 200, 100)
        self.sp_feather = QSpinBox()
        self.sp_feather.setRange(1, 10)
        self.sp_feather.setValue(3)
        self.cb_edge = QCheckBox("가장자리 마감선")
        self.sp_edge = QSpinBox()
        self.sp_edge.setRange(0, 60)
        self.sp_edge.setValue(8)
        self.cb_contact = QCheckBox("경계 접촉 음영")
        f.addRow("명암 유지", self.s_shade)
        f.addRow("색 맞춤", self.s_color)
        f.addRow("입자 크기", self.s_granule)
        f.addRow("경계 페더(px)", self.sp_feather)
        f.addRow(self.cb_edge, self.sp_edge)
        f.addRow(self.cb_contact)
        for w in (self.s_shade, self.s_color, self.s_granule):
            w.valueChanged.connect(self._params_changed)
        for w in (self.sp_feather, self.sp_edge):
            w.valueChanged.connect(self._params_changed)
        for w in (self.cb_edge, self.cb_contact):
            w.toggled.connect(self._params_changed)
        al = QVBoxLayout(self.adv)
        al.addWidget(self.adv_body)
        self.adv_body.hide()
        self.adv.toggled.connect(self.adv_body.setVisible)

        width_box = QWidget()
        wl = QHBoxLayout(width_box)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.width_real)
        wl.addWidget(self.width_spin)
        wl.addWidget(self.width_note)
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(flow_row(self.btn_back3, self.btn_quad, self.btn_auto_quad, self.segments, width_box, self.btn_next3))
        pl.addWidget(self.chips3)
        pl.addWidget(self.adv)
        return page

    def _page_result(self) -> QWidget:
        self.btn_back4 = big_button("← 조정")
        self.btn_back4.clicked.connect(lambda: self.go_step(3))
        self.btn_colors = big_button("색상 바꾸기", checkable=True)
        self.btn_hq = big_button("고품질로 다듬기")
        self.btn_hq.clicked.connect(self.start_hq)
        self.btn_local = big_button("로컬 결과 보기", checkable=True)
        self.btn_local.clicked.connect(self._show_current)
        self.btn_local.hide()
        self.btn_save = big_button("저장", primary=True)
        self.btn_save.clicked.connect(self.save)
        self.btn_present = big_button("프레젠테이션")
        self.btn_present.clicked.connect(self.start_presentation)
        self.site_name = QLineEdit()
        self.site_name.setPlaceholderText("현장명(선택)")
        self.site_name.setMinimumHeight(44)
        self.site_name.setMinimumWidth(160)
        self.site_name.setMaxLength(40)
        self.chips4 = PresetChips(self.presets)
        self.chips4.presetChosen.connect(self._set_preset)
        self.chips4.hide()
        self.btn_colors.toggled.connect(self.chips4.setVisible)
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(flow_row(self.btn_back4, self.btn_colors, self.btn_hq, self.btn_local, self.site_name,
                              self.btn_save, self.btn_present))
        pl.addWidget(self.chips4)
        return page

    @staticmethod
    def _slider(lo, hi, val) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.setMinimumHeight(36)
        return s

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_dialog)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.redo)
        QShortcut(QKeySequence("F5"), self, activated=self.start_presentation)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)

    # ================= 단계 이동 =================
    def _step_clicked(self, n: int) -> None:
        if n <= self._max_step():
            self.go_step(n)
        self._sync_step_buttons()

    def _max_step(self) -> int:
        if self.session is None:
            return 1
        if self.session.mask is None or not self.session.mask.any():
            return 2
        return 4

    def _sync_step_buttons(self) -> None:
        for i, b in enumerate(self.step_btns, start=1):
            b.setChecked(i == self.step)
            b.setEnabled(i <= self._max_step())

    def go_step(self, n: int) -> None:
        n = min(n, self._max_step())
        self.step = n
        for i, pg in enumerate(self.pages, start=1):
            pg.setVisible(i == n)
        self.guide.setText(GUIDE[n])
        if n == 1:
            self.view_stack.setCurrentWidget(self.home)
        elif n == 2:
            self.view_stack.setCurrentWidget(self.canvas)
            self.canvas.set_quad(None)
            no_model = self.segmenter is not None and not self.segmenter.available()
            self.set_tool("brush" if no_model else "point")
            if no_model:
                self.guide.setText("길 자동 지정 모델이 없어 [브러시]로 길을 칠해 주세요. " + self.segmenter.reason)
            elif not self.enc_ready:
                self.guide.setText("길 인식 준비 중… 잠시 후 흙길을 눌러 주세요.")
        elif n == 3:
            self.view_stack.setCurrentWidget(self.canvas)
            self.btn_quad.setChecked(False)
            self.canvas.set_mode("view")
            self._estimate_quad(force=False)
            self.chips3.set_current(self.session.preset_id)
        elif n == 4:
            self.view_stack.setCurrentWidget(self.compare)
            self.chips4.set_current(self.session.preset_id)
            ok, why = self.hq.available()
            self.btn_hq.setEnabled(ok)
            self.btn_hq.setToolTip("" if ok else why)
            self.render_preview(self.session.preset_id)
        self._sync_step_buttons()

    # ================= ① 사진 =================
    def open_dialog(self) -> None:
        start = self.settings.get("last_folder") or str(Path.home() / "Pictures")
        path, _ = QFileDialog.getOpenFileName(self, "현장 사진 열기", start, "사진 (*.jpg *.jpeg *.png *.heic *.heif)")
        if path:
            self.open_photo(path)

    def open_photo(self, path: str) -> None:
        self._busy("사진을 불러오는 중…", "load")
        self.runner.start("load", image_io.load_image, path,
                          on_done=lambda img: self._photo_loaded(img, path), on_fail=self._fail("load"))

    def _photo_loaded(self, img: np.ndarray, path: str) -> None:
        self._idle("load")
        if image_io.is_huge(img):
            ans = QMessageBox.question(self, "아주 큰 사진", f"사진이 {img.shape[1]}×{img.shape[0]}px(5천만 화소 초과)입니다. "
                                       f"처리 속도를 위해 긴 변 {image_io.HUGE_LIMIT_PX}px로 줄일까요?")
            if ans == QMessageBox.StandardButton.Yes:
                img = image_io.make_preview(img, image_io.HUGE_LIMIT_PX)[0]
        self.settings["last_folder"] = str(Path(path).parent)
        save_user_settings(self.settings)
        self.set_session(img, Path(path).name)

    def take_photo(self) -> None:
        from app.ui.camera_dialog import CameraDialog
        dlg = CameraDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.image is not None:
            self.set_session(dlg.image, "카메라 촬영")

    def show_recent(self) -> None:
        folder = self.settings.get("last_folder", "")
        paths = image_io.recent_images(folder, 6) if folder else []
        while self.recent_layout.count():
            w = self.recent_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not paths:
            self._banner("최근에 연 폴더에 사진이 없습니다. [사진 열기]로 사진을 선택하세요.")
            return

        def thumbs(ps):
            out = []
            for p in ps:
                try:
                    out.append((p, image_io.make_preview(image_io.load_image(p), 180)[0]))
                except (OSError, ValueError):
                    continue
            return out

        def show(items):
            self._idle("thumbs")
            for p, t in items:
                b = QPushButton()
                b.setIcon(QIcon(bgr_to_pixmap(t)))
                b.setIconSize(bgr_to_pixmap(t).size())
                b.setToolTip(Path(p).name)
                b.clicked.connect(lambda _=False, pp=p: self.open_photo(pp))
                self.recent_layout.addWidget(b)
        self._busy("최근 사진을 불러오는 중…", "thumbs")
        self.runner.start("thumbs", thumbs, paths, on_done=show, on_fail=self._fail("thumbs"))

    def set_session(self, img: np.ndarray, name: str) -> None:
        pid = self.session.preset_id if self.session else self.presets[0].id
        self.session = WorkSession(original=img, source_name=name, preset_id=pid, render_params=self._params(),
                                   mask_feather_px=self.sp_feather.value())
        self.preview_img, self.prev_scale = image_io.make_preview(img, self.max_prev)
        self.canvas.set_image(self.preview_img, self.prev_scale)
        self.pos, self.neg, self.strokes = [], [], []
        self.history.clear()
        self.redo_stack.clear()
        self.pred_cache.clear()
        self._invalidate()
        self.enc_ready = False
        self.banner.hide()
        if self._model_ok():
            self._start_encoder()
        self.go_step(2)

    # ================= ② 길 지정 =================
    def _model_loaded(self, seg: PathSegmenter) -> None:
        self.segmenter = seg
        if not seg.available():
            log.info("길 자동 지정 모델 없음")
        if self.session is not None and seg.available() and not self.enc_ready:
            self._start_encoder()
        if self.step == 2:
            self.go_step(2)

    def _model_ok(self) -> bool:
        return self.segmenter is not None and self.segmenter.available()

    def _start_encoder(self) -> None:
        img = self.session.original

        def done(_):
            self.enc_ready = True
            if self.step == 2:
                self.guide.setText(GUIDE[2])
            if self.pos:
                self._recompute()
        self.runner.start("encode", self.segmenter.set_image, img, on_done=done, on_fail=self._fail("encode"))

    def set_tool(self, mode: str) -> None:
        for m, b in self.mode_btns.items():
            b.setChecked(m == mode)
        self.btn_poly_done.setVisible(mode == "polygon")
        self.canvas.set_mode(mode)
        if mode == "polygon":
            self.guide.setText("길 가장자리를 차례로 눌러 꼭짓점을 찍고, 두 번 누르거나 [다각형 완료]를 누르세요.")
        elif self.step == 2 and self.enc_ready:
            self.guide.setText(GUIDE[2])

    def on_point(self, x: int, y: int, positive: bool) -> None:
        if self.step != 2 or self.session is None:
            return
        if self.segmenter is not None and not self.segmenter.available():
            self._banner("자동 지정 모델이 없어 점으로 지정할 수 없습니다. [브러시]로 길을 칠해 주세요.")
            return
        self._record("pos" if positive else "neg", (x, y))
        if not self._model_ok() or not self.enc_ready:
            self.guide.setText("길 인식 준비 중… 준비되면 자동으로 반영합니다.")
            self.canvas.set_points(self.pos, self.neg)
            return
        self._recompute()

    def on_stroke(self, pts: list, radius: int, add: bool) -> None:
        if self.step != 2 or self.session is None:
            return
        self._record("stroke", (pts, radius, add))
        self._recompute()

    def on_polygon(self, pts: list) -> None:
        """다각형 = 반지름 0인 붓질 기록(다시 적용할 때 채우기)."""
        if self.step != 2 or self.session is None:
            return
        self._record("stroke", (pts, 0, True))
        self._recompute()

    def _lists(self) -> dict:
        return {"pos": self.pos, "neg": self.neg, "stroke": self.strokes}

    def _record(self, kind: str, item) -> None:
        self._lists()[kind].append(item)
        self.history.append(kind)
        self.redo_stack.clear()

    def undo(self) -> None:
        if self.step != 2 or not self.history:
            return
        kind = self.history.pop()
        self.redo_stack.append((kind, self._lists()[kind].pop()))
        self._recompute()

    def redo(self) -> None:
        if self.step != 2 or not self.redo_stack:
            return
        kind, item = self.redo_stack.pop()
        self._lists()[kind].append(item)
        self.history.append(kind)
        self._recompute()

    def _recompute(self) -> None:
        """마스크 = 정리(모델 결과) + 브러시 기록 다시 적용. 작업 스레드에서 계산."""
        s = self.session
        pos, neg, strokes = list(self.pos), list(self.neg), list(self.strokes)
        key = (tuple(pos), tuple(neg))
        cached = self.pred_cache.get(key)
        seg, ratio = self.segmenter, self.config["segmentation"]["min_area_ratio"]
        use_model = self._model_ok() and self.enc_ready and pos

        def work():
            if cached is not None:
                base = cached
            elif use_model:
                base = clean_mask(seg.predict(pos, neg), ratio, keep_pts=neg)
            else:
                base = np.zeros(s.original.shape[:2], np.uint8)
            ed = MaskEditor(base.shape, base)
            for p, r, add in strokes:
                if r == 0:
                    ed.polygon(p, add)
                else:
                    ed.brush(p, r, add)
            return key, base, ed.mask

        def done(res):
            k, base, mask = res
            if use_model:
                self.pred_cache[k] = base
                while len(self.pred_cache) > 4:
                    self.pred_cache.pop(next(iter(self.pred_cache)))
            s.mask = mask
            self._invalidate()
            self.canvas.set_mask(mask)
            self.canvas.set_points(self.pos, self.neg)
            self._sync_step_buttons()
        self.canvas.set_points(self.pos, self.neg)
        self.runner.start("mask", work, on_done=done, on_fail=self._fail("mask"))

    # ================= ③ 확인 =================
    def _estimate_quad(self, force: bool) -> None:
        s = self.session
        if s is None or s.mask is None or not s.mask.any():
            return
        if s.quad is None or force:
            n = (1, 3, 4, 5)[self.segments.currentIndex()]
            try:
                quads = estimate_quads(s.mask, n)
            except ValueError as e:
                self._banner(str(e))
                return
            s.quad = quads[0]
            s.quad_segments = quads if n > 1 else None
            self._invalidate(keep_quad=True)
        self.canvas.set_mask(s.mask)
        self.canvas.set_points([], [])
        self.canvas.set_quad(self._display_quad())

    def _display_quad(self):
        """화면용 4점: 구간이 여럿이면 가장 가까운 구간 아랫변 + 가장 먼 구간 윗변."""
        s = self.session
        if s.quad_segments:
            return np.array([s.quad_segments[0][0], s.quad_segments[0][1],
                             s.quad_segments[-1][2], s.quad_segments[-1][3]], np.float32)
        return s.quad

    def on_quad_changed(self, quad) -> None:
        s = self.session
        new, warn = update_quad(self._display_quad(), quad)
        if warn:
            self._banner(warn)
            self.canvas.set_quad(self._display_quad())
            return
        self.banner.hide()
        s.quad, s.quad_segments = new, None       # 손으로 맞추면 한 구간(곧은 길)으로
        self.segments.blockSignals(True)
        self.segments.setCurrentIndex(0)
        self.segments.blockSignals(False)
        self._invalidate(keep_quad=True)
        self.canvas.set_quad(new)

    def _width_changed(self, *_):
        real = self.width_real.isChecked()
        self.width_spin.setEnabled(real)
        self.width_note.setVisible(not real)
        if self.session is not None:
            self.session.path_width_m = self.width_spin.value() if real else None
            self._invalidate(keep_quad=True)

    def _params(self) -> RenderParams:
        return RenderParams(shading_strength=self.s_shade.value() / 100, color_match=self.s_color.value() / 100,
                            granule_scale=self.s_granule.value() / 100, edge_band=self.cb_edge.isChecked(),
                            edge_band_px=self.sp_edge.value(), contact_shadow=self.cb_contact.isChecked())

    def _params_changed(self, *_):
        if self.session is None:
            return
        self.session.render_params = self._params()
        self.session.mask_feather_px = self.sp_feather.value()
        self._invalidate(keep_quad=True)

    def _set_preset(self, pid: str) -> None:
        if self.session is None:
            return
        self.session.preset_id = pid
        self.chips3.set_current(pid)
        self.chips4.set_current(pid)
        if self.presentation is not None:
            self.presentation.chips.set_current(pid)
        if self.step == 4 or self.presentation is not None:
            self.render_preview(pid)

    def _invalidate(self, keep_quad: bool = False) -> None:
        """마스크·설정 변경: 이전 렌더 결과 폐기."""
        self.gen += 1
        s = self.session
        if s is not None:
            if not keep_quad:
                s.quad, s.quad_segments = None, None
            s.result_local = s.result_hq = None
            s.verified = False
        self.previews.clear()
        self.hq_preview = None
        self.btn_local.hide()
        for k in ("preview", "prewarm", "full", "hq"):
            self.runner.cancel(k)

    # ================= ④ 결과 =================
    def _preview_pair(self):
        """미리보기 원본·마스크·페더(미리보기 배율)."""
        s = self.session
        h, w = self.preview_img.shape[:2]
        m = cv2.resize(s.mask, (w, h), interpolation=cv2.INTER_NEAREST)
        return self.preview_img, m, max(1, round(s.mask_feather_px * self.prev_scale))

    def _make_preview(self, pid: str):
        s = self.session
        img, m, f = self._preview_pair()
        maxp = self.max_prev

        def work():
            layer = render_local(s, self.preset_by_id[pid], preview=True, max_preview_px=maxp)
            if layer.shape[:2] != img.shape[:2]:
                layer = cv2.resize(layer, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
            return composite_verified(img, layer, m, f)
        return work

    def render_preview(self, pid: str) -> None:
        if self.session is None:
            return
        if self.hq_preview is not None and self.hq_preview[0] == pid and not self.btn_local.isChecked():
            self._show(self.hq_preview[1])
            return
        if pid in self.previews:
            self._show(self.previews[pid])
            self._prewarm()
            return
        gen = self.gen
        self._busy("예상도를 만드는 중…", "preview")

        def done(out):
            self._idle("preview")
            if gen != self.gen:
                return
            self.previews[pid] = out
            if self.session.preset_id == pid:
                self._show(out)
            self._prewarm()
        self.runner.start("preview", self._make_preview(pid), on_done=done, on_fail=self._fail("preview"))

    def _prewarm(self) -> None:
        """나머지 프리셋 미리보기를 뒤에서 미리 만들어 색 전환을 즉시(캐시) 처리."""
        if self.runner.busy("prewarm") or self.runner.busy("preview"):
            return
        todo = [p.id for p in self.presets if p.id not in self.previews]
        if not todo:
            return
        pid, gen = todo[0], self.gen

        def done(out):
            if gen == self.gen:
                self.previews[pid] = out
                if self.session.preset_id == pid and not self.runner.busy("preview"):
                    self._show(out)
                self._prewarm()
        self.runner.start("prewarm", self._make_preview(pid), on_done=done, on_fail=lambda m: log.info("미리 만들기 실패"))

    def _show(self, out: np.ndarray) -> None:
        self.compare.set_images(self.preview_img, out)
        if self.presentation is not None:
            self.presentation.set_images(self.preview_img, out)
            self.presentation.set_busy("")

    def _show_current(self) -> None:
        self.render_preview(self.session.preset_id)

    def _full_result(self, then) -> None:
        """원본 해상도 결과(고품질 결과가 선택돼 있으면 그것, 아니면 로컬 렌더 + 검증 합성)."""
        s = self.session
        if s.result_hq is not None and self.hq_preview and self.hq_preview[0] == s.preset_id and not self.btn_local.isChecked():
            then(s.result_hq)
            return
        if s.result_local is not None and s.verified:
            then(s.result_local)
            return
        gen, preset = self.gen, self.preset_by_id[s.preset_id]

        def work():
            layer = render_local(s, preset, preview=False)
            return composite_verified(s.original, layer, s.mask, s.mask_feather_px)

        def done(out):
            self._idle("full")
            if gen != self.gen:
                return
            s.result_local, s.verified = out, True
            then(out)
        self._busy("원본 해상도로 만드는 중…", "full")
        self.runner.start("full", work, on_done=done, on_fail=self._fail("full"))

    def save(self) -> None:
        if self.step != 4 or self.session is None:
            return
        folder = self.settings.get("output_folder") or self.config["paths"].get("output_default", "")
        if not folder or not Path(folder).is_dir():
            folder = QFileDialog.getExistingDirectory(self, "저장할 폴더 선택", str(Path.home() / "Pictures"))
            if not folder:
                return
            self.settings["output_folder"] = folder
            save_user_settings(self.settings)
        self._full_result(lambda out: self._save_files(out, folder))

    def _save_files(self, result: np.ndarray, folder: str) -> None:
        s, ex = self.session, self.config["export"]
        site, preset = self.site_name.text(), self.preset_by_id[s.preset_id].name
        wm = bool(self.settings.get("watermark", ex["watermark"]))

        def work():
            return export_result(s, folder, site, set(ex["formats"]), result=result, preset_name=preset,
                                 watermark=wm, jpeg_quality=ex["jpeg_quality"], image_format=ex["image_format"])

        def done(paths):
            self._idle("save")
            self.last_saved = paths
            self._banner("저장했습니다: " + ", ".join(Path(p).name for p in paths) + f"  (폴더: {folder})")
        self._busy("저장하는 중…", "save")
        self.runner.start("save", work, on_done=done, on_fail=self._fail("save"))

    def start_hq(self) -> None:
        ok, why = self.hq.available()
        if not ok:
            self._banner(why)
            return
        self._full_result(self._hq_confirm)

    def _hq_confirm(self, _out) -> None:
        s = self.session
        try:
            pkg = self.hq.prepare(s)
        except Exception as e:
            self._banner(str(e))
            return
        if self.consent.needs_confirmation():
            dlg = SendConfirmDialog(pkg, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            if dlg.skip.isChecked():
                self.consent.skip_for_this_run()
        pkg.confirmed = True
        n, gen, pid = self.settings.get("hq_candidates", 1), self.gen, s.preset_id
        self._busy("고품질로 다듬는 중…(최대 1분)", "hq")
        holder = {}

        def work():
            w = holder.get("w")
            return self.hq.refine(s, n=n, package=pkg, cancel=w.cancel if w else None)

        def done(cands):
            self._idle("hq")
            if gen != self.gen:
                return
            chosen = cands[0] if len(cands) == 1 else self._choose(cands)
            if chosen is None:
                return
            s.result_hq = chosen
            self.hq_preview = (pid, image_io.make_preview(chosen, self.max_prev)[0])
            self.btn_local.setChecked(False)
            self.btn_local.show()
            self._show(self.hq_preview[1])
            self._banner("고품질 결과를 표시합니다. [로컬 결과 보기]로 비교할 수 있습니다.")

        def fail(msg):
            self._idle("hq")
            self._banner(f"고품질 모드 실패: {msg}")
        holder["w"] = self.runner.start("hq", work, on_done=done, on_fail=fail)

    def _choose(self, cands):
        dlg = QDialog(self)
        dlg.setWindowTitle("고품질 후보 선택")
        lay = QHBoxLayout(dlg)
        picked = {}
        for i, c in enumerate(cands):
            b = QPushButton(f"후보 {i + 1}")
            t = image_io.make_preview(c, 360)[0]
            b.setIcon(QIcon(bgr_to_pixmap(t)))
            b.setIconSize(bgr_to_pixmap(t).size())
            b.clicked.connect(lambda _=False, k=i: (picked.update(k=k), dlg.accept()))
            lay.addWidget(b)
        return cands[picked["k"]] if dlg.exec() == QDialog.DialogCode.Accepted and "k" in picked else None

    def start_presentation(self) -> None:
        if self.step != 4 or self.session is None:
            return
        self.presentation = PresentationWindow(self.presets, self.session.preset_id)
        self.presentation.presetRequested.connect(self._present_preset)
        self.presentation.closed.connect(lambda: setattr(self, "presentation", None))
        cur = self.previews.get(self.session.preset_id)
        if self.hq_preview and self.hq_preview[0] == self.session.preset_id and not self.btn_local.isChecked():
            cur = self.hq_preview[1]
        self.presentation.set_images(self.preview_img, cur)
        self.presentation.showFullScreen()

    def _present_preset(self, pid: str) -> None:
        if pid not in self.previews and self.presentation is not None:
            self.presentation.set_busy("색상 준비 중…")
        self._set_preset(pid)

    # ================= 공통 =================
    def _open_settings(self) -> None:
        if SettingsDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.settings = load_user_settings()
            if self.step == 4:
                ok, why = self.hq.available()
                self.btn_hq.setEnabled(ok)
                self.btn_hq.setToolTip("" if ok else why)

    def _busy(self, text: str, kind: str) -> None:
        self._busy_kind = kind
        self.busy_label.setText(text)
        self.btn_cancel.setVisible(kind in ("hq", "full", "preview", "load"))
        self.busy_row.show()

    def _idle(self, kind: str) -> None:
        if self._busy_kind == kind:
            self.busy_row.hide()
            self._busy_kind = None

    def _cancel_busy(self) -> None:
        if self._busy_kind:
            self.runner.cancel(self._busy_kind)
            if self._busy_kind == "hq":
                self._banner("고품질 작업을 취소했습니다. 로컬 결과를 유지합니다.")
            self.busy_row.hide()
            self._busy_kind = None

    def _fail(self, kind: str):
        def handler(msg: str) -> None:
            self._idle(kind)
            self._banner(msg)
        return handler

    def _banner(self, text: str) -> None:
        self.banner.setText(text)
        self.banner.show()

    # 끌어놓기
    def dragEnterEvent(self, e) -> None:
        urls = e.mimeData().urls()
        if urls and Path(urls[0].toLocalFile()).suffix.lower() in image_io.SUPPORTED_EXTS:
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        self.open_photo(e.mimeData().urls()[0].toLocalFile())

    def closeEvent(self, e) -> None:
        for k in ("load", "encode", "mask", "preview", "prewarm", "full", "hq", "save", "thumbs"):
            self.runner.cancel(k)
        if self.presentation is not None:
            self.presentation.close()
        self.runner.shutdown()
        super().closeEvent(e)

