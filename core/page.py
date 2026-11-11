"""
Универсальное представление страницы.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from PIL import Image

@dataclass
class Paragraph:
    x1: float
    y1: float
    x2: float
    y2: float
    text: str
    angle: int = 0
    is_vector: bool = False
    font_size_pt: Optional[float] = None
    confidence: float = 1.0
    
    # Новые поля
    is_table: bool = False
    table_html: str = ""
    bg_color: tuple[int, int, int] = (255, 255, 255) # Цвет фона под текстом

    @property
    def w(self) -> float: return self.x2 - self.x1
    @property
    def h(self) -> float: return self.y2 - self.y1
    @property
    def cx(self) -> float: return (self.x1 + self.x2) / 2.0
    @property
    def cy(self) -> float: return (self.y1 + self.y2) / 2.0

@dataclass
class PageData:
    page_num: int
    image: Image.Image
    img_w_px: int
    img_h_px: int
    page_w_pt: float
    page_h_pt: float
    dpi: float = 72.0
    source_path: str = ""
    source_type: str = "image"

    vector_paragraphs: list[Paragraph] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    preprocess_meta: dict = field(default_factory=dict)

    @property
    def scale_x(self) -> float: return self.page_w_pt / self.img_w_px if self.img_w_px else 1.0
    @property
    def scale_y(self) -> float: return self.page_h_pt / self.img_h_px if self.img_h_px else 1.0

    def get_image_np(self) -> np.ndarray: return np.array(self.image.convert("RGB"))
    def has_vector_text(self) -> bool: return bool(self.vector_paragraphs)
    def has_any_text(self) -> bool: return bool(self.paragraphs)