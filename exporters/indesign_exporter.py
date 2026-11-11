"""
Экспорт в Adobe InDesign через COM (Windows).

Логика:
1. Подключаемся к активному InDesign (или запускаем новый).
2. Создаём документ с размерами первой страницы.
3. Настраиваем слои: «Оригинал», «Плашки (Фон)», «Живой текст».
4. Для каждой страницы:
   - Place() исходного PDF на монтажную область (или Picture для картинки)
   - TextFrames для каждой надписи на слое «Живой текст»
   - Подложки под оригинальный текст на слое «Плашки»

Ключевые отличия от исходного кода:
- Работа с Paragraph/PageData вместо словарей.
- Единый расчёт размера шрифта через base.compute_font_size.
- Меньше «немых» except — проблемные надписи логируются.
- Совместимость с разными версиями InDesign: если какой-то
  параметр не поддерживается, ловим и продолжаем.

ВАЖНО: работает только на Windows (COM).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from core.page import PageData, Paragraph

from .base import BaseExporter, ExportOptions


logger = logging.getLogger(__name__)


# Единицы измерения InDesign через COM:
# 2054188905 = idPoints
ID_POINTS = 2054188905

# PDF Crop — использовать физический размер листа, не TrimBox.
ID_PDF_CROP_MEDIA = 1131573313

# Fit — вписать в рамку.
ID_FIT_FRAME_TO_CONTENT = 1668247152

# Запас по ширине TextFrame в pt — чтобы текст не переносился.
TEXTFRAME_WIDTH_EXTRA_PT = 35.0

# Множитель высоты TextFrame относительно bbox.
TEXTFRAME_HEIGHT_FACTOR = 1.4

# Шрифты по приоритету. Используется первый доступный.
FONT_FALLBACKS = [
    "Arial",
    "Microsoft YaHei",  # для CJK
    "SimSun",
    "Arial Unicode MS",
]


class InDesignExporter(BaseExporter):
    """Экспортёр в Adobe InDesign."""

    @property
    def file_extension(self) -> str:
        return ".indd"

    def export(
        self,
        source_path: str,
        pages: list[PageData],
        options: ExportOptions,
    ) -> str:
        if not pages:
            raise RuntimeError("Нет страниц для экспорта.")

        options.log("Экспорт в Adobe InDesign...")

        try:
            app = self._connect_indesign()
        except Exception as e:
            raise RuntimeError(
                f"Не удалось подключиться к Adobe InDesign: {e}. "
                f"Убедитесь, что InDesign установлен и доступен через COM."
            ) from e

        first = pages[0]
        doc = self._create_document(app, first)
        layers = self._setup_layers(doc, options)

        abs_source = os.path.abspath(source_path)
        is_pdf = source_path.lower().endswith(".pdf")

        for idx, page in enumerate(pages):
            try:
                self._add_page_content(
                    app, doc, page, layers,
                    abs_source, is_pdf, options,
                )
                options.log(
                    f"  Страница {idx + 1}/{len(pages)}: "
                    f"{len(page.paragraphs)} надписей"
                )
            except Exception as e:
                options.log(f"    Ошибка страницы {idx + 1}: {e}")
                logger.exception("InDesign страница %d: %s", idx + 1, e)

        # Сохраняем документ
        output_path = options.output_path or self.default_output_path(source_path)
        try:
            doc.Save(os.path.abspath(output_path))
        except Exception as e:
            raise RuntimeError(
                f"Не удалось сохранить документ InDesign: {e}"
            ) from e

        options.log(f"Документ InDesign сохранён: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Подключение и создание документа
    # ------------------------------------------------------------------

    @staticmethod
    def _connect_indesign():
        """Подключается к активному InDesign или запускает новый."""
        try:
            import win32com.client
        except ImportError as e:
            raise RuntimeError(
                "pywin32 не установлен. Установите: pip install pywin32"
            ) from e

        try:
            app = win32com.client.GetActiveObject("InDesign.Application")
        except Exception:
            app = win32com.client.Dispatch("InDesign.Application")
        return app

    def _create_document(self, app, first_page: PageData):
        """Создаёт документ InDesign с размерами первой страницы."""
        doc = app.Documents.Add()
        try:
            doc.ViewPreferences.HorizontalMeasurementUnits = ID_POINTS
            doc.ViewPreferences.VerticalMeasurementUnits = ID_POINTS
        except Exception:
            pass  # некоторые версии не поддерживают

        doc.DocumentPreferences.FacingPages = False
        doc.DocumentPreferences.PageWidth = first_page.page_w_pt
        doc.DocumentPreferences.PageHeight = first_page.page_h_pt
        return doc

    def _setup_layers(self, doc, options: ExportOptions) -> dict:
        """
        Создаёт слои и возвращает словарь:
            {"bg": layer, "boxes": layer|None, "text": layer}
        """
        # Слой для оригинала
        try:
            layer_bg = doc.Layers.Item(1)
            layer_bg.Name = "Оригинал схемы"
        except Exception:
            layer_bg = doc.Layers.Add()
            layer_bg.Name = "Оригинал схемы"

        # Слой под белые плашки (только если hide_orig_text)
        layer_boxes = None
        if options.hide_orig_text:
            try:
                layer_boxes = doc.Layers.Item("Плашки (Фон)")
            except Exception:
                layer_boxes = doc.Layers.Add()
                layer_boxes.Name = "Плашки (Фон)"

        # Слой живого текста
        try:
            layer_text = doc.Layers.Item("Живой текст")
        except Exception:
            layer_text = doc.Layers.Add()
            layer_text.Name = "Живой текст"

        return {"bg": layer_bg, "boxes": layer_boxes, "text": layer_text}

    # ------------------------------------------------------------------
    # Одна страница
    # ------------------------------------------------------------------

    def _add_page_content(
        self, app, doc, page: PageData, layers: dict,
        source_path: str, is_pdf: bool, options: ExportOptions,
    ) -> None:
        # Первая страница уже есть, для остальных — добавляем
        if page.page_num > 1:
            new_page = doc.Pages.Add()
        else:
            new_page = doc.Pages.Item(1)

        # Обнуляем поля монтажной области
        mp = new_page.MarginPreferences
        mp.Top = 0
        mp.Bottom = 0
        mp.Left = 0
        mp.Right = 0

        w_pt = page.page_w_pt
        h_pt = page.page_h_pt

        # 1. Фон — Place исходного файла
        frame_bg = new_page.Rectangles.Add(layers["bg"])
        frame_bg.GeometricBounds = [0, 0, h_pt, w_pt]

        if is_pdf:
            try:
                app.PDFPlacePreferences.PageNumber = page.page_num
                app.PDFPlacePreferences.PDFCrop = ID_PDF_CROP_MEDIA
            except Exception:
                pass

        try:
            frame_bg.Place(source_path)
            frame_bg.Fit(ID_FIT_FRAME_TO_CONTENT)
        except Exception as e:
            options.log(f"    Place() не удался: {e}")
            logger.exception("InDesign Place: %s", e)

        # 2. Надписи
        for paragraph in page.paragraphs:
            try:
                self._add_paragraph(
                    doc, new_page, paragraph, page, layers, options,
                )
            except Exception as e:
                options.log(
                    f"    Пропущена надпись '{paragraph.text[:20]}': {e}"
                )

    # ------------------------------------------------------------------
    # Одна надпись
    # ------------------------------------------------------------------

    def _add_paragraph(
        self, doc, page_obj, paragraph: Paragraph, page: PageData,
        layers: dict, options: ExportOptions,
    ) -> None:
        # Координаты в pt
        left_pt = paragraph.x1 * page.scale_x
        top_pt = paragraph.y1 * page.scale_y
        right_pt = paragraph.x2 * page.scale_x
        bottom_pt = paragraph.y2 * page.scale_y

        # 1. Белая подложка
        if options.hide_orig_text and layers["boxes"] is not None:
            self._add_mask(doc, page_obj, layers["boxes"], top_pt,
                           left_pt, bottom_pt, right_pt)

        # 2. Размер шрифта
        font_size = self.compute_font_size(
            paragraph, page,
            font_scale=options.font_scale,
            min_size=options.min_font_size,
            max_size=options.max_font_size,
        )

        # 3. TextFrame
        tf = page_obj.TextFrames.Add(layers["text"])
        tf.GeometricBounds = [
            top_pt,
            left_pt,
            bottom_pt + (font_size * 0.4),
            right_pt + TEXTFRAME_WIDTH_EXTRA_PT,
        ]

        tf.Contents = str(paragraph.text)

        try:
            none_swatch = doc.Swatches.Item("None")
            tf.FillColor = none_swatch
        except Exception:
            pass

        # Убираем внутренние отступы
        tfp = tf.TextFramePreferences
        tfp.TopInset = 0
        tfp.BottomInset = 0
        tfp.LeftInset = 0
        tfp.RightInset = 0

        # Параметры текста через ParentStory
        story = tf.ParentStory
        try:
            story.PointSize = font_size
            story.Leading = font_size * 1.15
        except Exception:
            pass

        # Шрифт — первый доступный из fallback
        for font_name in FONT_FALLBACKS:
            try:
                story.AppliedFont = font_name
                break
            except Exception:
                continue

        # Поворот
        if paragraph.angle in (90, 270):
            try:
                tf.RotationAngle = 270 if paragraph.angle == 90 else 90
            except Exception:
                pass

    @staticmethod
    def _add_mask(
        doc, page_obj, layer_boxes,
        top_pt, left_pt, bottom_pt, right_pt,
    ) -> None:
        """Белый прямоугольник под оригинальный текст."""
        try:
            paper_swatch = doc.Swatches.Item("Paper")
        except Exception:
            paper_swatch = None

        bg_rect = page_obj.Rectangles.Add(layer_boxes)
        bg_rect.GeometricBounds = [top_pt, left_pt, bottom_pt, right_pt]
        if paper_swatch is not None:
            bg_rect.FillColor = paper_swatch
        bg_rect.StrokeWeight = 0