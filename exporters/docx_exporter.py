"""
Экспорт в MS Word (.docx) для перевода.
"""
from __future__ import annotations
import os
import logging
from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from core.page import PageData
from .base import BaseExporter, ExportOptions

logger = logging.getLogger(__name__)

def set_run_hidden(run):
    """Делает текст скрытым в Word (не попадает в экспорт для переводчика)."""
    rPr = run._element.get_or_add_rPr()
    # Проверяем, нет ли уже тега vanish
    if not rPr.find(qn('w:vanish')):
        vanish = OxmlElement('w:vanish')
        rPr.append(vanish)

class DOCXExporter(BaseExporter):
    @property
    def file_extension(self) -> str:
        return ".docx"

    def export(self, source_path: str, pages: list[PageData], options: ExportOptions) -> str:
        if not pages:
            raise RuntimeError("Нет страниц для экспорта.")
        
        options.log("Экспорт в MS Word (.docx)...")

        output_path = options.output_path or self.default_output_path(source_path)
        if not output_path.endswith(".docx"):
            output_path = output_path.replace("_vector", "_translation")

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
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)

        for page in pages:
            # 1. Скрытое имя файла НАД таблицей
            p_name = doc.add_paragraph()
            run_name = p_name.add_run(f"Файл: {os.path.basename(page.source_path)}")
            set_run_hidden(run_name)
            
            # 2. Картинка
            temp_path = self.temp_file(suffix=".png")
            try:
                page.image.save(temp_path, format="PNG")
                doc.add_picture(temp_path, width=Inches(6.0))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            finally:
                self.safe_remove(temp_path)

            # 3. Таблица (две колонки, по строке на каждый фрагмент)
            num_rows = max(1, len(page.paragraphs))
            table = doc.add_table(rows=num_rows, cols=2)
            table.style = 'Table Grid'
            table.autofit = True

            if not page.paragraphs:
                # Если текста нет, оставляем пустую таблицу
                pass
            else:
                for i, p in enumerate(page.paragraphs):
                    # Левая колонка: СКРЫТЫЙ ОРИГИНАЛ
                    cell_left = table.cell(i, 0)
                    p_left = cell_left.paragraphs[0]
                    run_l = p_left.add_run(p.text)
                    set_run_hidden(run_l)

                    # Правая колонка: ВИДИМЫЙ ТЕКСТ ДЛЯ ПЕРЕВОДА
                    cell_right = table.cell(i, 1)
                    cell_right.text = p.text

            # Пустой абзац между страницами
            doc.add_paragraph() 

        try:
            doc.save(output_path)
        except Exception as e:
            raise RuntimeError(f"Не удалось сохранить {output_path}: {e}") from e

        options.log(f"Файл Word сохранён: {output_path}")
        return output_path