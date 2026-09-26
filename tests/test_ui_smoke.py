import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from intrader.ui.mode_pages import AnalysisModePage, IntraderModePage, TimeTravelPage
from intrader.ui.utility_pages import (
    DashboardPage, ExportPage, RecordsManagerPage, ShadowTraderPage,
    SystemHealthPage, ThesisPage, TradeHistoryPage,
)


def test_primary_and_supporting_pages_construct_offscreen() -> None:
    app = QApplication.instance() or QApplication([])
    pages = [
        DashboardPage(),
        IntraderModePage(),
        TimeTravelPage(),
        AnalysisModePage(),
        ThesisPage(),
        ShadowTraderPage(),
        RecordsManagerPage(),
        TradeHistoryPage(),
        SystemHealthPage(),
        ExportPage(),
    ]

    assert all(page is not None for page in pages)
