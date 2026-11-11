"""
Слияние OCR-боксов и превращение их в Paragraph.
"""
from __future__ import annotations
import logging
from enum import Enum
from typing import Optional

from .ocr.base import OCRResult
from .page import Paragraph

logger = logging.getLogger(__name__)

class MergeProfile(str, Enum):
    DRAWING = "drawing"
    TABLE = "table"
    UI = "ui"
    DOCUMENT = "document" # Профиль для сплошного текста

DRAWING_Y_OVERLAP_FACTOR = 0.3
DRAWING_X_GAP_FACTOR = 3.0
UI_Y_OVERLAP_FACTOR = 0.15
UI_X_GAP_FACTOR = 1.2
UI_MIN_CONFIDENCE = 0.35
UI_MIN_HEIGHT_PX = 5.0
UI_MIN_WIDTH_PX = 3.0

GARBAGE_SINGLE_CHARS = set("|_-.,·•·[]{}()'\"`:;\\/<>=+*^~«»!?°")
SINGLE_CHAR_MAX_ASPECT_VERTICAL = 3.0
SINGLE_CHAR_MAX_ASPECT_HORIZONTAL = 8.0


def sort_paragraphs_reading_order(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Сортирует параграфы в порядке чтения (сверху вниз, слева направо)."""
    if not paragraphs:
        return []

    sorted_by_y = sorted(paragraphs, key=lambda p: p.cy)
    lines = []
    current_line = []
    
    for p in sorted_by_y:
        if not current_line:
            current_line.append(p)
        else:
            avg_cy = sum(item.cy for item in current_line) / len(current_line)
            avg_h = sum(item.h for item in current_line) / len(current_line)
            
            if abs(p.cy - avg_cy) < avg_h * 0.6:
                current_line.append(p)
            else:
                current_line.sort(key=lambda item: item.x1)
                lines.extend(current_line)
                current_line = [p]
    
    if current_line:
        current_line.sort(key=lambda item: item.x1)
        lines.extend(current_line)

    return lines


def group_lines_into_paragraphs(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """
    Объединяет отдельные строки в логические абзацы.
    Строка B приклеивается к строке A, если:
    - B находится прямо под A (расстояние меньше 1.2 высоты)
    - Они выровнены по левому краю (или сильно перекрываются)
    - Размер шрифта примерно одинаковый
    """
    if not paragraphs:
        return []
        
    paragraphs = sort_paragraphs_reading_order(paragraphs)
    merged = []
    current_group = []
    
    for p in paragraphs:
        if not current_group:
            current_group.append(p)
            continue
            
        prev = current_group[-1]
        avg_h = sum(item.h for item in current_group) / len(current_group)
        
        v_gap = p.y1 - prev.y2
        
        # Выравнивание по левому краю
        is_left_aligned = abs(p.x1 - current_group[0].x1) < avg_h * 1.5
        
        # Перекрытие по горизонтали
        overlap_x = min(p.x2, prev.x2) - max(p.x1, prev.x1)
        min_w = min(p.w, prev.w)
        is_overlapping = overlap_x > min_w * 0.4
        
        # Похожий размер шрифта
        similar_height = abs(p.h - avg_h) < avg_h * 0.3
        
        if -avg_h * 0.2 < v_gap < avg_h * 1.2 and (is_left_aligned or is_overlapping) and similar_height:
            current_group.append(p)
        else:
            merged.append(_combine_lines_to_paragraph(current_group))
            current_group = [p]
            
    if current_group:
        merged.append(_combine_lines_to_paragraph(current_group))
        
    return merged


def _combine_lines_to_paragraph(lines: list[Paragraph]) -> Paragraph:
    """Склеивает список строк в один Paragraph."""
    if len(lines) == 1:
        return lines[0]
        
    text = " ".join(line.text for line in lines)
    x1 = min(l.x1 for l in lines)
    y1 = min(l.y1 for l in lines)
    x2 = max(l.x2 for l in lines)
    y2 = max(l.y2 for l in lines)
    confidence = sum(l.confidence for l in lines) / len(lines)
    
    return Paragraph(
        x1=x1, y1=y1, x2=x2, y2=y2,
        text=text, angle=lines[0].angle, is_vector=lines[0].is_vector,
        font_size_pt=lines[0].font_size_pt, confidence=confidence,
        bg_color=lines[0].bg_color
    )


def ocr_results_to_paragraphs(
    results: list[OCRResult],
    profile: MergeProfile = MergeProfile.DRAWING,
    upscale_factor: float = 1.0,
    filter_noise: bool = False,
) -> list[Paragraph]:
    if not results:
        return []

    if upscale_factor > 1.0:
        results = _downscale_results(results, upscale_factor)

    if profile in (MergeProfile.UI, MergeProfile.DOCUMENT) or filter_noise:
        results = _filter_noise(results)

    if profile == MergeProfile.TABLE:
        merged = _no_merge(results)
    elif profile == MergeProfile.UI:
        merged = _merge_ui(results)
    elif profile == MergeProfile.DOCUMENT:
        merged = _merge_document(results)
    else:
        merged = _merge_drawing(results)

    paragraphs = [_result_to_paragraph(item) for item in merged]
    return sort_paragraphs_reading_order(paragraphs)


def _filter_noise(results: list[OCRResult]) -> list[OCRResult]:
    kept: list[OCRResult] = []
    for r in results:
        if r.confidence < UI_MIN_CONFIDENCE: continue
        if r.h < UI_MIN_HEIGHT_PX or r.w < UI_MIN_WIDTH_PX: continue

        text = r.text.strip()
        if not text: continue

        if len(text) == 1:
            if text in GARBAGE_SINGLE_CHARS: continue
            if r.h > 0 and r.w > 0:
                if (r.h / r.w) > SINGLE_CHAR_MAX_ASPECT_VERTICAL: continue
                if (r.w / r.h) > SINGLE_CHAR_MAX_ASPECT_HORIZONTAL: continue
            kept.append(r)
            continue

        if not any(c.isalnum() for c in text): continue
        kept.append(r)
    return kept

def _downscale_results(results: list[OCRResult], factor: float) -> list[OCRResult]:
    inv = 1.0 / factor
    out: list[OCRResult] = []
    for r in results:
        new_bbox = [[p[0] * inv, p[1] * inv] for p in r.bbox]
        out.append(OCRResult(bbox=new_bbox, text=r.text, confidence=r.confidence))
    return out

def _no_merge(results: list[OCRResult]) -> list[dict]:
    items = [_result_to_dict(r) for r in results]
    items.sort(key=lambda it: (round(it["y1"], 1), it["x1"]))
    return items

def _merge_drawing(results: list[OCRResult]) -> list[dict]:
    items = [_result_to_dict(r) for r in results]
    if not items: return []
    items.sort(key=lambda it: (it["y1"], it["x1"]))
    merged: list[dict] = []
    for box in items:
        placed = False
        for p in merged:
            avg_h = p["h_sum"] / p["count"]
            y_overlap = not (box["y2"] < p["y1"] - avg_h * DRAWING_Y_OVERLAP_FACTOR or box["y1"] > p["y2"] + avg_h * DRAWING_Y_OVERLAP_FACTOR)
            x_close = (box["x1"] >= p["x2"] and (box["x1"] - p["x2"]) < avg_h * DRAWING_X_GAP_FACTOR)
            if y_overlap and x_close:
                _append_to_merged(p, box)
                placed = True
                break
        if not placed: merged.append(_new_merged_entry(box))
    return merged

def _merge_ui(results: list[OCRResult]) -> list[dict]:
    items = [_result_to_dict(r) for r in results]
    if not items: return []
    items.sort(key=lambda it: (it["y1"], it["x1"]))
    merged: list[dict] = []
    for box in items:
        placed = False
        for p in merged:
            avg_h = p["h_sum"] / p["count"]
            overlap_h = min(box["y2"], p["y2"]) - max(box["y1"], p["y1"])
            y_overlap = overlap_h > avg_h * (1.0 - UI_Y_OVERLAP_FACTOR)
            x_gap = box["x1"] - p["x2"]
            x_close = 0 <= x_gap < avg_h * UI_X_GAP_FACTOR
            if y_overlap and x_close:
                _append_to_merged(p, box)
                placed = True
                break
        if not placed: merged.append(_new_merged_entry(box))
    return merged

def _merge_document(results: list[OCRResult]) -> list[dict]:
    """Специальный алгоритм для сплошного текста: склеивает строки в абзацы."""
    items = [_result_to_dict(r) for r in results]
    if not items: return []
    
    items.sort(key=lambda it: (it["y1"], it["x1"]))
    
    lines = []
    for box in items:
        placed = False
        for line in lines:
            avg_h = (line["y2"] - line["y1"] + box["y2"] - box["y1"]) / 2
            box_cy = (box["y1"] + box["y2"]) / 2
            line_cy = (line["y1"] + line["y2"]) / 2
            
            # Если центры по Y близко — это одна строка
            if abs(box_cy - line_cy) < avg_h * 0.6:
                line["text"] += " " + box["text"]
                line["x1"] = min(line["x1"], box["x1"])
                line["y1"] = min(line["y1"], box["y1"])
                line["x2"] = max(line["x2"], box["x2"])
                line["y2"] = max(line["y2"], box["y2"])
                line["confidence"] = (line["confidence"] + box["confidence"]) / 2
                placed = True
                break
        if not placed:
            lines.append(_new_merged_entry(box))
    
    lines.sort(key=lambda it: it["y1"])
    
    paragraphs = []
    current_para = []
    
    for line in lines:
        if not current_para:
            current_para.append(line)
        else:
            last_line = current_para[-1]
            avg_h = (last_line["y2"] - last_line["y1"] + line["y2"] - line["y1"]) / 2
            gap_y = line["y1"] - last_line["y2"]
            
            # Если между строками небольшой отступ — это один абзац
            if gap_y < avg_h * 1.2:
                current_para.append(line)
            else:
                paragraphs.append(_merge_lines_to_para(current_para))
                current_para = [line]
    
    if current_para:
        paragraphs.append(_merge_lines_to_para(current_para))
        
    return paragraphs

def _merge_lines_to_para(lines: list[dict]) -> dict:
    if not lines: return {}
    x1 = min(l["x1"] for l in lines)
    y1 = min(l["y1"] for l in lines)
    x2 = max(l["x2"] for l in lines)
    y2 = max(l["y2"] for l in lines)
    text = "\n".join(l["text"] for l in lines)
    conf = sum(l["confidence"] for l in lines) / len(lines)
    return {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "text": text, "confidence": conf, "h_sum": y2-y1, "count": len(lines)
    }

def _result_to_dict(r: OCRResult) -> dict:
    return {"x1": r.x1, "y1": r.y1, "x2": r.x2, "y2": r.y2, "text": r.text, "confidence": r.confidence, "h_sum": r.h, "count": 1}

def _new_merged_entry(box: dict) -> dict:
    return {"x1": box["x1"], "y1": box["y1"], "x2": box["x2"], "y2": box["y2"], "text": box["text"], "confidence": box["confidence"], "h_sum": box["h_sum"], "count": 1}

def _append_to_merged(p: dict, box: dict) -> None:
    p["text"] = f'{p["text"]} {box["text"]}'.strip()
    p["x1"] = min(p["x1"], box["x1"])
    p["y1"] = min(p["y1"], box["y1"])
    p["x2"] = max(p["x2"], box["x2"])
    p["y2"] = max(p["y2"], box["y2"])
    p["h_sum"] += box["h_sum"]
    p["count"] += 1
    p["confidence"] = (p["confidence"] * (p["count"] - 1) + box["confidence"]) / p["count"]

def _result_to_paragraph(item: dict) -> Paragraph:
    return Paragraph(x1=item["x1"], y1=item["y1"], x2=item["x2"], y2=item["y2"], text=item["text"], angle=0, is_vector=False, font_size_pt=None, confidence=item.get("confidence", 1.0))

def merge_zone_text(
    results: list[OCRResult],
    zone_w: float,
    zone_h: float,
    scale_y: float,
    filter_noise: bool = False
) -> Optional[Paragraph]:
    if not results:
        return None

    if filter_noise:
        results = _filter_noise(results)
        if not results:
            return None

    boxes = sorted(results, key=lambda r: r.cy)

    lines = []
    current_line = []
    current_y = -1

    for box in boxes:
        if not current_line:
            current_line.append(box)
            current_y = box.cy
        else:
            avg_h = sum(b.h for b in current_line) / len(current_line)
            if abs(box.cy - current_y) < avg_h * 0.6:
                current_line.append(box)
            else:
                lines.append(current_line)
                current_line = [box]
                current_y = box.cy
    if current_line:
        lines.append(current_line)

    text_lines = []
    for line in lines:
        line.sort(key=lambda b: b.x1)
        line_text = " ".join([b.text for b in line])
        text_lines.append(line_text)

    full_text = "\n".join(text_lines)

    heights = [b.h for b in results]
    avg_h = sum(heights) / len(heights) if heights else 10.0
    font_size_pt = max(4.0, (avg_h * scale_y) / 1.2)

    return Paragraph(
        x1=0, y1=0, x2=zone_w, y2=zone_h,
        text=full_text,
        angle=0,
        is_vector=False,
        font_size_pt=font_size_pt,
        confidence=sum(r.confidence for r in results) / len(results)
    )