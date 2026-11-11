"""
Реализация OCR-движка на базе PaddleOCR (совместимость с 3.x).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .base import OCREngineBase, OCRParams, OCRResult

logger = logging.getLogger(__name__)

LANGUAGE_MAP = {
    "ru": "ru",
    "en": "en",
    "ch_sim": "ch",
    "ch_tra": "chinese_cht",
    "ko": "korean",
    "ja": "japan",
    "de": "german",
    "fr": "fr",
    "es": "es",
    "it": "it",
    "pt": "pt",
}

class PaddleOCREngine(OCREngineBase):
    def __init__(self, languages: list[str], use_gpu: bool = True):
        super().__init__(languages, use_gpu)
        self._ocr = self._create_paddle_ocr()

    def _create_paddle_ocr(self):
        try:
            import torch  # noqa: F401
        except ImportError:
            pass

        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise ImportError("PaddleOCR не установлен.") from e

        primary_lang = "en"
        if self.languages:
            primary_lang = LANGUAGE_MAP.get(self.languages[0], self.languages[0])

        import paddle
        device = "cpu"
        if self.use_gpu:
            try:
                if paddle.device.is_compiled_with_cuda():
                    device = "gpu:0"
            except Exception:
                pass
        paddle.set_device(device)

        # --- ИСПРАВЛЕННЫЙ ВЫЗОВ ДЛЯ 3.x ---
        # Убираем log_level и use_gpu, оставляем только поддерживаемые аргументы
        try:
            ocr = PaddleOCR(
                lang=primary_lang,
                device=device,
                use_doc_orientation_classify=False,  # <--- ОТКЛЮЧАЕМ ВЫРАВНИВАНИЕ
                use_doc_unwarping=False,             # <--- ОТКЛЮЧАЕМ ИСКАЖЕНИЕ
                use_textline_orientation=False,
            )
            logger.info(f"PaddleOCR инициализирован (device={device}, unwarping=OFF).")
            return ocr
        except (TypeError, ValueError) as e:
            logger.warning("Ошибка инициализации PaddleOCR: %s", e)
            # Fallback для старых версий (2.x)
            try:
                ocr = PaddleOCR(
                    lang=primary_lang,
                    use_gpu=self.use_gpu,
                    use_angle_cls=False,
                    show_log=False,
                )
                logger.info("PaddleOCR инициализирован (fallback для 2.x).")
                return ocr
            except Exception as e2:
                raise RuntimeError(f"Не удалось инициализировать PaddleOCR: {e2}") from e2

    def recognize(self, image: np.ndarray, params: Optional[OCRParams] = None) -> list[OCRResult]:
        if image.ndim == 3 and image.shape[2] == 3:
            img_bgr = image[:, :, ::-1].copy()
        else:
            img_bgr = image

        try:
            if hasattr(self._ocr, "predict"):
                # Передаём картинку без дополнительных флагов (они уже в конструкторе)
                raw = self._ocr.predict(img_bgr)
            else:
                raw = self._ocr.ocr(img_bgr, cls=True)
        except Exception as e:
            logger.exception("PaddleOCR error: %s", e)
            return []

        return self._convert_results(raw)

    @staticmethod
    def _convert_results(raw) -> list[OCRResult]:
        results: list[OCRResult] = []
        if not raw:
            return results

        if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], dict):
            for item in raw:
                texts = item.get("rec_texts", [])
                scores = item.get("rec_scores", [])
                polys = item.get("rec_polys", [])
                for i, text in enumerate(texts):
                    if not text.strip() or i >= len(polys):
                        continue
                    bbox = [[float(p[0]), float(p[1])] for p in polys[i]]
                    conf = float(scores[i]) if i < len(scores) else 1.0
                    results.append(OCRResult(bbox=bbox, text=text.strip(), confidence=conf))
            return results

        try:
            page_results = raw[0] if isinstance(raw, list) and len(raw) > 0 else []
            if not page_results:
                return results
            for line in page_results:
                if not isinstance(line, (list, tuple)) or len(line) < 2:
                    continue
                bbox_raw, (text, conf) = line[0], line[1]
                if not text.strip():
                    continue
                bbox = [[float(p[0]), float(p[1])] for p in bbox_raw]
                results.append(OCRResult(bbox=bbox, text=text.strip(), confidence=float(conf)))
        except Exception as e:
            logger.exception("Ошибка парсинга PaddleOCR result: %s", e)

        return results

    @property
    def name(self) -> str:
        return "PaddleOCR"

    @property
    def device_info(self) -> str:
        if not self.use_gpu:
            return "CPU"
        try:
            import paddle
            if paddle.device.is_compiled_with_cuda():
                return "GPU (Paddle CUDA)"
        except Exception:
            pass
        return "CPU (GPU недоступна)"

    @staticmethod
    def available_languages() -> list[str]:
        return list(LANGUAGE_MAP.keys())

    @staticmethod
    def map_languages(universal_langs: list[str]) -> list[str]:
        return [LANGUAGE_MAP.get(code, code) for code in universal_langs]