"""
Многостраничный редактор зон (ROI) в стиле ABBYY FineReader.
"""

from __future__ import annotations
import os
import copy
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QSize
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QImage, QBrush, QPolygonF, QFont, 
    QIcon, QCursor, QKeySequence, QShortcut
)
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsPolygonItem, QGraphicsTextItem,
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QComboBox, QCheckBox, QLabel, QWidget, QSplitter,
    QMessageBox, QListView, QToolButton, QButtonGroup, QApplication
)

from core.zones_io import Zone
from core.table_recognizer import TableRecognizer


@dataclass
class PageData:
    file_path: str
    image: Image.Image
    zones: list[Zone] = field(default_factory=list)


class ZoneGraphicsItem:
    def __init__(self, zone: Zone, parent_view: 'GraphicsView'):
        self.zone = zone
        self.parent_view = parent_view
        
        self.rect_item = QGraphicsRectItem()
        self.rect_item.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.rect_item.setData(0, zone.id)
        self.parent_view.scene().addItem(self.rect_item)
        
        self.arrow_item = QGraphicsPolygonItem()
        self.parent_view.scene().addItem(self.arrow_item)
        
        self.label_item = QGraphicsTextItem(str(zone.id))
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        self.label_item.setFont(font)
        self.label_item.setDefaultTextColor(QColor(255, 255, 255))
        self.parent_view.scene().addItem(self.label_item)

        self.cell_items = []

        self.handles = []
        for _ in range(4):
            h = QGraphicsRectItem()
            h.setPen(QPen(Qt.GlobalColor.blue, 1))
            h.setBrush(QBrush(Qt.GlobalColor.white))
            h.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
            h.setVisible(False)
            self.parent_view.scene().addItem(h)
            self.handles.append(h)

        self._is_moving = False
        self._is_resizing = False
        self._resize_corner = None
        self._start_pos = QPointF()
        self._start_rect = QRectF()

        self.update_visuals()

    def update_visuals(self):
        z = self.zone
        rect = QRectF(z.x1, z.y1, z.x2 - z.x1, z.y2 - z.y1)
        self.rect_item.setRect(rect)
        
        if z.is_table:
            pen = QPen(QColor(128, 0, 128), 2, Qt.PenStyle.SolidLine)
            brush = QBrush(QColor(128, 0, 128, 30))
        elif z.invert:
            pen = QPen(QColor(230, 160, 0), 2, Qt.PenStyle.DashLine)
            brush = QBrush(QColor(255, 255, 0, 40))
        else:
            pen = QPen(QColor(43, 91, 132), 2, Qt.PenStyle.SolidLine)
            brush = QBrush(QColor(0, 0, 255, 20))
            
        self.rect_item.setPen(pen)
        self.rect_item.setBrush(brush)

        self.label_item.setPlainText(f"Таблица #{z.id}" if z.is_table else str(z.id))
        self.label_item.setPos(z.x1, z.y1)

        for item in self.cell_items:
            self.parent_view.scene().removeItem(item)
        self.cell_items.clear()

        if z.is_table and z.table_cells:
            for cell_dict in z.table_cells:
                if isinstance(cell_dict, dict) and "bbox" in cell_dict:
                    c_bbox = cell_dict["bbox"]
                else:
                    c_bbox = cell_dict
                    
                if len(c_bbox) != 4: 
                    continue
                    
                cx1, cy1, cx2, cy2 = float(c_bbox[0]), float(c_bbox[1]), float(c_bbox[2]), float(c_bbox[3])
                cell_rect = QRectF(cx1, cy1, cx2 - cx1, cy2 - cy1)
                cell_item = QGraphicsRectItem(cell_rect)
                cell_item.setPen(QPen(QColor(128, 0, 128), 1, Qt.PenStyle.DotLine))
                cell_item.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
                self.parent_view.scene().addItem(cell_item)
                self.cell_items.append(cell_item)

        cx = z.x1 + (z.x2 - z.x1) / 2
        cy = z.y1 + (z.y2 - z.y1) / 2
        arrow_size = 20

        if z.angle == 0:
            points = [QPointF(cx, cy - arrow_size), QPointF(cx - 8, cy + 8), QPointF(cx + 8, cy + 8)]
        elif z.angle == 90:
            points = [QPointF(cx + arrow_size, cy), QPointF(cx - 8, cy - 8), QPointF(cx - 8, cy + 8)]
        elif z.angle == 180:
            points = [QPointF(cx, cy + arrow_size), QPointF(cx - 8, cy - 8), QPointF(cx + 8, cy - 8)]
        elif z.angle == 270:
            points = [QPointF(cx - arrow_size, cy), QPointF(cx + 8, cy - 8), QPointF(cx + 8, cy + 8)]
        else:
            points = []
            
        poly = QPolygonF(points)
        self.arrow_item.setPolygon(poly)
        self.arrow_item.setPen(QPen(Qt.GlobalColor.transparent))
        self.arrow_item.setBrush(QBrush(QColor(200, 50, 50)))

        hs = 6
        tl = QRectF(z.x1 - hs/2, z.y1 - hs/2, hs, hs)
        tr = QRectF(z.x2 - hs/2, z.y1 - hs/2, hs, hs)
        bl = QRectF(z.x1 - hs/2, z.y2 - hs/2, hs, hs)
        br = QRectF(z.x2 - hs/2, z.y2 - hs/2, hs, hs)
        
        for i, r in enumerate([tl, tr, bl, br]):
            self.handles[i].setRect(r)

    def set_selected(self, selected: bool):
        for h in self.handles:
            h.setVisible(selected)

    def remove(self):
        self.parent_view.scene().removeItem(self.rect_item)
        self.parent_view.scene().removeItem(self.arrow_item)
        self.parent_view.scene().removeItem(self.label_item)
        for h in self.handles:
            self.parent_view.scene().removeItem(h)
        for item in self.cell_items:
            self.parent_view.scene().removeItem(item)

    def mousePressEvent(self, event, pos: QPointF) -> bool:
        rect = QRectF(self.zone.x1, self.zone.y1, self.zone.x2 - self.zone.x1, self.zone.y2 - self.zone.y1)
        for i, h in enumerate(self.handles):
            if h.isVisible() and h.rect().adjusted(-2,-2,2,2).contains(pos):
                self._is_resizing = True
                self._resize_corner = i
                self._start_pos = pos
                self._start_rect = QRectF(rect)
                return True
        if rect.contains(pos):
            self._is_moving = True
            self._start_pos = pos
            self._start_rect = QRectF(rect)
            return True
        return False

    def mouseMoveEvent(self, event, pos: QPointF) -> bool:
        if self._is_moving:
            delta = pos - self._start_pos
            self.zone.x1 = self._start_rect.x() + delta.x()
            self.zone.y1 = self._start_rect.y() + delta.y()
            self.zone.x2 = self.zone.x1 + self._start_rect.width()
            self.zone.y2 = self.zone.y1 + self._start_rect.height()
            self.update_visuals()
            return True
        if self._is_resizing:
            r = QRectF(self._start_rect)
            if self._resize_corner == 0: r.setTopLeft(pos)
            elif self._resize_corner == 1: r.setTopRight(pos)
            elif self._resize_corner == 2: r.setBottomLeft(pos)
            elif self._resize_corner == 3: r.setBottomRight(pos)
            r = r.normalized()
            if r.width() > 5 and r.height() > 5:
                self.zone.x1, self.zone.y1 = r.left(), r.top()
                self.zone.x2, self.zone.y2 = r.right(), r.bottom()
                self.update_visuals()
            return True
        return False

    def mouseReleaseEvent(self, event) -> bool:
        if self._is_moving or self._is_resizing:
            self._is_moving = False
            self._is_resizing = False
            return True
        return False


