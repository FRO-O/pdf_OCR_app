"""
Оркестратор пайплайна.
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Optional
import numpy as np
from PIL import Image

from core.box_merger import (
    MergeProfile, ocr_results_to_paragraphs, merge_zone_text, 
    sort_paragraphs_reading_order, group_lines_into_paragraphs
)
from core.image_loader import is_image_file, load_image
from core.ocr.base import OCRParams
from core.ocr.factory import get_ocr_engine
from core.page import PageData, Paragraph
from core.pdf_loader import is_pdf_file, load_pdf
from core.preprocessor import preprocess_image
from core.table_recognizer import TableRecognizer
from exporters.base import BaseExporter, ExportOptions

logger = logging.getLogger(__name__)

class ProcessProfile:
    DRAWING = "drawing"
    UI = "ui"
    DOCUMENT = "document"


@dataclass
class PipelineConfig:
    file_path: str = ""
    page_indices: Optional[list[int]] = None
    prefer_pdf_text: bool = True
    profile: str = ProcessProfile.DRAWING
    invert: bool = False
    auto_dark: bool = False
    upscale_small: bool = False
    enhance: bool = False
    binarize: bool = False
    engine_name: str = "PaddleOCR"
    languages: list[str] = field(default_factory=lambda: ["ru", "en"])
    use_gpu: bool = True
    api_key: str = "" 
    ocr_params: OCRParams = field(default_factory=OCRParams)
    target_app: str = "PPTX"
    export_options: ExportOptions = field(default_factory=ExportOptions)
    export_json: bool = False
    json_output_path: Optional[str] = None
    import_json_path: Optional[str] = None
    translation_background_white: bool = False
    filter_noise: bool = False
    zones_by_file: dict = field(default_factory=dict)
    review_callback: bool = False


@dataclass
class PipelineCallbacks:
    log_fn: Optional[Callable[[str], None]] = None
    progress_fn: Optional[Callable[[int], None]] = None
    stop_fn: Optional[Callable[[], bool]] = None
    stage_fn: Optional[Callable[[str], None]] = None

    def log(self, message: str) -> None:
        if self.log_fn: self.log_fn(message)
    def progress(self, percent: int) -> None:
        if self.progress_fn: self.progress_fn(max(0, min(100, percent)))
    def should_stop(self) -> bool:
        if self.stop_fn: return self.stop_fn()
        return False
    def stage(self, name: str) -> None:
        if self.stage_fn: self.stage_fn(name)


class PipelineStopped(Exception):
    pass


def _get_bg_color(img: Image.Image, x1: float, y1: float, x2: float, y2: float) -> tuple[int, int, int]:
    """Вычисляет медианный цвет фона в области bbox."""
    try:
        w, h = img.size
        left = max(0, min(int(x1), w - 1))
        top = max(0, min(int(y1), h - 1))
        right = max(0, min(int(x2), w))
        bottom = max(0, min(int(y2), h))
        
        if left >= right or top >= bottom: return (255, 255, 255)
            
        crop = img.crop((left, top, right, bottom)).convert("RGB")
        arr = np.array(crop)
        
        median_color = np.median(arr.reshape(-1, 3), axis=0)
        return (int(median_color[0]), int(median_color[1]), int(median_color[2]))
    except Exception:
        return (255, 255, 255)


def process_document(config: PipelineConfig, callbacks: Optional[PipelineCallbacks] = None) -> list[PageData]:
    cb = callbacks or PipelineCallbacks()
    if not config.file_path or not os.path.exists(config.file_path):
        raise FileNotFoundError(f"Файл не найден: {config.file_path}")

    cb.log(f"Файл: {os.path.basename(config.file_path)}")
    pages = _load_pages(config, cb)
    _process_pages(pages, config, cb)
    return pages


def export_document(source_path: str, pages: list[PageData], config: PipelineConfig, callbacks: Optional[PipelineCallbacks] = None) -> str:
    cb = callbacks or PipelineCallbacks()
    if config.export_json:
        _export_json(pages, config, cb)
    exporter = _create_exporter(config.target_app)
    return exporter.export(source_path=source_path, pages=pages, options=config.export_options)


def run_pipeline(config: PipelineConfig, callbacks: Optional[PipelineCallbacks] = None) -> str:
    if config.import_json_path:
        return _run_translation_pipeline(config, callbacks)
    pages = process_document(config, callbacks)
    return export_document(config.file_path, pages, config, callbacks)


def _run_translation_pipeline(config: PipelineConfig, cb: Optional[PipelineCallbacks] = None) -> str:
    from translate.json_io import load_translation_json
    from translate.replacer import build_pages_from_translation
    cb = cb or PipelineCallbacks()
    
    cb.stage("Загрузка JSON")
    try:
        data = load_translation_json(config.import_json_path)
    except Exception as e:
        raise RuntimeError(f"Ошибка загрузки JSON: {e}") from e

    if abs(data.font_scale - config.export_options.font_scale) > 0.01:
        config.export_options.font_scale = data.font_scale

    source_path = config.file_path
    if not source_path:
        json_dir = os.path.dirname(os.path.abspath(config.import_json_path))
        candidate = os.path.join(json_dir, data.source_file)
        if os.path.exists(candidate):
            source_path = candidate

    try:
        pages = build_pages_from_translation(data, source_path=source_path, background_white=config.translation_background_white)
    except Exception as e:
        raise RuntimeError(f"Ошибка сборки страниц из JSON: {e}") from e

    name_source = source_path or config.import_json_path
    exporter = _create_exporter(config.target_app)
    output_path = exporter.export(source_path=name_source, pages=pages, options=config.export_options)
    
    base, ext = os.path.splitext(output_path)
    new_path = f"{base}_translated{ext}"
    try:
        os.replace(output_path, new_path)
        output_path = new_path
    except Exception:
        pass
    return output_path


def _load_pages(config: PipelineConfig, cb: PipelineCallbacks) -> list[PageData]:
    path = config.file_path
    if is_pdf_file(path):
        return load_pdf(path, page_indices=config.page_indices, extract_vector_text=config.prefer_pdf_text)
    if is_image_file(path):
        page = load_image(path)
        return [page] if page else []
    raise RuntimeError(f"Неподдерживаемый формат: {os.path.splitext(path)[1]}")


def _process_pages(pages: list[PageData], config: PipelineConfig, cb: PipelineCallbacks) -> None:
    total = len(pages)
    engine = None
    table_recognizer = None
    current_zones = config.zones_by_file.get(config.file_path, [])

    for idx, page in enumerate(pages, start=1):
        _check_stop(cb)
        cb.progress(15 + int((idx - 1) / total * 70))

        # --- ОБРАБОТКА ПО ЗОНАМ (РУЧНАЯ РАЗМЕТКА) ---
        if current_zones:
            cb.log(f"--- Страница {idx}/{total} (обработка {len(current_zones)} зон) ---")
            if engine is None:
                engine = get_ocr_engine(config.engine_name, config.languages, config.use_gpu, config.api_key)
            
            all_paragraphs = []
            for zone in current_zones:
                _check_stop(cb)
                box = (int(zone.x1), int(zone.y1), int(zone.x2), int(zone.y2))
                orig_w = box[2] - box[0]
                orig_h = box[3] - box[1]
                
                zone_img = page.image.crop(box)
                
                # Если это таблица
                if getattr(zone, 'is_table', False):
                    cb.log(f"  Зона #{zone.id} (Таблица): анализ структуры...")
                    if table_recognizer is None:
                        table_recognizer = TableRecognizer(use_gpu=config.use_gpu)
                    
                    img_np = np.array(zone_img.convert("RGB"))
                    img_bgr = img_np[:, :, ::-1].copy()
                    
                    tables = table_recognizer.recognize_tables(img_bgr, ocr_engine=engine, ocr_params=config.ocr_params)
                    
                    if tables:
                        html = tables[0].get("html", "")
                        p = Paragraph(
                            x1=zone.x1, y1=zone.y1, x2=zone.x2, y2=zone.y2,
                            text="[Таблица]", 
                            is_table=True, 
                            table_html=html,
                            angle=zone.angle
                        )
                        all_paragraphs.append(p)
                    else:
                        cb.log(f"    ⚠ Не удалось найти структуру таблицы #{zone.id}")
                    continue
                
                # Обычный текст в зоне
                if zone.angle == 90: zone_img = zone_img.rotate(-90, expand=True)
                elif zone.angle == 180: zone_img = zone_img.rotate(180, expand=True)
                elif zone.angle == 270: zone_img = zone_img.rotate(90, expand=True)
                
                from PIL import ImageOps
                if zone.invert: zone_img = ImageOps.invert(zone_img.convert("RGB"))
                if not zone.use_ocr: continue

                img_np = np.array(zone_img.convert("RGB"))
                try:
                    ocr_results = engine.recognize(img_np, config.ocr_params)
                except Exception:
                    continue
                    
                p = merge_zone_text(ocr_results, zone_w=orig_w, zone_h=orig_h, scale_y=page.scale_y, filter_noise=config.filter_noise)
                
                if p:
                    rx1, ry1, rx2, ry2 = 0.0, 0.0, 0.0, 0.0
                    if zone.angle == 0:
                        rx1, ry1, rx2, ry2 = p.x1, p.y1, p.x2, p.y2
                    elif zone.angle == 90:
                        rx1 = orig_w - p.y2; ry1 = p.x1; rx2 = orig_w - p.y1; ry2 = p.x2
                    elif zone.angle == 180:
                        rx1 = orig_w - p.x2; ry1 = orig_h - p.y2; rx2 = orig_w - p.x1; ry2 = orig_h - p.y1
                    elif zone.angle == 270:
                        rx1 = p.y1; ry1 = orig_h - p.x2; rx2 = p.y2; ry2 = orig_h - p.x1

                    p.x1 = rx1 + zone.x1; p.y1 = ry1 + zone.y1
                    p.x2 = rx2 + zone.x1; p.y2 = ry2 + zone.y1
                    if p.x1 > p.x2: p.x1, p.x2 = p.x2, p.x1
                    if p.y1 > p.y2: p.y1, p.y2 = p.y2, p.y1

                    p.angle = zone.angle
                    p.bg_color = _get_bg_color(page.image, p.x1, p.y1, p.x2, p.y2)
                    all_paragraphs.append(p)
            
            page.paragraphs = sort_paragraphs_reading_order(all_paragraphs)
            continue

        # --- АВТОМАТИЧЕСКАЯ ОБРАБОТКА (БЕЗ ЗОН) ---
        cb.log(f"--- Страница {idx}/{total} ---")
        
        has_vector = config.prefer_pdf_text and page.has_vector_text()
        if has_vector:
            cb.log(f"  Векторный текст: {len(page.vector_paragraphs)} фрагментов")

        use_upscale = config.upscale_small and config.engine_name not in ("PaddleOCR", "Mistral OCR (API)")
        
        pre_result = preprocess_image(
            page.get_image_np(), invert=config.invert, auto_detect_dark=config.auto_dark,
            upscale_small_text=use_upscale, enhance=config.enhance, binarize=config.binarize,
        )

        if engine is None:
            engine = get_ocr_engine(config.engine_name, config.languages, config.use_gpu, config.api_key)

        try:
            ocr_results = engine.recognize(pre_result.image, config.ocr_params)
        except Exception as e:
            cb.log(f"    OCR упал: {e}")
            ocr_results = []

        merge_profile = _merge_profile_from_config(config)
        actual_upscale = pre_result.upscale_factor
        
        ocr_paragraphs = ocr_results_to_paragraphs(
            ocr_results, profile=merge_profile, upscale_factor=actual_upscale, filter_noise=config.filter_noise,
        )
        
        if has_vector:
            # Оставляем векторный текст, а из OCR берем только то, что не дублирует его (картинки-сканы)
            filtered_ocr = []
            for ocr_p in ocr_paragraphs:
                is_duplicate = False
                for vec_p in page.vector_paragraphs:
                    if not (ocr_p.x2 < vec_p.x1 or ocr_p.x1 > vec_p.x2 or ocr_p.y2 < vec_p.y1 or ocr_p.y1 > vec_p.y2):
                        is_duplicate = True
                        break
                if not is_duplicate:
                    filtered_ocr.append(ocr_p)
            
            page.paragraphs = list(page.vector_paragraphs) + filtered_ocr
            
            # Если выбран режим документа, прогоняем смешанный текст через группировщик абзацев
            if config.profile == ProcessProfile.DOCUMENT:
                page.paragraphs = group_lines_into_paragraphs(page.paragraphs)
            else:
                page.paragraphs = sort_paragraphs_reading_order(page.paragraphs)
        else:
            page.paragraphs = ocr_paragraphs

        # Применяем умный фон для всех элементов
        for p in page.paragraphs:
            p.bg_color = _get_bg_color(page.image, p.x1, p.y1, p.x2, p.y2)


def _merge_profile_from_config(config: PipelineConfig) -> MergeProfile:
    if config.profile == ProcessProfile.UI:
        return MergeProfile.UI
    if config.profile == ProcessProfile.DOCUMENT:
        return MergeProfile.DOCUMENT
    return MergeProfile.DRAWING


def _export_json(pages: list[PageData], config: PipelineConfig, cb: PipelineCallbacks) -> None:
    from translate.json_io import export_translation_json
    try:
        json_path = export_translation_json(
            pages=pages, source_path=config.file_path, target_app=config.target_app,
            profile=config.profile, languages=config.languages,
            font_scale=config.export_options.font_scale, output_path=config.json_output_path,
        )
        cb.log(f"JSON сохранен: {json_path}")
    except Exception as e:
        cb.log(f"⚠ Ошибка JSON: {e}")


def _create_exporter(target_app: str) -> BaseExporter:
    name = target_app.upper()
    
    if name == "PPTX":
        from exporters.pptx_exporter import PPTXExporter
        return PPTXExporter()
    if name == "DOCX_TRANSLATE":
        from exporters.docx_exporter import DOCXExporter
        return DOCXExporter()
    if name == "DOCX_DOCUMENT":
        from exporters.docx_document_exporter import DOCXDocumentExporter
        return DOCXDocumentExporter()
    if name == "INDESIGN":
        from exporters.indesign_exporter import IndesignExporter
        return IndesignExporter()
    if name == "ILLUSTRATOR":
        from exporters.illustrator_exporter import IllustratorExporter
        return IllustratorExporter()
        
    raise ValueError(f"Неизвестный формат: {target_app}")


def _check_stop(cb: PipelineCallbacks) -> None:
    if cb.should_stop(): raise PipelineStopped("Остановлено пользователем.")