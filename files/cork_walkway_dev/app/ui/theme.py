"""간편 화면 디자인 토큰·스타일시트.

UI/UX Pro Max 스킬 데이터(nextlevelbuilder/ui-ux-pro-max-skill, MIT)의 B2B 서비스 권장안을 따른다.
- 스타일: Minimalism & Swiss + Accessible(styles.csv 1·8행). 장식(그라데이션·유리 효과·과한 움직임) 없음
- 색: colors.csv B2B Service 행(슬레이트 중립색 + 신뢰감 있는 파란 CTA). 본문 대비 4.5:1 이상
- 글꼴: typography.csv 'Korean Modern' = Noto Sans KR(없으면 Windows 기본 맑은 고딕)
- 규칙: 라벨은 입력 위에, 눈에 보이는 포커스 테두리, 비활성·진행 중 상태 표시, 8px 이상 간격
"""
from __future__ import annotations

# ---- 색 토큰 ----
BG = "#F8FAFC"            # 앱 배경
CARD = "#FFFFFF"          # 패널·카드
TEXT = "#0F172A"          # 본문(배경 대비 약 17:1)
MUTED = "#475569"         # 보조 글자(약 7.5:1)
SUBTLE = "#64748B"        # 아주 옅은 안내(약 4.8:1)
BORDER = "#E2E8F0"
BORDER_STRONG = "#CBD5E1"
HOVER = "#F1F5F9"
PRIMARY = "#0369A1"       # CTA(흰 글자 대비 약 5.9:1)
PRIMARY_HOVER = "#075985"
PRIMARY_SOFT = "#E0F2FE"
ACCENT = "#B45309"        # 코르크 계열 포인트(제목 표식 등 장식용)
DANGER = "#DC2626"
INFO_BG, INFO_BORDER = "#F0F9FF", "#BAE6FD"
VIEW_BG = "#0F172A"       # 사진 비교 영역 배경

FONT = "'Noto Sans KR', 'Malgun Gothic', 'Segoe UI', sans-serif"
RADIUS = 10

QSS = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ font-family: {FONT}; font-size: 10.5pt; color: {TEXT}; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 6px 8px; }}

/* 상단 바 */
QFrame#header {{ background: {CARD}; border-bottom: 1px solid {BORDER}; }}
QLabel#brandMark {{ background: {ACCENT}; border-radius: 6px; }}
QLabel#brand {{ font-size: 13pt; font-weight: 700; }}
QLabel#brandSub {{ color: {MUTED}; font-size: 9.5pt; }}

/* 카드·구역 */
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
QLabel#stepNo {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; border-radius: 11px; font-weight: 700;
                 font-size: 9pt; min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }}
QLabel#sectionTitle {{ font-weight: 700; font-size: 10.5pt; }}
QLabel#hint {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#fileName {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#counter {{ color: {SUBTLE}; font-size: 9pt; }}

/* 버튼 */
QPushButton, QToolButton {{ background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
                            padding: 7px 14px; min-height: 22px; }}
QPushButton:hover, QToolButton:hover {{ background: {HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BORDER}; }}
QPushButton:focus, QToolButton:focus {{ border: 2px solid {PRIMARY}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #94A3B8; background: {HOVER}; border-color: {BORDER}; }}
QPushButton[primary="true"] {{ background: {PRIMARY}; color: white; border: 1px solid {PRIMARY}; font-weight: 700; }}
QPushButton[primary="true"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton[primary="true"]:focus {{ border: 2px solid {TEXT}; }}
QPushButton[primary="true"]:disabled {{ background: {BORDER}; border-color: {BORDER_STRONG}; color: {SUBTLE}; }}
QPushButton[ghost="true"], QToolButton[ghost="true"] {{ background: transparent; border: 1px solid transparent;
                                                       color: {MUTED}; }}
QPushButton[ghost="true"]:hover, QToolButton[ghost="true"]:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton[danger="true"] {{ color: {DANGER}; }}

/* 비교 방식 전환(세그먼트) */
QFrame#segment {{ background: {HOVER}; border: 1px solid {BORDER}; border-radius: 9px; }}
QFrame#segment QPushButton {{ background: transparent; border: none; border-radius: 7px; padding: 6px 14px;
                              color: {MUTED}; }}
QFrame#segment QPushButton:checked {{ background: {CARD}; color: {TEXT}; font-weight: 700;
                                      border: 1px solid {BORDER}; }}
QFrame#segment QPushButton:focus {{ border: 2px solid {PRIMARY}; }}

/* 입력 */
QLineEdit, QPlainTextEdit {{ background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
                             padding: 7px 10px; selection-background-color: {PRIMARY_SOFT};
                             selection-color: {TEXT}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {PRIMARY}; }}

/* 소재 목록 */
QListWidget#materials {{ background: transparent; border: none; outline: none; }}
QListWidget#materials::item {{ border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; margin: 0 0 6px 0;
                               background: {CARD}; color: {TEXT}; }}
QListWidget#materials::item:hover {{ background: {HOVER}; }}
QListWidget#materials::item:selected {{ border: 2px solid {PRIMARY}; background: {PRIMARY_SOFT}; color: {TEXT}; }}

/* 사진 영역 */
QFrame#stage {{ background: {VIEW_BG}; border-radius: {RADIUS}px; }}
QFrame#dropzone {{ background: {CARD}; border: 2px dashed {BORDER_STRONG}; border-radius: 14px; }}
QLabel#dropIcon {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; border-radius: 28px; font-size: 20pt;
                   font-weight: 700; }}
QLabel#dropTitle {{ font-size: 14pt; font-weight: 700; }}

/* 알림·진행 */
QLabel#banner {{ background: {INFO_BG}; border: 1px solid {INFO_BORDER}; border-radius: 8px; padding: 9px 12px;
                 color: {TEXT}; }}
QLabel#banner[kind="error"] {{ background: #FEF2F2; border-color: #FECACA; }}
QLabel#banner[kind="ok"] {{ background: #F0FDF4; border-color: #BBF7D0; }}
QFrame#busy {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; }}
QProgressBar {{ background: {BORDER}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 3px; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ image: none; border-left: 5px solid {BG}; border-right: 5px solid {BG};
                                background: {BORDER}; }}
QSplitter::handle:horizontal:hover {{ background: {PRIMARY}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QCheckBox {{ spacing: 8px; }}
QGroupBox {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; margin-top: 14px;
             padding: 18px 12px 12px 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {TEXT}; }}
QComboBox {{ background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 6px 10px; }}
QComboBox:focus {{ border: 2px solid {PRIMARY}; }}
QTableWidget {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; gridline-color: {BORDER}; }}
QHeaderView::section {{ background: {HOVER}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px;
                        font-weight: 700; }}
"""
