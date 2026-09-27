"""Reusable PySide6 widgets for the Intrader desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from datetime import datetime, timedelta

from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPicture, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QGraphicsDropShadowEffect, QGridLayout,
    QHeaderView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton,
    QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from intrader.historical import INDIA_TIME
from intrader.ui.theme import ACCENT_PRESETS, DEFAULT_ACCENT


BULLISH_COLOR = "#2d8a60"
BEARISH_COLOR = "#c64b4b"
TIMEFRAME_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
}


class LogoMark(QWidget):
    """Vector Intrader mark inspired by the approved geometric N/candlestick logo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(52, 52)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2

        painter.setPen(QPen(QColor("#D7D4CD"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), 22, 22)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#D85C5C"))
        painter.drawRect(QRectF(5, cy - 4, 42, 8))

        painter.setPen(QPen(QColor("#111318"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        painter.drawLine(QPointF(15, 12), QPointF(15, 40))
        painter.drawLine(QPointF(15, 13), QPointF(37, 39))
        painter.drawLine(QPointF(37, 12), QPointF(37, 40))

        painter.setPen(QPen(QColor("#BBB7AF"), 1))
        painter.drawLine(QPointF(cx, 4), QPointF(cx, 48))
        painter.drawLine(QPointF(4, cy), QPointF(48, cy))


class BrandLockup(QWidget):
    """Top-left Intrader brand lockup used across all workstation modes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(LogoMark())
        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 4, 0, 3)
        text_layout.setSpacing(0)
        title = QLabel("I N T R A D E R")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Market Intelligence")
        subtitle.setObjectName("BrandSubtitle")
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        layout.addWidget(text)


class DotMatrix(QWidget):
    """Tiny halftone field for the editorial visual language."""

    def __init__(
        self,
        accent: str = DEFAULT_ACCENT,
        *,
        columns: int = 6,
        rows: int = 4,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._accent = accent
        self._columns = columns
        self._rows = rows
        self.setFixedSize(max(20, columns * 7), max(16, rows * 7))

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._accent)
        color.setAlpha(150)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for row in range(self._rows):
            for column in range(self._columns):
                opacity = max(45, 155 - (column + row) * 12)
                dot = QColor(color)
                dot.setAlpha(opacity)
                painter.setBrush(dot)
                painter.drawEllipse(QPointF(4 + column * 7, 4 + row * 7), 1.3, 1.3)


class AccentDotButton(QAbstractButton):
    """Circular matte/pastel accent swatch."""

    def __init__(
        self,
        name: str,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.color = color
        self._selected = False
        self.setToolTip(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(22, 22)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        if self._selected:
            ring = QColor(self.color)
            ring.setAlpha(55)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ring)
            painter.drawEllipse(center, 10, 10)
            painter.setBrush(QColor("#FBFAF7"))
            painter.drawEllipse(center, 7, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.color))
        painter.drawEllipse(center, 4.7, 4.7)


class AccentSelector(QWidget):
    """Single visual customization control: matte/pastel accent color."""

    accent_changed = Signal(str)

    def __init__(self, current: str = DEFAULT_ACCENT) -> None:
        super().__init__()
        self._buttons: list[AccentDotButton] = []
        self._current = current
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel("Accent")
        label.setObjectName("Muted")
        layout.addWidget(label)
        for name, color in ACCENT_PRESETS:
            button = AccentDotButton(name, color)
            button.clicked.connect(
                lambda _checked=False, value=color: self.set_accent(value)
            )
            self._buttons.append(button)
            layout.addWidget(button)
        self.set_accent(current, emit=False)

    def set_accent(self, accent: str, *, emit: bool = True) -> None:
        valid = {color for _name, color in ACCENT_PRESETS}
        if accent not in valid:
            accent = DEFAULT_ACCENT
        self._current = accent
        for button in self._buttons:
            button.set_selected(button.color == accent)
        if emit:
            self.accent_changed.emit(accent)

    def accent(self) -> str:
        return self._current


class Card(QFrame):
    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(30, 34, 38, 18))
        self.setGraphicsEffect(shadow)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(14, 12, 14, 14)
        self.layout_box.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self.layout_box.addWidget(label)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.layout_box.addWidget(widget, stretch)


class TextPanel(Card):
    """Readable wrapped prose panel for analysis notes and explanations."""

    def __init__(self, title: str, text: str = "") -> None:
        super().__init__(title)
        self.text = QTextBrowser()
        self.text.setFrameShape(QFrame.Shape.NoFrame)
        self.text.setOpenExternalLinks(True)
        self.text.setMinimumHeight(90)
        self.layout_box.addWidget(self.text)
        self.set_text(text)

    def set_text(self, text: str | list[str] | tuple[str, ...]) -> None:
        if isinstance(text, (list, tuple)):
            values = [str(item) for item in text if str(item).strip()]
            rendered = "<br><br>".join(values)
        else:
            rendered = str(text or "")
        if not rendered:
            rendered = "<span style='color:#7b858c'>No analysis available for this selection.</span>"
        self.text.setHtml(rendered)


class CollapsibleSection(Card):
    """Compact section that gives space back to the workspace when collapsed."""

    def __init__(self, title: str, content: QWidget, *, expanded: bool = False) -> None:
        super().__init__(None)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.toggle.clicked.connect(self._toggle)
        self.content = content
        self.content.setVisible(expanded)
        self.layout_box.addWidget(self.toggle)
        self.layout_box.addWidget(self.content)

    def _toggle(self, checked: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(checked)


class ResponsiveMetricGrid(QWidget):
    """Reflow KPI cards instead of forcing a very wide minimum size."""

    def __init__(self, cards: list[QWidget], *, compact_height: int = 82) -> None:
        super().__init__()
        self.cards = list(cards)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self._columns = 0
        for card in self.cards:
            card.setMinimumHeight(compact_height)
            card.setMaximumHeight(compact_height + 18)
        self._reflow(6)

    def resizeEvent(self, event) -> None:
        width = max(1, event.size().width())
        columns = 6 if width >= 1120 else 3 if width >= 720 else 2
        self._reflow(columns)
        super().resizeEvent(event)

    def _reflow(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)


class MetricRibbon(QFrame):
    """Compact single-row KPI summary that prioritizes workspace height."""

    def __init__(self, metrics: list[tuple[str, str]]) -> None:
        super().__init__()
        self.setObjectName("MetricRibbon")
        self._labels: dict[str, QLabel] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(0)
        for index, (key, value) in enumerate(metrics):
            block = QWidget()
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(10, 0, 10, 0)
            block_layout.setSpacing(1)
            title = QLabel(key)
            title.setObjectName("RibbonLabel")
            value_label = QLabel(value)
            value_label.setObjectName("RibbonValue")
            block_layout.addWidget(title)
            block_layout.addWidget(value_label)
            layout.addWidget(block, 1)
            self._labels[key] = value_label
            if index < len(metrics) - 1:
                divider = QFrame()
                divider.setObjectName("RibbonDivider")
                divider.setFrameShape(QFrame.Shape.VLine)
                divider.setFixedWidth(1)
                layout.addWidget(divider)

    def set_metric(
        self,
        key: str,
        value: str,
        tone: str = "neutral",
        tooltip: str | None = None,
    ) -> None:
        label = self._labels[key]
        label.setText(str(value))
        label.setObjectName(
            "Positive"
            if tone == "positive"
            else "Negative"
            if tone == "negative"
            else "RibbonValue"
        )
        if tooltip is not None:
            label.setToolTip(tooltip)
        label.style().unpolish(label)
        label.style().polish(label)

    def value(self, key: str) -> str:
        return self._labels[key].text()


class TriangleDockButton(QAbstractButton):
    """Equilateral dock toggle using the exact candlestick direction colors."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dock_open = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Open navigation dock")
        self.setFixedSize(38, 32)

    def sizeHint(self) -> QSize:
        return QSize(38, 32)

    def set_dock_open(self, is_open: bool) -> None:
        if self._dock_open == is_open:
            return
        self._dock_open = is_open
        self.setToolTip(
            "Close navigation dock" if is_open else "Open navigation dock"
        )
        self.update()

    def dock_open(self) -> bool:
        return self._dock_open

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = 18.0
        height = side * (3.0 ** 0.5) / 2.0
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        if self._dock_open:
            points = [
                QPointF(cx - side / 2.0, cy - height / 2.0),
                QPointF(cx + side / 2.0, cy - height / 2.0),
                QPointF(cx, cy + height / 2.0),
            ]
            color = QColor(BEARISH_COLOR)
        else:
            points = [
                QPointF(cx, cy - height / 2.0),
                QPointF(cx - side / 2.0, cy + height / 2.0),
                QPointF(cx + side / 2.0, cy + height / 2.0),
            ]
            color = QColor(BULLISH_COLOR)
        path = QPainterPath(points[0])
        path.lineTo(points[1])
        path.lineTo(points[2])
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)


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
            background, foreground = "#e9f6ef", BULLISH_COLOR
        elif ok is False:
            background, foreground = "#faeaea", BEARISH_COLOR
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
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)

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
            xs = [row[0] for row in data]
            spacings = [
                later - earlier
                for earlier, later in zip(xs, xs[1:])
                if later > earlier
            ]
            width = (min(spacings) * 0.32) if spacings else 18.0
            lows = []
            highs = []
            for x, open_, close, low, high in data:
                positive = close >= open_
                color = QColor(BULLISH_COLOR if positive else BEARISH_COLOR)
                painter.setPen(QPen(color, 1))
                painter.drawLine(QLineF(x, low, x, high))
                top = max(open_, close)
                bottom = min(open_, close)
                height = max(top - bottom, 0.01)
                painter.fillRect(QRectF(x - width, bottom, width * 2, height), color)
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


class DateAxisItem(pg.AxisItem):
    """Human-readable India-local timestamps for market charts."""

    def tickStrings(self, values, scale, spacing):
        labels = []
        for value in values:
            try:
                at = datetime.fromtimestamp(float(value), tz=INDIA_TIME)
            except (OSError, OverflowError, ValueError):
                labels.append("")
                continue
            labels.append(
                at.strftime("%d %b\n%H:%M")
                if spacing >= 3600
                else at.strftime("%H:%M")
            )
        return labels


class MarketChart(Card):
    """Candlestick chart with built-in candle-size selector."""

    timeframe_changed = Signal(str)

    def __init__(
        self,
        title: str = "NIFTY CANDLES",
        *,
        show_timeframes: bool = True,
    ) -> None:
        super().__init__(None)
        self._title = title
        self._raw_candles = ()
        self._timeframe = "Auto"

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 2)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        header.addWidget(title_label)
        self.quote_label = QLabel("—")
        self.quote_label.setObjectName("MetricValue")
        header.addWidget(self.quote_label)
        header.addStretch(1)

        self.timeframe_group = QButtonGroup(self)
        self.timeframe_group.setExclusive(True)
        self.timeframe_buttons: dict[str, QPushButton] = {}
        if show_timeframes:
            for label in ("1m", "3m", "5m", "15m", "30m", "1H", "Auto"):
                button = QPushButton(label)
                button.setObjectName("TimeframeButton")
                button.setCheckable(True)
                button.setProperty("timeframeActive", label == "Auto")
                button.setChecked(label == "Auto")
                button.setFixedHeight(26)
                button.clicked.connect(
                    lambda _checked=False, value=label: self.set_timeframe(value)
                )
                self.timeframe_group.addButton(button)
                self.timeframe_buttons[label] = button
                header.addWidget(button)
        self.interval_hint = QLabel("Auto → 1m")
        self.interval_hint.setObjectName("Muted")
        header.addWidget(self.interval_hint)
        self.layout_box.insertLayout(0, header)

        self.plot = pg.PlotWidget(
            axisItems={"bottom": DateAxisItem(orientation="bottom")}
        )
        self.plot.setBackground("#FEFDFB")
        self.plot.showGrid(x=True, y=True, alpha=0.06)
        self.plot.getAxis("left").setPen("#9aa1a5")
        self.plot.getAxis("bottom").setPen("#9aa1a5")
        self.plot.setMouseEnabled(x=True, y=True)
        self.candles = CandlestickItem()
        self.plot.addItem(self.candles)
        self.layout_box.addWidget(self.plot)
        self.set_empty_message("No market data loaded.")

    def selected_timeframe(self) -> str:
        return self._timeframe

    def set_timeframe(self, label: str) -> None:
        if label not in (*TIMEFRAME_MINUTES.keys(), "Auto"):
            return
        self._timeframe = label
        for name, button in self.timeframe_buttons.items():
            active = name == label
            button.setChecked(active)
            button.setProperty("timeframeActive", active)
            button.style().unpolish(button)
            button.style().polish(button)
        if self._raw_candles:
            self._render_raw_candles()
        self.timeframe_changed.emit(label)

    def set_candle_objects(self, candles) -> None:
        self._raw_candles = tuple(sorted(candles, key=lambda c: c.at))
        if not self._raw_candles:
            self.set_empty_message("No market data loaded.")
            return
        last = self._raw_candles[-1]
        try:
            self.quote_label.setText(f"{float(last.close):,.2f}")
        except Exception:
            self.quote_label.setText(str(last.close))
        self._render_raw_candles()

    def _auto_minutes(self) -> int:
        if len(self._raw_candles) < 2:
            return 1
        span = self._raw_candles[-1].at - self._raw_candles[0].at
        if span <= timedelta(minutes=45):
            return 1
        if span <= timedelta(hours=3):
            return 3
        if span <= timedelta(days=1):
            return 5
        if span <= timedelta(days=5):
            return 15
        if span <= timedelta(days=10):
            return 30
        return 60

    def _render_raw_candles(self) -> None:
        minutes = (
            self._auto_minutes()
            if self._timeframe == "Auto"
            else TIMEFRAME_MINUTES[self._timeframe]
        )
        actual = "1H" if minutes == 60 else f"{minutes}m"
        self.interval_hint.setText(
            f"Auto → {actual}" if self._timeframe == "Auto" else actual
        )
        rows = self._aggregate(self._raw_candles, minutes)
        self.set_candles(rows)

    @staticmethod
    def _aggregate(candles, minutes: int):
        if minutes <= 1:
            return [
                (
                    c.at.timestamp(),
                    float(c.open),
                    float(c.close),
                    float(c.low),
                    float(c.high),
                )
                for c in candles
            ]
        buckets: list[list] = []
        current_key = None
        current: list = []
        for candle in candles:
            local = candle.at.astimezone(INDIA_TIME)
            minute_index = local.hour * 60 + local.minute
            session_anchor = 9 * 60 + 15
            bucket_minute = (
                ((minute_index - session_anchor) // minutes) * minutes
                + session_anchor
            )
            key = (local.date(), bucket_minute)
            if current_key is None or key == current_key:
                current.append(candle)
                current_key = key
            else:
                buckets.append(current)
                current = [candle]
                current_key = key
        if current:
            buckets.append(current)
        rows = []
        for bucket in buckets:
            first = bucket[0]
            last = bucket[-1]
            rows.append(
                (
                    first.at.timestamp(),
                    float(first.open),
                    float(last.close),
                    float(min(c.low for c in bucket)),
                    float(max(c.high for c in bucket)),
                )
            )
        return rows

    def set_candles(
        self,
        rows: list[tuple[float, float, float, float, float]],
    ) -> None:
        self.plot.clear()
        self.plot.showAxis("left")
        self.plot.showAxis("bottom")
        self.plot.showGrid(x=True, y=True, alpha=0.08)
        self.plot.setMouseEnabled(x=True, y=True)
        self.candles.set_data(rows)
        self.plot.addItem(self.candles)
        if rows:
            self.plot.enableAutoRange()

    def set_empty_message(self, message: str) -> None:
        self._raw_candles = ()
        self.interval_hint.setText("No data")
        self.quote_label.setText("—")
        self.plot.clear()
        self.candles.set_data([])
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.showGrid(x=False, y=False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setXRange(0, 1, padding=0)
        self.plot.setYRange(0, 1, padding=0)
        label = pg.TextItem(message, anchor=(0.5, 0.5), color="#7b858c")
        self.plot.addItem(label)
        label.setPos(0.5, 0.5)
