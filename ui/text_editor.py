"""
Интерактивный редактор текста (Preview).
"""
from __future__ import annotations
import numpy as np
from PIL import Image

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage, QBrush
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QSplitter, QWidget, QLabel, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QHeaderView, QAbstractItemView
)

from core.page import PageData, Paragraph


class PreviewGraphicsView(QGraphicsView):
    """Холст для отображения картинки и боксов (с поддержкой зума)."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        
        self._pixmap_item: QGraphicsPixmapItem = None
        self.rect_items: list[QGraphicsRectItem] = []

    def set_page(self, page: PageData):
        self.scene().clear()
        self.rect_items.clear()
        
        img_rgb = page.image.convert("RGB")
        arr = np.array(img_rgb)
        h, w, ch = arr.shape
        qimg = QImage(arr.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene().addItem(self._pixmap_item)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        
        for p in page.paragraphs:
            rect = QRectF(p.x1, p.y1, p.w, p.h)
            item = QGraphicsRectItem(rect)
            
            if p.confidence < 0.5:
                color = QColor(255, 0, 0, 100)
            elif p.confidence < 0.8:
                color = QColor(255, 165, 0, 100)
            else:
                color = QColor(0, 255, 0, 50)
                
            item.setPen(QPen(color, 2))
            item.setBrush(QBrush(color))
            self.scene().addItem(item)
            self.rect_items.append(item)
            
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        # Масштабирование колесом мыши с зажатым Ctrl
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def highlight_paragraph(self, index: int):
        for i, item in enumerate(self.rect_items):
            if i == index:
                item.setPen(QPen(QColor(0, 0, 255), 3))
            else:
                if item.brush().color().red() == 255 and item.brush().color().alpha() == 100:
                    item.setPen(QPen(QColor(255, 0, 0, 100), 2))
                elif item.brush().color().green() == 255:
                    item.setPen(QPen(QColor(0, 255, 0, 50), 2))
                else:
                    item.setPen(QPen(QColor(255, 165, 0, 100), 2))


class TextEditorDialog(QDialog):
    def __init__(self, pages: list[PageData], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Проверка распознанного текста")
        self.resize(1200, 700)
        
        self.pages = pages
        self.current_page_index = 0

        self._build_ui()
        self._load_page(0)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая часть: Картинка
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
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
        
        hint = QLabel("<span style='color:#888; font-size:10px;'>Ctrl+Колесо — зум</span>")
        zoom_layout.addWidget(hint)
        
        left_layout.addLayout(zoom_layout)

        self.view = PreviewGraphicsView()
        left_layout.addWidget(self.view)
        splitter.addWidget(left_widget)

        # Правая часть: Таблица с текстом
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        if len(self.pages) > 1:
            page_layout = QHBoxLayout()
            page_layout.addWidget(QLabel("Страница:"))
            self.btn_prev_page = QPushButton("<")
            self.btn_next_page = QPushButton(">")
            self.lbl_page_info = QLabel(f"1 из {len(self.pages)}")
            
            self.btn_prev_page.clicked.connect(self._prev_page)
            self.btn_next_page.clicked.connect(self._next_page)
            
            page_layout.addWidget(self.btn_prev_page)
            page_layout.addWidget(self.lbl_page_info)
            page_layout.addWidget(self.btn_next_page)
            page_layout.addStretch()
            right_layout.addLayout(page_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["#", "Распознанный текст", "Увер."])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 60)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.itemChanged.connect(self._on_item_changed)
        
        right_layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Отмена (не экспортировать)")
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("Продолжить (Экспорт)")
        btn_ok.setFixedHeight(35)
        btn_ok.setStyleSheet("font-weight: bold; background-color: #2b5b84; color: white;")
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        
        right_layout.addLayout(btn_layout)
        splitter.addWidget(right_widget)
        splitter.setSizes([600, 600])
        
        main_layout.addWidget(splitter)

    def _load_page(self, index: int):
        if not (0 <= index < len(self.pages)):
            return
            
        self.current_page_index = index
        if len(self.pages) > 1:
            self.lbl_page_info.setText(f"{index + 1} из {len(self.pages)}")
            
        page = self.pages[index]
        self.view.set_page(page)
        
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        
        for i, p in enumerate(page.paragraphs):
            self.table.insertRow(i)
            
            item_id = QTableWidgetItem(str(i+1))
            item_id.setFlags(item_id.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, item_id)
            
            item_text = QTableWidgetItem(p.text)
            self.table.setItem(i, 1, item_text)
            
            item_conf = QTableWidgetItem(f"{p.confidence*100:.0f}%")
            item_conf.setFlags(item_conf.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 2, item_conf)
            
            if p.confidence < 0.5:
                color = QColor(255, 200, 200)
            elif p.confidence < 0.8:
                color = QColor(255, 240, 200)
            else:
                color = QColor(200, 255, 200)
                
            for col in range(3):
                self.table.item(i, col).setBackground(color)
                
        self.table.blockSignals(False)

    def _prev_page(self):
        if self.current_page_index > 0:
            self._load_page(self.current_page_index - 1)

    def _next_page(self):
        if self.current_page_index < len(self.pages) - 1:
            self._load_page(self.current_page_index + 1)

    def _on_row_selected(self):
        row = self.table.currentRow()
        self.view.highlight_paragraph(row)

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 1:
            row = item.row()
            page = self.pages[self.current_page_index]
            if 0 <= row < len(page.paragraphs):
                page.paragraphs[row].text = item.text()