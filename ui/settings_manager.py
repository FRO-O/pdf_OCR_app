"""
Управление сохранением настроек между запусками через QSettings.

Что сохраняем:
- Геометрия окна (позиция, размер).
- Последняя активная вкладка.
- Настройки обработки: языки, GPU, пресет, слайдеры, чекбоксы.
- Последние пути к файлам (файл, папка, выходной файл).

Что НЕ сохраняем:
- Содержимое логов.
- Выбранный OCR-движок, если он не установлен.
- Временные состояния (running/stopped).

Ключи хранятся с префиксом ("ui/", "ocr/", "export/"), чтобы
в реестре/на диске они были структурированы.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from PyQt6.QtCore import QByteArray, QSettings
from PyQt6.QtWidgets import QMainWindow, QWidget


logger = logging.getLogger(__name__)


# Идентификатор приложения для QSettings.
# В Windows это попадёт в HKEY_CURRENT_USER\Software\PDFOCRApp\PDFOCRApp.
# В Linux — в ~/.config/PDFOCRApp/PDFOCRApp.conf.
ORG_NAME = "PDFOCRApp"
APP_NAME = "PDFOCRApp"


class SettingsManager:
    """Обёртка над QSettings с типизированными get/set."""

    def __init__(self):
        self._s = QSettings(ORG_NAME, APP_NAME)

    # ------------------------------------------------------------------
    # Низкоуровневые операции (с типами)
    # ------------------------------------------------------------------

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self._s.value(key, default)
        # QSettings может вернуть строку ("true"/"false") на некоторых ОС
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v)

    def set_bool(self, key: str, value: bool) -> None:
        self._s.setValue(key, bool(value))

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._s.value(key, default))
        except (TypeError, ValueError):
            return default

    def set_int(self, key: str, value: int) -> None:
        self._s.setValue(key, int(value))

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self._s.value(key, default))
        except (TypeError, ValueError):
            return default

    def set_float(self, key: str, value: float) -> None:
        self._s.setValue(key, float(value))

    def get_str(self, key: str, default: str = "") -> str:
        v = self._s.value(key, default)
        return str(v) if v is not None else default

    def set_str(self, key: str, value: str) -> None:
        self._s.setValue(key, str(value))

    def get_list(self, key: str, default: Optional[list] = None) -> list:
        """
        Список строк. QSettings на разных ОС может вернуть list,
        строку или одиночное значение — нормализуем.
        """
        v = self._s.value(key, None)
        if v is None:
            return list(default) if default else []
        if isinstance(v, list):
            return [str(item) for item in v]
        if isinstance(v, str):
            # Если в строке есть запятые — считаем, что это список
            if "," in v:
                return [s.strip() for s in v.split(",") if s.strip()]
            return [v] if v else []
        return [str(v)]

    def set_list(self, key: str, value: list) -> None:
        self._s.setValue(key, [str(item) for item in value])

    # ------------------------------------------------------------------
    # Геометрия окна
    # ------------------------------------------------------------------

    def save_window_state(self, window: QMainWindow) -> None:
        try:
            self._s.setValue("ui/window_geometry", window.saveGeometry())
            self._s.setValue("ui/window_state", window.saveState())
        except Exception as e:
            logger.debug("Не удалось сохранить геометрию окна: %s", e)

    def restore_window_state(self, window: QMainWindow) -> bool:
        """
        Возвращает True, если геометрия была восстановлена.
        """
        geom = self._s.value("ui/window_geometry")
        if geom is None:
            return False
        try:
            window.restoreGeometry(geom)
            state = self._s.value("ui/window_state")
            if state is not None:
                window.restoreState(state)
            return True
        except Exception as e:
            logger.debug("Не удалось восстановить геометрию: %s", e)
            return False

    # ------------------------------------------------------------------
    # Очистка
    # ------------------------------------------------------------------

    def clear_all(self) -> None:
        """Полный сброс всех сохранённых настроек."""
        self._s.clear()
        self._s.sync()

    def sync(self) -> None:
        """Форсирует запись на диск (иногда полезно перед закрытием)."""
        self._s.sync()