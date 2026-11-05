"""간편 모드 메인 창 (모듈 08): 사진 올리기 → Gemini API 자동 변환 → 시공 전·후 비교 → 저장.

왼쪽: ① 현장 사진 ② 바닥 소재(기본 코르크 + 사용자가 추가한 소재) ③ 추가 요청(선택) → [시공 예상도 만들기]
오른쪽: 사진 놓는 곳 / 전·후 비교 + 비교 방식·저장.
사진을 열면 (전송 확인 후) 바로 Gemini API로 보낸다. 결과는 gemini_convert가 정렬·길 영역만 합성·
무변경 검증까지 마친 것만 보인다. 무거운 작업(사진 읽기, 소재 등록, Gemini 호출, 저장)은 Runner에서 실행한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QProgressBar, QScrollArea, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)

from app.ai.gemini_convert import GeminiConvert
from app.config import load_user_settings, resolve_resource, save_user_settings
from app.core import image_io
from app.core.cork_material import load_presets
from app.core.export import export_result
from app.core.materials import add_custom, list_custom, remove_custom
from app.models import WorkSession
from app.security.privacy import SendConsent, TransferLog
from app.ui.compare_view import CompareView
from app.ui.quick_panels import (AddMaterialDialog, DropZone, MaterialPanel, button, header_bar, photo_card,
                                 request_card, section)
from app.ui.settings_dialog import SendConfirmDialog, SettingsDialog, TransferLogDialog
from app.ui.theme import QSS
from app.ui.workers import Runner

log = logging.getLogger("corkwalkway")

GUIDE_RESULT = "가운데 선을 끌거나 ← → 키로 시공 전·후를 비교하세요."
COMPARE_MODES = (("slider", "가운데 선"), ("side", "나란히"), ("toggle", "전·후 전환"))
_TASKS = ("load", "convert", "save", "material")
APP_TITLE = "시공 시뮬레이터"
SIDEBAR_MIN, SIDEBAR_MAX = 280, 560     # 왼쪽 패널 폭 범위(px). 사용자가 구분선을 끌어 조정, 다음 실행에도 유지
MAIN_MIN_W = 620                        # 오른쪽 사진 영역 최소 폭
WINDOW_MIN = (SIDEBAR_MIN + MAIN_MIN_W + 48, 600)
SMALL_SCREEN = (1400, 900)              # 이보다 작은 화면(태블릿·노트북)은 최대화로 시작


class QuickWindow(QMainWindow):
    def __init__(self, config: dict, runner: Runner | None = None, converter: GeminiConvert | None = None) -> None:
        super().__init__()
        self.config = config
        self.settings = load_user_settings()
        self.setWindowTitle(APP_TITLE)
        self.setStyleSheet(QSS)
        self.setAcceptDrops(True)
        self.setMinimumSize(*WINDOW_MIN)      # 이보다 작으면 메뉴·버튼이 잘리므로 막는다
        self.resize(1360, 860)
        self.runner = runner or Runner()
        self.materials_dir = resolve_resource(config["paths"]["materials"])
        self.presets = load_presets(str(self.materials_dir / "presets.yaml"))
        self.gemini = converter or GeminiConvert(config, SendConsent(), TransferLog(), materials_dir=self.materials_dir)
        # 전송 확인·내역은 실제로 보내는 객체의 것을 써야 한다(창과 변환기가 따로 가지면 어긋남)
        self.consent, self.transfer_log = self.gemini.consent, self.gemini.transfer_log
        self.max_prev = config["render"]["max_preview_px"]
        self.session: WorkSession | None = None
        self.preview_before: np.ndarray | None = None
        self.result_preset: str | None = None      # 현재 결과를 만든 소재 id
        self.last_saved: list[str] = []
        self._busy_kind: str | None = None
        self._build_ui()
        self.reload_materials()
        self._sync()

    # ================= 화면 구성 =================
    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header())
        main = self.main_area = QWidget()
        main.setMinimumWidth(MAIN_MIN_W)
        main.setLayout(self._main_area())
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(14)
        self.splitter.addWidget(self._sidebar())
        self.splitter.addWidget(main)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        w = min(SIDEBAR_MAX, max(SIDEBAR_MIN, int(self.settings.get("sidebar_width", 340))))
        self.splitter.setSizes([w, 1360 - w])
        self.splitter.splitterMoved.connect(self._sidebar_moved)
        self.splitter.handle(1).setToolTip("끌어서 왼쪽 메뉴 폭 조정")
        body = QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 16)
        body.addWidget(self.splitter)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)
        for btn in self.mode_btns.values():        # 스타일 적용 후 크기로 최소 폭 고정: 창이 좁아도 글자가 잘리지 않게
            btn.ensurePolished()
            btn.setMinimumWidth(btn.sizeHint().width())

    def _sidebar_moved(self, *_):
        self.settings["sidebar_width"] = int(self.splitter.sizes()[0])

    def sidebar_width(self) -> int:
        return int(self.splitter.sizes()[0])

    def _header(self) -> QFrame:
        bar, self.btn_log, self.btn_settings = header_bar(APP_TITLE, "현장 사진 한 장으로 만드는 AI 바닥 시공 예상도")
        self.btn_log.clicked.connect(lambda: TransferLogDialog(self.transfer_log, self).exec())
        self.btn_settings.clicked.connect(self._open_settings)
        return bar

    def _sidebar(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(12)

        from app.ui.camera_dialog import has_camera
        card, self.btn_open, self.btn_camera, self.file_label, self.size_label = photo_card()
        self.btn_open.clicked.connect(self.open_dialog)
        self.btn_camera.clicked.connect(self.take_photo)
        self.btn_camera.setVisible(has_camera())
        lay.addWidget(card)

        card, c = section("2", "바닥 소재", "기본은 코르크입니다. 다른 바닥재 샘플 사진을 추가하면 그 소재로 바꿔 보여 줍니다.")
        self.material_panel = MaterialPanel()
        self.material_panel.changed.connect(self._preset_changed)
        self.material_panel.addRequested.connect(self.add_material)
        self.material_panel.removeRequested.connect(self.remove_material)
        c.addWidget(self.material_panel)
        lay.addWidget(card)

        card, self.chk_debris, self.chk_edge, self.note_panel = request_card(
            bool(self.settings.get("clear_debris", True)), bool(self.settings.get("edge_finish", True)))
        self.chk_debris.toggled.connect(lambda on: self._option_toggled("clear_debris", on))
        self.chk_edge.toggled.connect(lambda on: self._option_toggled("edge_finish", on))
        lay.addWidget(card)

        lay.addStretch(1)
        panel.setMinimumWidth(1)
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 실행 버튼은 스크롤 밖에 고정해 화면이 작아도 항상 보이게 한다
        self.btn_convert = button("시공 예상도 만들기", primary=True, tip="Gemini 호출 1회(요금 발생)")
        self.btn_convert.setMinimumHeight(50)
        self.btn_convert.clicked.connect(self.start_convert)
        side = QWidget()
        side.setMinimumWidth(SIDEBAR_MIN)
        side.setMaximumWidth(SIDEBAR_MAX)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(12)
        sl.addWidget(scroll, 1)
        sl.addWidget(self.btn_convert)
        return side

    def _main_area(self) -> QVBoxLayout:
        lay = QVBoxLayout()
        lay.setSpacing(10)
        self.view_stack = QStackedWidget()
        self.home = DropZone()
        self.home.openRequested.connect(self.open_dialog)
        self.compare = CompareView()
        self.view_stack.addWidget(self.home)
        self.view_stack.addWidget(self.compare)          # 비교 화면은 스스로 짙은 배경을 칠한다
        lay.addWidget(self.view_stack, 1)

        self.banner = QLabel(objectName="banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        lay.addWidget(self.banner)

        self.busy_row = QFrame(objectName="busy")
        busy = QHBoxLayout(self.busy_row)
        busy.setContentsMargins(14, 8, 8, 8)
        self.busy_label = QLabel("")
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(180)
        self.btn_cancel = button("취소", ghost=True)
        self.btn_cancel.clicked.connect(self._cancel_busy)
        busy.addWidget(self.busy_label, 1)
        busy.addWidget(self.busy_bar)
        busy.addWidget(self.btn_cancel)
        self.busy_row.hide()
        lay.addWidget(self.busy_row)

        self.bottom = QFrame(objectName="card")
        bottom = QHBoxLayout(self.bottom)
        bottom.setContentsMargins(12, 10, 12, 10)
        bottom.setSpacing(10)
        seg = QFrame(objectName="segment")
        sg = QHBoxLayout(seg)
        sg.setContentsMargins(3, 3, 3, 3)
        sg.setSpacing(2)
        self.mode_btns = {}
        for mode, label in COMPARE_MODES:
            b = button(label)
            b.setCheckable(True)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, m=mode: self._set_mode(m))
            sg.addWidget(b)
            self.mode_btns[mode] = b
        self.mode_btns["slider"].setChecked(True)
        bottom.addWidget(seg)
        bottom.addStretch(1)
        bottom.addWidget(QLabel("현장 이름"))
        self.site_name = QLineEdit(placeholderText="저장 파일 이름에 쓰입니다")
        self.site_name.setMinimumHeight(40)
        self.site_name.setMinimumWidth(120)
        self.site_name.setMaximumWidth(260)
        self.btn_save = button("저장", primary=True, tip="시공 후 사진·전후 비교·PDF")
        self.btn_save.setMinimumWidth(110)
        self.btn_save.clicked.connect(self.save)
        bottom.addWidget(self.site_name)
        bottom.addWidget(self.btn_save)
        lay.addWidget(self.bottom)
        return lay

    def _has_result(self) -> bool:
        return self.session is not None and self.session.result_hq is not None and self.session.verified

    def _sync(self) -> None:
        has_photo, busy = self.session is not None, self._busy_kind is not None
        self.view_stack.setCurrentIndex(1 if has_photo else 0)
        self.bottom.setVisible(self._has_result())
        self.btn_save.setEnabled(self._has_result() and not busy)
        self.btn_convert.setEnabled(has_photo and not busy)
        self.btn_convert.setText("다시 만들기" if self._has_result() else "시공 예상도 만들기")
        self.btn_open.setEnabled(not busy)
        self.home.btn.setEnabled(not busy)
        self.material_panel.btn_add.setEnabled(self._busy_kind != "material")

    # ================= 사진 =================
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
            img = image_io.make_preview(img, image_io.HUGE_LIMIT_PX)[0]
            log.info("아주 큰 사진: 긴 변 %dpx로 축소", image_io.HUGE_LIMIT_PX)
        self.settings["last_folder"] = str(Path(path).parent)
        save_user_settings(self.settings)
        self.set_session(img, Path(path).name)

    def take_photo(self) -> None:
        from app.ui.camera_dialog import CameraDialog
        dlg = CameraDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.image is not None:
            self.set_session(dlg.image, "카메라 촬영")

    def set_session(self, img: np.ndarray, name: str) -> None:
        """새 사진 → 비교 화면에 '시공 전'을 띄우고 바로 자동 변환 시작."""
        self.runner.cancel("convert")
        self.session = WorkSession(original=img, source_name=name, preset_id=self._preset_id())
        self.preview_before = image_io.make_preview(img, self.max_prev)[0]
        self.result_preset = None
        self.file_label.set_full_text(name)
        self.size_label.setText(f"{img.shape[1]} × {img.shape[0]} px")
        self.size_label.show()
        self.banner.hide()
        self.compare.set_images(self.preview_before, None)
        self._sync()
        self.start_convert()

    # ================= 바닥 소재 =================
    def reload_materials(self, select: str | None = None) -> None:
        self.materials = [*self.presets, *list_custom()]
        self.material_by_id = {m.id: m for m in self.materials}
        self.material_panel.set_materials(self.materials, self.materials_dir, select)

    def _preset_id(self) -> str:
        mid = self.material_panel.current_id()
        return mid if mid in self.material_by_id else self.presets[0].id

    def _preset_changed(self, *_):
        if self.session is None:
            return
        self.session.preset_id = self._preset_id()
        if self.result_preset is not None and self.result_preset != self.session.preset_id:
            self._banner("소재를 바꿨습니다. [다시 만들기]를 누르면 이 소재로 다시 만듭니다(호출 1회 요금 발생).")

    def add_material(self) -> None:
        dlg = AddMaterialDialog(self.settings.get("last_folder") or str(Path.home() / "Pictures"), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path, name = dlg.path, dlg.name.text()

        def done(mat):
            self._idle("material")
            self.reload_materials(select=mat.id)
            self._banner(f"소재 '{mat.name}'을(를) 추가했습니다. 이 소재로 바꾸려면 [다시 만들기]를 누르세요."
                         if self.session else f"소재 '{mat.name}'을(를) 추가했습니다.", "ok")

        def fail(msg):
            self._idle("material")
            self._banner(f"소재를 추가하지 못했습니다: {msg}", "error")
        self._busy("소재 샘플을 등록하는 중…", "material")
        self.runner.start("material", add_custom, path, name, on_done=done, on_fail=fail)

    def remove_material(self, material_id: str) -> None:
        m = self.material_by_id.get(material_id)
        if m is None or m in self.presets:
            return
        ok = QMessageBox.question(self, "소재 삭제", f"'{m.name}' 소재를 삭제할까요?\n등록한 샘플 사진도 함께 지워집니다.",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            remove_custom(material_id)
        except (OSError, ValueError) as e:
            log.warning("소재 삭제 실패: %s", type(e).__name__)
            self._banner("소재를 삭제하지 못했습니다. 프로그램을 다시 열어 시도하세요.", "error")
            return
        self.reload_materials(select=self.presets[0].id)

    # ================= Gemini 자동 변환 =================
    def start_convert(self) -> None:
        s = self.session
        if s is None or self.runner.busy("convert"):
            return
        ok, why = self.gemini.available()
        if not ok:
            self._banner(f"자동 변환을 할 수 없습니다: {why} — 오른쪽 위 [설정]에서 확인하세요.", "error")
            return
        material = self.material_by_id[self._preset_id()]
        try:
            pkg = self.gemini.prepare_full(s, material, self.note_panel.text(), self.chk_debris.isChecked(),
                                           self.chk_edge.isChecked())
        except (OSError, ValueError) as e:
            log.warning("전송 준비 실패: %s", type(e).__name__)
            self._banner("보낼 사진을 준비하지 못했습니다. 사진이나 소재 샘플을 다시 확인해 주세요.", "error")
            return
        if self.consent.needs_confirmation():
            dlg = SendConfirmDialog(pkg, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._banner("전송을 취소했습니다. [시공 예상도 만들기]로 언제든 다시 시도할 수 있습니다.")
                return
            if dlg.skip.isChecked():
                self.consent.skip_for_this_run()
        pkg.confirmed = True
        self.banner.hide()
        self._busy(f"Gemini로 '{material.name}' 시공 예상도를 만드는 중… (보통 10~60초)", "convert")
        holder: dict = {}

        def work():
            w = holder.get("w")
            return self.gemini.convert(s, pkg, cancel=w.cancel if w else None)

        def done(res):
            self._idle("convert")
            if s is not self.session:            # 그 사이 다른 사진을 열었으면 버림
                return
            result, mask = res
            s.mask, s.result_hq, s.verified = mask, result, True
            self.result_preset = material.id
            self.compare.set_images(self.preview_before, image_io.make_preview(result, self.max_prev)[0])
            self.compare.setFocus()
            self._banner(GUIDE_RESULT, "ok")
            self._sync()

        def fail(msg):
            self._idle("convert")
            self._banner(f"변환 실패: {msg}", "error")
        holder["w"] = self.runner.start("convert", work, on_done=done, on_fail=fail)
        self._sync()

    # ================= 비교·저장 =================
    def _set_mode(self, mode: str) -> None:
        for m, b in self.mode_btns.items():
            b.setChecked(m == mode)
        self.compare.set_mode(mode)

    def save(self) -> None:
        s = self.session
        if not self._has_result():
            return
        folder = self.settings.get("output_folder") or self.config["paths"].get("output_default", "")
        if not folder or not Path(folder).is_dir():
            folder = QFileDialog.getExistingDirectory(self, "저장할 폴더 선택", str(Path.home() / "Pictures"))
            if not folder:
                return
            self.settings["output_folder"] = folder
            save_user_settings(self.settings)
        ex = self.config["export"]
        m = self.material_by_id.get(self.result_preset or s.preset_id)
        site, preset = self.site_name.text(), (m.name if m else "")
        wm = bool(self.settings.get("watermark", ex["watermark"]))

        def work():
            return export_result(s, folder, site, set(ex["formats"]), result=s.result_hq, preset_name=preset,
                                 watermark=wm, jpeg_quality=ex["jpeg_quality"], image_format=ex["image_format"])

        def done(paths):
            self._idle("save")
            self.last_saved = paths
            self._banner("저장했습니다: " + ", ".join(Path(p).name for p in paths) + f"  (폴더: {folder})", "ok")
        self._busy("저장하는 중…", "save")
        self.runner.start("save", work, on_done=done, on_fail=self._fail("save"))

    # ================= 공통 =================
    def _open_settings(self) -> None:
        if SettingsDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.settings = load_user_settings()
            if self.session is not None and not self._has_result() and self.gemini.available()[0]:
                self._banner("설정을 저장했습니다. [시공 예상도 만들기]를 누르면 변환합니다.")

    def _busy(self, text: str, kind: str) -> None:
        self._busy_kind = kind
        self.busy_label.setText(text)
        self.btn_cancel.setVisible(kind in ("load", "convert"))
        self.busy_row.show()
        self._sync()

    def _idle(self, kind: str) -> None:
        if self._busy_kind == kind:
            self.busy_row.hide()
            self._busy_kind = None
        self._sync()

    def _cancel_busy(self) -> None:
        kind = self._busy_kind
        if kind:
            self.runner.cancel(kind)
            if kind == "convert":
                self._banner("변환을 취소했습니다. (이미 보낸 요청은 Google 서버에서 처리되어 요금이 나갈 수 있습니다)")
            self._idle(kind)

    def _fail(self, kind: str):
        def handler(msg: str) -> None:
            self._idle(kind)
            self._banner(msg, "error")
        return handler

    def _banner(self, text: str, kind: str = "info") -> None:
        self.banner.setText(text)
        self.banner.setProperty("kind", kind)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.show()

    def dragEnterEvent(self, e) -> None:
        urls = e.mimeData().urls()
        if urls and Path(urls[0].toLocalFile()).suffix.lower() in image_io.SUPPORTED_EXTS:
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        if self._busy_kind is None:
            self.open_photo(e.mimeData().urls()[0].toLocalFile())

    def _option_toggled(self, key: str, on: bool) -> None:
        self.settings[key] = bool(on)
        save_user_settings(self.settings)
        if self._has_result():
            self._banner("옵션을 바꿨습니다. [다시 만들기]를 누르면 반영됩니다(호출 1회 요금 발생).")

    def fit_to_screen(self, avail: tuple[int, int] | None = None) -> bool:
        """화면(태블릿 등)이 최소 크기보다 작으면 최소 크기를 화면에 맞춘다. 작은 화면이면 True(최대화 권장)."""
        if avail is None:
            scr = self.screen()
            if scr is None:
                return False
            g = scr.availableGeometry()
            avail = (g.width(), g.height())
        w, h = avail
        self.main_area.setMinimumWidth(max(200, min(MAIN_MIN_W, w - SIDEBAR_MIN - 48)))
        self.setMinimumSize(min(WINDOW_MIN[0], w), min(WINDOW_MIN[1], h))
        return w < SMALL_SCREEN[0] or h < SMALL_SCREEN[1]

    def closeEvent(self, e) -> None:
        self.settings["sidebar_width"] = self.sidebar_width()
        try:
            save_user_settings(self.settings)
        except OSError:
            log.warning("화면 설정을 저장하지 못함")
        for k in _TASKS:
            self.runner.cancel(k)
        self.runner.shutdown()
        super().closeEvent(e)
