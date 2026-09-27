"""Intrader fixed light editorial workstation theme.

The visual identity is intentionally fixed. Only the accent hue is user-selectable.
Market semantics remain fixed: bullish green and bearish red never follow the accent.
"""

from __future__ import annotations


DEFAULT_ACCENT = "#D85C5C"
ACCENT_PRESETS = (
    ("Matte Red", "#D85C5C"),
    ("Pastel Peach", "#F2B894"),
    ("Matte Green", "#5E9B72"),
    ("Pastel Cyan", "#A6D7D8"),
    ("Matte Blue", "#5E7FAE"),
    ("Pastel Violet", "#C7B7DF"),
    ("Matte Orange", "#D9874E"),
    ("Pastel Pink", "#E3B5C4"),
)

BULLISH_COLOR = "#2D8A60"
BEARISH_COLOR = "#C64B4B"


def build_stylesheet(accent: str = DEFAULT_ACCENT) -> str:
    return f"""
QWidget {{
    background: transparent;
    color: #17191c;
    font-family: "Segoe UI";
    font-size: 12px;
}}
QMainWindow, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: #F5F4F1;
}}
QFrame#TopBar {{
    background: #FBFAF7;
    border: none;
    border-bottom: 1px solid #E5E2DB;
}}
QFrame#Card,
QFrame#MetricRibbon,
QFrame#SoftPanel {{
    background: rgba(255,255,255,0.94);
    border: 1px solid #E8E5DE;
    border-radius: 14px;
}}
QFrame#BottomDock {{
    background: #171717;
    border: none;
    border-radius: 14px;
}}
QFrame#RibbonDivider {{
    background: #E7E4DD;
    border: none;
}}
QLabel#AppTitle {{
    color: #111318;
    font-size: 18px;
    font-weight: 720;
    letter-spacing: 4px;
}}
QLabel#BrandSubtitle {{
    color: #92979C;
    font-size: 9px;
    letter-spacing: 3px;
}}
QLabel#PageTitle {{
    color: #17191c;
    font-size: 22px;
    font-weight: 720;
}}
QLabel#SectionTitle {{
    color: #17191c;
    font-size: 15px;
    font-weight: 680;
}}
QLabel#CardTitle {{
    color: #58616A;
    font-size: 10px;
    font-weight: 680;
    letter-spacing: 1px;
}}
QLabel#HeroValue {{
    color: #17191c;
    font-size: 28px;
    font-weight: 760;
}}
QLabel#MetricValue {{
    color: #17191c;
    font-size: 18px;
    font-weight: 720;
}}
QLabel#RibbonLabel {{
    color: #757D84;
    font-size: 9px;
    font-weight: 680;
    letter-spacing: 1px;
}}
QLabel#RibbonValue {{
    color: #17191c;
    font-size: 18px;
    font-weight: 720;
}}
QLabel#Muted {{ color: #7C848A; }}
QLabel#Positive {{ color: #2D8A60; font-weight: 700; }}
QLabel#Negative {{ color: #C64B4B; font-weight: 700; }}
QLabel#Accent {{ color: {accent}; font-weight: 700; }}
QLabel#Warning {{ color: #A36D16; font-weight: 700; }}

QPushButton, QToolButton {{
    background: #FBFAF7;
    border: 1px solid #DFDCD5;
    border-radius: 9px;
    padding: 7px 11px;
    color: #25292D;
}}
QPushButton:hover, QToolButton:hover {{
    background: #F1F0EC;
    border-color: #D4D0C8;
}}
QPushButton:pressed, QToolButton:pressed {{
    background: #EDEBE6;
}}
QPushButton#PrimaryButton {{
    background: #171717;
    border: 1px solid #171717;
    color: white;
    font-weight: 680;
}}
QPushButton#SecondaryButton {{
    background: #FBFAF7;
    border: 1px solid #DFDCD5;
    color: #25292D;
}}
QPushButton#DockNavButton {{
    color: #BABEC2;
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 8px 14px;
}}
QPushButton#DockNavButton:hover {{
    background: #262626;
    color: white;
}}
QPushButton#DockNavButton[active="true"] {{
    background: #262626;
    color: white;
    font-weight: 700;
}}
QPushButton#TimeframeButton {{
    min-width: 30px;
    max-width: 44px;
    min-height: 24px;
    max-height: 24px;
    padding: 0 6px;
    border-radius: 7px;
    background: #FAF9F6;
    border: 1px solid #E5E2DB;
    color: #70777D;
    font-size: 10px;
    font-weight: 650;
}}
QPushButton#TimeframeButton:hover {{
    color: #17191c;
    background: #F0EFEB;
}}
QPushButton#TimeframeButton[timeframeActive="true"] {{
    color: white;
    background: #171717;
    border-color: #171717;
}}
QPushButton#AccentDot {{
    border: none;
    border-radius: 8px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    padding: 0;
}}
QPushButton#AccentDot[selected="true"] {{
    border: 2px solid #171717;
}}

QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox {{
    background: #FBFAF7;
    border: 1px solid #DFDCD5;
    border-radius: 8px;
    padding: 7px 9px;
    color: #272A2E;
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none;
    width: 18px;
}}

QTableWidget, QTextBrowser {{
    background: #FEFDFB;
    alternate-background-color: #FAF9F6;
    border: 1px solid #E7E4DD;
    border-radius: 9px;
    gridline-color: #ECE9E3;
    selection-background-color: #EEF6F2;
    selection-color: #17191c;
}}
QHeaderView::section {{
    background: #F6F4F0;
    color: #5F676E;
    border: none;
    border-bottom: 1px solid #E5E2DB;
    padding: 7px;
    font-weight: 650;
}}

QTabWidget::pane {{
    border: 1px solid #E7E4DD;
    background: #FEFDFB;
    border-radius: 9px;
}}
QTabBar::tab {{
    background: transparent;
    border: none;
    color: #6C7379;
    padding: 8px 15px;
}}
QTabBar::tab:selected {{
    color: #17191c;
    font-weight: 700;
    border-bottom: 2px solid {accent};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: #E1DED8;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: {accent};
}}
QProgressBar {{
    background: #ECE9E3;
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 4px;
}}
QSplitter::handle {{
    background: transparent;
    width: 5px;
    height: 5px;
}}
QScrollBar:vertical {{
    width: 8px;
    background: transparent;
}}
QScrollBar::handle:vertical {{
    background: #D4D0C8;
    min-height: 28px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


APP_STYLESHEET = build_stylesheet(DEFAULT_ACCENT)
