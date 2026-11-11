"""
Проверка зависимостей и железа при старте приложения.

Логика:
- Критичные пакеты (PyQt6, Pillow, numpy) — блокируют запуск.
- Функциональные (PyMuPDF, python-pptx, easyocr, ...) — предупреждение,
  соответствующая вкладка/функция отключается.
- Железо (RAM, GPU) — мягкое предупреждение с рекомендациями.
"""

from __future__ import annotations

import importlib
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Описание требований
# ---------------------------------------------------------------------------

@dataclass
class PackageRequirement:
    name: str                 # имя для импорта (например, "PyQt6")
    pip_name: str             # имя для pip (например, "PyQt6" или "python-pptx")
    min_version: str          # минимальная версия "6.5.0" или "" если не важно
    purpose: str              # зачем нужен — показывается пользователю
    critical: bool = False    # True = блокирует запуск
    size_mb: int = 0          # примерный размер на диске
    note: str = ""            # дополнительная информация (например, про модели)


# Критичные пакеты — без них программа не запустится.
CRITICAL_PACKAGES: list[PackageRequirement] = [
    PackageRequirement(
        name="PyQt6", pip_name="PyQt6", min_version="6.5.0",
        purpose="Интерфейс программы",
        critical=True, size_mb=80,
    ),
    PackageRequirement(
        name="PIL", pip_name="Pillow", min_version="10.0.0",
        purpose="Работа с изображениями",
        critical=True, size_mb=10,
    ),
    PackageRequirement(
        name="numpy", pip_name="numpy", min_version="1.24.0",
        purpose="Численные вычисления",
        critical=True, size_mb=30,
    ),
]


