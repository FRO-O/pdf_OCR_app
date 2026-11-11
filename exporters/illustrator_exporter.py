"""
Экспорт в Adobe Illustrator через COM (Windows).

Логика:
1. Подключаемся к Illustrator.
2. Если исходник — PDF, открываем его. Иначе создаём новый документ
   нужного размера и кладём картинку как PlacedItem.
3. Artboards = страницы (по одной на каждую).
4. Слои: «Оригинал схемы», «Плашки (Фон)», «Живой текст».
5. Для каждой надписи — PointText (точечный текст) на слое «Живой текст».

Ключевые улучшения:
- Работа с Paragraph/PageData.
- Единый расчёт размера шрифта.
- try/except на каждой надписи — сбой одной не рушит экспорт.
- Явное приведение координат к float (Illustrator API капризен
  к типам numpy).

ВАЖНО: работает только на Windows (COM).
"""

from __future__ import annotations

import logging
import os

from core.page import PageData, Paragraph

from .base import BaseExporter, ExportOptions


logger = logging.getLogger(__name__)


# Константы Illustrator API
AI_COLOR_WHITE = (255, 255, 255)

# Смещение точки TextFrame относительно центра bbox по вертикали.
# Illustrator позиционирует точку по baseline, а мы работаем с bbox.
POINT_TEXT_Y_OFFSET_FACTOR = 0.75