class GraphicsView(QGraphicsView):
    zone_created = pyqtSignal(QRectF)
    zone_selected = pyqtSignal(int)
    zones_modified = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._start_pos: Optional[QPointF] = None
        self._current_rect_item: Optional[QGraphicsRectItem] = None
        self.zone_items: list[ZoneGraphicsItem] = []
        
        self._is_panning = False
        self._pan_start_pos = QPointF()
        self._active_zone_item = None

    def set_image(self, image: Image.Image):
        self.scene().clear()
        self.zone_items.clear()
        
        img_rgb = image.convert("RGB")
        arr = np.array(img_rgb)
        h, w, ch = arr.shape
        bytes_per_line = ch * w
        qimg = QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene().addItem(self._pixmap_item)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def add_zone_visual(self, zone: Zone):
        item = ZoneGraphicsItem(zone, self)
        self.zone_items.append(item)
        return item

    def update_zone_visual(self, zone: Zone):
        for item in self.zone_items:
            if item.zone.id == zone.id:
                item.update_visuals()
                break

    def remove_zone_visual(self, zone_id: int):
        for i, item in enumerate(self.zone_items):
            if item.zone.id == zone_id:
                item.remove()
                del self.zone_items[i]
                break

    def clear_zones(self):
        for item in self.zone_items:
            item.remove()
        self.zone_items.clear()

    def select_zone_visual(self, zone_id: int):
        for item in self.zone_items:
            item.set_selected(item.zone.id == zone_id)

    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._pixmap_item:
            for item in reversed(self.zone_items):
                if item.mousePressEvent(event, scene_pos):
                    self._active_zone_item = item
                    self.zone_selected.emit(item.zone.id)
                    event.accept()
                    return

            self.zone_selected.emit(-1)
            self._start_pos = scene_pos
            self._current_rect_item = QGraphicsRectItem()
            self._current_rect_item.setPen(QPen(QColor(255, 0, 0), 2, Qt.PenStyle.DashLine))
            self.scene().addItem(self._current_rect_item)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        if self._is_panning:
            delta = event.position() - self._pan_start_pos
            self._pan_start_pos = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return

        if self._active_zone_item:
            self._active_zone_item.mouseMoveEvent(event, scene_pos)
            event.accept()
            return

        if self._start_pos and self._current_rect_item:
            rect = QRectF(self._start_pos, scene_pos).normalized()
            self._current_rect_item.setRect(rect)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        if self._active_zone_item:
            if self._active_zone_item.mouseReleaseEvent(event):
                self.zones_modified.emit()
            self._active_zone_item = None
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._current_rect_item:
            rect = self._current_rect_item.rect()
            self.scene().removeItem(self._current_rect_item)
            self._current_rect_item = None
            self._start_pos = None
            
            if rect.width() > 10 and rect.height() > 10:
                self.zone_created.emit(rect)
            event.accept()
            return

        super().mouseReleaseEvent(event)


