"""
Реализация OCR-движка на базе Mistral API.
"""
from __future__ import annotations
import base64
import io
import logging
import time
import random
from typing import Optional
import numpy as np
from PIL import Image
from .base import OCREngineBase, OCRParams, OCRResult

logger = logging.getLogger(__name__)

class MistralOCREngine(OCREngineBase):
    def __init__(self, languages: list[str], use_gpu: bool = True, api_key: str = ""):
        super().__init__(languages, use_gpu)
        self.api_key = api_key
        self._client = None
        self.is_v1 = False
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.warning("Mistral API: Ключ не указан.")
            return
        try:
            from mistralai.client import Mistral
            self._client = Mistral(api_key=self.api_key)
            self.is_v1 = True
            logger.info("Mistral OCR инициализирован (SDK v1+).")
            return
        except ImportError:
            pass
        try:
            from mistralai.client import MistralClient
            self._client = MistralClient(api_key=self.api_key)
            self.is_v1 = False
            logger.info("Mistral OCR инициализирован (старый SDK).")
            return
        except ImportError:
            logger.error("Библиотека mistralai не установлена.")

    def recognize(self, image: np.ndarray, params: Optional[OCRParams] = None) -> list[OCRResult]:
        if self._client is None: return []
        try:
            pil_img = Image.fromarray(image)
            buffered = io.BytesIO()
            pil_img.save(buffered, format="PNG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        except Exception as e:
            logger.error("Mistral: Ошибка base64: %s", e)
            return []

        document = {"type": "image_url", "image_url": f"data:image/png;base64,{img_b64}"}
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if self.is_v1:
                    response = self._client.ocr.process(model="mistral-ocr-latest", document=document, include_blocks=True)
                else:
                    response = self._client.ocr(model="mistral-ocr-latest", document=document, include_blocks=True)
                break
            except Exception as e:
                err_msg = str(e)
                if "401" in err_msg or "403" in err_msg or "Upgrade" in err_msg or "Unauthorized" in err_msg:
                    logger.error("Mistral API: Ключ не активирован или неверен.")
                    return []
                if "429" in err_msg or "rate_limited" in err_msg:
                    wait_time = (2 ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(f"Mistral API: Лимит запросов. Ждём {wait_time:.1f} сек...")
                    time.sleep(wait_time)
                else:
                    logger.error("Ошибка Mistral API: %s", err_msg)
                    return []
        else:
            logger.error("Mistral API: Превышено максимальное количество попыток.")
            return []

        results = []
        try:
            for page in response.pages:
                if hasattr(page, "blocks") and page.blocks:
                    for block in page.blocks:
                        text = getattr(block, "text", "").strip()
                        if not text: continue
                        bbox = getattr(block, "bbox", None)
                        if bbox and len(bbox) == 4:
                            x1, y1, x2, y2 = bbox
                            poly = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                        else:
                            poly = [[0, 0], [10, 0], [10, 10], [0, 10]]
                        conf = getattr(block, "confidence", 1.0) or 1.0
                        results.append(OCRResult(bbox=poly, text=text, confidence=float(conf)))
                elif hasattr(page, "markdown") and page.markdown:
                    text = page.markdown.strip()
                    if text:
                        poly = [[0, 0], [100, 0], [100, 100], [0, 100]]
                        results.append(OCRResult(bbox=poly, text=text, confidence=1.0))
        except Exception as e:
            logger.error("Ошибка парсинга Mistral: %s", e)
        return results

    @property
    def name(self) -> str:
        return "Mistral OCR (API)"

    @property
    def device_info(self) -> str:
        return "Cloud (API)"

    @staticmethod
    def available_languages() -> list[str]:
        from .base import UNIVERSAL_LANGUAGES
        return list(UNIVERSAL_LANGUAGES.keys())

    @staticmethod
    def map_languages(universal_langs: list[str]) -> list[str]:
        return universal_langs