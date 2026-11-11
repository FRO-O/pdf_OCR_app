"""
Базовые абстракции для OCR-движков.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class OCRResult:
    bbox: list[list[float]]
    text: str
    confidence: float = 1.0

    @property
    def x1(self) -> float:
        return min(p[0] for p in self.bbox)

    @property
    def y1(self) -> float:
        return min(p[1] for p in self.bbox)

    @property
    def x2(self) -> float:
        return max(p[0] for p in self.bbox)

    @property
    def y2(self) -> float:
        return max(p[1] for p in self.bbox)

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox,
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
            "x2": round(self.x2, 2),
            "y2": round(self.y2, 2),
        }


@dataclass
class OCRParams:
    """Параметры распознавания."""
    mag_ratio: float = 1.5
    text_threshold: float = 0.5
    low_text: float = 0.3
    link_threshold: float = 0.4
    min_size: int = 10
    width_ths: float = 0.5
    paragraph: bool = False
    rotation_info: list[int] = field(default_factory=list)  # [90, 270]
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_easyocr_kwargs(self) -> dict[str, Any]:
        kwargs = {
            "mag_ratio": self.mag_ratio,
            "text_threshold": self.text_threshold,
            "low_text": self.low_text,
            "link_threshold": self.link_threshold,
            "min_size": self.min_size,
            "width_ths": self.width_ths,
            "paragraph": self.paragraph,
        }
        if self.rotation_info:
            kwargs["rotation_info"] = self.rotation_info
        kwargs.update(self.extra_params)
        return kwargs


class OCREngineBase(ABC):
    def __init__(self, languages: list[str], use_gpu: bool = True):
        if not languages:
            raise ValueError("Список языков пуст — нечего распознавать.")
        self.languages = list(languages)
        self.use_gpu = use_gpu

    @abstractmethod
    def recognize(
        self,
        image: np.ndarray,
        params: Optional[OCRParams] = None,
    ) -> list[OCRResult]:
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def available_languages() -> list[str]:
        raise NotImplementedError

    @staticmethod
    def map_languages(universal_langs: list[str]) -> list[str]:
        return list(universal_langs)

    @property
    def device_info(self) -> str:
        return "GPU" if self.use_gpu else "CPU"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} langs={self.languages} gpu={self.use_gpu}>"


UNIVERSAL_LANGUAGES: dict[str, str] = {
    "ru":     "Русский",
    "en":     "Английский",
    "ko":     "Корейский",
    "ja":     "Японский",
    "ch_sim": "Китайский (упрощённый)",
    "ch_tra": "Китайский (традиционный)",
    "de":     "Немецкий",
    "fr":     "Французский",
    "es":     "Испанский",
    "it":     "Итальянский",
    "pt":     "Португальский",
    "tr":     "Турецкий",
    "ar":     "Арабский",
}


def is_universal_language(code: str) -> bool:
    return code in UNIVERSAL_LANGUAGES