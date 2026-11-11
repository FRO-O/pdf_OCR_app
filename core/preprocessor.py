"""
Препроцессинг изображений перед OCR.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_DARK_THRESHOLD = 100.0
DEFAULT_MIN_TEXT_HEIGHT_PX = 8
DEFAULT_MAX_UPSCALE = 3.0


@dataclass
class PreprocessResult:
    image: np.ndarray
    was_inverted: bool = False
    upscale_factor: float = 1.0
    detected_dark: bool = False
    mean_brightness: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def was_modified(self) -> bool:
        return self.was_inverted or self.upscale_factor > 1.0


def compute_mean_brightness(img: np.ndarray) -> float:
    if img.ndim == 3 and img.shape[2] == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img
    h, w = gray.shape[:2]
    if h * w > 250_000:
        small = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA)
        return float(small.mean())
    return float(gray.mean())


def auto_detect_dark_theme(img: np.ndarray, threshold: float = DEFAULT_DARK_THRESHOLD) -> tuple[bool, float]:
    mean_brightness = compute_mean_brightness(img)
    is_dark = mean_brightness < threshold
    return is_dark, mean_brightness


def apply_inversion(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3 and img.shape[2] == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img
    inverted_gray = 255 - gray
    return cv2.cvtColor(inverted_gray, cv2.COLOR_GRAY2RGB)


def estimate_text_height(img: np.ndarray) -> Optional[float]:
    try:
        if img.ndim == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels < 2:
            return None
        heights = [stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, num_labels) if 4 <= stats[i, cv2.CC_STAT_HEIGHT] <= 200]
        if not heights:
            return None
        return float(np.median(heights))
    except Exception as e:
        logger.debug("estimate_text_height: %s", e)
        return None


def upscale_if_small(img: np.ndarray, min_text_height: float = DEFAULT_MIN_TEXT_HEIGHT_PX, max_upscale: float = DEFAULT_MAX_UPSCALE) -> tuple[np.ndarray, float]:
    estimated_h = estimate_text_height(img)
    if estimated_h is None or estimated_h >= min_text_height:
        return img, 1.0
    scale = min(min_text_height / estimated_h, max_upscale)
    if scale <= 1.05:
        return img, 1.0
    scale = round(scale, 1)
    h, w = img.shape[:2]
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    return resized, scale


def enhance_contrast(img: np.ndarray, clip_limit: float = 2.0) -> np.ndarray:
    if img.ndim != 3 or img.shape[2] != 3:
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        return clahe.apply(img)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def binarize_for_drawings(img: np.ndarray) -> np.ndarray:
    """Перевод в чёрно-белый вид (адаптивная бинаризация)."""
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img
    
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 35, 10
    )
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)


def preprocess_image(
    img: np.ndarray,
    invert: bool = False,
    auto_detect_dark: bool = False,
    upscale_small_text: bool = False,
    enhance: bool = False,
    binarize: bool = False,
    min_text_height: float = DEFAULT_MIN_TEXT_HEIGHT_PX,
    max_upscale: float = DEFAULT_MAX_UPSCALE,
) -> PreprocessResult:
    if img is None or img.size == 0:
        raise ValueError("Пустое изображение на входе препроцессинга.")

    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    elif img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)

    result = PreprocessResult(image=img)

    is_dark, brightness = auto_detect_dark_theme(img)
    result.mean_brightness = brightness
    result.detected_dark = is_dark
    if is_dark:
        result.notes.append(f"Тёмная тема обнаружена (яркость {brightness:.0f})")

    should_invert = invert or (auto_detect_dark and is_dark)
    if should_invert:
        result.image = apply_inversion(result.image)
        result.was_inverted = True
        result.notes.append("Применена инверсия")

    if upscale_small_text:
        result.image, scale = upscale_if_small(result.image, min_text_height=min_text_height, max_upscale=max_upscale)
        if scale > 1.0:
            result.upscale_factor = scale
            result.notes.append(f"Изображение увеличено в {scale}×")

    if enhance:
        result.image = enhance_contrast(result.image)
        result.notes.append("Повышен контраст (CLAHE)")

    if binarize:
        result.image = binarize_for_drawings(result.image)
        result.notes.append("Применена бинаризация (ч/б)")

    return result