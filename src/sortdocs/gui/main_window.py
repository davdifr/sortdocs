from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sortdocs.executor import ExecutionProgressEvent, ExecutionReport, ExecutionStage
from sortdocs.gui.api_key_dialog import ApiKeyDialog
from sortdocs.gui.presenter import (
    build_plan_rows,
    format_action_details,
    format_execution_summary,
    format_skipped_directories,
    summarize_plan,
)
from sortdocs.gui.workers import AnalysisResultBundle, AnalysisWorker, ApplyWorker
from sortdocs.onboarding import OPENAI_API_KEY_ENV, load_saved_environment
from sortdocs.pipeline import PipelineProgressEvent
from sortdocs.utils import limit_text


class SortdocsMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("sortdocs")
        self.resize(1360, 840)

        self.thread_pool = QThreadPool.globalInstance()
        self.current_analysis: Optional[AnalysisResultBundle] = None
        self.current_report: Optional[ExecutionReport] = None
        self._active_workers: list[object] = []

        load_saved_environment()
        self._build_ui()
        self._set_default_source_dir()
        self._refresh_api_key_status()
        self._set_idle_state("Choose a folder and click Analyze.")

    def _build_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        intro_label = QLabel(
            "Analyze a folder, review the plan, and apply changes only after confirmation."
        )
        layout.addWidget(intro_label)

        folder_layout = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Choose a folder to organize")
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_for_folder)
        folder_layout.addWidget(QLabel("Folder"))
        folder_layout.addWidget(self.folder_input, stretch=1)
        folder_layout.addWidget(browse_button)
        layout.addLayout(folder_layout)
        self.browse_button = browse_button

        controls_layout = QHBoxLayout()
        self.api_key_status_label = QLabel()
        self.api_key_button = QPushButton("Set API Key…")
        self.api_key_button.clicked.connect(self._open_api_key_dialog)
        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.clicked.connect(self._start_analysis)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self._start_apply)
        self.apply_button.setEnabled(False)
        controls_layout.addWidget(self.api_key_status_label)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.api_key_button)
        controls_layout.addWidget(self.analyze_button)
        controls_layout.addWidget(self.apply_button)
        layout.addLayout(controls_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        summary_group = QGroupBox("Plan Summary")
        summary_layout = QGridLayout(summary_group)
        self.summary_discovered = QLabel("0")
        self.summary_actions = QLabel("0")
        self.summary_moves = QLabel("0")
        self.summary_renames = QLabel("0")
        self.summary_reviews = QLabel("0")
        self.summary_skips = QLabel("0")
        self.summary_cache = QLabel("0")
        self.summary_skipped_dirs = QLabel("0")
        summary_layout.addWidget(QLabel("Files discovered"), 0, 0)
        summary_layout.addWidget(self.summary_discovered, 0, 1)
        summary_layout.addWidget(QLabel("Planned actions"), 0, 2)
        summary_layout.addWidget(self.summary_actions, 0, 3)
        summary_layout.addWidget(QLabel("Moves"), 1, 0)
        summary_layout.addWidget(self.summary_moves, 1, 1)
        summary_layout.addWidget(QLabel("Renames"), 1, 2)
        summary_layout.addWidget(self.summary_renames, 1, 3)
        summary_layout.addWidget(QLabel("Reviews"), 2, 0)
        summary_layout.addWidget(self.summary_reviews, 2, 1)
        summary_layout.addWidget(QLabel("Skips"), 2, 2)
        summary_layout.addWidget(self.summary_skips, 2, 3)
        summary_layout.addWidget(QLabel("Cache hits"), 3, 0)
        summary_layout.addWidget(self.summary_cache, 3, 1)
        summary_layout.addWidget(QLabel("Skipped dirs"), 3, 2)
        summary_layout.addWidget(self.summary_skipped_dirs, 3, 3)
        layout.addWidget(summary_group)

        splitter = QSplitter()
        layout.addWidget(splitter, stretch=1)

        self.plan_table = QTableWidget(0, 6)
        self.plan_table.setHorizontalHeaderLabels(
            ["Action", "Conf", "Source", "Target", "Why", "Notes"]
        )
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.plan_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.plan_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.plan_table.itemSelectionChanged.connect(self._update_action_details)
        self.plan_table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.plan_table)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.details_text = QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setPlaceholderText("Select a planned action to inspect its details.")
        right_layout.addWidget(QLabel("Action Details"))
        right_layout.addWidget(self.details_text, stretch=3)
        self.notes_text = QPlainTextEdit()
        self.notes_text.setReadOnly(True)
        right_layout.addWidget(QLabel("Run Notes"))
        right_layout.addWidget(self.notes_text, stretch=2)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    def _set_default_source_dir(self) -> None:
        documents_dir = Path.home() / "Documents"
        default_dir = documents_dir if documents_dir.exists() else Path.cwd()
        self.folder_input.setText(str(default_dir))

    def _browse_for_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Folder", self.folder_input.text())
        if selected:
            self.folder_input.setText(selected)

    def _open_api_key_dialog(self) -> None:
        dialog = ApiKeyDialog(self)
        if dialog.exec():
            self._refresh_api_key_status()

    def _refresh_api_key_status(self) -> None:
        load_saved_environment()
        has_key = bool(os.getenv(OPENAI_API_KEY_ENV, "").strip())
        if has_key:
            self.api_key_status_label.setText("OpenAI API key: configured")
        else:
            self.api_key_status_label.setText("OpenAI API key: missing")

    def _ensure_api_key(self) -> bool:
        self._refresh_api_key_status()
        if os.getenv(OPENAI_API_KEY_ENV, "").strip():
            return True
        dialog = ApiKeyDialog(self)
        if dialog.exec():
            self._refresh_api_key_status()
            return bool(os.getenv(OPENAI_API_KEY_ENV, "").strip())
        return False

    def _selected_source_dir(self) -> Optional[Path]:
        raw_value = self.folder_input.text().strip()
        if not raw_value:
            QMessageBox.warning(self, "Missing Folder", "Please choose a folder first.")
            return None
        source_dir = Path(raw_value).expanduser().resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            QMessageBox.warning(self, "Invalid Folder", f"The selected folder is not valid:\n\n{source_dir}")
            return None
        return source_dir

    def _start_analysis(self) -> None:
        source_dir = self._selected_source_dir()
        if source_dir is None:
            return
        if not self._ensure_api_key():
            QMessageBox.warning(self, "Missing API Key", "An OpenAI API key is required to analyze files.")
            return

        self.current_analysis = None
        self.current_report = None
        self.apply_button.setEnabled(False)
        self._set_busy_state("Analyzing folder...")

        worker = AnalysisWorker(source_dir=source_dir)
        worker.signals.progress.connect(self._handle_analysis_progress)
        worker.signals.finished.connect(self._handle_analysis_finished)
        worker.signals.error.connect(self._handle_worker_error)
        self._start_worker(worker)

    def _start_apply(self) -> None:
        if self.current_analysis is None:
            QMessageBox.information(self, "Nothing To Apply", "Analyze a folder first.")
            return
        if not self.current_analysis.plan.actions:
            QMessageBox.information(self, "Nothing To Apply", "There are no planned actions to apply.")
            return

        answer = QMessageBox.question(
            self,
            "Apply Planned Actions",
            "Apply the current plan to the filesystem?",
        )
        if answer != QMessageBox.Yes:
            return

        self._set_busy_state("Applying planned actions...")
        worker = ApplyWorker(analysis_bundle=self.current_analysis)
        worker.signals.progress.connect(self._handle_apply_progress)
        worker.signals.finished.connect(self._handle_apply_finished)
        worker.signals.error.connect(self._handle_worker_error)
        self._start_worker(worker)

    def _start_worker(self, worker: object) -> None:
        self._active_workers.append(worker)
        worker.signals.finished.connect(lambda *_args, w=worker: self._release_worker(w))
        worker.signals.error.connect(lambda *_args, w=worker: self._release_worker(w))
        self.thread_pool.start(worker)

    def _release_worker(self, worker: object) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)

    def _handle_analysis_progress(self, event: PipelineProgressEvent) -> None:
        if event.stage == "scanning":
            self.progress_bar.setRange(0, 0)
            self.status_label.setText("Scanning files...")
            return
        if event.stage == "scan_complete":
            total = max(event.total or 0, 1)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
            self.status_label.setText(f"Found {event.total or 0} files. Starting classification...")
            return
        if event.stage == "classifying":
            total = max(event.total or 0, 1)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(event.current)
            current_name = event.current_path.name if event.current_path is not None else "current file"
            self.status_label.setText(
                f"Classifying {event.current}/{event.total or 0} - "
                f"{limit_text(current_name, 72)} - cache hits {event.cache_hits}"
            )
            return
        if event.stage == "planning_complete":
            total = max(event.total or 0, 1)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(total)
            self.status_label.setText(f"Plan ready for {event.current} files.")

    def _handle_analysis_finished(self, bundle: AnalysisResultBundle) -> None:
        self.current_analysis = bundle
        self.current_report = None
        self._set_idle_state("Review the plan and apply it when ready.")
        self._populate_plan(bundle)

        if bundle.plan.actions:
            self.apply_button.setEnabled(True)
        if not bundle.plan.discovered_files:
            QMessageBox.information(self, "No Files Found", "No files were discovered in the selected folder.")

    def _handle_apply_progress(self, event: ExecutionProgressEvent) -> None:
        total = max(event.total, 1)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(event.current)
        if event.stage == ExecutionStage.COMPLETE:
            self.status_label.setText("Apply complete.")
            return
        self.status_label.setText(
            f"Applying {event.current}/{event.total} - "
            f"{limit_text(event.action.target_filename, 72)}"
        )

    def _handle_apply_finished(self, report: ExecutionReport) -> None:
        self.current_report = report
        self.apply_button.setEnabled(False)
        self._set_idle_state("Apply finished. Re-analyze the folder to build a fresh plan.")
        notes = self.notes_text.toPlainText().strip()
        report_summary = format_execution_summary(report)
        combined = f"{notes}\n\nExecution Summary\n{report_summary}".strip()
        self.notes_text.setPlainText(combined)

        if report.counts.failed:
            QMessageBox.warning(
                self,
                "Apply Finished With Errors",
                f"The apply step finished with {report.counts.failed} failures.",
            )
        else:
            QMessageBox.information(self, "Apply Finished", "The plan was applied successfully.")

    def _handle_worker_error(self, message: str) -> None:
        self.apply_button.setEnabled(self.current_analysis is not None and bool(self.current_analysis.plan.actions))
        self._set_idle_state("The last operation did not complete successfully.")
        QMessageBox.warning(self, "sortdocs", message)

    def _set_busy_state(self, message: str) -> None:
        self.analyze_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.api_key_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.folder_input.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(message)

    def _set_idle_state(self, message: str) -> None:
        self.analyze_button.setEnabled(True)
        self.api_key_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.folder_input.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.status_label.setText(message)

    def _populate_plan(self, bundle: AnalysisResultBundle) -> None:
        summary = summarize_plan(bundle.plan)
        self.summary_discovered.setText(str(summary.discovered_files))
        self.summary_actions.setText(str(summary.planned_actions))
        self.summary_moves.setText(str(summary.moves))
        self.summary_renames.setText(str(summary.renames))
        self.summary_reviews.setText(str(summary.reviews))
        self.summary_skips.setText(str(summary.skips))
        self.summary_cache.setText(str(summary.cache_hits))
        self.summary_skipped_dirs.setText(str(summary.skipped_directories))

        rows = build_plan_rows(bundle.plan, base_dir=bundle.context.source_dir.parent)
        self.plan_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(
                [
                    row.action_label,
                    row.confidence_label,
                    row.source_label,
                    row.target_label,
                    row.reason_label,
                    row.notes_label,
                ]
            ):
                self.plan_table.setItem(row_index, column_index, QTableWidgetItem(value))
        self.plan_table.resizeColumnsToContents()
        if rows:
            self.plan_table.selectRow(0)
        else:
            self.details_text.clear()

        config_label = bundle.context.config_path or "defaults"
        notes = [
            f"Folder: {bundle.context.source_dir}",
            f"Config: {config_label}",
            "",
            "Protected / ignored directories:",
            format_skipped_directories(bundle.plan.skipped_directories),
        ]
        self.notes_text.setPlainText("\n".join(str(item) for item in notes))

    def _update_action_details(self) -> None:
        if self.current_analysis is None:
            self.details_text.clear()
            return
        selected_items = self.plan_table.selectedItems()
        if not selected_items:
            self.details_text.clear()
            return
        row_index = selected_items[0].row()
        if row_index >= len(self.current_analysis.plan.actions):
            self.details_text.clear()
            return
        self.details_text.setPlainText(format_action_details(self.current_analysis.plan.actions[row_index]))
