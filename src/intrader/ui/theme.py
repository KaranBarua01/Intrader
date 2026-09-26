"""Minimal light theme for the Intrader desktop application."""

APP_STYLESHEET = r"""
QWidget {
    background: #f6f4ef;
    color: #243039;
    font-family: "Segoe UI";
    font-size: 12px;
}
QMainWindow, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #f6f4ef;
}
QFrame#Sidebar {
    background: #fbfaf7;
    border-right: 1px solid #e4e1da;
}
QFrame#TopBar {
    background: #fbfaf7;
    border-bottom: 1px solid #e4e1da;
}
QFrame#Card {
    background: #fffefa;
    border: 1px solid #e8e5de;
    border-radius: 12px;
}
QLabel#AppTitle {
    font-size: 22px;
    font-weight: 700;
    color: #1f2a32;
}
QLabel#PageTitle {
    font-size: 20px;
    font-weight: 700;
    color: #1f2a32;
}
QLabel#CardTitle {
    font-size: 12px;
    font-weight: 700;
    color: #66727b;
}
QLabel#HeroValue {
    font-size: 31px;
    font-weight: 750;
    color: #1f2a32;
}
QLabel#MetricValue {
    font-size: 20px;
    font-weight: 700;
    color: #1f2a32;
}
QLabel#Muted { color: #7b858c; }
QLabel#Positive { color: #198754; font-weight: 700; }
QLabel#Negative { color: #c23a3a; font-weight: 700; }
QLabel#Warning { color: #a36d16; font-weight: 700; }
QPushButton {
    background: #fffefa;
    border: 1px solid #dcd9d2;
    border-radius: 8px;
    padding: 8px 12px;
    color: #2f3941;
}
QPushButton:hover { background: #f1f5f6; border-color: #c9d7dc; }
QPushButton:pressed { background: #e8eff2; }
QPushButton#PrimaryButton {
    background: #edf4f6;
    border: 1px solid #c9dbe2;
    color: #29444f;
    font-weight: 650;
}
QPushButton#NavButton {
    border: none;
    text-align: left;
    padding: 9px 12px;
    background: transparent;
    border-radius: 7px;
}
QPushButton#NavButton:hover { background: #f0efeb; }
QPushButton#NavButton[active="true"] {
    background: #eaf1f3;
    color: #24404b;
    font-weight: 700;
}
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox {
    background: #fffefa;
    border: 1px solid #ddd9d2;
    border-radius: 7px;
    padding: 7px 9px;
}
QTableWidget {
    background: #fffefa;
    alternate-background-color: #faf9f5;
    border: 1px solid #e7e3dc;
    border-radius: 8px;
    gridline-color: #ebe8e2;
    selection-background-color: #eaf1f3;
    selection-color: #1f2a32;
}
QHeaderView::section {
    background: #f2f1ed;
    color: #5c6770;
    border: none;
    border-bottom: 1px solid #dfdcd6;
    padding: 7px;
    font-weight: 650;
}
QTabWidget::pane {
    border: 1px solid #e5e2dc;
    background: #fffefa;
    border-radius: 8px;
}
QTabBar::tab {
    background: #f2f1ed;
    border: 1px solid #e1ded7;
    padding: 7px 12px;
}
QTabBar::tab:selected {
    background: #fffefa;
    color: #29444f;
    font-weight: 700;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #dfddd7;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #9bb8c3;
}
QProgressBar {
    background: #eceae5;
    border: none;
    border-radius: 5px;
    min-height: 10px;
    text-align: center;
}
QProgressBar::chunk { background: #a7c2ca; border-radius: 5px; }
"""
