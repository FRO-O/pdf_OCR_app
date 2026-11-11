"""
Сохранение и загрузка зон (ROI) для файлов.
"""
from __future__ import annotations
import json
import os
import logging
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)

@dataclass
class Zone:
    id: int
    x1: float
    y1: float
    x2: float
    y2: float
    angle: int = 0
    invert: bool = False
    use_ocr: bool = True
    
    # Новые поля для таблиц
    is_table: bool = False
    table_html: str = ""
    table_cells: list[list[float]] = field(default_factory=list)

def get_zones_file_path(image_path: str) -> str:
    return f"{image_path}.zones.json"

def save_zones(image_path: str, zones: list[Zone]) -> None:
    if not image_path: return
    file_path = get_zones_file_path(image_path)
    
    if not zones:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception as e: logger.error("Не удалось удалить файл зон %s: %s", file_path, e)
        return

    data = {"version": "1.1", "zones": [asdict(z) for z in zones]}
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Ошибка сохранения зон в %s: %s", file_path, e)

def load_zones(image_path: str) -> list[Zone]:
    if not image_path: return []
    file_path = get_zones_file_path(image_path)
    if not os.path.exists(file_path): return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        zones = []
        for z_data in data.get("zones", []):
            zones.append(Zone(
                id=int(z_data["id"]),
                x1=float(z_data["x1"]),
                y1=float(z_data["y1"]),
                x2=float(z_data["x2"]),
                y2=float(z_data["y2"]),
                angle=int(z_data.get("angle", 0)),
                invert=bool(z_data.get("invert", False)),
                use_ocr=bool(z_data.get("use_ocr", True)),
                is_table=bool(z_data.get("is_table", False)),
                table_html=str(z_data.get("table_html", "")),
                table_cells=z_data.get("table_cells", [])
            ))
        return zones
    except Exception as e:
        logger.error("Ошибка загрузки зон из %s: %s", file_path, e)
        return []