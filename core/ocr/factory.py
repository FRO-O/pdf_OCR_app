"""
Фабрика OCR-движков.
"""
from __future__ import annotations
import logging
from typing import Callable, Type

from .base import OCREngineBase

logger = logging.getLogger(__name__)

_ENGINE_REGISTRY: dict[str, Callable[[], Type[OCREngineBase]]] = {}

def _register_easyocr() -> Type[OCREngineBase]:
    from .easyocr_engine import EasyOCREngine
    return EasyOCREngine

def _register_paddleocr() -> Type[OCREngineBase]:
    from .paddleocr_engine import PaddleOCREngine
    return PaddleOCREngine

def _register_mistral() -> Type[OCREngineBase]:
    from .mistral_engine import MistralOCREngine
    return MistralOCREngine

_ENGINE_REGISTRY["PaddleOCR"] = _register_paddleocr
_ENGINE_REGISTRY["EasyOCR"] = _register_easyocr
_ENGINE_REGISTRY["Mistral OCR (API)"] = _register_mistral

_ENGINE_CACHE: dict[tuple, OCREngineBase] = {}

def get_ocr_engine(
    engine_name: str,
    languages: list[str],
    use_gpu: bool = True,
    api_key: str = "",
) -> OCREngineBase:
    if engine_name not in _ENGINE_REGISTRY:
        available = ", ".join(sorted(_ENGINE_REGISTRY.keys()))
        raise ValueError(f"OCR-движок '{engine_name}' не зарегистрирован. Доступные: {available}")

    key = (engine_name, frozenset(languages), bool(use_gpu), api_key)
    if key in _ENGINE_CACHE:
        return _ENGINE_CACHE[key]

    engine_class = _ENGINE_REGISTRY[engine_name]()
    if engine_name == "Mistral OCR (API)":
        engine = engine_class(languages, use_gpu=use_gpu, api_key=api_key)
    else:
        engine = engine_class(languages, use_gpu=use_gpu)

    _ENGINE_CACHE[key] = engine
    return engine

def list_available_engines() -> list[str]:
    return list(_ENGINE_REGISTRY.keys())

def is_engine_installed(engine_name: str) -> bool:
    if engine_name == "EasyOCR":
        try: import easyocr; return True
        except ImportError: return False
    if engine_name == "PaddleOCR":
        try: import paddleocr; return True
        except ImportError: return False
    if engine_name == "Mistral OCR (API)":
        try: import mistralai; return True
        except ImportError: return False
    return False

def get_engine_display_name(engine_name: str) -> str:
    if not is_engine_installed(engine_name):
        return f"{engine_name} (не установлен)"
    return engine_name