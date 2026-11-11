"""
Главное окно с двумя вкладками: Чертежи / Интерфейсы.
"""

from __future__ import annotations
import logging
import os
import threading
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QProgressBar,
    QToolButton, QGroupBox, QTabWidget, QScrollArea, QSizePolicy, QDialog,
)

from app.pipeline import (
    PipelineCallbacks, PipelineConfig, PipelineStopped, 
    process_document, export_document, run_pipeline
)
from app.batch_pipeline import BatchConfig, BatchCallbacks, run_batch_pipeline
from ui.settings_manager import SettingsManager
from ui.tabs.base_tab import BaseTab
from ui.tabs.drawings_tab import DrawingsTab
from ui.tabs.ui_tab import UITab
from ui.text_editor import TextEditorDialog

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    stage = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    review_needed = pyqtSignal(object) # Для передачи страниц в главный поток


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF/Image → PPTX / InDesign / Illustrator")

        self.stop_requested: bool = False
        self._worker_thread: Optional[threading.Thread] = None

        self.settings = SettingsManager()

        self.signals = WorkerSignals()
        self.signals.log.connect(self._on_worker_log)
        self.signals.progress.connect(self._on_worker_progress)
        self.signals.stage.connect(self._on_worker_stage)
        self.signals.finished.connect(self._on_worker_finished)
        self.signals.review_needed.connect(self._show_text_editor)

        # Синхронизация для остановки воркера перед показом редактора
        self._review_event = threading.Event()
        self._review_result = False

        self._build_ui()
        self._fit_to_screen()
        self._restore_settings()

        self._sync_tabs_from(self.current_tab())

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        self._content = content

        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.drawings_tab = DrawingsTab()
        self.ui_tab = UITab()
        self.tabs.addTab(self.drawings_tab, "Чертежи")
        self.tabs.addTab(self.ui_tab, "Интерфейсы")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.tabs.setMinimumHeight(280)
        main_layout.addWidget(self.tabs)

        self.progress_label = QLabel("Готов к запуску")
        self.progress_label.setStyleSheet("color: #555; font-size: 11px;")
        main_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(18)
        main_layout.addWidget(self.progress_bar)

        self.btn_toggle_log = QToolButton()
        self.btn_toggle_log.setText("▶ Журнал выполнения")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setStyleSheet(
            "QToolButton { text-align: left; padding: 2px; "
            "font-size: 11px; }"
        )
        self.btn_toggle_log.toggled.connect(self._on_toggle_log)
        main_layout.addWidget(self.btn_toggle_log)

        self.log_group = QGroupBox()
        self.log_group.setStyleSheet("QGroupBox { margin: 0; padding: 0; }")
        log_layout = QVBoxLayout(self.log_group)
        log_layout.setContentsMargins(2, 2, 2, 2)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(100)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        self.log_group.setVisible(False)
        main_layout.addWidget(self.log_group)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_run = QPushButton("ЗАПУСТИТЬ ЭКСПОРТ")
        self.btn_run.setFixedHeight(40)
        self.btn_run.setStyleSheet(
            "font-weight: bold; font-size: 13px; "
            "background-color: #2b5b84; color: white;"
        )
        self.btn_run.clicked.connect(self._on_run)

        self.btn_stop = QPushButton("СТОП")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setFixedWidth(110)
        self.btn_stop.setStyleSheet(
            "font-weight: bold; font-size: 13px; "
            "background-color: #c93b2b; color: white;"
        )
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)

        btn_row.addWidget(self.btn_run, stretch=1)
        btn_row.addWidget(self.btn_stop)
        main_layout.addLayout(btn_row)

        main_layout.addStretch(1)

    def _fit_to_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(880, 780)
            return

        available = screen.availableGeometry()
        max_w = available.width() - 40
        max_h = available.height() - 40

        target_w = min(880, max_w)
        target_h = min(780, max_h)

        target_w = max(target_w, 700)
        target_h = max(target_h, 480)

        self.resize(target_w, target_h)
        x = available.x() + (available.width() - target_w) // 2
        y = available.y() + (available.height() - target_h) // 2
        self.move(x, y)

    # ==================================================================
    # Вкладки
    # ==================================================================

    def current_tab(self) -> BaseTab:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, BaseTab) else self.drawings_tab

    def _on_tab_changed(self, index: int) -> None:
        self._sync_tabs_from(self.current_tab())

    def _sync_tabs_from(self, source: BaseTab) -> None:
        langs = source.get_languages()
        gpu = source.chk_gpu.isChecked()
        engine = self._get_engine_name(source)
        target = self._get_target_name(source)
        hide_text = source.chk_hide_orig_text.isChecked()
        review_text = source.chk_review_text.isChecked()

        for tab in (self.drawings_tab, self.ui_tab):
            if tab is source:
                continue
            tab.set_languages(langs)
            tab.chk_gpu.setChecked(gpu)
            self._set_engine_name(tab, engine)
            self._set_target_name(tab, target)
            tab.chk_hide_orig_text.setChecked(hide_text)
            tab.chk_review_text.setChecked(review_text)

    @staticmethod
    def _get_engine_name(tab: BaseTab) -> str:
        for name, rb in tab._engine_buttons.items():
            if rb.isChecked():
                return name
        return "EasyOCR"

    @staticmethod
    def _set_engine_name(tab: BaseTab, name: str) -> None:
        if name in tab._engine_buttons:
            rb = tab._engine_buttons[name]
            if rb.isEnabled():
                rb.setChecked(True)

    @staticmethod
    def _get_target_name(tab: BaseTab) -> str:
        for name, rb in tab._target_buttons.items():
            if rb.isChecked():
                return name
        return "PPTX"

    @staticmethod
    def _set_target_name(tab: BaseTab, name: str) -> None:
        if name in tab._target_buttons:
            tab._target_buttons[name].setChecked(True)

    # ==================================================================
    # Лог
    # ==================================================================

    def _on_toggle_log(self, checked: bool) -> None:
        self.log_group.setVisible(checked)
        self.btn_toggle_log.setText(
            ("▼ " if checked else "▶ ") + "Журнал выполнения"
        )

    # ==================================================================
    # Запуск / Остановка
    # ==================================================================

    def _on_run(self) -> None:
        tab = self.current_tab()
        if not tab.selected_file_path or not os.path.exists(tab.selected_file_path):
            QMessageBox.warning(self, "Ошибка", "Выберите файл или папку.")
            return

        self.stop_requested = False
        self._set_ui_running(True)
        self.log_text.clear()
        self.progress_bar.setValue(0)

        try:
            config = tab.build_config()
            # Динамически добавляем флаг проверки текста в конфиг
            config.review_callback = tab.chk_review_text.isChecked()
        except ValueError as e:
            self._set_ui_running(False)
            QMessageBox.warning(self, "Ошибка настроек", str(e))
            return

        config.export_options.log_fn = self.signals.log.emit

        if tab.rb_batch.isChecked():
            self.progress_label.setText("Запуск пакетной обработки...")
            self._worker_thread = threading.Thread(
                target=self._run_batch_worker, args=(config,), daemon=True,
            )
        else:
            self.progress_label.setText("Запуск...")
            self._worker_thread = threading.Thread(
                target=self._run_worker, args=(config,), daemon=True,
            )
        self._worker_thread.start()

    def _on_stop(self) -> None:
        self.stop_requested = True
        self.signals.log.emit("\n[ОСТАНОВКА] Запрошена отмена процесса...")
        self.btn_stop.setEnabled(False)
        
        # Если ждём в редакторе, разбудим поток
        if not self._review_event.is_set():
            self._review_result = False
            self._review_event.set()

    def _run_worker(self, config: PipelineConfig) -> None:
        callbacks = PipelineCallbacks(
            log_fn=self.signals.log.emit,
            progress_fn=self.signals.progress.emit,
            stage_fn=self.signals.stage.emit,
            stop_fn=lambda: self.stop_requested,
        )
        try:
            # Если включена проверка текста
            if getattr(config, "review_callback", False):
                # 1. Распознаём
                pages = process_document(config, callbacks)
                
                if self.stop_requested:
                    raise PipelineStopped("Остановлено пользователем")

                # 2. Отправляем в UI
                self._review_event.clear()
                self.signals.review_needed.emit(pages)
                
                # 3. Ждём ответа от UI-потока
                self._review_event.wait()
                
                if not self._review_result:
                    raise PipelineStopped("Экспорт отменён пользователем после проверки.")
                
                # 4. Экспортируем
                output = export_document(config.file_path, pages, config, callbacks)
            else:
                # Полный цикл без остановки
                output = run_pipeline(config, callbacks)
                
            self.signals.finished.emit(True, output)
            
        except PipelineStopped as e:
            self.signals.finished.emit(False, f"Остановлено: {e}")
        except Exception as e:
            logger.exception("Pipeline error")
            self.signals.finished.emit(False, str(e))

    def _run_batch_worker(self, config: PipelineConfig) -> None:
        batch_callbacks = BatchCallbacks(
            log_fn=self.signals.log.emit,
            progress_fn=self.signals.progress.emit,
            stage_fn=self.signals.stage.emit,
            stop_fn=lambda: self.stop_requested,
        )
        
        batch_config = BatchConfig(
            folder_path=config.file_path,
            base_config=config,
        )
        
        try:
            created_files = run_batch_pipeline(batch_config, batch_callbacks)
            if created_files:
                self.signals.finished.emit(True, f"Обработано файлов: {len(created_files)}")
            else:
                self.signals.finished.emit(False, "Ни один файл не был обработан.")
        except Exception as e:
            logger.exception("Batch pipeline error")
            self.signals.finished.emit(False, f"Ошибка пакетной обработки: {e}")

    def _show_text_editor(self, pages) -> None:
        """Вызывается в главном потоке (через сигнал). Открывает редактор."""
        dialog = TextEditorDialog(pages, self)
        res = dialog.exec()
        self._review_result = (res == QDialog.DialogCode.Accepted)
        self._review_event.set() # Будим рабочий поток

    def _on_worker_log(self, message: str) -> None:
        self.log_text.append(message)

    def _on_worker_progress(self, value: int) -> None:
        self.progress_bar.setValue(value)

    def _on_worker_stage(self, stage_name: str) -> None:
        self.progress_label.setText(stage_name)

    def _on_worker_finished(self, success: bool, message: str) -> None:
        self._set_ui_running(False)
        if success:
            self.progress_label.setText("Готово")
            self.log_text.append(f"\n[УСПЕХ] {message}")
            QMessageBox.information(self, "Готово", f"{message}")
        else:
            self.progress_label.setText("Ошибка или остановка")
            self.log_text.append(f"\n[СТАТУС] {message}")
            if "Остановлено" in message or "остановлен" in message:
                QMessageBox.information(self, "Остановлено", message)
            else:
                QMessageBox.critical(self, "Ошибка", message)

    def _set_ui_running(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        for tab in (self.drawings_tab, self.ui_tab):
            tab.btn_select_file.setEnabled(not running)

    # ==================================================================
    # QSettings
    # ==================================================================

    def _save_settings(self) -> None:
        s = self.settings
        s.save_window_state(self)
        s.set_int("ui/active_tab", self.tabs.currentIndex())
        s.set_bool("ui/log_visible", self.btn_toggle_log.isChecked())

        active = self.current_tab()
        s.set_list("shared/languages", active.get_languages())
        s.set_bool("shared/gpu", active.chk_gpu.isChecked())
        s.set_str("shared/engine", self._get_engine_name(active))
        s.set_str("shared/target", self._get_target_name(active))
        s.set_bool("shared/hide_orig_text", active.chk_hide_orig_text.isChecked())
        s.set_bool("shared/review_text", active.chk_review_text.isChecked())

        self._save_tab(s, "tab/drawings", self.drawings_tab)
        self._save_tab(s, "tab/ui", self.ui_tab)

        s.sync()

    def _save_tab(self, s: SettingsManager, prefix: str, tab: BaseTab) -> None:
        s.set_str(f"{prefix}/file", tab.selected_file_path)
        s.set_str(f"{prefix}/pages", tab.txt_pages.text())
        s.set_bool(f"{prefix}/batch_mode", tab.rb_batch.isChecked())

        preset = ""
        for name, rb in tab._preset_buttons.items():
            if rb.isChecked():
                preset = name
                break
        s.set_str(f"{prefix}/preset", preset)

        s.set_float(f"{prefix}/font_scale", tab.slider_font.value())
        s.set_float(f"{prefix}/mag_ratio", tab.slider_mag.value())
        s.set_float(f"{prefix}/text_threshold", tab.slider_text_thresh.value())
        s.set_float(f"{prefix}/low_text", tab.slider_low_text.value())
        s.set_float(f"{prefix}/link_threshold", tab.slider_link.value())

    def _restore_settings(self) -> None:
        s = self.settings
        self._restore_geometry_safe()

        idx = s.get_int("ui/active_tab", 0)
        if 0 <= idx < self.tabs.count():
            self.tabs.setCurrentIndex(idx)

        log_visible = s.get_bool("ui/log_visible", False)
        self.btn_toggle_log.setChecked(log_visible)

        langs = s.get_list("shared/languages", ["ru", "en"])
        gpu = s.get_bool("shared/gpu", True)
        engine = s.get_str("shared/engine", "EasyOCR")
        target = s.get_str("shared/target", "PPTX")
        hide_text = s.get_bool("shared/hide_orig_text", True)
        review_text = s.get_bool("shared/review_text", False)

        for tab in (self.drawings_tab, self.ui_tab):
            tab.set_languages(langs)
            tab.chk_gpu.setChecked(gpu)
            self._set_engine_name(tab, engine)
            self._set_target_name(tab, target)
            tab.chk_hide_orig_text.setChecked(hide_text)
            tab.chk_review_text.setChecked(review_text)

        self._restore_tab(s, "tab/drawings", self.drawings_tab)
        self._restore_tab(s, "tab/ui", self.ui_tab)

    def _restore_tab(self, s: SettingsManager, prefix: str, tab: BaseTab) -> None:
        last_file = s.get_str(f"{prefix}/file", "")
        if last_file and os.path.exists(last_file):
            tab.selected_file_path = last_file
            tab.path_label.setText(os.path.basename(last_file))
        
        batch_mode = s.get_bool(f"{prefix}/batch_mode", False)
        if batch_mode:
            tab.rb_batch.setChecked(True)
            tab.btn_select_file.setText("Выбрать папку...")
        else:
            tab.rb_single.setChecked(True)
            if last_file and os.path.exists(last_file):
                tab.btn_zones.setEnabled(True)

        tab.txt_pages.setText(s.get_str(f"{prefix}/pages", ""))

        preset_name = s.get_str(f"{prefix}/preset", "")
        if preset_name and preset_name in tab._preset_buttons:
            tab._preset_buttons[preset_name].setChecked(True)

        tab.slider_font.setValueSilent(s.get_float(f"{prefix}/font_scale", 0.75))
        tab.slider_mag.setValueSilent(s.get_float(f"{prefix}/mag_ratio", 1.75))
        tab.slider_text_thresh.setValueSilent(
            s.get_float(f"{prefix}/text_threshold", 0.50)
        )
        tab.slider_low_text.setValueSilent(
            s.get_float(f"{prefix}/low_text", 0.20)
        )
        tab.slider_link.setValueSilent(
            s.get_float(f"{prefix}/link_threshold", 0.40)
        )

    def _restore_geometry_safe(self) -> None:
        restored = self.settings.restore_window_state(self)
        if not restored:
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        if frame.width() > avail.width() or frame.height() > avail.height():
            target_w = min(880, avail.width() - 40)
            target_h = min(780, avail.height() - 40)
            target_w = max(target_w, 700)
            target_h = max(target_h, 480)
            self.resize(target_w, target_h)
            x = avail.x() + (avail.width() - target_w) // 2
            y = avail.y() + (avail.height() - target_h) // 2
            self.move(x, y)

    def closeEvent(self, event) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            reply = QMessageBox.question(
                self, "Процесс выполняется",
                "Обработка ещё идёт. Остановить и выйти?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.stop_requested = True
            if not self._review_event.is_set():
                self._review_result = False
                self._review_event.set()

        try:
            self._save_settings()
        except Exception as e:
            logger.exception("Ошибка сохранения настроек: %s", e)
        event.accept()