"""Main window and orchestration for the Intrader Phase 4 desktop app."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from intrader.ui.data_service import DesktopDataService
from intrader.ui.exporter import export_reason_audits, export_reasoning, export_shadow_results
from intrader.ui.mode_pages import AnalysisModePage, IntraderModePage, TimeTravelPage
from intrader.ui.theme import APP_STYLESHEET
from intrader.ui.updater import UpdateApplyResult, UpdateError, UpdateService, UpdateStatus
from intrader.ui.utility_pages import (
    CalibrationPage, DashboardPage, ExportPage, RecordsManagerPage,
    ResearchBrowserPage, ShadowTraderPage, SystemHealthPage, ThesisPage,
    TradeHistoryPage,
)
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
        self.setWindowTitle("Intrader")
        self.resize(1540, 940)
        self.setMinimumSize(1180, 760)
        self.setStyleSheet(APP_STYLESHEET)
        self.service = DesktopDataService()
        self.updater = UpdateService()
        self._workers: set[TaskThread] = set()
        self._nav_buttons: dict[str, QPushButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(205)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 14, 12, 14)
        logo = QLabel("INTRADER")
        logo.setObjectName("AppTitle")
        side.addWidget(logo)
        subtitle = QLabel("Market Intelligence")
        subtitle.setObjectName("Muted")
        side.addWidget(subtitle)
        side.addSpacing(14)

        nav = [
            ("Dashboard", "Dashboard"),
            ("Intrader Mode", "Intrader Mode"),
            ("Time Travel", "Time Travel"),
            ("Analysis Mode", "Analysis Mode"),
            ("Thesis", "Thesis"),
            ("Shadow Trader", "Shadow Trader"),
            ("Records Manager", "Records Manager"),
            ("Trade History", "Trade History"),
            ("Research Browser", "Research Browser"),
            ("Calibration", "Calibration"),
            ("System Health", "System Health"),
            ("Export", "Export"),
        ]
        for label, page_name in nav:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setProperty("active", False)
            button.clicked.connect(lambda _checked=False, name=page_name: self.show_page(name))
            side.addWidget(button)
            self._nav_buttons[page_name] = button
        side.addStretch(1)
        version = QLabel("Phase 4 Desktop")
        version.setObjectName("Muted")
        side.addWidget(version)
        root.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        top = QFrame()
        top.setObjectName("TopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(14, 9, 14, 9)
        self.mode_label = QLabel("INTRADER MODE")
        self.mode_label.setObjectName("CardTitle")
        top_layout.addWidget(self.mode_label)
        top_layout.addSpacing(14)
        self.mode_buttons = {}
        for text, page in (("Intrader", "Intrader Mode"), ("Time Travel", "Time Travel"), ("Analysis", "Analysis Mode")):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, name=page: self.show_page(name))
            self.mode_buttons[page] = button
            top_layout.addWidget(button)
        top_layout.addStretch(1)
        self.refresh_button = QPushButton("Refresh Data")
        self.refresh_button.setObjectName("PrimaryButton")
        self.refresh_button.clicked.connect(self.refresh_all)
        top_layout.addWidget(self.refresh_button)
        self.update_button = QPushButton("Update")
        self.update_button.setObjectName("PrimaryButton")
        self.update_button.clicked.connect(self.check_updates)
        top_layout.addWidget(self.update_button)
        content_layout.addWidget(top)

        self.stack = QStackedWidget()
        self.dashboard_page = DashboardPage()
        self.intrader_page = IntraderModePage()
        self.time_page = TimeTravelPage()
        self.analysis_page = AnalysisModePage()
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
            self._pages[name] = page
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content, 1)
        self.setCentralWidget(central)

        self.time_page.load_button.clicked.connect(self.load_time_travel)
        self.time_page.range_load_button.clicked.connect(self.load_time_range)
        self.time_page.reanalyze_button.clicked.connect(self.reanalyze_time_travel)
        self.calibration_page.refresh_requested.connect(self.refresh_calibration)
        self.export_page.shadow_export_requested.connect(self.export_shadow)
        self.export_page.reasoning_export_requested.connect(self.export_reasoning_log)
        self.export_page.audit_export_requested.connect(self.export_audits)
        self.show_page("Intrader Mode")

    def _run_task(self, task: Callable[[], object], success: Callable[[object], None], failure: Callable[[str], None] | None = None) -> None:
        worker = TaskThread(task)
        self._workers.add(worker)
        worker.succeeded.connect(success)
        worker.failed.connect(failure or self._show_error)
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        worker.start()

    def show_page(self, name: str) -> None:
        page = self._pages[name]
        self.stack.setCurrentWidget(page)
        for page_name, button in self._nav_buttons.items():
            button.setProperty("active", page_name == name)
            button.style().unpolish(button)
            button.style().polish(button)
        if name in ("Intrader Mode", "Time Travel", "Analysis Mode"):
            self.mode_label.setText(name.upper())
        else:
            self.mode_label.setText(name.upper())

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
            try:
                self.service.refresh_global_news(start=start, end=end)
            except Exception:
                pass
            return (
                self.service.decisions_for_day(day),
                self.service.completed_for_day(day),
                self.service.load_nifty_candle_range(
                    start, end, backfill_missing=True
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
            return self.service.analyze_time_range(start, end)

        def done(payload) -> None:
            self.time_page.range_load_button.setEnabled(True)
            self.time_page.range_load_button.setText("Analyze Period")
            analysis, opening, candles, _news, _events = payload
            self.time_page.set_range_analysis(analysis, opening, candles)
            self.statusBar().showMessage(
                "Historical range analysis complete.", 5000
            )

        def failed(message: str) -> None:
            self.time_page.range_load_button.setEnabled(True)
            self.time_page.range_load_button.setText("Analyze Period")
            self._show_error(message)

        self._run_task(task, done, failed)

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
            self.update_button.setText("Update")
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
            self.update_button.setText("Update")
            self._show_error(message)
        self._run_task(self.updater.check, done, failed)

    def _apply_update(self) -> None:
        self.update_button.setEnabled(False)
        self.update_button.setText("Updating…")
        def done(result: UpdateApplyResult) -> None:
            self.update_button.setEnabled(True)
            self.update_button.setText("Update")
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
            self.update_button.setText("Update")
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

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Intrader", message or "Operation unavailable.")