class ZoneEditorDialog(QDialog):
    def __init__(self, files_data: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Мастер разметки зон (FineReader Style)")
        self.resize(1200, 800)
        
        self.pages: list[PageData] = []
        self.current_page_index = -1
        
        self.history: list[list[Zone]] = []
        self.history_index = -1
        self.clipboard: list[Zone] = []
        self.table_recognizer = None

        for fd in files_data:
            self.pages.append(PageData(
                file_path=fd['file_path'],
                image=fd['image'],
                zones=fd.get('zones', [])
            ))

        self._build_ui()
        self._populate_list()

        QShortcut(QKeySequence.StandardKey.Undo, self, self._undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self._redo)
        QShortcut(QKeySequence.StandardKey.Copy, self, self._copy_zones)
        QShortcut(QKeySequence.StandardKey.Paste, self, self._paste_zones)
        QShortcut(QKeySequence.StandardKey.Delete, self, self._on_delete_selected)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(3)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #ddd; }")

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(2)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<b>Страницы</b>"))
        header_layout.addStretch()
        
        self.btn_view_list = QToolButton()
        self.btn_view_list.setText("≡")
        self.btn_view_list.setCheckable(True)
        self.btn_view_list.setChecked(True)
        
        self.btn_view_tiles = QToolButton()
        self.btn_view_tiles.setText("▦")
        self.btn_view_tiles.setCheckable(True)
        
        view_group = QButtonGroup(self)
        view_group.addButton(self.btn_view_list)
        view_group.addButton(self.btn_view_tiles)
        
        self.btn_view_list.clicked.connect(self._set_view_mode_list)
        self.btn_view_tiles.clicked.connect(self._set_view_mode_tiles)
        
        header_layout.addWidget(self.btn_view_list)
        header_layout.addWidget(self.btn_view_tiles)
        left_layout.addLayout(header_layout)
        
        self.list_pages = QListWidget()
        self.list_pages.currentRowChanged.connect(self._on_page_changed)
        self.list_pages.setIconSize(QSize(120, 80))
        self.list_pages.setResizeMode(QListView.ResizeMode.Adjust)
        left_layout.addWidget(self.list_pages)
        
        self.splitter.addWidget(left_panel)

        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(4, 0, 4, 0)
        center_layout.setSpacing(2)
        
        zoom_layout = QHBoxLayout()
        btn_zoom_out = QPushButton("-")
        btn_zoom_out.setFixedWidth(30)
        btn_zoom_out.clicked.connect(lambda: self.view.scale(1/1.2, 1/1.2))
        
        btn_zoom_fit = QPushButton("1:1")
        btn_zoom_fit.setFixedWidth(40)
        btn_zoom_fit.clicked.connect(lambda: self.view.fitInView(self.view._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio))
        
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(30)
        btn_zoom_in.clicked.connect(lambda: self.view.scale(1.2, 1.2))
        
        zoom_layout.addWidget(btn_zoom_out)
        zoom_layout.addWidget(btn_zoom_fit)
        zoom_layout.addWidget(btn_zoom_in)
        zoom_layout.addStretch()
        hint = QLabel("<span style='color:#888; font-size:10px;'>ЛКМ — рисовать/тянуть, СКМ — двигать</span>")
        zoom_layout.addWidget(hint)
        center_layout.addLayout(zoom_layout)

        self.view = GraphicsView()
        self.view.zone_created.connect(self._on_zone_drawn)
        self.view.zone_selected.connect(self._on_zone_selected_from_view)
        self.view.zones_modified.connect(self._save_state)
        center_layout.addWidget(self.view)
        
        self.splitter.addWidget(center_widget)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)
        
        top_btn_layout = QHBoxLayout()
        btn_auto = QPushButton("✨ Умные зоны")
        btn_auto.clicked.connect(self._on_auto_zones)
        top_btn_layout.addWidget(btn_auto)
        
        self.btn_find_tables = QPushButton("📊 Найти таблицы")
        self.btn_find_tables.clicked.connect(self._on_find_tables)
        top_btn_layout.addWidget(self.btn_find_tables)
        
        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(self._on_clear_all)
        top_btn_layout.addWidget(btn_clear)
        
        right_layout.addLayout(top_btn_layout)

        copy_paste_layout = QHBoxLayout()
        btn_copy = QPushButton("📋 Копировать")
        btn_copy.clicked.connect(self._copy_zones)
        btn_paste = QPushButton("📥 Вставить")
        btn_paste.clicked.connect(self._paste_zones)
        copy_paste_layout.addWidget(btn_copy)
        copy_paste_layout.addWidget(btn_paste)
        right_layout.addLayout(copy_paste_layout)

        right_layout.addWidget(QLabel("<b>Зоны текущей страницы:</b>"))
        
        self.list_zones = QListWidget()
        self.list_zones.currentRowChanged.connect(self._on_zone_selected)
        right_layout.addWidget(self.list_zones)

        self.settings_group = QWidget()
        settings_layout = QVBoxLayout(self.settings_group)
        settings_layout.setContentsMargins(0, 10, 0, 0)
        settings_layout.setSpacing(4)

        self.lbl_zone_type = QLabel("Тип: Текст")
        self.lbl_zone_type.setStyleSheet("font-weight: bold; color: #333;")
        settings_layout.addWidget(self.lbl_zone_type)

        self.cmb_angle = QComboBox()
        self.cmb_angle.addItems(["0°", "+90°", "180°", "-90°"])
        self.cmb_angle.currentIndexChanged.connect(self._on_zone_settings_changed)
        settings_layout.addWidget(QLabel("Поворот текста:"))
        settings_layout.addWidget(self.cmb_angle)

        self.chk_invert = QCheckBox("Инверсия (белый текст на тёмном)")
        self.chk_invert.stateChanged.connect(self._on_zone_settings_changed)
        settings_layout.addWidget(self.chk_invert)

        self.chk_ocr = QCheckBox("Распознавать текст (OCR)")
        self.chk_ocr.setChecked(True)
        self.chk_ocr.stateChanged.connect(self._on_zone_settings_changed)
        settings_layout.addWidget(self.chk_ocr)

        self.btn_delete = QPushButton("🗑 Удалить выбранную зону")
        self.btn_delete.setStyleSheet("color: #c0392b; padding: 4px;")
        self.btn_delete.clicked.connect(self._on_delete_selected)
        settings_layout.addWidget(self.btn_delete)

        self.settings_group.setEnabled(False)
        right_layout.addWidget(self.settings_group)
        right_layout.addStretch()
        
        btn_ok = QPushButton("Применить и закрыть")
        btn_ok.setFixedHeight(35)
        btn_ok.setStyleSheet("font-weight: bold; background-color: #2b5b84; color: white;")
        btn_ok.clicked.connect(self.accept)
        right_layout.addWidget(btn_ok)
        
        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([250, 650, 300])
        
        main_layout.addWidget(self.splitter)

    def _save_state(self):
        if self.current_page_index < 0: return
        self.history = self.history[:self.history_index + 1]
        current_zones = self.pages[self.current_page_index].zones
        self.history.append(copy.deepcopy(current_zones))
        self.history_index += 1

    def _undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_from_history()

    def _redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._restore_from_history()

    def _restore_from_history(self):
        if 0 <= self.history_index < len(self.history):
            restored_zones = copy.deepcopy(self.history[self.history_index])
            self.pages[self.current_page_index].zones = restored_zones
            self._on_page_changed(self.current_page_index)

    def _copy_zones(self):
        zones = self._get_current_zones()
        if zones:
            self.clipboard = copy.deepcopy(zones)
            QMessageBox.information(self, "Копирование", f"Скопировано зон: {len(zones)}")

    def _paste_zones(self):
        if not self.clipboard or self.current_page_index < 0: return
        zones = self._get_current_zones()
        max_id = max([z.id for z in zones], default=0)
        
        for z in self.clipboard:
            max_id += 1
            new_zone = Zone(
                id=max_id, x1=z.x1 + 20, y1=z.y1 + 20, x2=z.x2 + 20, y2=z.y2 + 20,
                angle=z.angle, invert=z.invert, use_ocr=z.use_ocr,
                is_table=z.is_table, table_html=z.table_html, table_cells=z.table_cells
            )
            zones.append(new_zone)
            self.view.add_zone_visual(new_zone)
            
        self._refresh_zones_list(zones)
        self._save_state()

    def _set_view_mode_list(self):
        self.list_pages.setViewMode(QListView.ViewMode.ListMode)
        self.list_pages.setIconSize(QSize(24, 24))
        self.list_pages.setGridSize(QSize())
        self.btn_view_list.setChecked(True)

    def _set_view_mode_tiles(self):
        self.list_pages.setViewMode(QListView.ViewMode.IconMode)
        self.list_pages.setIconSize(QSize(140, 90))
        self.list_pages.setGridSize(QSize(150, 120))
        self.list_pages.setWordWrap(True)
        self.btn_view_tiles.setChecked(True)

    def _populate_list(self):
        self.list_pages.clear()
        for i, page in enumerate(self.pages):
            name = os.path.basename(page.file_path)
            img_thumb = page.image.copy()
            img_thumb.thumbnail((140, 90), Image.Resampling.LANCZOS)
            
            arr = np.array(img_thumb.convert("RGB"))
            h, w, ch = arr.shape
            qimg = QImage(arr.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            
            item = QListWidgetItem(f"{i+1}. {name}")
            item.setIcon(QIcon(pixmap))
            self.list_pages.addItem(item)
        
        if self.pages:
            self.list_pages.setCurrentRow(0)

    def _on_page_changed(self, index: int):
        if not (0 <= index < len(self.pages)): return

        self.current_page_index = index
        page = self.pages[index]
        self.view.set_image(page.image)

        for zone in page.zones:
            self.view.add_zone_visual(zone)
        
        self._refresh_zones_list(page.zones)

        self.history = []
        self.history_index = -1
        self._save_state()

    def _refresh_zones_list(self, zones: list[Zone]):
        self.list_zones.blockSignals(True)
        self.list_zones.clear()
        for i, zone in enumerate(zones):
            name = f"📊 Таблица #{zone.id}" if zone.is_table else f"Зона #{zone.id}"
            self.list_zones.addItem(name)
        self.list_zones.blockSignals(False)
        
        if zones:
            self.list_zones.setCurrentRow(0)
        else:
            self.settings_group.setEnabled(False)

    def _get_current_zones(self) -> list[Zone]:
        if 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index].zones
        return []

    def _on_zone_drawn(self, rect: QRectF):
        zones = self._get_current_zones()
        max_id = max([z.id for z in zones], default=0)
        
        zone = Zone(
            id=max_id + 1, x1=rect.left(), y1=rect.top(),
            x2=rect.right(), y2=rect.bottom(),
        )
        zones.append(zone)
        
        self.list_zones.addItem(f"Зона #{zone.id}")
        self.view.add_zone_visual(zone)
        self.list_zones.setCurrentRow(self.list_zones.count() - 1)
        self._save_state()

    def _on_auto_zones(self):
        if self.current_page_index < 0: return
        QMessageBox.information(self, "Умные зоны", "Функция в разработке.")

    def _on_find_tables(self):
        if self.current_page_index < 0: return
        page = self.pages[self.current_page_index]
        
        # ОЧИЩАЕМ СТАРЫЕ ТАБЛИЦЫ ПЕРЕД НОВЫМ ПОИСКОМ
        zones_to_remove = [z for z in page.zones if z.is_table]
        for z in zones_to_remove:
            page.zones.remove(z)
            self.view.remove_zone_visual(z.id)
        
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self.table_recognizer is None:
                self.table_recognizer = TableRecognizer(use_gpu=True) # Включаем GPU!
            
            img_np = np.array(page.image.convert("RGB"))
            img_bgr = img_np[:, :, ::-1].copy()
            
            tables = self.table_recognizer.recognize_tables(img_bgr)
            
            if not tables:
                QMessageBox.warning(self, "Таблицы", "Таблиц на изображении не найдено.")
                self._refresh_zones_list(page.zones)
                return

            count = 0
            max_id = max([z.id for z in page.zones], default=0)
            
            for tbl in tables:
                bbox = tbl.get("bbox", [])
                if len(bbox) < 4: continue
                
                x1 = float(bbox[0])
                y1 = float(bbox[1])
                x2 = float(bbox[2])
                y2 = float(bbox[3])
                
                max_id += 1
                zone = Zone(
                    id=max_id,
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    is_table=True,
                    table_html=tbl.get("html", ""),
                    table_cells=tbl.get("cells", [])
                )
                page.zones.append(zone)
                self.view.add_zone_visual(zone)
                count += 1
                
            self._refresh_zones_list(page.zones)
            self._save_state()
            QMessageBox.information(self, "Таблицы", f"Успешно найдено и добавлено таблиц: {count}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Ошибка", f"Не удалось распознать таблицы: {e}")
            self._refresh_zones_list(page.zones)
        finally:
            QApplication.restoreOverrideCursor()

    def _on_zone_selected(self, index: int):
        zones = self._get_current_zones()
        if 0 <= index < len(zones):
            self.settings_group.setEnabled(True)
            zone = zones[index]
            
            self.view.select_zone_visual(zone.id)
            
            self.cmb_angle.blockSignals(True)
            self.chk_invert.blockSignals(True)
            self.chk_ocr.blockSignals(True)
            
            if zone.is_table:
                self.lbl_zone_type.setText("Тип: Таблица")
                self.lbl_zone_type.setStyleSheet("font-weight: bold; color: #800080;")
                self.cmb_angle.setEnabled(False)
                self.chk_invert.setEnabled(False)
                self.chk_ocr.setEnabled(False)
            else:
                self.lbl_zone_type.setText("Тип: Текст")
                self.lbl_zone_type.setStyleSheet("font-weight: bold; color: #333;")
                self.cmb_angle.setEnabled(True)
                self.chk_invert.setEnabled(True)
                self.chk_ocr.setEnabled(True)
                
                angle_map = {0: 0, 90: 1, 180: 2, 270: 3}
                self.cmb_angle.setCurrentIndex(angle_map.get(zone.angle, 0))
                self.chk_invert.setChecked(bool(zone.invert))
                self.chk_ocr.setChecked(bool(zone.use_ocr))
            
            self.cmb_angle.blockSignals(False)
            self.chk_invert.blockSignals(False)
            self.chk_ocr.blockSignals(False)
        else:
            self.settings_group.setEnabled(False)

    def _on_zone_selected_from_view(self, zone_id: int):
        if zone_id == -1:
            self.list_zones.clearSelection()
            self.list_zones.setCurrentRow(-1)
            self.view.select_zone_visual(-1)
        else:
            zones = self._get_current_zones()
            for i, zone in enumerate(zones):
                if zone.id == zone_id:
                    self.list_zones.setCurrentRow(i)
                    break

    def _on_zone_settings_changed(self):
        index = self.list_zones.currentRow()
        zones = self._get_current_zones()
        
        if 0 <= index < len(zones):
            zone = zones[index]
            if zone.is_table: return
            
            idx = self.cmb_angle.currentIndex()
            angle_map_rev = {0: 0, 1: 90, 2: 180, 3: 270}
            
            zone.angle = angle_map_rev.get(idx, 0)
            zone.invert = self.chk_invert.isChecked()
            zone.use_ocr = self.chk_ocr.isChecked()
            self.view.update_zone_visual(zone)
            self._save_state()

    def _on_delete_selected(self):
        index = self.list_zones.currentRow()
        zones = self._get_current_zones()
        
        if 0 <= index < len(zones):
            zone = zones.pop(index)
            self.view.remove_zone_visual(zone.id)
            self.list_zones.takeItem(index)
            self.settings_group.setEnabled(False)
            self._save_state()

    def _on_clear_all(self):
        zones = self._get_current_zones()
        zones.clear()
        self.list_zones.clear()
        self.view.clear_zones()
        self.settings_group.setEnabled(False)
        self._save_state()

    def get_results(self) -> list[dict]:
        return [
            {"file_path": p.file_path, "zones": p.zones}
            for p in self.pages
        ]