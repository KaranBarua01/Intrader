"""Reusable PySide6 widgets for the Intrader desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPicture, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
import pyqtgraph as pg


class Card(QFrame):
    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(14, 12, 14, 14)
        self.layout_box.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self.layout_box.addWidget(label)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.layout_box.addWidget(widget, stretch)


class MetricCard(Card):
    def __init__(self, title: str, value: str = "N/A", subtitle: str = "") -> None:
        super().__init__(title)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("Muted")
        self.layout_box.addWidget(self.value_label)
        self.layout_box.addWidget(self.subtitle_label)

    def set_value(self, value: str, tone: str = "neutral", subtitle: str | None = None) -> None:
        self.value_label.setText(value)
        self.value_label.setObjectName(
            "Positive" if tone == "positive" else "Negative" if tone == "negative" else "MetricValue"
        )
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)


class DecisionCard(Card):
    def __init__(self) -> None:
        super().__init__("CURRENT DECISION")
        self.state = QLabel("WAITING FOR DATA")
        self.state.setObjectName("HeroValue")
        self.reason = QLabel("No verified live decision is available yet.")
        self.reason.setWordWrap(True)
        self.reason.setObjectName("Muted")
        self.layout_box.addWidget(self.state)
        self.layout_box.addWidget(self.reason)

    def set_decision(self, state: str, reason: str = "") -> None:
        self.state.setText(state)
        self.reason.setText(reason or "Decision produced by the Market Brain.")
        if "CALL" in state:
            self.state.setObjectName("Positive")
        elif "PUT" in state or "NO TRADE" in state:
            self.state.setObjectName("Negative")
        else:
            self.state.setObjectName("HeroValue")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)


class StatusPill(QLabel):
    def __init__(self, label: str, ok: bool | None = None) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(88)
        self.set_status(label, ok)

    def set_status(self, label: str, ok: bool | None) -> None:
        self.setText(label)
        if ok is True:
            background, foreground = "#e9f6ef", "#28704d"
        elif ok is False:
            background, foreground = "#faeaea", "#a83535"
        else:
            background, foreground = "#efeee9", "#6f777c"
        self.setStyleSheet(
            f"background:{background};color:{foreground};border-radius:10px;padding:4px 8px;font-weight:650;"
        )


class ReasonList(Card):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.layout_box.addWidget(self.list)

    def set_reasons(self, reasons: list[tuple[str, str]]) -> None:
        self.list.clear()
        if not reasons:
            self.list.addItem("No recorded reasoning.")
            return
        for code, explanation in reasons:
            item = QListWidgetItem(f"{code}\n{explanation}")
            item.setToolTip(explanation)
            self.list.addItem(item)


class DataTable(QTableWidget):
    def __init__(self, headers: list[str]) -> None:
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

    def set_rows(self, rows: list[list[object]]) -> None:
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QTableWidgetItem("" if value is None else str(value))
                self.setItem(row_index, column_index, item)
        self.resizeColumnsToContents()


class CandlestickItem(pg.GraphicsObject):
    """Small candlestick renderer using pyqtgraph coordinates."""

    def __init__(self) -> None:
        super().__init__()
        self._picture = QPicture()
        self._bounds = QRectF()

    def set_data(self, data: list[tuple[float, float, float, float, float]]) -> None:
        picture = QPicture()
        painter = QPainter(picture)
        if data:
            width = 0.32
            lows = []
            highs = []
            xs = []
            for x, open_, close, low, high in data:
                positive = close >= open_
                color = QColor("#2d8a60" if positive else "#c64b4b")
                painter.setPen(QPen(color, 1))
                painter.drawLine(int(x), int(low), int(x), int(high))
                top = max(open_, close)
                bottom = min(open_, close)
                height = max(top - bottom, 0.01)
                painter.fillRect(QRectF(x - width, bottom, width * 2, height), color)
                xs.append(x)
                lows.append(low)
                highs.append(high)
            self._bounds = QRectF(
                min(xs) - 1, min(lows), (max(xs) - min(xs)) + 2, max(highs) - min(lows)
            )
        else:
            self._bounds = QRectF()
        painter.end()
        self.prepareGeometryChange()
        self._picture = picture
        self.update()

    def paint(self, painter: QPainter, *_args) -> None:
        painter.drawPicture(0, 0, self._picture)

    def boundingRect(self) -> QRectF:
        return self._bounds


class MarketChart(Card):
    def __init__(self, title: str = "NIFTY CANDLES") -> None:
        super().__init__(title)
        self.plot = pg.PlotWidget()
        self.plot.setBackground("#fffefa")
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.getAxis("left").setPen("#9aa1a5")
        self.plot.getAxis("bottom").setPen("#9aa1a5")
        self.plot.setMouseEnabled(x=True, y=True)
        self.candles = CandlestickItem()
        self.plot.addItem(self.candles)
        self.layout_box.addWidget(self.plot)

    def set_candles(self, rows: list[tuple[float, float, float, float, float]]) -> None:
        self.candles.set_data(rows)
        if rows:
            self.plot.enableAutoRange()

    def set_empty_message(self, message: str) -> None:
        self.plot.clear()
        self.plot.addItem(self.candles)
        label = pg.TextItem(message, anchor=(0.5, 0.5), color="#7b858c")
        self.plot.addItem(label)
        label.setPos(0, 0)

