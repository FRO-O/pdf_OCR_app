"""
Сборка PageData из загруженного JSON.

Логика:
1. Загружаем JSON (координаты там — в pt).
2. Если есть исходный файл (PNG/PDF) — используем его как фон,
   а координаты пересчитываем из pt в пиксели растра.
3. Если исходного файла нет — создаём белый лист,
   где 1 pt = 1 px (scale_x = scale_y = 1.0).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PIL import Image

from core.image_loader import is_image_file, load_image
from core.page import PageData, Paragraph
from core.pdf_loader import is_pdf_file, load_pdf

from .json_io import TranslationData, translation_to_paragraphs


logger = logging.getLogger(__name__)


BLANK_COLOR = (255, 255, 255)


def build_pages_from_translation(
    data: TranslationData,
    source_path: Optional[str] = None,
    background_white: bool = False,
) -> list[PageData]:
    """
    Собирает PageData для экспорта с переводом.
    """
    paragraphs_by_page = translation_to_paragraphs(
        data, use_translation=True
    )

    source_pages: dict[int, PageData] = {}

    if source_path and not background_white and os.path.exists(source_path):
        try:
            if is_pdf_file(source_path):
                pages = load_pdf(
                    source_path,
                    page_indices=None,
                    extract_vector_text=False,
                )
                for p in pages:
                    source_pages[p.page_num] = p
            elif is_image_file(source_path):
                page = load_image(source_path)
                if page is not None:
                    source_pages[page.page_num] = page
        except Exception as e:
            logger.exception(
                "Не удалось загрузить фон из %s: %s", source_path, e
            )

    result: list[PageData] = []

    for page_json in data.pages:
        page_num = page_json.page
        paragraphs_pt = paragraphs_by_page.get(page_num, [])

        if page_num in source_pages:
            src = source_pages[page_num]
            converted = _convert_pt_to_pixels(paragraphs_pt, src)
            src.paragraphs = converted
            result.append(src)
        else:
            page = _make_blank_page(
                page_num=page_num,
                width_pt=page_json.width_pt,
                height_pt=page_json.height_pt,
                paragraphs=paragraphs_pt,
                source_path=source_path or "",
            )
            result.append(page)

    logger.info(
        "Собрано страниц для экспорта с переводом: %d", len(result)
    )
    return result


def _convert_pt_to_pixels(
    paragraphs_pt: list[Paragraph],
    page: PageData,
) -> list[Paragraph]:
    """
    Пересчитывает координаты Paragraph из pt (JSON) в пиксели растра.

    font_size_pt НЕ пересчитывается — он в pt, так и должен быть.
    """
    if page.img_w_px <= 0 or page.page_w_pt <= 0:
        return paragraphs_pt

    inv_scale_x = page.img_w_px / page.page_w_pt
    inv_scale_y = page.img_h_px / page.page_h_pt

    result: list[Paragraph] = []
    for p in paragraphs_pt:
        result.append(Paragraph(
            x1=p.x1 * inv_scale_x,
            y1=p.y1 * inv_scale_y,
            x2=p.x2 * inv_scale_x,
            y2=p.y2 * inv_scale_y,
            text=p.text,
            angle=p.angle,
            is_vector=p.is_vector,
            font_size_pt=p.font_size_pt,
            confidence=p.confidence,
        ))
    return result


def _make_blank_page(
    page_num: int,
    width_pt: float,
    height_pt: float,
    paragraphs: list[Paragraph],
    source_path: str = "",
) -> PageData:
    """Создаёт PageData с белым фоном."""
    w_px = max(1, int(round(width_pt)))
    h_px = max(1, int(round(height_pt)))

    img = Image.new("RGB", (w_px, h_px), BLANK_COLOR)

    return PageData(
        page_num=page_num,
        image=img,
        img_w_px=w_px,
        img_h_px=h_px,
        page_w_pt=width_pt,
        page_h_pt=height_pt,
        dpi=72.0,
        source_path=source_path,
        source_type="image",
        paragraphs=paragraphs,
    )