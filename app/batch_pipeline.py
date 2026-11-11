"""
Оркестратор пакетной обработки.
"""
from __future__ import annotations
import os
import logging
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from app.pipeline import (
    PipelineConfig, PipelineCallbacks, run_pipeline, 
    process_document, export_document
)
from core.image_loader import is_image_file

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    folder_path: str = ""
    base_config: PipelineConfig = field(default_factory=PipelineConfig)
    output_folder: Optional[str] = None


@dataclass
class BatchCallbacks:
    log_fn: Optional[Callable[[str], None]] = None
    progress_fn: Optional[Callable[[int], None]] = None
    stop_fn: Optional[Callable[[], bool]] = None
    stage_fn: Optional[Callable[[str], None]] = None

    def log(self, message: str) -> None:
        if self.log_fn:
            self.log_fn(message)

    def progress(self, percent: int) -> None:
        if self.progress_fn:
            self.progress_fn(max(0, min(100, percent)))

    def should_stop(self) -> bool:
        if self.stop_fn:
            return self.stop_fn()
        return False

    def stage(self, name: str) -> None:
        if self.stage_fn:
            self.stage_fn(name)


def run_batch_pipeline(config: BatchConfig, callbacks: Optional[BatchCallbacks] = None) -> list[str]:
    """
    Запускает пакетную обработку папки.
    Возвращает список путей к созданным файлам.
    """
    cb = callbacks or BatchCallbacks()

    if not config.folder_path or not os.path.isdir(config.folder_path):
        raise ValueError(f"Папка не найдена: {config.folder_path}")

    # 1. Собираем список файлов (PNG, JPG, PDF)
    files = []
    for f in sorted(os.listdir(config.folder_path)):
        full_path = os.path.join(config.folder_path, f)
        if os.path.isfile(full_path) and (is_image_file(full_path) or f.lower().endswith(".pdf")):
            files.append(full_path)

    if not files:
        raise RuntimeError("В выбранной папке не найдено подходящих файлов (PNG, JPG, PDF).")

    cb.log(f"=== Пакетная обработка: найдено {len(files)} файлов ===")

    # 2. Создаём папку для результатов
    out_dir = config.output_folder
    if not out_dir:
        out_dir = os.path.join(config.folder_path, "_output")
    
    os.makedirs(out_dir, exist_ok=True)
    cb.log(f"Папка результатов: {out_dir}")

    created_files = []
    total = len(files)
    target_app = config.base_config.target_app.upper()

    # =========================================================================
    # СПЕЦИАЛЬНЫЙ РЕЖИМ ДЛЯ WORD: СБОР ВСЕХ СТРАНИЦ В ОДИН ФАЙЛ
    # =========================================================================
    if target_app in ("DOCX_TRANSLATE", "DOCX_DOCUMENT"):
        cb.log(f"=== Режим {target_app}: сбор всех страниц в один файл ===")
        all_pages = []
        
        pipeline_cb = PipelineCallbacks(
            log_fn=cb.log,
            stop_fn=cb.should_stop,
            stage_fn=cb.stage
        )

        for idx, file_path in enumerate(files, start=1):
            if cb.should_stop():
                break
                
            cb.log(f"\n--- Чтение {idx}/{total}: {os.path.basename(file_path)} ---")
            file_config = replace(config.base_config, file_path=file_path)
            
            base_prog = int((idx - 1) / total * 100)
            def file_prog(pct, base=base_prog, t=total):
                cb.progress(base + int(pct / 100 * (100 / t)))
            pipeline_cb.progress_fn = file_prog

            try:
                # Распознаём файл, но пока не экспортируем
                pages = process_document(file_config, pipeline_cb)
                all_pages.extend(pages)
            except Exception as e:
                cb.log(f"  ⚠ Ошибка обработки файла {os.path.basename(file_path)}: {e}")
                logger.exception("Batch error on file %s", file_path)

        # Экспортируем один раз в конце
        suffix = "Translation" if target_app == "DOCX_TRANSLATE" else "Document"
        out_path = os.path.join(out_dir, f"Batch_{suffix}.docx")
        
        # Подменяем путь в конфиге, чтобы экспортер сохранил туда
        config.base_config.export_options.output_path = out_path

        try:
            export_document(config.folder_path, all_pages, config.base_config, pipeline_cb)
            created_files.append(out_path)
            cb.log(f"\nВсего успешно обработано страниц: {len(all_pages)}.")
        except Exception as e:
            cb.log(f"  ⚠ Ошибка сохранения Word: {e}")

        cb.progress(100)
        return created_files

    # =========================================================================
    # ОБЫЧНЫЙ РЕЖИМ: КАЖДЫЙ ФАЙЛ ЭКСПОРТИРУЕТСЯ ОТДЕЛЬНО
    # =========================================================================
    for idx, file_path in enumerate(files, start=1):
        if cb.should_stop():
            cb.log("Пакетная обработка остановлена пользователем.")
            break
            
        cb.log(f"\n--- Файл {idx}/{total}: {os.path.basename(file_path)} ---")
        
        base_progress = int((idx - 1) / total * 100)
        def file_progress(pct, base=base_progress, t=total):
            cb.progress(base + int(pct / 100 * (100 / t)))

        file_config = replace(config.base_config, file_path=file_path)
        
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # Определяем правильное расширение
        if target_app == "PPTX":
            ext = ".pptx"
        elif target_app == "INDESIGN":
            ext = ".indd"
        elif target_app == "ILLUSTRATOR":
            ext = ".ai"
        else:
            ext = ".pptx"
            
        file_config.export_options.output_path = os.path.join(out_dir, f"{base_name}_vector{ext}")

        pipeline_cb = PipelineCallbacks(
            log_fn=cb.log,
            progress_fn=file_progress,
            stop_fn=cb.should_stop,
            stage_fn=lambda stage: cb.stage(f"Файл {idx}/{total}: {stage}")
        )

        try:
            output_path = run_pipeline(file_config, pipeline_cb)
            created_files.append(output_path)
        except Exception as e:
            cb.log(f"  ⚠ Ошибка обработки файла {os.path.basename(file_path)}: {e}")
            logger.exception("Batch error on file %s", file_path)

    cb.progress(100)
    cb.log(f"\n=== Пакетная обработка завершена. Успешно: {len(created_files)}/{total} ===")
    return created_files