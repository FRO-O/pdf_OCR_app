"""
Вкладка «Чертежи».
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QCheckBox, QLabel,
)
from app.pipeline import ProcessProfile, PipelineConfig
from ui.tabs.base_tab import BaseTab

DRAWING_PRESETS: dict[str, tuple] = {
    "тонкий чертёж":             (2.0,  0.45, 0.15, 0.35, False),
    "тонкий чертёж с таблицами": (2.0,  0.45, 0.15, 0.15, True),
    "чертёж":                    (1.75, 0.50, 0.20, 0.40, False),
    "чертёж с таблицами":        (1.75, 0.50, 0.20, 0.15, True),
    "схема":                     (1.5,  0.40, 0.20, 0.30, False),
    "схема с таблицами":         (1.5,  0.40, 0.20, 0.15, True),
    "текст":                     (1.0,  0.70, 0.40, 0.60, False),
    "текст с таблицами":         (1.25, 0.65, 0.35, 0.15, True),
    "сложный макет":             (1.75, 0.50, 0.25, 0.35, False),
}

DEFAULT_PRESET = "чертёж"

class DrawingsTab(BaseTab):
    def __init__(self, parent=None):
        self._current_profile = ProcessProfile.DRAWING
        super().__init__(parent)

    def _add_specific_groups(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Источник текста")
        self.chk_prefer_pdf_text = QCheckBox("Извлекать векторный текст из PDF (с компенсацией поворота)")
        self.chk_prefer_pdf_text.setChecked(True)
        self.chk_prefer_pdf_text.setStyleSheet("font-weight: bold; color: #27ae60;")
        vbox.addWidget(self.chk_prefer_pdf_text)
        parent_layout.addWidget(group)

    def _add_processing_checkboxes(self, parent_layout: QVBoxLayout) -> None:
        group, vbox = self._make_group("Настройки обработки")
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(2)

        self.chk_invert = QCheckBox("Распознавать белый текст на тёмном фоне")
        self.chk_auto_dark = QCheckBox("Автоопределение тёмной темы")
        self.chk_table_mode = QCheckBox("Строгий режим таблиц")
        self.chk_upscale = QCheckBox("Увеличивать мелкий текст")
        
        self.chk_filter_noise = QCheckBox("Фильтровать мусор (мелкие боксы)")
        self.chk_filter_noise.setToolTip("Отбрасывать одиночные мусорные символы и слишком вытянутые боксы.")

        # Новая галочка — по умолчанию ВЫКЛ
        self.chk_binarize = QCheckBox("Бинаризация (ч/б для цветных схем)")
        self.chk_binarize.setToolTip("Переводит картинку в чёрно-белый вид. Улучшает распознавание цветных блок-схем.")

        grid.addWidget(self.chk_invert,        0, 0)
        grid.addWidget(self.chk_auto_dark,     0, 1)
        grid.addWidget(self.chk_table_mode,    1, 0)
        grid.addWidget(self.chk_upscale,       1, 1)
        grid.addWidget(self.chk_filter_noise,  2, 0)
        grid.addWidget(self.chk_binarize,      2, 1)
        vbox.addLayout(grid)
        parent_layout.addWidget(group)

    def _get_presets(self) -> dict[str, tuple]:
        return DRAWING_PRESETS

    def _get_default_preset(self) -> str:
        return DEFAULT_PRESET

    def _get_process_profile(self) -> str:
        return self._current_profile

    def _apply_preset(self, name: str, preset: tuple) -> None:
        mag, tt, lt, link, is_table = preset
        self.slider_mag.setValueSilent(mag)
        self.slider_text_thresh.setValueSilent(tt)
        self.slider_low_text.setValueSilent(lt)
        self.slider_link.setValueSilent(link)
        self.chk_table_mode.setChecked(is_table)
        
        # Переключаем профиль в зависимости от пресета
        if name.startswith("текст"):
            self._current_profile = ProcessProfile.DOCUMENT
        else:
            self._current_profile = ProcessProfile.DRAWING

    def _apply_extra_config(self, config: PipelineConfig) -> None:
        config.filter_noise = self.chk_filter_noise.isChecked()

    def _is_table_mode(self) -> bool:
        return self.chk_table_mode.isChecked()

    def _prefer_pdf_text(self) -> bool:
        return self.chk_prefer_pdf_text.isChecked()

    def _invert_enabled(self) -> bool:
        return self.chk_invert.isChecked()

    def _auto_dark_enabled(self) -> bool:
        return self.chk_auto_dark.isChecked()

    def _upscale_enabled(self) -> bool:
        return self.chk_upscale.isChecked()

    def _binarize_enabled(self) -> bool:
        return self.chk_binarize.isChecked()