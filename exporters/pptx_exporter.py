"""
Экспорт в MS PowerPoint (.pptx).
"""
from __future__ import annotations
import os
import logging
from typing import Optional

from PIL import ImageFont
from pptx import Presentation
from pptx.util import Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

from core.page import PageData, Paragraph
from .base import BaseExporter, ExportOptions

logger = logging.getLogger(__name__)

MASK_PADDING_PT = 0.5
MAX_SLIDE_SIZE_PT = 4000.0

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}

def _get_measure_font(size_pt: int) -> ImageFont.FreeTypeFont:
    size = max(6, min(200, int(size_pt)))
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            _FONT_CACHE[size] = font
            return font
        except (OSError, IOError):
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font

class PPTXExporter(BaseExporter):
    @property
    def file_extension(self) -> str:
        return ".pptx"

    def export(self, source_path: str, pages: list[PageData], options: ExportOptions) -> str:
        if not pages:
            raise RuntimeError("Нет страниц для экспорта.")
        options.log("Экспорт в MS PowerPoint (.pptx)...")

        output_path = options.output_path or self.default_output_path(source_path)
        
        if os.path.exists(output_path):
            try:
                with open(output_path, "ab"): pass
            except PermissionError:
                base, ext = os.path.splitext(output_path)
                for i in range(1, 100):
                    new_path = f"{base}_v{i}{ext}"
                    if not os.path.exists(new_path):
                        output_path = new_path
                        options.log(f"  ⚠ Старый файл занят. Сохраняем как: {os.path.basename(output_path)}")
                        break

        prs = Presentation()
        first = pages[0]
        
        w_pt = first.page_w_pt
        h_pt = first.page_h_pt
        scale_factor = 1.0
        
        if w_pt > MAX_SLIDE_SIZE_PT or h_pt > MAX_SLIDE_SIZE_PT:
            scale_factor = min(MAX_SLIDE_SIZE_PT / w_pt, MAX_SLIDE_SIZE_PT / h_pt)
            w_pt = w_pt * scale_factor
            h_pt = h_pt * scale_factor
            options.log(f"  ⚠ Изображение слишком большое. Масштабируем слайд на {scale_factor:.2f}")

        prs.slide_width = Pt(w_pt)
        prs.slide_height = Pt(h_pt)
        blank_layout = prs.slide_layouts[6]

        for idx, page in enumerate(pages):
            self._add_slide(prs, blank_layout, page, options, scale_factor)
            options.log(f"  Слайд {idx + 1}/{len(pages)}: {len(page.paragraphs)} надписей")

        try:
            prs.save(output_path)
        except Exception as e:
            raise RuntimeError(f"Не удалось сохранить {output_path}: {e}") from e

        options.log(f"Презентация сохранена: {output_path}")
        return output_path

    def _add_slide(self, prs: Presentation, layout, page: PageData, options: ExportOptions, scale_factor: float = 1.0) -> None:
        slide = prs.slides.add_slide(layout)

        temp_path = self.temp_file(suffix=".png")
        try:
            page.image.save(temp_path, format="PNG")
            slide.shapes.add_picture(temp_path, 0, 0, width=Pt(page.page_w_pt * scale_factor), height=Pt(page.page_h_pt * scale_factor))
        finally:
            self.safe_remove(temp_path)

        for paragraph in page.paragraphs:
            try:
                if paragraph.is_table and paragraph.table_html:
                    self._add_table(slide, paragraph, page, scale_factor)
                else:
                    self._add_text_shape(slide, paragraph, page, options, scale_factor)
            except Exception as e:
                options.log(f"    Пропущена надпись '{paragraph.text[:20]}': {e}")
                logger.exception("Ошибка вставки текста: %s", e)

    def _add_table(self, slide, paragraph: Paragraph, page: PageData, scale_factor: float) -> None:
        from lxml import html as lxml_html
        try:
            tree = lxml_html.fromstring(paragraph.table_html)
        except Exception:
            return

        rows = tree.xpath('//tr')
        if not rows: return

        num_rows = len(rows)
        num_cols = max(len(r.xpath('./td|./th')) for r in rows)

        left_pt = paragraph.x1 * page.scale_x * scale_factor
        top_pt = paragraph.y1 * page.scale_y * scale_factor
        width_pt = paragraph.w * page.scale_x * scale_factor
        height_pt = paragraph.h * page.scale_y * scale_factor

        shape = slide.shapes.add_table(num_rows, num_cols, Pt(left_pt), Pt(top_pt), Pt(width_pt), Pt(height_pt))
        table = shape.table

        for r_idx, row in enumerate(rows):
            cells = row.xpath('./td|./th')
            c_idx = 0
            for cell in cells:
                if c_idx >= num_cols: break
                
                text = " ".join(cell.text_content().split())
                colspan = int(cell.get('colspan', 1))
                rowspan = int(cell.get('rowspan', 1))
                
                try:
                    if colspan > 1 or rowspan > 1:
                        table.cell(r_idx, c_idx).merge(table.cell(r_idx + rowspan - 1, c_idx + colspan - 1))
                    
                    table_cell = table.cell(r_idx, c_idx)
                    table_cell.text = text
                    
                    for p in table_cell.text_frame.paragraphs:
                        p.font.size = Pt(10)
                        p.font.name = "Arial"
                except Exception:
                    pass
                
                c_idx += colspan

    def _add_text_shape(self, slide, paragraph: Paragraph, page: PageData, options: ExportOptions, scale_factor: float = 1.0) -> None:
        left_pt = paragraph.x1 * page.scale_x * scale_factor
        top_pt = paragraph.y1 * page.scale_y * scale_factor
        bbox_w = max(4.0, paragraph.w * page.scale_x * scale_factor)
        angle = paragraph.angle

        font_size = self.compute_font_size(
            paragraph, page, font_scale=options.font_scale, min_size=options.min_font_size, max_size=options.max_font_size,
        )
        font_size *= scale_factor
        
        # Округление шрифта
        font_size = round(font_size * 2) / 2

        if options.fit_to_bbox and paragraph.text:
            font_size = self._fit_font_to_width(
                text=paragraph.text, max_width_pt=bbox_w, initial_size=font_size, min_size=options.min_font_size,
            )
            font_size = round(font_size * 2) / 2

        tight_h = font_size * 1.25 

        if options.hide_orig_text:
            self._add_mask(slide, left_pt, top_pt, bbox_w, tight_h, paragraph.bg_color)

        if angle in (90, 270):
            self._add_rotated_textbox(slide, paragraph, left_pt, top_pt, bbox_w, tight_h, font_size, angle)
        elif angle == 180:
            self._add_textbox_180(slide, left_pt, top_pt, bbox_w, tight_h, paragraph.text, font_size)
        else:
            self._add_normal_textbox(slide, left_pt, top_pt, bbox_w, tight_h, paragraph.text, font_size)

    @staticmethod
    def _add_mask(slide, left_pt, top_pt, width_pt, height_pt, bg_color: tuple[int, int, int]) -> None:
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Pt(left_pt - MASK_PADDING_PT), Pt(top_pt - MASK_PADDING_PT),
            Pt(width_pt + MASK_PADDING_PT * 2), Pt(height_pt + MASK_PADDING_PT * 2),
        )
        shape.fill.solid()
        # Применяем умный цвет
        shape.fill.fore_color.rgb = RGBColor(bg_color[0], bg_color[1], bg_color[2])
        shape.line.fill.background()
        shape.shadow.inherit = False

    def _add_normal_textbox(self, slide, left_pt, top_pt, width_pt, height_pt, text: str, font_size: float) -> None:
        txBox = slide.shapes.add_textbox(Pt(left_pt), Pt(top_pt), Pt(width_pt + 5.0), Pt(height_pt))
        self._fill_textbox(txBox, text, font_size)

    def _add_textbox_180(self, slide, left_pt, top_pt, width_pt, height_pt, text: str, font_size: float) -> None:
        txBox = slide.shapes.add_textbox(Pt(left_pt), Pt(top_pt), Pt(width_pt + 5.0), Pt(height_pt))
        txBox.rotation = 180
        self._fill_textbox(txBox, text, font_size)

    def _add_rotated_textbox(self, slide, paragraph: Paragraph, left_pt, top_pt, width_pt, height_pt, font_size: float, angle: int) -> None:
        box_w = height_pt
        box_h = width_pt + 5.0
        center_x = left_pt + width_pt / 2.0
        center_y = top_pt + height_pt / 2.0
        txBox = slide.shapes.add_textbox(Pt(center_x - box_w / 2.0), Pt(center_y - box_h / 2.0), Pt(box_w), Pt(box_h))
        txBox.rotation = 90 if angle == 90 else 270
        self._fill_textbox(txBox, paragraph.text, font_size)

    @staticmethod
    def _fill_textbox(txBox, text: str, font_size: float) -> None:
        tf = txBox.text_frame
        tf.word_wrap = False
        
        tf.margin_left = Pt(0)
        tf.margin_right = Pt(0)
        tf.margin_top = Pt(0)
        tf.margin_bottom = Pt(0)

        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT
        p.text = text
        p.font.size = Pt(font_size)
        p.font.name = "Arial"
        p.font.color.rgb = RGBColor(0, 0, 0)

    @staticmethod
    def _fit_font_to_width(text: str, max_width_pt: float, initial_size: float, min_size: float) -> float:
        if max_width_pt <= 0 or not text: return initial_size
        size = initial_size
        lo, hi = float(min_size), float(initial_size)
        best = min_size
        while hi - lo > 0.5:
            mid = (lo + hi) / 2.0
            measured = PPTXExporter._measure_text_width(text, mid)
            if measured <= max_width_pt:
                best = mid; lo = mid
            else:
                hi = mid
        if PPTXExporter._measure_text_width(text, initial_size) <= max_width_pt: return initial_size
        return max(min_size, best)

    @staticmethod
    def _measure_text_width(text: str, size_pt: float) -> float:
        try:
            font = _get_measure_font(int(round(size_pt)))
            bbox = font.getbbox(text)
            return float(bbox[2] - bbox[0])
        except Exception:
            return len(text) * size_pt * 0.55