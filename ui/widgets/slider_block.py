"""
Виджет «слайдер с заголовком и описанием».

Используется для всех числовых настроек OCR (mag_ratio, thresholds и т.п.).

Внешний вид:
    ┌──────────────────────────────────────┐
    │ Масштаб картинки (mag_ratio): 1.25   │
    │ [─────●──────────────]               │
    │ Увеличение изображения перед OCR.    │
    └──────────────────────────────────────┘

Наружу даёт:
    - value() / setValue()
    - сигнал valueChanged(float)
    - float-значения (внутри хранит int = float * step_factor)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
)


class SliderBlock(QWidget):
    """
    Слайдер с заголовком, значением и описанием.

    Параметры:
        title:       заголовок (HTML поддерживается).
        description: подпись под слайдером (HTML поддерживается).
        min_value:   минимальное значение (float).
        max_value:   максимальное значение (float).
        default:     значение по умолчанию.
        step:        шаг изменения (float, по умолчанию 0.05).
        decimals:    количество знаков после запятой.
    """

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        title: str,
        description: str = "",
        min_value: float = 0.0,
        max_value: float = 1.0,
        default: float = 0.5,
        step: float = 0.05,
        decimals: int = 2,
        parent: QWidget = None,
    ):
        super().__init__(parent)

        self._min = float(min_value)
        self._max = float(max_value)
        self._step = float(step)
        self._decimals = int(decimals)

        # Внутри QSlider хранит int. Определяем «множитель»:
        # 1.0 → 100 шагов на единицу (для decimals=2).
        # 0.05 → 20 шагов на единицу.
        # Считаем через decimals: factor = 10^decimals.
        self._factor = 10 ** self._decimals

        self._build_ui(title, description, default)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self, title: str, description: str, default: float) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(2)

        # Заголовок + значение
        header = QHBoxLayout()
        self._title_label = QLabel(f"<b>{title}</b>")
        self._value_label = QLabel(self._format_value(default))
        self._value_label.setStyleSheet(
            "color: #2b5b84; font-weight: bold;"
        )
        header.addWidget(self._title_label)
        header.addStretch()
        header.addWidget(self._value_label)
        layout.addLayout(header)

        # Слайдер
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(self._to_int(self._min))
        self._slider.setMaximum(self._to_int(self._max))
        self._slider.setValue(self._to_int(default))
        self._slider.setSingleStep(max(1, self._to_int(self._step)))
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider)

        # Описание
        if description:
            desc = QLabel(
                f"<span style='color:#666; font-size:11px;'>{description}</span>"
            )
            desc.setWordWrap(True)
            layout.addWidget(desc)

    # ------------------------------------------------------------------
    # Преобразования float ↔ int
    # ------------------------------------------------------------------

    def _to_int(self, value: float) -> int:
        return int(round(value * self._factor))

    def _to_float(self, value: int) -> float:
        return value / self._factor

    def _format_value(self, value: float) -> str:
        return f"{value:.{self._decimals}f}"

    # ------------------------------------------------------------------
    # Реакции
    # ------------------------------------------------------------------

    def _on_slider_changed(self, int_value: int) -> None:
        val = self._to_float(int_value)
        self._value_label.setText(self._format_value(val))
        self.valueChanged.emit(val)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def value(self) -> float:
        return self._to_float(self._slider.value())

    def setValue(self, value: float) -> None:
        """Программная установка значения. Не эмитит valueChanged,
        если значение не изменилось."""
        clamped = max(self._min, min(self._max, float(value)))
        self._slider.setValue(self._to_int(clamped))

    def setValueSilent(self, value: float) -> None:
        """
        Установить значение без эмита сигнала.
        Полезно при загрузке пресета: хотим обновить UI,
        но не триггерить реакцию «пользователь подвинул слайдер».
        """
        blocked = self._slider.blockSignals(True)
        try:
            clamped = max(self._min, min(self._max, float(value)))
            self._slider.setValue(self._to_int(clamped))
            self._value_label.setText(self._format_value(clamped))
        finally:
            self._slider.blockSignals(blocked)