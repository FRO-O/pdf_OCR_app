"""
Загрузка PDF: рендер страниц + извлечение векторного текста.

Возвращает список PageData, готовых к pipeline.

Ключевые моменты:
- Рендер в высоком DPI (300) — стабильнее для OCR и не теряет мелкий текст.
- Векторный текст извлекается через page.get_text("dict"),
  координаты сразу переводятся в пиксели растра.
- Поворот строк определяется по вектору направления (line["dir"]);
  квантуется до 0/90/180/270.
- Вертикальные цепочки (поворот 90/270) сливаются в одну строку
  с адаптивными порогами: параметры зависят от размера шрифта,
  а не от магических чисел.

Единицы измерения:
- Внутри PageData/Paragraph — пиксели растра.
- Размер шрифта (font_size_pt) — в pt (как в PDF), НЕ пересчитывается.
  При экспорте он умножается на font_scale_mult из настроек.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

from .page import PageData, Paragraph


logger = logging.getLogger(__name__)


# DPI рендера. 300 — золотая середина: векторный PDF всё равно рендерится
# в растр, а OCR по 300 DPI даёт заметно лучший результат, чем 150 или 200.
DEFAULT_RENDER_DPI = 300.0


# Порог вертикального слияния для повёрнутого текста.
# Умножается на высоту строки в пикселях, то есть адаптивно.
VERTICAL_MERGE_Y_FACTOR = 1.2   # расстояние между строками в цепочке
VERTICAL_MERGE_X_FACTOR = 0.5   # допуск по X для принадлежности к одной цепочке


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def is_pdf_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".pdf"


def get_pdf_page_count(path: str) -> int:
    """Количество страниц в PDF (для валидации пользовательского ввода)."""
    try:
        with fitz.open(path) as doc:
            return len(doc)
    except Exception:
        return 0


def load_pdf(
    path: str,
    page_indices: Optional[list[int]] = None,
    render_dpi: float = DEFAULT_RENDER_DPI,
    extract_vector_text: bool = True,
) -> list[PageData]:
    """
    Загружает PDF и возвращает список PageData.

    Args:
        path: путь к PDF.
        page_indices: список 0-based индексов страниц. None = все.
        render_dpi: DPI рендера (по умолчанию 300).
        extract_vector_text: извлекать ли векторный текст.

    Returns:
        Список PageData. Пустой, если PDF не открылся.
    """
    if not os.path.exists(path):
        logger.error("PDF не найден: %s", path)
        return []

    try:
        doc = fitz.open(path)
    except Exception as e:
        logger.exception("Ошибка открытия PDF %s: %s", path, e)
        return []

    try:
        total = len(doc)
        if page_indices is None:
            page_indices = list(range(total))
        else:
            page_indices = [i for i in page_indices if 0 <= i < total]

        pages: list[PageData] = []
        for idx in page_indices:
            page = _load_single_page(
                doc, idx, path, render_dpi, extract_vector_text
            )
            if page is not None:
                pages.append(page)

        logger.info(
            "PDF загружен: %s (%d/%d страниц)",
            os.path.basename(path), len(pages), total,
        )
        return pages

    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Одна страница
# ---------------------------------------------------------------------------

def _load_single_page(
    doc: "fitz.Document",
    page_idx: int,
    source_path: str,
    render_dpi: float,
    extract_vector: bool,
) -> Optional[PageData]:
    """Рендерит и парсит одну страницу."""
    try:
        page = doc[page_idx]
    except Exception as e:
        logger.error("Не удалось получить страницу %d: %s", page_idx, e)
        return None

    # Реальный размер страницы в pt
    rect = page.rect
    page_w_pt = rect.width
    page_h_pt = rect.height

    # Рендер в растр
    try:
        zoom = render_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        # clip=rect — заставляем PyMuPDF рендерить страницу целиком,
        # включая поля (без этого могут быть обрезаны края).
        pix = page.get_pixmap(matrix=mat, clip=rect)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    except Exception as e:
        logger.exception("Ошибка рендера страницы %d: %s", page_idx, e)
        return None

    page_data = PageData(
        page_num=page_idx + 1,
        image=img,
        img_w_px=pix.width,
        img_h_px=pix.height,
        page_w_pt=page_w_pt,
        page_h_pt=page_h_pt,
        dpi=render_dpi,
        source_path=os.path.abspath(source_path),
        source_type="pdf",
    )

    # Векторный текст
    if extract_vector:
        try:
            paragraphs = extract_vector_paragraphs(
                page, pix.width, pix.height
            )
            page_data.vector_paragraphs = paragraphs
            if paragraphs:
                logger.debug(
                    "Страница %d: найдено %d векторных надписей",
                    page_idx + 1, len(paragraphs),
                )
        except Exception as e:
            logger.exception(
                "Ошибка извлечения векторного текста со страницы %d: %s",
                page_idx + 1, e,
            )

    return page_data


# ---------------------------------------------------------------------------
# Извлечение векторного текста
# ---------------------------------------------------------------------------

def extract_vector_paragraphs(
    page: "fitz.Page",
    img_w_px: int,
    img_h_px: int,
) -> list[Paragraph]:
    """
    Извлекает векторный текст со страницы PDF.

    Возвращает список Paragraph в системе координат растра
    (то есть x1/y1/x2/y2 — в пикселях изображения img_w_px × img_h_px).
    """
    rect = page.rect
    scale_x = img_w_px / rect.width if rect.width else 1.0
    scale_y = img_h_px / rect.height if rect.height else 1.0

    try:
        blocks = page.get_text("dict")["blocks"]
    except Exception as e:
        logger.error("get_text('dict') упал: %s", e)
        return []

    raw: list[dict] = []

    for block in blocks:
        if block.get("type") != 0:
            # type != 0 — это картинки, не текст
            continue
        for line in block.get("lines", []):
            parsed = _parse_line(line, scale_x, scale_y)
            if parsed is not None:
                raw.append(parsed)

    if not raw:
        return []

    # Сливаем вертикальные цепочки (поворот 90/270)
    merged = _merge_vertical_chains(raw)

    # Преобразуем словари в Paragraph
    paragraphs: list[Paragraph] = []
    for m in merged:
        text = (m["text"] or "").strip()
        if not text:
            continue

        paragraphs.append(Paragraph(
            x1=m["x1"],
            y1=m["y1"],
            x2=m["x2"],
            y2=m["y2"],
            text=text,
            angle=m["angle"],
            is_vector=True,
            font_size_pt=m["font_size_pt"],
            confidence=1.0,
        ))

    return paragraphs


# ---------------------------------------------------------------------------
# Парсинг одной строки PDF
# ---------------------------------------------------------------------------

def _parse_line(
    line: dict,
    scale_x: float,
    scale_y: float,
) -> Optional[dict]:
    """
    Преобразует 'line' из page.get_text('dict') в промежуточный словарь
    с координатами в пикселях растра и определённым углом.
    """
    spans = line.get("spans", [])
    if not spans:
        return None

    text = "".join(span.get("text", "") for span in spans).strip()
    if not text:
        return None

    bbox = line.get("bbox")  # [x0, y0, x1, y1] в pt
    if not bbox or len(bbox) != 4:
        return None

    # Определяем угол по направлению строки
    dx, dy = line.get("dir", (1.0, 0.0))
    angle = _quantize_angle(dx, dy)

    # Размер шрифта — берём из первого span
    font_size = float(spans[0].get("size", 8.0))

    return {
        "x1": float(bbox[0]) * scale_x,
        "y1": float(bbox[1]) * scale_y,
        "x2": float(bbox[2]) * scale_x,
        "y2": float(bbox[3]) * scale_y,
        "text": text,
        "font_size_pt": font_size,
        "angle": angle,
    }


def _quantize_angle(dx: float, dy: float) -> int:
    """
    Квантует направление строки до 0/90/180/270.

    В PDF Y растёт вниз, поэтому atan2(-dy, dx) даёт
    математический угол (против часовой стрелки).
    """
    if dx == 0 and dy == 0:
        return 0
    angle_deg = round(math.degrees(math.atan2(-dy, dx))) % 360

    if 45 <= angle_deg < 135:
        return 90
    if 135 <= angle_deg < 225:
        return 180
    if 225 <= angle_deg < 315:
        return 270
    return 0


# ---------------------------------------------------------------------------
# Слияние вертикальных цепочек
# ---------------------------------------------------------------------------

def _merge_vertical_chains(items: list[dict]) -> list[dict]:
    """
    Сливает фрагменты текста, идущие вертикальной цепочкой.

    Это нужно для повёрнутых надписей (угол 90/270): каждая буква
    или слово приходит отдельной строкой, а нам нужен единый фрагмент.

    Условия слияния:
    - Одинаковый angle (оба 90 или оба 270).
    - Разница по X (или Y) меньше, чем адаптивный порог,
      вычисленный от средней высоты строки в цепочке.
    - Промежуток между ними не превышает VERTICAL_MERGE_Y_FACTOR * высоты.

    Горизонтальные строки (angle=0/180) не сливаются — они и так
    корректно приходят из PDF.
    """
    # Разделяем по углу: горизонтальные оставляем как есть,
    # вертикальные обрабатываем отдельно.
    horizontal = [it for it in items if it["angle"] in (0, 180)]
    vertical = [it for it in items if it["angle"] in (90, 270)]

    if not vertical:
        return horizontal

    # Сортируем вертикальные по X, потом по Y —
    # чтобы цепочки шли подряд.
    vertical.sort(key=lambda it: (round(it["x1"], 1), it["y1"]))

    merged: list[dict] = []
    used = [False] * len(vertical)

    for i, item in enumerate(vertical):
        if used[i]:
            continue
        used[i] = True
        chain = [item]

        # Ищем все последующие фрагменты, которые продолжают эту цепочку
        for j in range(i + 1, len(vertical)):
            if used[j]:
                continue
            candidate = vertical[j]

            # Проверяем, что та же цепочка по X
            chain_h = _avg_height(chain)
            if abs(candidate["x1"] - chain[0]["x1"]) > chain_h * VERTICAL_MERGE_X_FACTOR:
                continue

            # Проверяем, что близко по Y к последнему элементу
            last = chain[-1]
            gap = candidate["y1"] - last["y2"]
            if gap < 0:
                gap = last["y1"] - candidate["y2"]
            if gap > chain_h * VERTICAL_MERGE_Y_FACTOR:
                continue

            # Проверяем, что тот же угол
            if candidate["angle"] != chain[0]["angle"]:
                continue

            chain.append(candidate)
            used[j] = True

        merged.append(_combine_chain(chain))

    # Горизонтальные + объединённые вертикальные
    result = horizontal + merged
    return result


def _avg_height(chain: list[dict]) -> float:
    if not chain:
        return 1.0
    hs = [abs(it["y2"] - it["y1"]) for it in chain if abs(it["y2"] - it["y1"]) > 0]
    return sum(hs) / len(hs) if hs else 1.0


def _combine_chain(chain: list[dict]) -> dict:
    """Объединяет элементы цепочки в один словарь."""
    if len(chain) == 1:
        return chain[0].copy()

    # Сортируем по возрастанию Y (сверху вниз)
    # Для угла 270 текст читается снизу вверх, для 90 — сверху вниз.
    chain = sorted(chain, key=lambda it: it["y1"])

    x1 = min(it["x1"] for it in chain)
    y1 = min(it["y1"] for it in chain)
    x2 = max(it["x2"] for it in chain)
    y2 = max(it["y2"] for it in chain)

    # Собираем текст в правильном порядке
    angle = chain[0]["angle"]
    if angle == 270:
        # 270° — обычно текст, читаемый снизу вверх, значит
        # при сортировке по Y сверху вниз он идёт в обратном порядке.
        texts = [it["text"] for it in reversed(chain)]
    else:
        texts = [it["text"] for it in chain]

    combined_text = " ".join(texts)

    return {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "text": combined_text,
        "font_size_pt": chain[0]["font_size_pt"],
        "angle": angle,
    }