"""
Экспорт и импорт JSON со структурой текста для перевода.

Публичные функции:
    export_translation_json(pages, source_path, ...) -> str
    load_translation_json(path) -> TranslationData

Формат JSON:
{
  "version": "1.0",
  "generator": "...",
  "source_file": "...",
  "target_export": "PPTX",
  "profile": "ui",
  "languages": ["en", "ru"],
  "font_scale": 0.75,
  "page_size_pt": [w, h],
  "pages": [
    {
      "page": 1,
      "width_pt": w,
      "height_pt": h,
      "items": [
        {
          "id": 1,
          "text": "File",
          "translation": "",
          "bbox_pt": [x1, y1, x2, y2],
          "angle": 0,
          "is_vector": false,
          "confidence": 0.96,
          "font_size_pt": 10.42
        }
      ]
    }
  ]
}

Ключевое: font_size_pt — это БАЗОВЫЙ размер шрифта
(без умножения на font_scale). При импорте compute_font_size
умножит его на font_scale — так же, как в первом запуске.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from core.page import PageData, Paragraph


logger = logging.getLogger(__name__)


JSON_FORMAT_VERSION = "1.0"
GENERATOR_NAME = "PDF/Image OCR → Office v2.0"


# ---------------------------------------------------------------------------
# Датаклассы
# ---------------------------------------------------------------------------

@dataclass
class TranslationItem:
    """Один фрагмент с переводом."""
    id: int
    text: str
    translation: str = ""
    bbox_pt: list[float] = field(default_factory=list)
    angle: int = 0
    is_vector: bool = False
    confidence: float = 1.0
    font_size_pt: Optional[float] = None

    @property
    def has_translation(self) -> bool:
        return bool(self.translation.strip())

    @property
    def effective_text(self) -> str:
        return self.translation.strip() if self.has_translation else self.text


@dataclass
class TranslationPage:
    page: int
    width_pt: float
    height_pt: float
    items: list[TranslationItem] = field(default_factory=list)


@dataclass
class TranslationData:
    version: str = JSON_FORMAT_VERSION
    generator: str = GENERATOR_NAME
    source_file: str = ""
    target_export: str = "PPTX"
    profile: str = "drawing"
    languages: list[str] = field(default_factory=list)
    font_scale: float = 0.75
    page_size_pt: list[float] = field(default_factory=list)
    pages: list[TranslationPage] = field(default_factory=list)

    def all_items(self) -> list[TranslationItem]:
        result = []
        for p in self.pages:
            result.extend(p.items)
        return result

    def stats(self) -> dict[str, int]:
        items = self.all_items()
        translated = sum(1 for it in items if it.has_translation)
        return {
            "total": len(items),
            "translated": translated,
            "untranslated": len(items) - translated,
        }


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------

def export_translation_json(
    pages: list[PageData],
    source_path: str,
    target_app: str = "PPTX",
    profile: str = "drawing",
    languages: Optional[list[str]] = None,
    font_scale: float = 0.75,
    output_path: Optional[str] = None,
) -> str:
    """
    Сохраняет JSON со всеми текстовыми фрагментами для перевода.
    """
    if not pages:
        raise ValueError("Нет страниц для экспорта JSON.")

    if output_path is None:
        base, _ = os.path.splitext(source_path)
        output_path = f"{base}_translate.json"

    first = pages[0]

    data = {
        "version": JSON_FORMAT_VERSION,
        "generator": GENERATOR_NAME,
        "source_file": os.path.basename(source_path),
        "target_export": target_app,
        "profile": profile,
        "languages": list(languages) if languages else [],
        "font_scale": round(float(font_scale), 3),
        "page_size_pt": [round(first.page_w_pt, 2), round(first.page_h_pt, 2)],
        "pages": [],
    }

    item_id = 0

    for page in pages:
        page_items = []
        scale_x = page.scale_x
        scale_y = page.scale_y

        for p in page.paragraphs:
            item_id += 1

            bbox_pt = [
                round(p.x1 * scale_x, 2),
                round(p.y1 * scale_y, 2),
                round(p.x2 * scale_x, 2),
                round(p.y2 * scale_y, 2),
            ]

            # Базовый размер шрифта (без font_scale).
            # - Для векторного текста — реальный размер из PDF.
            # - Для OCR — оценка из высоты bbox: h_pt / 1.2
            #   (та же формула, что в compute_font_size,
            #    но БЕЗ умножения на font_scale).
            if p.is_vector and p.font_size_pt:
                base_font_size = round(float(p.font_size_pt), 2)
            else:
                h_pt = p.h * page.scale_y
                if h_pt > 0:
                    base_font_size = round(h_pt / 1.2, 2)
                else:
                    base_font_size = None

            page_items.append({
                "id": item_id,
                "text": p.text,
                "translation": "",
                "bbox_pt": bbox_pt,
                "angle": int(p.angle),
                "is_vector": bool(p.is_vector),
                "confidence": round(float(p.confidence), 3),
                "font_size_pt": base_font_size,
            })

        data["pages"].append({
            "page": page.page_num,
            "width_pt": round(page.page_w_pt, 2),
            "height_pt": round(page.page_h_pt, 2),
            "items": page_items,
        })

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"Не удалось сохранить JSON: {e}") from e

    total_items = sum(len(p["items"]) for p in data["pages"])
    logger.info(
        "JSON для перевода сохранён: %s (%d страниц, %d фрагментов)",
        output_path, len(data["pages"]), total_items,
    )
    return output_path


# ---------------------------------------------------------------------------
# Импорт
# ---------------------------------------------------------------------------

def load_translation_json(path: str) -> TranslationData:
    """Загружает JSON и возвращает TranslationData."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"JSON не найден: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Некорректный JSON: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Не удалось прочитать JSON: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError("Корень JSON должен быть объектом.")

    data = TranslationData(
        version=raw.get("version", JSON_FORMAT_VERSION),
        generator=raw.get("generator", GENERATOR_NAME),
        source_file=raw.get("source_file", ""),
        target_export=raw.get("target_export", "PPTX"),
        profile=raw.get("profile", "drawing"),
        languages=list(raw.get("languages") or []),
        font_scale=float(raw.get("font_scale", 0.75)),
        page_size_pt=list(raw.get("page_size_pt") or []),
    )

    pages_raw = raw.get("pages")
    if not isinstance(pages_raw, list):
        raise ValueError("Поле 'pages' отсутствует или не список.")

    for page_raw in pages_raw:
        if not isinstance(page_raw, dict):
            continue

        page_obj = TranslationPage(
            page=int(page_raw.get("page", 1)),
            width_pt=float(page_raw.get("width_pt", 0.0)),
            height_pt=float(page_raw.get("height_pt", 0.0)),
        )

        for item_raw in page_raw.get("items", []):
            if not isinstance(item_raw, dict):
                continue

            try:
                bbox = [float(x) for x in item_raw.get("bbox_pt", [])]
            except (TypeError, ValueError):
                bbox = []

            if len(bbox) != 4:
                continue

            item = TranslationItem(
                id=int(item_raw.get("id", 0)),
                text=str(item_raw.get("text", "")),
                translation=str(item_raw.get("translation", "")),
                bbox_pt=bbox,
                angle=int(item_raw.get("angle", 0)),
                is_vector=bool(item_raw.get("is_vector", False)),
                confidence=float(item_raw.get("confidence", 1.0)),
                font_size_pt=(
                    float(item_raw["font_size_pt"])
                    if item_raw.get("font_size_pt") is not None
                    else None
                ),
            )
            page_obj.items.append(item)

        data.pages.append(page_obj)

    logger.info(
        "JSON загружен: %s (%d страниц, %d фрагментов)",
        path, len(data.pages), len(data.all_items()),
    )
    return data


# ---------------------------------------------------------------------------
# Конвертация: JSON → Paragraph
# ---------------------------------------------------------------------------

def translation_to_paragraphs(
    data: TranslationData,
    use_translation: bool = True,
) -> dict[int, list[Paragraph]]:
    """
    Превращает JSON в словарь {page_num: [Paragraph, ...]}.

    Координаты в Paragraph — В ПУНКТАХ (не в пикселях).
    Дальнейший пересчёт делает replacer._convert_pt_to_pixels,
    если используется исходный фон.
    """
    result: dict[int, list[Paragraph]] = {}

    for page in data.pages:
        paragraphs: list[Paragraph] = []
        for item in page.items:
            text = item.effective_text if use_translation else item.text
            if not text.strip():
                continue

            x1, y1, x2, y2 = item.bbox_pt
            paragraphs.append(Paragraph(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                text=text,
                angle=item.angle,
                is_vector=item.is_vector,
                font_size_pt=item.font_size_pt,
                confidence=item.confidence,
            ))
        result[page.page] = paragraphs

    return result