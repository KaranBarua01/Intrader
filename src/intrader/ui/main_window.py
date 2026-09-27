"""Main window and orchestration for the Intrader Phase 4 desktop app."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QSettings, QThread, QTime, Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from intrader.ui.components import AccentSelector, BrandLockup, DotMatrix, TriangleDockButton
from intrader.ui.data_service import DesktopDataService
from intrader.ui.exporter import export_reason_audits, export_reasoning, export_shadow_results
from intrader.ui.mode_pages import AnalysisModePage, IntraderModePage, TimeTravelPage
from intrader.ui.strategy_lab_page import StrategyLabPage
from intrader.ui.theme import ACCENT_PRESETS, DEFAULT_ACCENT, build_stylesheet
from intrader.ui.updater import UpdateApplyResult, UpdateError, UpdateService, UpdateStatus
from intrader.ui.utility_pages import (
    CalibrationPage, DashboardPage, ExportPage, RecordsManagerPage,
    ResearchBrowserPage, ShadowTraderPage, SystemHealthPage, ThesisPage,
    TradeHistoryPage,
)
from intrader import __version__
from intrader.historical import INDIA_TIME
from intrader.storage import SQLiteStore


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            self.succeeded.emit(self._task())
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("Intrader", "Desktop")
        self.setWindowTitle("Intrader")
        self.resize(1540, 940)
        self.setMinimumSize(900, 620)
        self.current_accent = str(
            self.settings.value("accent", DEFAULT_ACCENT)
        )
        valid_accents = {color for _name, color in ACCENT_PRESETS}
        if self.current_accent not in valid_accents:
            self.current_accent = DEFAULT_ACCENT
        self.setStyleSheet(build_stylesheet(self.current_accent))
        self.service = DesktopDataService()
        self.updater = UpdateService()
        self._workers: set[TaskThread] = set()
        self._nav_buttons: dict[str, QPushButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._page_widgets: dict[str, QWidget] = {}
        self._dock_visible = False
        self._build_ui()
        self.apply_accent(self.current_accent)
        saved_geometry = self.settings.value("geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        self.refresh_all()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(72)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 8, 16, 8)
        top_layout.setSpacing(10)

        self.brand = BrandLockup()
        top_layout.addWidget(self.brand)
        top_layout.addStretch(1)

        self.accent_selector = AccentSelector(self.current_accent)
        self.accent_selector.accent_changed.connect(self.apply_accent)
        top_layout.addWidget(self.accent_selector)

        self.refresh_button = QPushButton("↻  Refresh Data")
        self.refresh_button.setObjectName("SecondaryButton")
        self.refresh_button.clicked.connect(self.refresh_all)
        top_layout.addWidget(self.refresh_button)

        self.update_button = QPushButton("↓  Update")
        self.update_button.setObjectName("PrimaryButton")
        self.update_button.clicked.connect(self.check_updates)
        top_layout.addWidget(self.update_button)
        root.addWidget(top)

        self.stack = QStackedWidget()
        self.dashboard_page = DashboardPage()
        self.intrader_page = IntraderModePage()
        self.time_page = TimeTravelPage()
        self.analysis_page = AnalysisModePage()
        self.strategy_page = StrategyLabPage()
        self.thesis_page = ThesisPage()
        self.shadow_page = ShadowTraderPage()
        self.records_page = RecordsManagerPage()
        self.history_page = TradeHistoryPage()
        self.browser_page = ResearchBrowserPage()
        self.calibration_page = CalibrationPage()
        self.health_page = SystemHealthPage()
        self.export_page = ExportPage()

        pages = [
            ("Dashboard", self.dashboard_page),
            ("Intrader Mode", self.intrader_page),
            ("Time Travel", self.time_page),
            ("Analysis Mode", self.analysis_page),
            ("Strategy Lab", self.strategy_page),
            ("Thesis", self.thesis_page),
            ("Shadow Trader", self.shadow_page),
            ("Records Manager", self.records_page),
            ("Trade History", self.history_page),
            ("Research Browser", self.browser_page),
            ("Calibration", self.calibration_page),
            ("System Health", self.health_page),
            ("Export", self.export_page),
        ]
        for name, page in pages:
            wrapper = QScrollArea()
            wrapper.setWidgetResizable(True)
            wrapper.setFrameShape(QFrame.Shape.NoFrame)
            wrapper.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            wrapper.setWidget(page)
            self._pages[name] = wrapper
            self._page_widgets[name] = page
            self.stack.addWidget(wrapper)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # Floating bottom dock: hidden by default so work gets the canvas.
        self.bottom_dock = QFrame(central)
        self.bottom_dock.setObjectName("BottomDock")
        dock_shadow = QGraphicsDropShadowEffect(self.bottom_dock)
        dock_shadow.setBlurRadius(26)
        dock_shadow.setOffset(0, 5)
        dock_shadow.setColor(QColor(30, 55, 70, 45))
        self.bottom_dock.setGraphicsEffect(dock_shadow)
        dock_layout = QHBoxLayout(self.bottom_dock)
        dock_layout.setContentsMargins(10, 8, 10, 8)
        dock_layout.setSpacing(4)

        brand = QLabel("INTRADER")
        brand.setStyleSheet(
            "color:white;font-weight:750;letter-spacing:2px;padding:0 8px;"
        )
        dock_layout.addWidget(brand)
        divider = QLabel("│")
        divider.setStyleSheet("color:#565656;")
        dock_layout.addWidget(divider)

        primary = [
            ("Intrader", "Intrader Mode"),
            ("Time Travel", "Time Travel"),
            ("Analysis", "Analysis Mode"),
            ("Strategy Lab", "Strategy Lab"),
        ]
        for label, page_name in primary:
            button = QPushButton(label)
            button.setObjectName("DockNavButton")
            button.setProperty("active", False)
            button.clicked.connect(
                lambda _checked=False, name=page_name: self.show_page(name)
            )
            dock_layout.addWidget(button)
            self._nav_buttons[page_name] = button

        self.more_button = QPushButton("More")
        self.more_button.setObjectName("DockNavButton")
        self.more_menu = QMenu(self.more_button)
        for label, page_name in (
            ("Dashboard", "Dashboard"),
            ("Thesis", "Thesis"),
            ("Shadow Trader", "Shadow Trader"),
            ("Records Manager", "Records Manager"),
            ("Trade History", "Trade History"),
            ("Research Browser", "Research Browser"),
            ("Calibration", "Calibration"),
            ("System Health", "System Health"),
            ("Export", "Export"),
        ):
            action = self.more_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, name=page_name: self.show_page(name)
            )
        self.more_button.setMenu(self.more_menu)
        dock_layout.addWidget(self.more_button)
        dock_layout.addSpacing(8)

        dock_layout.addStretch(1)
        version = QLabel(f"Intrader {__version__}")
        version.setStyleSheet("color:#A9A9A9;padding:0 8px;")
        dock_layout.addWidget(version)
        self.bottom_dock.hide()

        self.dock_handle = TriangleDockButton(central)
        self.dock_handle.clicked.connect(self.toggle_bottom_dock)

        self.time_page.load_button.clicked.connect(self.load_time_travel)
        self.time_page.range_load_button.clicked.connect(self.load_time_range)
        self.time_page.session_requested.connect(self.load_session_to_now)
        self.time_page.reanalyze_button.clicked.connect(self.reanalyze_time_travel)
        if hasattr(self.time_page, "replay_enrich_button"):
            self.time_page.replay_enrich_button.clicked.connect(
                lambda: self.enrich_time_travel(False)
            )
        if hasattr(self.time_page, "range_enrich_button"):
            self.time_page.range_enrich_button.clicked.connect(
                lambda: self.enrich_time_travel(True)
            )
        self.strategy_page.analyze_requested.connect(self.load_strategy_lab)
        self.strategy_page.replay_requested.connect(self.open_strategy_replay)
        if hasattr(self.strategy_page, "enrich_requested"):
            self.strategy_page.enrich_requested.connect(self.enrich_strategy_lab)
        self.calibration_page.refresh_requested.connect(self.refresh_calibration)
        self.export_page.shadow_export_requested.connect(self.export_shadow)
        self.export_page.reasoning_export_requested.connect(self.export_reasoning_log)
        self.export_page.audit_export_requested.connect(self.export_audits)

        self.show_page("Intrader Mode")
        self._position_bottom_navigation()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_bottom_navigation()

    def _position_bottom_navigation(self) -> None:
        central = self.centralWidget()
        if central is None or not hasattr(self, "dock_handle"):
            return
        width = central.width()
        height = central.height()
        dock_width = max(520, width - 24)
        dock_height = 54
        dock_x = max(8, (width - dock_width) // 2)
        dock_y = max(72, height - dock_height - 8)
        self.bottom_dock.setGeometry(dock_x, dock_y, dock_width, dock_height)
        handle_width = self.dock_handle.width()
        handle_height = self.dock_handle.height()
        handle_y = (
            dock_y - handle_height + 8
            if self._dock_visible
            else max(48, height - handle_height - 3)
        )
        self.dock_handle.setGeometry(
            max(8, (width - handle_width) // 2),
            handle_y,
            handle_width,
            handle_height,
        )
        self.bottom_dock.raise_()
        self.dock_handle.raise_()

    def toggle_bottom_dock(self) -> None:
        self._dock_visible = not self._dock_visible
        self.bottom_dock.setVisible(self._dock_visible)
        self.dock_handle.set_dock_open(self._dock_visible)
        self._position_bottom_navigation()

    def apply_accent(self, accent: str) -> None:
        valid = {color for _name, color in ACCENT_PRESETS}
        if accent not in valid:
            accent = DEFAULT_ACCENT
        self.current_accent = accent
        if hasattr(self, "accent_selector") and self.accent_selector.accent() != accent:
            self.accent_selector.set_accent(accent, emit=False)
        self.setStyleSheet(build_stylesheet(accent))
        self.settings.setValue("accent", accent)
        for dots in self.findChildren(DotMatrix):
            dots.set_accent(accent)

    def apply_layout_preset(self, preset: str = "Compact") -> None:
        current = self.stack.currentWidget()
        page = None
        for name, wrapper in self._pages.items():
            if wrapper is current:
                page = self._page_widgets.get(name)
                break
        if page is not None and hasattr(page, "apply_layout_preset"):
            page.apply_layout_preset("Compact")

    def _run_task(self, task: Callable[[], object], success: Callable[[object], None], failure: Callable[[str], None] | None = None) -> None:
        worker = TaskThread(task)
        self._workers.add(worker)
        worker.succeeded.connect(success)
        worker.failed.connect(failure or self._show_error)
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        worker.start()

    def show_page(self, name: str) -> None:
        wrapper = self._pages[name]
        self.stack.setCurrentWidget(wrapper)
        for page_name, button in self._nav_buttons.items():
            button.setProperty("active", page_name == name)
            button.style().unpolish(button)
            button.style().polish(button)
        primary_names = set(self._nav_buttons)
        self.more_button.setText("More" if name in primary_names else f"More • {name}")
        page = self._page_widgets[name]
        if hasattr(page, "apply_layout_preset"):
            page.apply_layout_preset("Compact")
        if self._dock_visible:
            self.toggle_bottom_dock()

    def refresh_all(self) -> None:
        self.refresh_button.setEnabled(False)
        def task():
            now = datetime.now(INDIA_TIME)
            news_error = None
            try:
                self.service.refresh_global_news(end=now)
            except Exception as exc:
                news_error = str(exc) or exc.__class__.__name__
            desktop = self.service.snapshot(now)
            manager = self.service.records_manager()
            candles = ()
            candle_error = None
            try:
                candles = self.service.load_nifty_candles(now.date())
            except Exception as exc:
                candle_error = str(exc) or exc.__class__.__name__
            return desktop, manager, candles, candle_error, news_error
        def done(payload) -> None:
            desktop, manager, candles, candle_error, news_error = payload
            self.refresh_button.setEnabled(True)
            self.dashboard_page.refresh(desktop, manager)
            self.intrader_page.refresh_snapshot(desktop)
            self.intrader_page.set_candles(candles)
            self.analysis_page.refresh_manager(manager, desktop.completed_bundles)
            self.thesis_page.refresh(desktop)
            self.shadow_page.refresh(desktop)
            self.records_page.refresh(manager)
            self.history_page.refresh(desktop)
            self.health_page.refresh(desktop)
            issues = []
            if candle_error:
                issues.append(f"Candles: {candle_error}")
            if news_error:
                issues.append(f"Global news: {news_error}")
            if issues:
                self.statusBar().showMessage("Local data refreshed. " + " | ".join(issues), 9000)
            else:
                self.statusBar().showMessage("Intrader data and global context refreshed.", 4000)
        def failed(message: str) -> None:
            self.refresh_button.setEnabled(True)
            self._show_error(message)
        self._run_task(task, done, failed)

    def load_time_travel(self) -> None:
        self.time_page.load_button.setEnabled(False)
        day = self.time_page.selected_day()
        end = self.time_page.selected_end_datetime()
        start = end - timedelta(minutes=30)
        def task():
            return (
                self.service.decisions_for_day(day),
                self.service.completed_for_day(day),
                self.service.load_nifty_candle_range(
                    start, end, backfill_missing=False
                ),
                self.service.news_for_window(start, end),
            )
        def done(payload) -> None:
            self.time_page.load_button.setEnabled(True)
            self.time_page.set_session_data(*payload)
            self.statusBar().showMessage("Time Travel window loaded.", 4000)
        def failed(message: str) -> None:
            self.time_page.load_button.setEnabled(True)
            self._show_error(message)
        self._run_task(task, done, failed)

    def load_time_range(self) -> None:
        start, end = self.time_page.selected_range()
        if start >= end:
            QMessageBox.information(
                self,
                "Time Travel",
                "The range start must be earlier than the range end.",
            )
            return
        if end - start > timedelta(days=30, minutes=1):
            QMessageBox.information(
                self,
                "Time Travel",
                "Range Analysis is limited to 30 days.",
            )
            return

        self.time_page.range_load_button.setEnabled(False)
        self.time_page.range_load_button.setText("Analyzing…")

        def task():
            return self.service.analyze_time_range(
                start,
                end,
                enrich_missing=True,
            )

        def done(payload) -> None:
            self.time_page.range_load_button.setEnabled(True)
            self.time_page.range_load_button.setText("▶  Analyze Period")
            analysis, opening, candles, news, events = payload
            self.time_page.set_range_analysis(
                analysis,
                opening,
                candles,
                news,
                events,
            )
            self.statusBar().showMessage(
                "Historical range analysis complete across candles, cached market context, "
                "recorded decisions and every available stored data family.",
                6500,
            )

        def failed(message: str) -> None:
            self.time_page.range_load_button.setEnabled(True)
            self.time_page.range_load_button.setText("▶  Analyze Period")
            self._show_error(message)

        self._run_task(task, done, failed)

    def load_session_to_now(self) -> None:
        self.time_page.session_view_button.setEnabled(False)
        self.time_page.session_view_button.setText("Analyzing Session…")

        def task():
            return self.service.analyze_session_to_now()

        def done(payload) -> None:
            (
                analysis,
                opening,
                candles,
                news,
                events,
                latest_decision,
                session_start,
                session_end,
            ) = payload
            self.time_page.session_view_button.setEnabled(True)
            self.time_page.session_view_button.setText("Session to Now")
            self.time_page.tabs.setCurrentIndex(1)
            self.time_page.set_range_inputs(session_start, session_end)
            self.time_page.set_range_analysis(
                analysis,
                opening,
                candles,
                news,
                events,
                session_decision=latest_decision,
                session_mode=True,
            )
            self.statusBar().showMessage(
                "Session-to-Now analysis complete. Guidance uses the latest verified "
                "Market Brain decision; missing families are never guessed.",
                6500,
            )

        def failed(message: str) -> None:
            self.time_page.session_view_button.setEnabled(True)
            self.time_page.session_view_button.setText("Session to Now")
            self._show_error(message)

        self._run_task(task, done, failed)

    def enrich_time_travel(self, range_mode: bool) -> None:
        if range_mode:
            start, end = self.time_page.selected_range()
            button = self.time_page.range_enrich_button
        else:
            end = self.time_page.selected_end_datetime()
            start = end - timedelta(minutes=30)
            button = self.time_page.replay_enrich_button
        button.setEnabled(False)
        button.setText("Fetching…")

        def done(payload) -> None:
            button.setEnabled(True)
            button.setText("Fetch Missing")
            candles, news = payload
            self.statusBar().showMessage(
                f"Historical enrichment complete: +{candles} candles, +{news} relevant news items.",
                6000,
            )
            if range_mode:
                self.load_time_range()
            else:
                self.load_time_travel()

        def failed(message: str) -> None:
            button.setEnabled(True)
            button.setText("Fetch Missing")
            self._show_error(message)

        self._run_task(
            lambda: self.service.enrich_time_range(start, end),
            done,
            failed,
        )

    def reanalyze_time_travel(self) -> None:
        at = self.time_page.selected_replay_datetime()
        self.time_page.reanalyze_button.setEnabled(False)
        self.time_page.reanalyze_button.setText("Re-analyzing…")

        def task():
            return self.service.reanalyze_timestamp(at)

        def done(record) -> None:
            self.time_page.reanalyze_button.setEnabled(True)
            self.time_page.reanalyze_button.setText(
                "Re-analyze with Current Brain"
            )
            self.time_page.set_reanalysis(record)
            self.statusBar().showMessage(
                "Current-Brain historical re-analysis complete. "
                "No historical record was modified.",
                6000,
            )

        def failed(message: str) -> None:
            self.time_page.reanalyze_button.setEnabled(True)
            self.time_page.reanalyze_button.setText(
                "Re-analyze with Current Brain"
            )
            QMessageBox.information(
                self,
                "Historical Re-analysis",
                "Full re-analysis needs stored price, options, futures/VIX "
                "and order-flow data for the selected timestamp.\n\n"
                + message,
            )

        self._run_task(task, done, failed)

    def load_strategy_lab(self) -> None:
        start, end = self.strategy_page.selected_range()
        if start >= end:
            QMessageBox.information(
                self,
                "Strategy Lab",
                "The strategy-analysis start must be earlier than the end.",
            )
            return
        if end - start > timedelta(days=30, minutes=1):
            QMessageBox.information(
                self,
                "Strategy Lab",
                "Strategy Lab is limited to 30 days per run.",
            )
            return

        self.strategy_page.analyze_button.setEnabled(False)
        self.strategy_page.analyze_button.setText("Analyzing…")

        def task():
            return self.service.analyze_strategy_range(start, end)

        def done(snapshot) -> None:
            self.strategy_page.analyze_button.setEnabled(True)
            self.strategy_page.analyze_button.setText("▶  Analyze Strategies")
            self.strategy_page.set_snapshot(snapshot)
            self.statusBar().showMessage(
                "Strategy Lab analysis complete. No Intrader rules were changed.",
                6000,
            )

        def failed(message: str) -> None:
            self.strategy_page.analyze_button.setEnabled(True)
            self.strategy_page.analyze_button.setText("▶  Analyze Strategies")
            self._show_error(message)

        self._run_task(task, done, failed)

    def enrich_strategy_lab(self) -> None:
        start, end = self.strategy_page.selected_range()
        button = self.strategy_page.fetch_button
        button.setEnabled(False)
        button.setText("Fetching…")

        def done(payload) -> None:
            button.setEnabled(True)
            button.setText("Fetch Missing")
            candles, news = payload
            self.statusBar().showMessage(
                f"Strategy Lab enrichment complete: +{candles} candles, +{news} relevant news items.",
                6000,
            )
            self.load_strategy_lab()

        def failed(message: str) -> None:
            button.setEnabled(True)
            button.setText("Fetch Missing")
            self._show_error(message)

        self._run_task(
            lambda: self.service.enrich_time_range(start, end),
            done,
            failed,
        )

    def open_strategy_replay(self, at) -> None:
        replay_end = at.astimezone(INDIA_TIME) + timedelta(minutes=15)
        self.time_page.day.setDate(
            QDate(replay_end.year, replay_end.month, replay_end.day)
        )
        self.time_page.end_time.setTime(
            QTime(replay_end.hour, replay_end.minute)
        )
        self.time_page.tabs.setCurrentIndex(0)
        self.show_page("Time Travel")
        self.load_time_travel()

    def refresh_calibration(self) -> None:
        self.calibration_page.refresh_button.setEnabled(False)
        def task():
            report = self.service.calibration_report()
            calibration, promotion = self.service.promotion_report()
            return report, promotion
        def done(payload) -> None:
            self.calibration_page.refresh_button.setEnabled(True)
            self.calibration_page.set_report(*payload)
        def failed(message: str) -> None:
            self.calibration_page.refresh_button.setEnabled(True)
            QMessageBox.information(self, "Calibration", "Calibration is not ready yet. More completed shadow history is required.\n\n" + message)
        self._run_task(task, done, failed)

    def check_updates(self) -> None:
        self.update_button.setEnabled(False)
        self.update_button.setText("Checking…")
        def done(status: UpdateStatus) -> None:
            self.update_button.setEnabled(True)
            self.update_button.setText("↓  Update")
            if not status.available:
                QMessageBox.information(self, "Intrader Update", status.summary)
                return
            details = status.summary
            if status.commits:
                details += "\n\n" + "\n".join(status.commits)
            prompt = (
                details
                + "\n\nApply this update now? "
                + ("The app will close and relaunch automatically." if status.mode == "release" else "The app must be restarted afterward.")
            )
            response = QMessageBox.question(self, "Intrader Update", prompt)
            if response == QMessageBox.StandardButton.Yes:
                self._apply_update()
        def failed(message: str) -> None:
            self.update_button.setEnabled(True)
            self.update_button.setText("↓  Update")
            self._show_error(message)
        self._run_task(self.updater.check, done, failed)

    def _apply_update(self) -> None:
        self.update_button.setEnabled(False)
        self.update_button.setText("Updating…")
        def done(result: UpdateApplyResult) -> None:
            self.update_button.setEnabled(True)
            self.update_button.setText("↓  Update")
            if result.exit_to_install:
                QMessageBox.information(self, "Intrader Update", result.message)
                app = QApplication.instance()
                if app is not None:
                    app.quit()
                return
            QMessageBox.information(
                self,
                "Intrader Updated",
                result.message + ("\n\nRestart Intrader to load the updated code." if result.restart_required else ""),
            )
        def failed(message: str) -> None:
            self.update_button.setEnabled(True)
            self.update_button.setText("↓  Update")
            self._show_error(message)
        self._run_task(self.updater.apply, done, failed)

    def export_shadow(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Shadow Results", "intrader_shadow_results.csv", "CSV Files (*.csv)")
        if path:
            self._export(lambda store: export_shadow_results(store, Path(path)))

    def export_reasoning_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Reasoning", "intrader_reasoning.json", "JSON Files (*.json)")
        if path:
            self._export(lambda store: export_reasoning(store, Path(path)))

    def export_audits(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Reason Audits", "intrader_reason_audits.csv", "CSV Files (*.csv)")
        if path:
            self._export(lambda store: export_reason_audits(store, Path(path)))

    def _export(self, exporter: Callable[[SQLiteStore], Path]) -> None:
        def task():
            with SQLiteStore(self.service.database_path) as store:
                return exporter(store)
        def done(path: object) -> None:
            QMessageBox.information(self, "Export Complete", f"Saved to:\n{path}")
        self._run_task(task, done)

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("accent", self.current_accent)
        super().closeEvent(event)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Intrader", message or "Operation unavailable.")
