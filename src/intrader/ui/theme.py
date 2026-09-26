"""Minimal, low-noise themes for the Intrader desktop application."""

from __future__ import annotations


THEMES = {
    "Sand": {
        "bg": "#f6f4ef",
        "panel": "#fffefa",
        "panel2": "#fbfaf7",
        "border": "#e8e5de",
        "muted": "#7b858c",
        "text": "#243039",
        "title": "#1f2a32",
        "accent": "#edf4f6",
        "accent_border": "#c9dbe2",
        "accent_text": "#29444f",
        "header": "#f2f1ed",
    },
    "Frost": {
        "bg": "#f4f8fb",
        "panel": "#fbfdff",
        "panel2": "#f7fbfe",
        "border": "#dde7ed",
        "muted": "#71808b",
        "text": "#24313a",
        "title": "#1d2b35",
        "accent": "#eaf4fb",
        "accent_border": "#c5dceb",
        "accent_text": "#23495f",
        "header": "#edf4f8",
    },
    "Paper": {
        "bg": "#f8f7f4",
        "panel": "#ffffff",
        "panel2": "#fcfbf8",
        "border": "#e8e6e1",
        "muted": "#797f84",
        "text": "#2b3135",
        "title": "#20262a",
        "accent": "#f0f3f4",
        "accent_border": "#d7dfe2",
        "accent_text": "#304149",
        "header": "#f4f3f0",
    },
}


def build_stylesheet(theme_name: str = "Sand") -> str:
    p = THEMES.get(theme_name, THEMES["Sand"])
    return f"""
QWidget {{
    background: {p["bg"]};
    color: {p["text"]};
    font-family: "Segoe UI";
    font-size: 12px;
}}
QMainWindow, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {p["bg"]};
}}
QFrame#TopBar {{
    background: {p["panel2"]};
    border-bottom: 1px solid {p["border"]};
}}
QFrame#Card {{
    background: {p["panel"]};
    border: 1px solid {p["border"]};
    border-radius: 12px;
}}
QFrame#BottomDock {{
    background: {p["panel"]};
    border: 1px solid {p["border"]};
    border-radius: 18px;
}}
QLabel#AppTitle {{
    font-size: 20px;
    font-weight: 750;
    color: {p["title"]};
}}
QLabel#PageTitle {{
    font-size: 20px;
    font-weight: 750;
    color: {p["title"]};
}}
QLabel#CardTitle {{
    font-size: 11px;
    font-weight: 700;
    color: #66727b;
}}
QLabel#HeroValue {{
    font-size: 29px;
    font-weight: 750;
    color: {p["title"]};
}}
QLabel#MetricValue {{
    font-size: 19px;
    font-weight: 700;
    color: {p["title"]};
}}
QLabel#Muted {{ color: {p["muted"]}; }}
QLabel#Positive {{ color: #198754; font-weight: 700; }}
QLabel#Negative {{ color: #c23a3a; font-weight: 700; }}
QLabel#Warning {{ color: #a36d16; font-weight: 700; }}
QPushButton, QToolButton {{
    background: {p["panel"]};
    border: 1px solid #dcd9d2;
    border-radius: 8px;
    padding: 7px 11px;
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
QPushButton#DockHandle {{
    min-width: 46px;
    max-width: 46px;
    min-height: 22px;
    max-height: 22px;
    border-radius: 11px;
    padding: 0;
    background: {p["panel"]};
    border: 1px solid {p["border"]};
    color: {p["muted"]};
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
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox {{
    background: {p["panel"]};
    border: 1px solid #ddd9d2;
    border-radius: 7px;
    padding: 6px 8px;
}}
QTableWidget, QTextBrowser {{
    background: {p["panel"]};
    alternate-background-color: {p["panel2"]};
    border: 1px solid {p["border"]};
    border-radius: 8px;
    gridline-color: #ebe8e2;
    selection-background-color: {p["accent"]};
    selection-color: {p["title"]};
}}
QHeaderView::section {{
    background: {p["header"]};
    color: #5c6770;
    border: none;
    border-bottom: 1px solid #dfdcd6;
    padding: 6px;
    font-weight: 650;
}}
QTabWidget::pane {{
    border: 1px solid {p["border"]};
    background: {p["panel"]};
    border-radius: 8px;
}}
QTabBar::tab {{
    background: {p["header"]};
    border: 1px solid {p["border"]};
    padding: 7px 11px;
}}
QTabBar::tab:selected {{
    background: {p["panel"]};
    color: {p["accent_text"]};
    font-weight: 700;
}}
QSlider::groove:horizontal {{
    height: 5px;
    background: #dfddd7;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #9bb8c3;
}}
QProgressBar {{
    background: #eceae5;
    border: none;
    border-radius: 5px;
    min-height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{ background: #a7c2ca; border-radius: 5px; }}
QSplitter::handle {{
    background: transparent;
    width: 5px;
    height: 5px;
}}
"""


APP_STYLESHEET = build_stylesheet("Sand")
