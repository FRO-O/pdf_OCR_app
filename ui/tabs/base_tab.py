"""
Базовый класс вкладки.
"""
from __future__ import annotations
import os
from abc import abstractmethod
from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QFileDialog, QCheckBox, QRadioButton,
    QButtonGroup, QLineEdit, QMessageBox,
)
from app.pipeline import PipelineConfig, ProcessProfile
from core.ocr.base import OCRParams
from core.ocr.factory import get_engine_display_name, list_available_engines
from core.image_loader import is_image_file
from core.zones_io import load_zones, save_zones
from exporters.base import ExportOptions
from ui.widgets.slider_block import SliderBlock

COMPACT_GROUPBOX_STYLE = """
QGroupBox {
    margin-top: 6px;
    padding-top: 4px;
    padding-left: 2px;
    padding-right: 2px;
    padding-bottom: 2px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    left: 6px;
}
"""

class BaseTab(QWidget):
    request_run = pyqtSignal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.selected_file_path: str = ""
        self.zones_by_file: dict = {}
        self._engine_buttons: dict[str, QRadioButton] = {}
        self._target_buttons: dict[str, QRadioButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(4, 4, 4, 4)
        self._main_layout.setSpacing(4)

        self._build_file_group(self._main_layout)
        self._add_specific_groups(self._main_layout)
        self._build_language_group(self._main_layout)
        self._build_ocr_engine_group(self._main_layout)
        self._add_processing_checkboxes(self._main_layout)
        self._build_target_group(self._main_layout)
        self._build_presets_group(self._main_layout)
        self._build_sliders_group(self._main_layout)
        self._add_tail_groups(self._main_layout)

    @staticmethod
    def _make_group(title: str) -> tuple[QGroupBox, QVBoxLayout]:
        group = QGroupBox(title)
        group.setStyleSheet(COMPACT_GROUPBOX_STYLE)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        return group, layout

    def _build_file_group(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Файл")
        mode_layout = QHBoxLayout()
        self.rb_single = QRadioButton("Одиночный файл")
        self.rb_single.setChecked(True)
        self.rb_batch = QRadioButton("Пакетная обработка (папка)")
        self.rb_single.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self.rb_single)
        mode_layout.addWidget(self.rb_batch)
        mode_layout.addStretch()
        vbox.addLayout(mode_layout)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.path_label = QLabel("Файл не выбран")
        self.path_label.setStyleSheet("color: #555;")
        
        self.btn_select_file = QPushButton("Обзор...")
        self.btn_select_file.setMaximumWidth(100)
        self.btn_select_file.clicked.connect(self._on_select_file)

        self.btn_zones = QPushButton("Зоны OCR...")
        self.btn_zones.setMaximumWidth(100)
        self.btn_zones.setEnabled(False)
        self.btn_zones.clicked.connect(self._open_zone_editor)

        row.addWidget(self.path_label, stretch=1)
        row.addWidget(self.btn_select_file)
        row.addWidget(self.btn_zones)
        vbox.addLayout(row)

        pages_row = QHBoxLayout()
        pages_row.setSpacing(4)
        pages_row.addWidget(QLabel("Страницы:"))
        self.txt_pages = QLineEdit()
        self.txt_pages.setPlaceholderText("1, 3, 5-10 (пусто = все)")
        pages_row.addWidget(self.txt_pages)
        vbox.addLayout(pages_row)
        parent_layout.addWidget(group)

    def _on_mode_changed(self):
        is_batch = self.rb_batch.isChecked()
        self.btn_zones.setEnabled(bool(self.selected_file_path))
        if is_batch:
            self.btn_select_file.setText("Выбрать папку...")
            self.path_label.setText("Папка не выбрана")
        else:
            self.btn_select_file.setText("Обзор...")
            self.path_label.setText("Файл не выбран")
        self.zones_by_file.clear()

    def _build_language_group(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Языки распознавания")
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        preset_row.addWidget(QLabel("Пресеты:"))
        self.btn_lang_ru_en = QPushButton("RU+EN")
        self.btn_lang_ru_en_zh = QPushButton("RU+EN+ZH")
        self.btn_lang_en = QPushButton("EN")
        self.btn_lang_zh = QPushButton("ZH")
        for b in (self.btn_lang_ru_en, self.btn_lang_ru_en_zh, self.btn_lang_en, self.btn_lang_zh):
            b.setMaximumWidth(90)
            b.setMaximumHeight(24)
            preset_row.addWidget(b)
        preset_row.addStretch()
        vbox.addLayout(preset_row)

        self.btn_lang_ru_en.clicked.connect(lambda: self.set_languages(["ru", "en"]))
        self.btn_lang_ru_en_zh.clicked.connect(lambda: self.set_languages(["ru", "en", "ch_sim"]))
        self.btn_lang_en.clicked.connect(lambda: self.set_languages(["en"]))
        self.btn_lang_zh.clicked.connect(lambda: self.set_languages(["ch_sim"]))

        self.chk_lang_ru = QCheckBox("Русский (ru)")
        self.chk_lang_en = QCheckBox("Английский (en)")
        self.chk_lang_ko = QCheckBox("Корейский (ko)")
        self.chk_lang_ch_sim = QCheckBox("Кит. упр. (ch_sim)")
        self.chk_lang_ch_tra = QCheckBox("Кит. трад. (ch_tra)")
        self.chk_lang_ja = QCheckBox("Японский (ja)")

        self.chk_lang_ru.setChecked(True)
        self.chk_lang_en.setChecked(True)

        grid = QGridLayout()
        grid.setHorizontalSpacing(15)
        grid.setVerticalSpacing(2)
        grid.addWidget(self.chk_lang_ru,     0, 0)
        grid.addWidget(self.chk_lang_ko,     0, 1)
        grid.addWidget(self.chk_lang_en,     1, 0)
        grid.addWidget(self.chk_lang_ch_sim, 1, 1)
        grid.addWidget(self.chk_lang_ja,     2, 0)
        grid.addWidget(self.chk_lang_ch_tra, 2, 1)
        vbox.addLayout(grid)
        parent_layout.addWidget(group)

    def _build_ocr_engine_group(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("OCR")
        engine_row = QHBoxLayout()
        engine_row.setSpacing(8)
        engine_row.addWidget(QLabel("Движок:"))
        self._engine_group = QButtonGroup(self)
        for i, engine_name in enumerate(list_available_engines()):
            rb = QRadioButton(get_engine_display_name(engine_name))
            if i == 0:
                rb.setChecked(True)
            rb.setEnabled("не установлен" not in rb.text())
            rb.toggled.connect(self._on_engine_changed)
            self._engine_group.addButton(rb)
            self._engine_buttons[engine_name] = rb
            engine_row.addWidget(rb)
        engine_row.addStretch()
        vbox.addLayout(engine_row)

        self.chk_gpu = QCheckBox("Использовать GPU (CUDA)")
        self.chk_gpu.setChecked(True)
        vbox.addWidget(self.chk_gpu)

        self.api_key_layout = QHBoxLayout()
        self.api_key_layout.addWidget(QLabel("Mistral API Key:"))
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setPlaceholderText("Введите ключ...")
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_layout.addWidget(self.txt_api_key)
        vbox.addLayout(self.api_key_layout)
        self.api_key_layout.setEnabled(False)

        parent_layout.addWidget(group)

    def _on_engine_changed(self):
        is_mistral = self._engine_buttons.get("Mistral OCR (API)").isChecked() if "Mistral OCR (API)" in self._engine_buttons else False
        self.api_key_layout.setEnabled(is_mistral)
        self.chk_gpu.setEnabled(not is_mistral)

    def _build_target_group(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Целевое приложение")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.rb_pptx = QRadioButton("MS PowerPoint (.pptx)")
        self.rb_pptx.setChecked(True)
        self.rb_docx = QRadioButton("Word (две колонки)")
        self.rb_docx_doc = QRadioButton("Word (документ)")
        self.rb_indesign = QRadioButton("Adobe InDesign")
        self.rb_illustrator = QRadioButton("Adobe Illustrator")

        self._target_buttons["PPTX"] = self.rb_pptx
        self._target_buttons["DOCX_TRANSLATE"] = self.rb_docx
        self._target_buttons["DOCX_DOCUMENT"] = self.rb_docx_doc
        self._target_buttons["InDesign"] = self.rb_indesign
        self._target_buttons["Illustrator"] = self.rb_illustrator

        row.addWidget(self.rb_pptx)
        row.addWidget(self.rb_docx)
        row.addWidget(self.rb_docx_doc)
        row.addWidget(self.rb_indesign)
        row.addWidget(self.rb_illustrator)
        row.addStretch()
        vbox.addLayout(row)

        self.chk_hide_orig_text = QCheckBox("Скрывать оригинальный текст (белые подложки)")
        self.chk_hide_orig_text.setChecked(True)
        self.chk_hide_orig_text.setStyleSheet("font-weight: bold; color: #1b4f72;")
        vbox.addWidget(self.chk_hide_orig_text)

        self.chk_review_text = QCheckBox("Проверка текста после OCR (редактор)")
        vbox.addWidget(self.chk_review_text)
        parent_layout.addWidget(group)

    def _build_presets_group(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Пресеты")
        self._preset_group = QButtonGroup(self)
        self._preset_buttons: dict[str, QRadioButton] = {}
        presets = self._get_presets()
        cols = 4
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        for i, name in enumerate(presets.keys()):
            rb = QRadioButton(name)
            if name == self._get_default_preset():
                rb.setChecked(True)
            self._preset_group.addButton(rb)
            self._preset_buttons[name] = rb
            grid.addWidget(rb, i // cols, i % cols)
        vbox.addLayout(grid)
        self._preset_group.buttonClicked.connect(self._on_preset_clicked)

        self.btn_reset = QPushButton("Сбросить настройки")
        self.btn_reset.setStyleSheet("color: #555; font-size: 11px; padding: 2px;")
        self.btn_reset.setMaximumHeight(22)
        self.btn_reset.clicked.connect(self.reset_to_defaults)
        vbox.addWidget(self.btn_reset, alignment=Qt.AlignmentFlag.AlignRight)
        parent_layout.addWidget(group)

    def _build_sliders_group(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Параметры OCR и размер шрифта")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)

        self.slider_font = SliderBlock("Множитель шрифта", "Кегль (0.6–0.85 оптимально).", 0.3, 2.0, 0.75, 0.05, 2)
        self.slider_mag = SliderBlock("Масштаб картинки", "Увеличение перед OCR.", 1.0, 3.0, 1.75, 0.05, 2)
        self.slider_text_thresh = SliderBlock("Порог текста", "Мелкий текст — понизить.", 0.1, 0.9, 0.50, 0.05, 2)
        self.slider_low_text = SliderBlock("Порог тонких линий", "Связывание пикселей.", 0.1, 0.9, 0.20, 0.05, 2)
        self.slider_link = SliderBlock("Связывание букв", "Склеивание символов.", 0.05, 0.9, 0.40, 0.05, 2)

        grid.addWidget(self.slider_font,        0, 0)
        grid.addWidget(self.slider_mag,         0, 1)
        grid.addWidget(self.slider_text_thresh, 1, 0)
        grid.addWidget(self.slider_low_text,    1, 1)
        grid.addWidget(self.slider_link,        2, 0)
        vbox.addLayout(grid)
        parent_layout.addWidget(group)

    @abstractmethod
    def _add_specific_groups(self, parent_layout: QVBoxLayout) -> None: ...
    @abstractmethod
    def _add_processing_checkboxes(self, parent_layout: QVBoxLayout) -> None: ...
    def _add_tail_groups(self, parent_layout: QVBoxLayout) -> None: pass
    @abstractmethod
    def _get_presets(self) -> dict[str, tuple]: ...
    @abstractmethod
    def _get_default_preset(self) -> str: ...
    @abstractmethod
    def _get_process_profile(self) -> str: ...

    def build_config(self) -> PipelineConfig:
        target = "PPTX"
        for name, rb in self._target_buttons.items():
            if rb.isChecked(): target = name; break

        engine_name = "PaddleOCR"
        for name, rb in self._engine_buttons.items():
            if rb.isChecked(): engine_name = name; break

        ocr_params = OCRParams(
            mag_ratio=self.slider_mag.value(),
            text_threshold=self.slider_text_thresh.value(),
            low_text=self.slider_low_text.value(),
            link_threshold=self.slider_link.value(),
            width_ths=0.1 if self._is_table_mode() else 0.5,
            min_size=self._get_min_size(),
        )

        export_options = ExportOptions(
            font_scale=self.slider_font.value(),
            hide_orig_text=self.chk_hide_orig_text.isChecked(),
        )

        config = PipelineConfig(
            file_path=self.selected_file_path,
            page_indices=self.parse_pages(self.txt_pages.text()),
            prefer_pdf_text=self._prefer_pdf_text(),
            profile=self._get_process_profile(),
            invert=self._invert_enabled(),
            auto_dark=self._auto_dark_enabled(),
            upscale_small=self._upscale_enabled(),
            enhance=False,
            binarize=self._binarize_enabled(),
            engine_name=engine_name,
            languages=self.get_languages(),
            use_gpu=self.chk_gpu.isChecked(),
            api_key=self.txt_api_key.text().strip(),
            ocr_params=ocr_params,
            target_app=target,
            export_options=export_options,
            zones_by_file=self.zones_by_file,
        )
        self._apply_extra_config(config)
        return config

    def set_file_path(self, path: str) -> None:
        if path and os.path.exists(path):
            self.selected_file_path = path
            self.path_label.setText(os.path.basename(path))
            self.btn_zones.setEnabled(True)
            self.zones_by_file = {}
            saved_zones = load_zones(path)
            if saved_zones:
                self.zones_by_file[path] = saved_zones
                self.path_label.setText(f"{os.path.basename(path)} (зон: {len(saved_zones)})")

    def set_languages(self, langs: list[str]) -> None:
        self.chk_lang_ru.setChecked("ru" in langs)
        self.chk_lang_en.setChecked("en" in langs)
        self.chk_lang_ko.setChecked("ko" in langs)
        self.chk_lang_ch_sim.setChecked("ch_sim" in langs)
        self.chk_lang_ch_tra.setChecked("ch_tra" in langs)
        self.chk_lang_ja.setChecked("ja" in langs)

    def get_languages(self) -> list[str]:
        langs = []
        if self.chk_lang_ru.isChecked(): langs.append("ru")
        if self.chk_lang_en.isChecked(): langs.append("en")
        if self.chk_lang_ko.isChecked(): langs.append("ko")
        if self.chk_lang_ch_sim.isChecked(): langs.append("ch_sim")
        if self.chk_lang_ch_tra.isChecked(): langs.append("ch_tra")
        if self.chk_lang_ja.isChecked(): langs.append("ja")
        return langs if langs else ["ru", "en"]

    def reset_to_defaults(self) -> None:
        default_name = self._get_default_preset()
        if default_name in self._preset_buttons:
            self._preset_buttons[default_name].setChecked(True)
            self._on_preset_clicked(self._preset_buttons[default_name])
        self.slider_font.setValueSilent(0.75)
        self.chk_hide_orig_text.setChecked(True)
        self.txt_pages.clear()
        self.zones_by_file = {}

    def _on_select_file(self) -> None:
        if self.rb_batch.isChecked():
            path = QFileDialog.getExistingDirectory(self, "Выберите папку с файлами")
            if path:
                self.selected_file_path = path
                self.btn_zones.setEnabled(True)
                self.zones_by_file = {}
                total_zones = 0
                for f in os.listdir(path):
                    full_path = os.path.join(path, f)
                    if os.path.isfile(full_path) and is_image_file(full_path):
                        z = load_zones(full_path)
                        if z:
                            self.zones_by_file[full_path] = z
                            total_zones += len(z)
                if total_zones > 0: self.path_label.setText(f"{os.path.basename(path)} (зон: {total_zones})")
                else: self.path_label.setText(os.path.basename(path))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Выберите файл", "", "Все поддерживаемые (*.png *.jpg *.jpeg *.bmp *.tiff *.pdf);;Изображения (*.png *.jpg *.jpeg *.bmp *.tiff);;PDF документы (*.pdf)")
            if path: self.set_file_path(path)

    def _open_zone_editor(self) -> None:
        from ui.zone_editor import ZoneEditorDialog
        from PIL import Image
        files_data = []
        if self.rb_batch.isChecked() and os.path.isdir(self.selected_file_path):
            for f in sorted(os.listdir(self.selected_file_path)):
                full_path = os.path.join(self.selected_file_path, f)
                if os.path.isfile(full_path) and is_image_file(full_path):
                    try:
                        img = Image.open(full_path)
                        files_data.append({'file_path': full_path, 'image': img, 'zones': self.zones_by_file.get(full_path, load_zones(full_path))})
                    except Exception: pass
            if not files_data:
                QMessageBox.warning(self, "Ошибка", "В папке не найдено картинок для разметки.")
                return
        elif not self.rb_batch.isChecked() and self.selected_file_path:
            try:
                img = Image.open(self.selected_file_path)
                files_data.append({'file_path': self.selected_file_path, 'image': img, 'zones': self.zones_by_file.get(self.selected_file_path, [])})
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл: {e}")
                return
        else: return

        dialog = ZoneEditorDialog(files_data, self)
        if dialog.exec():
            results = dialog.get_results()
            self.zones_by_file.clear()
            total_zones = 0
            for res in results:
                file_path = res['file_path']
                zones = res['zones']
                self.zones_by_file[file_path] = zones
                total_zones += len(zones)
                save_zones(file_path, zones)
            if total_zones > 0: self.path_label.setText(f"{os.path.basename(self.selected_file_path)} (зон: {total_zones})")
            else: self.path_label.setText(os.path.basename(self.selected_file_path))

    def _on_preset_clicked(self, button: QRadioButton) -> None:
        name = button.text()
        preset = self._get_presets().get(name)
        if not preset: return
        self._apply_preset(name, preset)

    @staticmethod
    def parse_pages(text: str) -> Optional[list[int]]:
        text = text.strip()
        if not text: return None
        pages = set()
        for part in text.split(","):
            part = part.strip()
            if not part: continue
            if "-" in part:
                sub = part.split("-")
                if len(sub) == 2 and sub[0].isdigit() and sub[1].isdigit():
                    start, end = int(sub[0]), int(sub[1])
                    if start > end: start, end = end, start
                    for p in range(start, end + 1):
                        if p >= 1: pages.add(p - 1)
            elif part.isdigit():
                p = int(part)
                if p >= 1: pages.add(p - 1)
        return sorted(pages) if pages else None

    def _apply_preset(self, name: str, preset: tuple) -> None:
        mag, tt, lt, link = preset[:4]
        self.slider_mag.setValueSilent(mag)
        self.slider_text_thresh.setValueSilent(tt)
        self.slider_low_text.setValueSilent(lt)
        self.slider_link.setValueSilent(link)

    def _apply_extra_config(self, config: PipelineConfig) -> None: pass
    def _is_table_mode(self) -> bool: return False
    def _get_min_size(self) -> int: return 10
    def _prefer_pdf_text(self) -> bool: return True
    def _invert_enabled(self) -> bool: return False
    def _auto_dark_enabled(self) -> bool: return False
    def _upscale_enabled(self) -> bool: return False
    def _binarize_enabled(self) -> bool: return False