# Функциональные пакеты — предупреждение, но не блокируют.
# Отключение помечается флагом `critical=False`, UI сам решит,
# какие вкладки/кнопки сделать неактивными.
OPTIONAL_PACKAGES: list[PackageRequirement] = [
    PackageRequirement(
        name="fitz", pip_name="PyMuPDF", min_version="1.24.0",
        purpose="Обработка PDF (рендер + векторный текст)",
        critical=False, size_mb=25,
    ),
    PackageRequirement(
        name="pptx", pip_name="python-pptx", min_version="0.6.21",
        purpose="Экспорт в MS PowerPoint",
        critical=False, size_mb=10,
    ),
    PackageRequirement(
        name="easyocr", pip_name="easyocr", min_version="1.7.0",
        purpose="OCR-распознавание (сканы, скриншоты)",
        critical=False, size_mb=150,
        note="Плюс 100–200 МБ на каждый язык (скачивается при первом запуске OCR).",
    ),
    PackageRequirement(
        name="cv2", pip_name="opencv-python", min_version="4.8.0",
        purpose="Обработка изображений (препроцессинг)",
        critical=False, size_mb=60,
    ),
    PackageRequirement(
        name="win32com", pip_name="pywin32", min_version="306",
        purpose="Экспорт в Adobe InDesign / Illustrator",
        critical=False, size_mb=15,
        note="Только для Windows.",
    ),
    PackageRequirement(
        name="psutil", pip_name="psutil", min_version="5.9.0",
        purpose="Диагностика системы (RAM, нагрузка)",
        critical=False, size_mb=2,
    ),
    PackageRequirement(
        name="torch", pip_name="torch", min_version="2.0.0",
        purpose="GPU-ускорение OCR (опционально)",
        critical=False, size_mb=2500,
        note=(
            "CPU-версия ~200 МБ, CUDA-версия ~2.5 ГБ. "
            "Без torch OCR работает на CPU (медленнее в 5–10 раз). "
            "Установка GPU-версии: "
            "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Результаты проверки
# ---------------------------------------------------------------------------

@dataclass
class PackageStatus:
    req: PackageRequirement
    installed: bool = False
    version: Optional[str] = None
    problem: str = ""          # "missing", "too_old", "import_error: ..."

    @property
    def ok(self) -> bool:
        return self.installed and not self.problem


@dataclass
class HardwareStatus:
    os_name: str = ""
    python_version: str = ""
    cpu_cores: int = 0
    ram_gb: float = 0.0
    gpu_name: str = ""
    vram_gb: float = 0.0
    cuda_available: bool = False
    torch_installed: bool = False
    free_disk_gb: float = 0.0
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class DependencyReport:
    critical_failed: list[PackageStatus] = field(default_factory=list)
    optional_missing: list[PackageStatus] = field(default_factory=list)
    optional_outdated: list[PackageStatus] = field(default_factory=list)
    hardware: HardwareStatus = field(default_factory=HardwareStatus)

    @property
    def can_run(self) -> bool:
        return len(self.critical_failed) == 0

    @property
    def has_warnings(self) -> bool:
        return (
            bool(self.optional_missing)
            or bool(self.optional_outdated)
            or bool(self.hardware.warnings)
        )


# ---------------------------------------------------------------------------
# Проверка версий
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...]:
    """'6.5.1' -> (6, 5, 1). Без учёта pre-release."""
    parts = []
    for p in v.split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _version_ge(actual: str, minimum: str) -> bool:
    if not minimum:
        return True
    return _parse_version(actual) >= _parse_version(minimum)


def _check_package(req: PackageRequirement) -> PackageStatus:
    status = PackageStatus(req=req)
    try:
        module = importlib.import_module(req.name)
    except ImportError:
        status.problem = "missing"
        return status
    except Exception as e:
        # Редкий случай: пакет есть, но падает при импорте (например, DLL).
        status.problem = f"import_error: {e}"
        return status

    status.installed = True
    version = getattr(module, "__version__", None)
    if version is None:
        # Некоторые пакеты (например, easyocr) не выставляют __version__.
        try:
            from importlib.metadata import version as md_version
            version = md_version(req.pip_name)
        except Exception:
            version = "unknown"
    status.version = str(version)

    if req.min_version and version != "unknown":
        if not _version_ge(str(version), req.min_version):
            status.problem = "too_old"

    return status


# ---------------------------------------------------------------------------
# Проверка железа
# ---------------------------------------------------------------------------

def _check_hardware() -> HardwareStatus:
    hw = HardwareStatus()
    hw.os_name = f"{platform.system()} {platform.release()}"
    hw.python_version = platform.python_version()

    # --- CPU и RAM через psutil ---
    try:
        import psutil
        hw.cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 0
        hw.ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        hw.cpu_cores = 0
        hw.ram_gb = 0.0

    # --- Свободное место на диске (для моделей OCR) ---
    try:
        easyocr_dir = Path.home() / ".EasyOCR"
        # Если папки ещё нет — проверяем домашнюю директорию,
        # т.к. .EasyOCR создастся именно там.
        check_path = easyocr_dir if easyocr_dir.exists() else Path.home()
        _, _, free = shutil.disk_usage(str(check_path))
        hw.free_disk_gb = free / (1024 ** 3)
    except Exception:
        hw.free_disk_gb = 0.0

    # --- GPU через torch (единственный надёжный способ без WMI) ---
    try:
        import torch
        hw.torch_installed = True
        if torch.cuda.is_available():
            hw.cuda_available = True
            try:
                props = torch.cuda.get_device_properties(0)
                hw.gpu_name = props.name
                hw.vram_gb = props.total_memory / (1024 ** 3)
            except Exception:
                hw.gpu_name = "NVIDIA GPU (unknown)"
    except ImportError:
        hw.torch_installed = False

    # --- Формируем предупреждения и рекомендации ---

    if hw.ram_gb and hw.ram_gb < 8:
        hw.warnings.append(
            f"Мало оперативной памяти: {hw.ram_gb:.1f} ГБ "
            f"(минимум 8 ГБ, рекомендуем 16 ГБ)."
        )
        hw.recommendations.append(
            "Ограничьте набор языков до 2 (например, ru + en) — "
            "каждый язык загружает отдельную модель."
        )
        hw.recommendations.append(
            "Не запускайте обработку больших PDF (50+ страниц) за один раз."
        )
    elif hw.ram_gb and hw.ram_gb < 16:
        hw.recommendations.append(
            f"ОЗУ: {hw.ram_gb:.1f} ГБ — достаточно, но для больших PDF "
            f"рекомендуем 16 ГБ."
        )

    if not hw.torch_installed:
        hw.warnings.append(
            "PyTorch (torch) не установлен — GPU-режим OCR недоступен. "
            "OCR будет работать на CPU (медленнее в 5–10 раз)."
        )
        hw.recommendations.append(
            "Для GPU-режима: pip install torch torchvision --index-url "
            "https://download.pytorch.org/whl/cu121"
        )
    elif not hw.cuda_available:
        hw.warnings.append(
            "CUDA недоступна — OCR будет работать на CPU. "
            "Если у вас NVIDIA GPU, переустановите torch с поддержкой CUDA."
        )
    else:
        # CUDA есть, смотрим VRAM.
        if hw.vram_gb and hw.vram_gb < 2:
            hw.warnings.append(
                f"Мало видеопамяти: {hw.vram_gb:.1f} ГБ "
                f"(минимум 2 ГБ для EasyOCR)."
            )
            hw.recommendations.append(
                "Отключите GPU-режим в настройках — на CPU будет стабильнее."
            )
        elif hw.vram_gb and hw.vram_gb < 4:
            hw.recommendations.append(
                f"VRAM: {hw.vram_gb:.1f} ГБ — хватит для 2–3 языков. "
                f"Для большого набора рекомендуем 4+ ГБ."
            )

    if hw.cpu_cores and hw.cpu_cores < 4:
        hw.warnings.append(
            f"Мало ядер CPU: {hw.cpu_cores} (минимум 4, рекомендуем 8)."
        )

    if hw.free_disk_gb and hw.free_disk_gb < 2:
        hw.warnings.append(
            f"Мало свободного места на диске: {hw.free_disk_gb:.1f} ГБ. "
            f"Модели OCR могут не поместиться."
        )

    return hw


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def run_dependency_check() -> DependencyReport:
    """Полная проверка. Вызывается один раз при старте приложения."""
    report = DependencyReport()

    for req in CRITICAL_PACKAGES:
        st = _check_package(req)
        if not st.ok:
            report.critical_failed.append(st)

    for req in OPTIONAL_PACKAGES:
        st = _check_package(req)
        if st.problem == "missing":
            report.optional_missing.append(st)
        elif st.problem == "too_old":
            report.optional_outdated.append(st)

    report.hardware = _check_hardware()
    return report


def format_report_text(report: DependencyReport) -> str:
    """Формирует читаемый текст для консоли или лога."""
    lines: list[str] = []
    hw = report.hardware

    lines.append("=== Система ===")
    lines.append(f"OS: {hw.os_name}")
    lines.append(f"Python: {hw.python_version}")
    if hw.cpu_cores:
        lines.append(f"CPU: {hw.cpu_cores} ядер")
    if hw.ram_gb:
        lines.append(f"RAM: {hw.ram_gb:.1f} ГБ")
    if hw.free_disk_gb:
        lines.append(f"Свободно на диске: {hw.free_disk_gb:.1f} ГБ")
    if hw.gpu_name:
        lines.append(f"GPU: {hw.gpu_name} ({hw.vram_gb:.1f} ГБ VRAM)")
        lines.append(f"CUDA: {'да' if hw.cuda_available else 'нет'}")
    else:
        lines.append("GPU: не обнаружена")

    if report.critical_failed:
        lines.append("\n=== КРИТИЧНО (запуск невозможен) ===")
        for st in report.critical_failed:
            lines.append(
                f"  ✗ {st.req.pip_name} "
                f"(нужно >= {st.req.min_version}) — {st.req.purpose}"
            )
            lines.append(f"    pip install {st.req.pip_name}")

    if report.optional_missing:
        lines.append("\n=== Отсутствуют (функция будет недоступна) ===")
        for st in report.optional_missing:
            lines.append(
                f"  • {st.req.pip_name} — {st.req.purpose}"
                f" (~{st.req.size_mb} МБ)"
            )
            lines.append(f"    pip install {st.req.pip_name}")
            if st.req.note:
                lines.append(f"    ℹ {st.req.note}")

    if report.optional_outdated:
        lines.append("\n=== Устаревшие версии ===")
        for st in report.optional_outdated:
            lines.append(
                f"  • {st.req.pip_name}: {st.version} "
                f"(рекомендуем >= {st.req.min_version})"
            )
            lines.append(f"    pip install --upgrade {st.req.pip_name}")

    if hw.warnings:
        lines.append("\n=== Предупреждения по железу ===")
        for w in hw.warnings:
            lines.append(f"  ⚠ {w}")

    if hw.recommendations:
        lines.append("\n=== Рекомендации ===")
        for r in hw.recommendations:
            lines.append(f"  → {r}")

    if not report.critical_failed and not report.has_warnings:
        lines.append("\n✓ Все зависимости на месте, железо в норме.")

    return "\n".join(lines)


def get_pip_install_commands(report: DependencyReport) -> list[str]:
    """Список команд pip для копирования в буфер."""
    cmds: list[str] = []
    for st in report.critical_failed + report.optional_missing:
        cmds.append(f"pip install {st.req.pip_name}")
    for st in report.optional_outdated:
        cmds.append(f"pip install --upgrade {st.req.pip_name}")
    return cmds


# ---------------------------------------------------------------------------
# Диалог для показа пользователю (импортируется только внутри UI-кода)
# ---------------------------------------------------------------------------

def build_report_dialog(report: DependencyReport):
    """
    Возвращает QDialog с подробным отчётом.
    Импорт PyQt6 — здесь, чтобы модуль можно было использовать без GUI
    (например, из консольного скрипта).
    """
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QTextEdit, QApplication,
    )
    from PyQt6.QtCore import Qt

    dlg = QDialog()
    dlg.setWindowTitle("Проверка зависимостей")
    dlg.resize(720, 560)

    layout = QVBoxLayout(dlg)

    if not report.can_run:
        title = QLabel("<h3 style='color:#c0392b;'>❌ Не хватает критичных пакетов</h3>")
    elif report.has_warnings:
        title = QLabel("<h3 style='color:#d68910;'>⚠️ Есть замечания</h3>")
    else:
        title = QLabel("<h3 style='color:#27ae60;'>✓ Всё в порядке</h3>")
    title.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(title)

    txt = QTextEdit()
    txt.setReadOnly(True)
    txt.setPlainText(format_report_text(report))
    layout.addWidget(txt)

    # Кнопки
    btn_layout = QHBoxLayout()

    pip_cmds = get_pip_install_commands(report)
    if pip_cmds:
        btn_copy = QPushButton("📋 Скопировать команды pip")

        def copy_to_clipboard():
            QApplication.clipboard().setText("\n".join(pip_cmds))
            btn_copy.setText("✓ Скопировано")

        btn_copy.clicked.connect(copy_to_clipboard)
        btn_layout.addWidget(btn_copy)

    btn_layout.addStretch()

    btn_ok = QPushButton("OK" if report.can_run else "Закрыть")
    btn_ok.clicked.connect(dlg.accept)
    btn_layout.addWidget(btn_ok)

    layout.addLayout(btn_layout)
    return dlg