"""
Точка входа приложения.
"""

from __future__ import annotations

import os
import sys
import site
import logging

# --- ОТКЛЮЧАЕМ ПРОВЕРКУ МОДЕЛЕЙ PADDLEOCR ---
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

# --- АВТОМАТИЧЕСКИ ПРОПИСЫВАЕМ ПУТИ К CUDA (чтобы Paddle видел GPU) ---
try:
    site_packages = site.getsitepackages()
    nvidia_dirs = []
    for sp in site_packages:
        nvidia_path = os.path.join(sp, "nvidia")
        if os.path.exists(nvidia_path):
            for item in os.listdir(nvidia_path):
                bin_path = os.path.join(nvidia_path, item, "bin")
                if os.path.exists(bin_path):
                    nvidia_dirs.append(bin_path)
    
    if nvidia_dirs:
        os.environ["PATH"] = os.pathsep.join(nvidia_dirs) + os.pathsep + os.environ["PATH"]
        print(f"[GPU] Добавлено {len(nvidia_dirs)} путей к CUDA в PATH.")
except Exception as e:
    print(f"[GPU] Не удалось автоматически прописать пути к CUDA: {e}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

def main() -> int:
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("КРИТИЧНО: PyQt6 не установлен.", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("PDF/Image OCR → Office")
    app.setOrganizationName("PDFOCRApp")

    from app.dependency_check import build_report_dialog, run_dependency_check
    report = run_dependency_check()

    if not report.can_run:
        dlg = build_report_dialog(report)
        dlg.setWindowTitle("Не запустить: отсутствуют критичные пакеты")
        dlg.exec()
        return 2

    if report.has_warnings:
        dlg = build_report_dialog(report)
        dlg.exec()

    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    return app.exec()

if __name__ == "__main__":
    sys.exit(main())