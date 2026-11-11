"""
Базовый класс для всех экспортёров.
"""

from __future__ import annotations

import logging
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.page import PageData, Paragraph


logger = logging.getLogger(__name__)


@dataclass
class ExportOptions:
    """Общие настройки экспорта."""
    font_scale: float = 0.75
    hide_orig_text: bool = True
    min_font_size: float = 4.0
    max_font_size: float = 140.0
    output_path: Optional[str] = None
    fit_to_bbox: bool = False
    log_fn: Optional[Callable[[str], None]] = None

    def log(self, message: str) -> None:
        if self.log_fn is not None:
            self.log_fn(message)
        else:
            logger.info(message)


class BaseExporter(ABC):
    """Базовый класс экспортёра."""

    @property
    @abstractmethod
    def file_extension(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def export(
        self,
        source_path: str,
        pages: list[PageData],
        options: ExportOptions,
    ) -> str:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def default_output_path(
        self,
        source_path: str,
        suffix: str = "_vector",
    ) -> str:
        base, _ = os.path.splitext(source_path)
        return f"{base}{suffix}{self.file_extension}"

    @staticmethod
    def compute_font_size(
        paragraph: Paragraph,
        page: PageData,
        font_scale: float,
        min_size: float,
        max_size: float,
    ) -> float:
        """
        Вычисляет размер шрифта для фрагмента текста.

        Логика:
        - Если font_size_pt задан (векторный текст из PDF
          ИЛИ OCR-текст, импортированный из JSON) — используем
          его напрямую, умноженный на font_scale.
        - Если font_size_pt = None (свежий OCR) — оцениваем размер
          из высоты bbox: h_pt / 1.2 * font_scale.

        Результат зажимается в [min_size, max_size].
        """
        if paragraph.font_size_pt:
            size = paragraph.font_size_pt * font_scale
        else:
            h_pt = paragraph.h * page.scale_y
            if h_pt <= 0:
                return min_size
            size = (h_pt / 1.2) * font_scale

        size = max(min_size, min(size, max_size))
        return float(size)

    @staticmethod
    def safe_remove(path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.debug("Не удалось удалить %s: %s", path, e)

    @staticmethod
    def temp_file(suffix: str = ".png") -> str:
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="pdf_ocr_")
        os.close(fd)
        return path