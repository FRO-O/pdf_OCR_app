"""
Экспорт в MS Word (.docx) как в FineReader: живой текст и таблицы.
"""
from __future__ import annotations
import os
import logging
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from lxml import html as lxml_html

from core.page import PageData, Paragraph
from .base import BaseExporter, ExportOptions

logger = logging.getLogger(__name__)

class DOCXDocumentExporter(BaseExporter):
    @property
    def file_extension(self) -> str:
        return ".docx"

    def export(self, source_path: str, pages: list[PageData], options: ExportOptions) -> str:
        if not pages:
            raise RuntimeError("Нет страниц для экспорта.")
        
        options.log("Экспорт в MS Word (.docx) как документ...")

        output_path = options.output_path or self.default_output_path(source_path)
        if output_path.endswith("_vector.docx"):
            output_path = output_path.replace("_vector.docx", "_doc.docx")

        if os.path.exists(output_path):
            try:
                with open(output_path, "ab"): pass
            except PermissionError:
                base, ext = os.path.splitext(output_path)
                for i in range(1, 100):
                    new_path = f"{base}_v{i}{ext}"
                    if not os.path.exists(new_path):
                        output_path = new_path
                        break

        doc = Document()
        
        section = doc.sections[0]
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)

        for page in pages:
            # Убрали "Страница #". Сразу переходим к тексту.
            if not page.paragraphs:
                doc.add_paragraph("[Текст не найден]")
                continue

            for p in page.paragraphs:
                if p.is_table and p.table_html:
                    self._add_table_from_html(doc, p.table_html)
                    doc.add_paragraph() # Отступ после таблицы
                else:
                    # Добавляем обычный абзац
                    para = doc.add_paragraph(p.text)
                    para.paragraph_format.space_after = Pt(4)

            # Разрыв страницы между страницами
            doc.add_page_break()

        try:
            doc.save(output_path)
        except Exception as e:
            raise RuntimeError(f"Не удалось сохранить {output_path}: {e}") from e

        options.log(f"Документ Word сохранён: {output_path}")
        return output_path

    def _add_table_from_html(self, doc, html_content: str):
        """Парсит HTML и создает нативную таблицу Word."""
        try:
            tree = lxml_html.fromstring(html_content)
            rows = tree.xpath('//tr')
            if not rows: return
            
            num_rows = len(rows)
            num_cols = max(len(r.xpath('./td|./th')) for r in rows)
            
            table = doc.add_table(rows=num_rows, cols=num_cols)
            table.style = 'Table Grid'
            
            for r_idx, row in enumerate(rows):
                cells = row.xpath('./td|./th')
                c_idx = 0
                for cell in cells:
                    if c_idx >= num_cols: break
                    
                    text = " ".join(cell.text_content().split())
                    colspan = int(cell.get('colspan', 1))
                    rowspan = int(cell.get('rowspan', 1))
                    
                    try:
                        # Объединяем ячейки, если нужно
                        if colspan > 1 or rowspan > 1:
                            table.cell(r_idx, c_idx).merge(
                                table.cell(r_idx + rowspan - 1, c_idx + colspan - 1)
                            )
                        
                        # Заполняем текст
                        table_cell = table.cell(r_idx, c_idx)
                        table_cell.text = text
                        
                        # Форматирование
                        for p in table_cell.paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(10)
                                run.font.name = "Arial"
                    except Exception as e:
                        logger.debug("Ошибка заполнения ячейки таблицы Word: %s", e)
                    
                    c_idx += colspan
        except Exception as e:
            logger.error("Ошибка парсинга HTML таблицы для Word: %s", e)