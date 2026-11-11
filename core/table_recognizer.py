"""
Модуль распознавания таблиц на базе нейросетей PaddleOCR (с поддержкой GPU).
"""

from __future__ import annotations
import logging
import os
import cv2
import numpy as np

logger = logging.getLogger(__name__)

class TableRecognizer:
    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self._engine = None
        self._paddle_available = True

    def _init_engine(self):
        if self._engine is not None or not self._paddle_available:
            return

        try:
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
            
            import paddle
            device = "gpu:0" if self.use_gpu else "cpu"
            
            try:
                paddle.set_device(device)
            except Exception as e:
                logger.warning(f"Не удалось установить device='{device}': {e}. Откат на CPU.")
                device = "cpu"
                paddle.set_device(device)

            is_cuda = paddle.device.is_compiled_with_cuda()
            logger.info(f"Paddle установлен с поддержкой CUDA: {is_cuda}. Текущее устройство: {device}")

            # --- ПОПЫТКА 1: Полный набор аргументов ---
            try:
                from paddleocr import TableRecognitionPipelineV2
                try:
                    self._engine = TableRecognitionPipelineV2(
                        device=device,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        use_layout_detection=False,
                    )
                    logger.info(f"TableRecognitionPipelineV2 (полный набор аргументов), device={device}")
                    return
                except (TypeError, ValueError) as e:
                    logger.warning(f"Полный набор аргументов не поддерживается: {e}. Пробуем минимальный.")
                    # --- ПОПЫТКА 2: Минимальный набор ---
                    self._engine = TableRecognitionPipelineV2(device=device)
                    logger.info(f"TableRecognitionPipelineV2 (минимальный набор), device={device}")
                    return
            except ImportError:
                pass

            # --- ПОПЫТКА 3: PPStructureV3 ---
            try:
                from paddleocr import PPStructureV3
                self._engine = PPStructureV3(
                    device=device,
                    use_table_recognition=True,
                )
                logger.info(f"PPStructureV3 инициализирован (device={device}).")
                return
            except Exception as e:
                logger.error(f"PPStructureV3 тоже не запустился: {e}")

        except Exception as e:
            logger.error("Не удалось инициализировать PaddleOCR для таблиц: %s", e)
            self._engine = None

    def recognize_tables(self, image: np.ndarray, ocr_engine=None, ocr_params=None) -> list[dict]:
        tables = []
        
        if self._paddle_available:
            self._init_engine()
            if self._engine:
                try:
                    h, w = image.shape[:2]
                    max_size = 1600
                    if max(h, w) > max_size:
                        scale = max_size / max(h, w)
                        new_w, new_h = int(w * scale), int(h * scale)
                        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
                        logger.info(f"Таблица уменьшена для OCR: {w}x{h} -> {new_w}x{new_h}")

                    logger.info("Запуск распознавания структуры таблицы (Paddle GPU)...")
                    output = self._engine.predict(input=image)
                    
                    for res in output:
                        data = res.json if hasattr(res, 'json') else (res if isinstance(res, dict) else getattr(res, '__dict__', {}))
                        for tbl in data.get("table_res_list", []):
                            html = tbl.get("pred_html", "")
                            bbox = tbl.get("bbox", tbl.get("table_bbox", [0, 0, 0, 0]))
                            if html:
                                tables.append({"bbox": bbox, "html": html, "cells": tbl.get("cell_box_list", [])})
                                
                    if tables:
                        logger.info("Paddle успешно распознал структуру таблицы.")
                        return tables
                    else:
                        logger.info("Paddle не вернул HTML структуры. Пробуем OpenCV...")
                except Exception as e:
                    logger.error("Ошибка PaddleOCR: %s. Переключаемся на OpenCV...", e)

        logger.info("Запуск OpenCV-детектора линий...")
        return self._find_tables_by_lines(image)

    def _find_tables_by_lines(self, image: np.ndarray) -> list[dict]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        thresh = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
        
        horizontal = thresh.copy()
        cols = horizontal.shape[1]
        horizontal_size = cols // 15
        horizontalStructure = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_size, 1))
        horizontal = cv2.erode(horizontal, horizontalStructure)
        horizontal = cv2.dilate(horizontal, horizontalStructure)
        
        vertical = thresh.copy()
        rows = vertical.shape[0]
        vertical_size = rows // 15
        verticalStructure = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_size))
        vertical = cv2.erode(vertical, verticalStructure)
        vertical = cv2.dilate(vertical, verticalStructure)
        
        mask = cv2.add(horizontal, vertical)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.dilate(mask, kernel, iterations=2)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        tables = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w > 200 and h > 100:
                tables.append({"bbox": [x, y, x + w, y + h], "html": "", "cells": []})
        
        logger.info("OpenCV нашёл %d областей с сеткой (резервный режим).", len(tables))
        return tables