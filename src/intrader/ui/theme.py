"""Minimal workstation themes for the Intrader desktop application."""

from __future__ import annotations


THEMES = {
    "Sand": {
        "bg": "#f6f4ef",
        "bg2": "#f1f5f6",
        "panel": "#fffefa",
        "panel2": "#fbfaf7",
        "border": "#ece8e1",
        "muted": "#78838a",
        "text": "#243039",
        "title": "#1f2a32",
        "accent": "#edf4f6",
        "accent_border": "#d6e3e7",
        "accent_text": "#29444f",
        "header": "#f4f3ef",
    },
    "Frost": {
        "bg": "#f4f8fb",
        "bg2": "#eef5f8",
        "panel": "#fbfdff",
        "panel2": "#f7fbfe",
        "border": "#e3ebef",
        "muted": "#71808b",
        "text": "#24313a",
        "title": "#1d2b35",
        "accent": "#eaf4fb",
        "accent_border": "#d0e2ed",
        "accent_text": "#23495f",
        "header": "#eff5f8",
    },
    "Paper": {
        "bg": "#f8f7f4",
        "bg2": "#f3f5f4",
        "panel": "#ffffff",
        "panel2": "#fcfbf8",
        "border": "#eceae5",
        "muted": "#797f84",
        "text": "#2b3135",
        "title": "#20262a",
        "accent": "#f0f4f5",
        "accent_border": "#dce5e7",
        "accent_text": "#304149",
        "header": "#f5f4f1",
    },
}


def build_stylesheet(theme_name: str = "Sand") -> str:
    p = THEMES.get(theme_name, THEMES["Sand"])
    return f"""
QWidget {{
    background: transparent;
    color: {p["text"]};
    font-family: "Segoe UI";
    font-size: 12px;
}}
QMainWindow, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 {p["bg"]},
        stop:0.58 {p["bg"]},
        stop:1 {p["bg2"]}
    );
}}
QFrame#TopBar {{
    background: rgba(255,255,255,0.78);
    border: none;
    border-bottom: 1px solid {p["border"]};
}}
QFrame#Card {{
    background: {p["panel"]};
    border: 1px solid {p["border"]};
    border-radius: 14px;
}}
QFrame#MetricRibbon {{
    background: {p["panel"]};
    border: 1px solid {p["border"]};
    border-radius: 13px;
}}
QFrame#RibbonDivider {{
    background: {p["border"]};
    border: none;
}}
QFrame#BottomDock {{
    background: rgba(255,255,255,0.96);
    border: 1px solid {p["border"]};
    border-radius: 18px;
}}
QLabel#AppTitle {{
    font-size: 19px;
    font-weight: 750;
    color: {p["title"]};
}}
QLabel#PageTitle {{
    font-size: 19px;
    font-weight: 700;
    color: {p["title"]};
}}
QLabel#CardTitle {{
    font-size: 11px;
    font-weight: 650;
    color: #66727b;
}}
QLabel#HeroValue {{
    font-size: 27px;
    font-weight: 740;
    color: {p["title"]};
}}
QLabel#MetricValue {{
    font-size: 18px;
    font-weight: 700;
    color: {p["title"]};
}}
QLabel#RibbonLabel {{
    font-size: 10px;
    font-weight: 650;
    color: {p["muted"]};
}}
QLabel#RibbonValue {{
    font-size: 17px;
    font-weight: 700;
    color: {p["title"]};
}}
QLabel#Muted {{ color: {p["muted"]}; }}
QLabel#Positive {{ color: #2d8a60; font-weight: 700; }}
QLabel#Negative {{ color: #c64b4b; font-weight: 700; }}
QLabel#Warning {{ color: #a36d16; font-weight: 700; }}
QPushButton, QToolButton {{
    background: rgba(255,255,255,0.80);
    border: 1px solid {p["border"]};
    border-radius: 8px;
    padding: 6px 10px;
    color: #2f3941;
}}
QPushButton:hover, QToolButton:hover {{
    background: {p["accent"]};
    border-color: {p["accent_border"]};
}}
QPushButton:pressed, QToolButton:pressed {{ background: {p["header"]}; }}
QPushButton#PrimaryButton {{
    background: {p["accent"]};
    border: 1px solid {p["accent_border"]};
    color: {p["accent_text"]};
    font-weight: 650;
}}
QPushButton#DockNavButton {{
    border: none;
    padding: 8px 12px;
    background: transparent;
    border-radius: 10px;
}}
QPushButton#DockNavButton:hover {{ background: {p["header"]}; }}
QPushButton#DockNavButton[active="true"] {{
    background: {p["accent"]};
    color: {p["accent_text"]};
    font-weight: 700;
}}
QPushButton#TimeframeButton {{
    min-width: 30px;
    max-width: 42px;
    min-height: 24px;
    max-height: 24px;
    padding: 0 5px;
    border-radius: 7px;
    border: 1px solid transparent;
    background: transparent;
    color: {p["muted"]};
    font-size: 10px;
    font-weight: 650;
}}
QPushButton#TimeframeButton:hover {{
    background: {p["header"]};
}}
QPushButton#TimeframeButton[timeframeActive="true"] {{
    background: {p["accent"]};
    border: 1px solid {p["accent_border"]};
    color: {p["accent_text"]};
}}
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox {{
    background: rgba(255,255,255,0.86);
    border: 1px solid {p["border"]};
    border-radius: 8px;
    padding: 6px 8px;
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none;
    width: 18px;
}}
QTableWidget, QTextBrowser {{
    background: rgba(255,255,255,0.82);
    alternate-background-color: {p["panel2"]};
    border: 1px solid {p["border"]};
    border-radius: 9px;
    gridline-color: #f0ede8;
    selection-background-color: {p["accent"]};
    selection-color: {p["title"]};
}}
QHeaderView::section {{
    background: {p["header"]};
    color: #5f6970;
    border: none;
    border-bottom: 1px solid {p["border"]};
    padding: 6px;
    font-weight: 620;
}}
QTabWidget::pane {{
    border: 1px solid {p["border"]};
    background: rgba(255,255,255,0.66);
    border-radius: 9px;
}}
QTabBar::tab {{
    background: {p["header"]};
    border: none;
    padding: 7px 11px;
    color: {p["muted"]};
}}
QTabBar::tab:selected {{
    background: {p["panel"]};
    color: {p["accent_text"]};
    font-weight: 700;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: #dfddd7;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 13px;
    margin: -5px 0;
    border-radius: 7px;
    background: #91afba;
}}
QProgressBar {{
    background: #eceff0;
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background: #a7c2ca; border-radius: 4px; }}
QSplitter::handle {{
    background: transparent;
    width: 5px;
    height: 5px;
}}
"""


APP_STYLESHEET = build_stylesheet("Sand")