class IllustratorExporter(BaseExporter):
    """Экспортёр в Adobe Illustrator."""

    @property
    def file_extension(self) -> str:
        return ".ai"

    def export(
        self,
        source_path: str,
        pages: list[PageData],
        options: ExportOptions,
    ) -> str:
        if not pages:
            raise RuntimeError("Нет страниц для экспорта.")

        options.log("Экспорт в Adobe Illustrator...")

        try:
            app = self._connect_illustrator()
        except Exception as e:
            raise RuntimeError(
                f"Не удалось подключиться к Adobe Illustrator: {e}. "
                f"Убедитесь, что Illustrator установлен и доступен через COM."
            ) from e

        first = pages[0]
        abs_source = os.path.abspath(source_path)
        is_pdf = source_path.lower().endswith(".pdf")

        try:
            if is_pdf:
                doc = app.Open(abs_source)
            else:
                doc = self._create_document(app, first, abs_source)
        except Exception as e:
            raise RuntimeError(
                f"Не удалось открыть/создать документ Illustrator: {e}"
            ) from e

        layers = self._setup_layers(doc, options)
        white_color = self._make_white_color(app)

        for idx, page in enumerate(pages):
            try:
                self._add_page_content(
                    doc, page, layers, white_color, options,
                )
                options.log(
                    f"  Страница {idx + 1}/{len(pages)}: "
                    f"{len(page.paragraphs)} надписей"
                )
            except Exception as e:
                options.log(f"    Ошибка страницы {idx + 1}: {e}")
                logger.exception("Illustrator страница %d: %s", idx + 1, e)

        # Сохраняем
        output_path = options.output_path or self.default_output_path(source_path)
        try:
            doc.SaveAs(os.path.abspath(output_path))
        except Exception as e:
            raise RuntimeError(
                f"Не удалось сохранить документ Illustrator: {e}"
            ) from e

        options.log(f"Документ Illustrator сохранён: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Подключение и создание документа
    # ------------------------------------------------------------------

    @staticmethod
    def _connect_illustrator():
        try:
            import win32com.client
        except ImportError as e:
            raise RuntimeError(
                "pywin32 не установлен. Установите: pip install pywin32"
            ) from e

        try:
            app = win32com.client.GetActiveObject("Illustrator.Application")
        except Exception:
            app = win32com.client.Dispatch("Illustrator.Application")
        return app

    def _create_document(self, app, first_page: PageData, image_path: str):
        """Создаёт документ и кладёт картинку на первый слой."""
        doc = app.Documents.Add(
            1,
            float(first_page.page_w_pt),
            float(first_page.page_h_pt),
        )
        try:
            layer_bg = doc.Layers(1)
            layer_bg.Name = "Оригинал схемы"
        except Exception:
            pass

        try:
            item = doc.Layers(1).PlacedItems.Add()
            item.File = image_path
            item.Left = 0.0
            item.Top = float(first_page.page_h_pt)
            item.Width = float(first_page.page_w_pt)
            item.Height = float(first_page.page_h_pt)
        except Exception as e:
            logger.exception("Illustrator PlacedItem: %s", e)

        return doc

    def _setup_layers(self, doc, options: ExportOptions) -> dict:
        layers = {"boxes": None, "text": None}

        if options.hide_orig_text:
            try:
                layers["boxes"] = doc.Layers.Item("Плашки (Фон)")
            except Exception:
                layers["boxes"] = doc.Layers.Add()
                layers["boxes"].Name = "Плашки (Фон)"

        try:
            layers["text"] = doc.Layers.Item("Живой текст")
        except Exception:
            layers["text"] = doc.Layers.Add()
            layers["text"].Name = "Живой текст"

        return layers

    @staticmethod
    def _make_white_color(app):
        """Создаёт RGBColor-объект для белого."""
        try:
            color = app.RGBColor
            color.Red = AI_COLOR_WHITE[0]
            color.Green = AI_COLOR_WHITE[1]
            color.Blue = AI_COLOR_WHITE[2]
            return color
        except Exception:
            import win32com.client
            color = win32com.client.Dispatch("Illustrator.RGBColor")
            color.Red = AI_COLOR_WHITE[0]
            color.Green = AI_COLOR_WHITE[1]
            color.Blue = AI_COLOR_WHITE[2]
            return color

    # ------------------------------------------------------------------
    # Одна страница
    # ------------------------------------------------------------------

    def _add_page_content(
        self, doc, page: PageData, layers: dict,
        white_color, options: ExportOptions,
    ) -> None:
        # Смещение артборда (для многостраничных документов)
        try:
            artboard = doc.Artboards(page.page_num)
            ab_rect = artboard.ArtboardRect
            ab_left = float(ab_rect[0])
            ab_top = float(ab_rect[1])
        except Exception:
            ab_left = 0.0
            ab_top = float(page.page_h_pt)

        for paragraph in page.paragraphs:
            try:
                self._add_paragraph(
                    doc, page, paragraph, layers,
                    white_color, ab_left, ab_top, options,
                )
            except Exception as e:
                options.log(
                    f"    Пропущена надпись '{paragraph.text[:20]}': {e}"
                )

    # ------------------------------------------------------------------
    # Одна надпись
    # ------------------------------------------------------------------

    def _add_paragraph(
        self, doc, page: PageData, paragraph: Paragraph, layers: dict,
        white_color, ab_left: float, ab_top: float, options: ExportOptions,
    ) -> None:
        # Координаты в pt, приведённые к системе артборда
        x1_pt = float(paragraph.x1) * page.scale_x + ab_left
        y1_pt = ab_top - (float(paragraph.y1) * page.scale_y)
        w_pt = float(paragraph.w) * page.scale_x
        h_pt = float(paragraph.h) * page.scale_y

        # 1. Подложка
        if options.hide_orig_text and layers["boxes"] is not None:
            try:
                rect_bg = layers["boxes"].PathItems.Rectangle(
                    y1_pt, x1_pt, w_pt, h_pt
                )
                rect_bg.FillColor = white_color
                rect_bg.Filled = True
                rect_bg.Stroked = False
            except Exception as e:
                logger.debug("Illustrator mask: %s", e)

        # 2. Размер шрифта
        font_size = self.compute_font_size(
            paragraph, page,
            font_scale=options.font_scale,
            min_size=options.min_font_size,
            max_size=options.max_font_size,
        )

        # 3. PointText
        # Illustrator позиционирует текст по baseline, а мы — по bbox.
        # Смещаем точку вниз, чтобы baseline оказался примерно
        # на 75% высоты bbox (эмпирически даёт визуально верный результат).
        text_y = y1_pt - (h_pt * POINT_TEXT_Y_OFFSET_FACTOR)

        tf = layers["text"].TextFrames.PointText([x1_pt, text_y])
        tf.Contents = str(paragraph.text)

        # Параметры текста
        tr = tf.Story.TextRange
        tr.CharacterAttributes.Size = font_size
        tr.CharacterAttributes.Leading = font_size * 1.15

        # 4. Поворот
        if paragraph.angle in (90, 270):
            try:
                # Illustrator Rotate принимает угол в градусах.
                # Знак: -90 для 90°, +90 для 270° (потому что
                # Illustrator крутит по часовой, а «угол чтения»
                # считается против).
                tf.Rotate(-90.0 if paragraph.angle == 90 else 90.0)
            except Exception:
                pass