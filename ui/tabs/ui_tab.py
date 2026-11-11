"""
Вкладка «Интерфейсы».

Для скриншотов интерфейсов программ.
Профиль слияния — UI (минимальное слияние, фильтр мусора).
Включает инструменты перевода (JSON-экспорт/импорт).

По умолчанию включены:
- Автоопределение тёмной темы
- Апскейл мелкого текста
- Фильтр мусора
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QCheckBox, QRadioButton, QLabel, QButtonGroup, QToolButton,
    QWidget, QPushButton, QFileDialog, QLineEdit,
)

from app.pipeline import ProcessProfile, PipelineConfig
from ui.tabs.base_tab import BaseTab


# Пресеты для UI-скриншотов:
# name: (mag_ratio, text_threshold, low_text, link_threshold,
#        invert, is_table)
UI_PRESETS: dict[str, tuple] = {
    "UI светлая тема": (2.0, 0.55, 0.30, 0.35, False, False),
    "UI тёмная тема":  (2.0, 0.60, 0.35, 0.40, True,  False),
    "UI мелкий шрифт": (2.5, 0.50, 0.25, 0.30, False, False),
    "UI + таблицы":    (2.0, 0.55, 0.30, 0.15, False, True),
    "блок-схема":      (2.0, 0.35, 0.15, 0.30, False, False),
}

DEFAULT_PRESET = "UI светлая тема"


class UITab(BaseTab):
    """Вкладка для скриншотов интерфейсов."""

    def __init__(self, parent: QWidget = None):
        # Инициализируем внутреннее состояние ДО вызова super().__init__(),
        # потому что _add_tail_groups() (вызывается внутри _build_ui)
        # уже обращается к _import_json_path.
        self._import_json_path: str = ""
        super().__init__(parent)

    # ------------------------------------------------------------------
    # Специфичные группы
    # ------------------------------------------------------------------

    def _add_specific_groups(self, parent_layout: QVBoxLayout) -> None:
        # Профиль интерфейса
        group, vbox = self._make_group("Профиль интерфейса")

        row = QHBoxLayout()
        row.setSpacing(8)
        self.rb_theme_light = QRadioButton("Светлая тема")
        self.rb_theme_light.setChecked(True)
        self.rb_theme_dark = QRadioButton("Тёмная тема")
        self.rb_theme_auto = QRadioButton("Автоопределение")

        self._theme_group = QButtonGroup(self)
        self._theme_group.addButton(self.rb_theme_light)
        self._theme_group.addButton(self.rb_theme_dark)
        self._theme_group.addButton(self.rb_theme_auto)

        row.addWidget(self.rb_theme_light)
        row.addWidget(self.rb_theme_dark)
        row.addWidget(self.rb_theme_auto)
        row.addStretch()
        vbox.addLayout(row)

        hint = QLabel(
            "<span style='color:#666; font-size:10px;'>"
            "Автоопределение инвертирует изображение при тёмной теме."
            "</span>"
        )
        hint.setWordWrap(True)
        vbox.addWidget(hint)

        parent_layout.addWidget(group)

    def _add_processing_checkboxes(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Настройки обработки")

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(2)

        self.chk_invert = QCheckBox("Принудительная инверсия")
        self.chk_auto_dark = QCheckBox("Автоопределение тёмной темы")
        self.chk_upscale = QCheckBox("Увеличивать мелкий текст (HiDPI)")
        self.chk_filter_noise = QCheckBox("Фильтровать мусор (мелкие боксы)")
        self.chk_table_mode = QCheckBox("Строгий режим таблиц")

        self.chk_auto_dark.setChecked(True)
        self.chk_upscale.setChecked(True)
        self.chk_filter_noise.setChecked(True)

        grid.addWidget(self.chk_invert,        0, 0)
        grid.addWidget(self.chk_auto_dark,     0, 1)
        grid.addWidget(self.chk_upscale,       1, 0)
        grid.addWidget(self.chk_filter_noise,  1, 1)
        grid.addWidget(self.chk_table_mode,    2, 0)
        vbox.addLayout(grid)

        parent_layout.addWidget(group)

    # ------------------------------------------------------------------
    # Хвост — «Инструменты перевода»
    # ------------------------------------------------------------------

    def _add_tail_groups(self, parent_layout: QVBoxLayout) -> None:
        # Заголовок-переключатель
        self.btn_toggle_translate = QToolButton()
        self.btn_toggle_translate.setText("▶ Инструменты перевода")
        self.btn_toggle_translate.setCheckable(True)
        self.btn_toggle_translate.setChecked(False)
        self.btn_toggle_translate.setStyleSheet(
            "QToolButton { text-align: left; padding: 4px; "
            "font-weight: bold; color: #8e44ad; }"
        )
        self.btn_toggle_translate.toggled.connect(self._on_toggle_translate)
        parent_layout.addWidget(self.btn_toggle_translate)

        # Тело блока (свёрнуто по умолчанию)
        self.translate_group = QGroupBox()
        self.translate_group.setStyleSheet(
            "QGroupBox { margin-top: 4px; padding: 4px; }"
        )
        translate_layout = QVBoxLayout(self.translate_group)
        translate_layout.setContentsMargins(8, 6, 8, 6)
        translate_layout.setSpacing(6)

        hint = QLabel(
            "<span style='color:#666; font-size:10px;'>"
            "Экспорт текста в JSON для перевода или импорт готового "
            "перевода для сборки финального PPTX."
            "</span>"
        )
        hint.setWordWrap(True)
        translate_layout.addWidget(hint)

        # Экспорт JSON
        self.chk_export_json = QCheckBox("Экспортировать JSON для перевода")
        self.chk_export_json.setToolTip(
            "Сохраняет рядом с результатом файл <имя>_translate.json "
            "со всей структурой текста и координатами."
        )
        translate_layout.addWidget(self.chk_export_json)

        # Импорт JSON
        self.chk_import_json = QCheckBox("Импортировать перевод из JSON")
        self.chk_import_json.setToolTip(
            "Пропускает OCR и собирает PPTX/InDesign по данным JSON "
            "(поля translation)."
        )
        self.chk_import_json.toggled.connect(self._on_import_toggled)
        translate_layout.addWidget(self.chk_import_json)

        # Строка выбора JSON-файла (активна только если import_json включён)
        import_row = QHBoxLayout()
        import_row.setSpacing(4)
        self.json_path_label = QLabel("JSON не выбран")
        self.json_path_label.setStyleSheet("color: #888; font-size: 10px;")
        self.btn_select_json = QPushButton("Выбрать JSON...")
        self.btn_select_json.setMaximumWidth(140)
        self.btn_select_json.setEnabled(False)
        self.btn_select_json.clicked.connect(self._on_select_json)
        import_row.addWidget(self.json_path_label, stretch=1)
        import_row.addWidget(self.btn_select_json)
        translate_layout.addLayout(import_row)

        # Автоподгонка шрифта под перевод
        self.chk_fit_font = QCheckBox(
            "Автоподгонка размера шрифта под перевод"
        )
        self.chk_fit_font.setToolTip(
            "Уменьшает размер шрифта, если перевод длиннее оригинала "
            "и не влезает в исходную рамку."
        )
        self.chk_fit_font.setChecked(True)
        translate_layout.addWidget(self.chk_fit_font)

        # Белый фон вместо исходного изображения
        self.chk_translation_white_bg = QCheckBox(
            "Белый фон при экспорте перевода (без исходной картинки)"
        )
        self.chk_translation_white_bg.setToolTip(
            "Полезно, если исходный скриншот — только черновик "
            "или его не нужно сохранять в финальном файле."
        )
        translate_layout.addWidget(self.chk_translation_white_bg)

        self.translate_group.setVisible(False)
        parent_layout.addWidget(self.translate_group)

    def _on_toggle_translate(self, checked: bool) -> None:
        self.translate_group.setVisible(checked)
        prefix = "▼" if checked else "▶"
        self.btn_toggle_translate.setText(
            f"{prefix} Инструменты перевода"
        )

    def _on_import_toggled(self, checked: bool) -> None:
        """Активирует/деактивирует выбор JSON."""
        self.btn_select_json.setEnabled(checked)
        if checked:
            self.json_path_label.setStyleSheet(
                "color: #333; font-size: 10px; font-weight: bold;"
            )
        else:
            self.json_path_label.setStyleSheet(
                "color: #888; font-size: 10px;"
            )

    def _on_select_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите JSON с переводом",
            "",
            "JSON файлы (*.json);;Все файлы (*.*)",
        )
        if path:
            self._import_json_path = path
            self.json_path_label.setText(os.path.basename(path))
            self.json_path_label.setToolTip(path)

    # ------------------------------------------------------------------
    # Публичный API для pipeline
    # ------------------------------------------------------------------

    def get_translation_settings(self) -> dict:
        """Возвращает настройки перевода для pipeline."""
        return {
            "export_json": self.chk_export_json.isChecked(),
            "import_json_path": (
                self._import_json_path
                if self.chk_import_json.isChecked() else None
            ),
            "background_white": self.chk_translation_white_bg.isChecked(),
            "fit_to_bbox": self.chk_fit_font.isChecked(),
        }

    # ------------------------------------------------------------------
    # Пресеты / профиль
    # ------------------------------------------------------------------

    def _get_presets(self) -> dict[str, tuple]:
        return UI_PRESETS

    def _get_default_preset(self) -> str:
        return DEFAULT_PRESET

    def _get_process_profile(self) -> str:
        return ProcessProfile.UI

    # ------------------------------------------------------------------
    # Хуки для build_config
    # ------------------------------------------------------------------

    def _apply_preset(self, name: str, preset: tuple) -> None:
        mag, tt, lt, link, invert, is_table = preset
        self.slider_mag.setValueSilent(mag)
        self.slider_text_thresh.setValueSilent(tt)
        self.slider_low_text.setValueSilent(lt)
        self.slider_link.setValueSilent(link)
        self.chk_table_mode.setChecked(is_table)

        if "тёмная" in name.lower() or "темная" in name.lower():
            self.rb_theme_dark.setChecked(True)
            self.chk_invert.setChecked(True)
            self.chk_auto_dark.setChecked(False)
        elif "светлая" in name.lower():
            self.rb_theme_light.setChecked(True)
            self.chk_invert.setChecked(False)
            self.chk_auto_dark.setChecked(False)

    def _apply_extra_config(self, config: PipelineConfig) -> None:
        """Дописывает в конфиг настройки перевода."""
        settings = self.get_translation_settings()
        config.export_json = settings["export_json"]
        config.import_json_path = settings["import_json_path"]
        config.translation_background_white = settings["background_white"]
        # Автоподгонка идёт в ExportOptions
        config.export_options.fit_to_bbox = settings["fit_to_bbox"]

    def _is_table_mode(self) -> bool:
        return self.chk_table_mode.isChecked()

    def _get_min_size(self) -> int:
        return 5

    def _prefer_pdf_text(self) -> bool:
        return True

    def _invert_enabled(self) -> bool:
        if self.rb_theme_dark.isChecked():
            return True
        return self.chk_invert.isChecked()

    def _auto_dark_enabled(self) -> bool:
        if self.rb_theme_auto.isChecked():
            return True
        return self.chk_auto_dark.isChecked()

    def _upscale_enabled(self) -> bool:
        return self.chk_upscale.isChecked()