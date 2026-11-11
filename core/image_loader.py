"""
Загрузка растровых изображений (PNG, JPG, BMP, TIFF).

Возвращает PageData, готовый к препроцессингу и OCR.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PIL import Image

from .page import PageData


logger = logging.getLogger(__name__)


# DPI по умолчанию для изображений без метаданных.
# 96 — стандарт для Windows-скриншотов.
DEFAULT_IMAGE_DPI = 96.0


SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp",
}


def is_image_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


def load_image(path: str) -> Optional[PageData]:
    """
    Загружает изображение и возвращает PageData.
    """
    if not os.path.exists(path):
        logger.error("Файл не найден: %s", path)
        return None

    if not is_image_file(path):
        logger.error("Не поддерживаемое расширение: %s", path)
        return None

    try:
        img = Image.open(path)
        img.load()
    except Exception as e:
        logger.exception("Ошибка открытия изображения %s: %s", path, e)
        return None

    if img.mode != "RGB":
        img = img.convert("RGB")

    w_px, h_px = img.size

    dpi = _extract_dpi(img)
    if dpi is None:
        dpi = DEFAULT_IMAGE_DPI

    # pt = px * 72 / dpi
    w_pt = w_px * 72.0 / dpi
    h_pt = h_px * 72.0 / dpi

    page = PageData(
        page_num=1,
        image=img,
        img_w_px=w_px,
        img_h_px=h_px,
        page_w_pt=w_pt,
        page_h_pt=h_pt,
        dpi=dpi,
        source_path=os.path.abspath(path),
        source_type="image",
    )

    logger.info(
        "Изображение загружено: %s (%dx%d px, %.1f DPI, %.1fx%.1f pt)",
        os.path.basename(path), w_px, h_px, dpi, w_pt, h_pt,
    )
    return page


def _extract_dpi(img: Image.Image) -> Optional[float]:
    """Достаёт DPI из метаданных PIL."""
    try:
        dpi_info = img.info.get("dpi")
        if not dpi_info:
            return None
        if isinstance(dpi_info, tuple) and len(dpi_info) >= 2:
            x, y = float(dpi_info[0]), float(dpi_info[1])
            if x <= 0 or y <= 0:
                return None
            return x if abs(x - y) < 1 else (x + y) / 2
        return float(dpi_info)
    except Exception:
        return None


def load_images_from_folder(folder: str) -> list[PageData]:
    """
    Загружает все изображения из папки (не рекурсивно).
    Для будущего пакетного режима.
    """
    if not os.path.isdir(folder):
        return []

    files = sorted(
        f for f in os.listdir(folder)
        if is_image_file(os.path.join(folder, f))
    )

    pages: list[PageData] = []
    for idx, fname in enumerate(files, start=1):
        full = os.path.join(folder, fname)
        page = load_image(full)
        if page is not None:
            page.page_num = idx
            pages.append(page)

    logger.info("Из папки загружено %d изображений", len(pages))
    return pages