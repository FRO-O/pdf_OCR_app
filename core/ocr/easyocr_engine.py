"""
Реализация OCR-движка на базе EasyOCR.

Задача: обернуть easyocr.Reader так, чтобы остальная программа
не знала о его существовании. Наружу — только OCREngineBase.

Особенности EasyOCR, которые здесь учитываются:
- Формат результата: [(bbox_4_points, text, confidence), ...]
- Коды языков: 'ru', 'en', 'ch_sim', 'ch_tra', 'ko', 'ja', ...
  (в целом совпадают с универсальными, но не полностью — см. LANGUAGE_MAP)
- Параметры readtext() передаются как kwargs
- Модели скачиваются в ~/.EasyOCR при первом запуске (100-200 МБ на язык)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .base import OCREngineBase, OCRParams, OCRResult


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Маппинг универсальных кодов → коды EasyOCR
# ---------------------------------------------------------------------------

# В EasyOCR используется большая часть тех же кодов, что и в нашей программе,
# но есть нюансы. Проверяем через easyocr.config.all_lang_list.
#
# Например:
#   наш "ch_sim" → EasyOCR "ch_sim"  (совпадает)
#   наш "ch_tra" → EasyOCR "ch_tra"  (совпадает)
#   наш "ja"     → EasyOCR "ja"      (совпадает)
#   наш "en"     → EasyOCR "en"
#   наш "ru"     → EasyOCR "ru"
#
# Но некоторые коды у EasyOCR отличаются: например, 'en' имеет алиасы
# ('en', 'eng'), у некоторых языков есть только один код.
# Здесь — единая точка маппинга для явных отличий.

LANGUAGE_MAP: dict[str, str] = {
    # Пока все совпадают, но оставляем место для будущих правок.
    # Пример на будущее:
    # "zh": "ch_sim",
}


def _map_language(universal_code: str) -> str:
    """Универсальный код → код EasyOCR."""
    return LANGUAGE_MAP.get(universal_code, universal_code)


# ---------------------------------------------------------------------------
# Движок
# ---------------------------------------------------------------------------

class EasyOCREngine(OCREngineBase):
    """
    Обёртка над easyocr.Reader.

    Инициализация загружает модели в память (медленно: 5–15 сек и 200+ МБ
    на язык). Поэтому один экземпляр создаётся один раз и переиспользуется.

    Используйте фабрику get_ocr_engine() — она кэширует экземпляры.
    """

    # Список поддерживаемых языков (в универсальном формате).
    # Заполняется один раз при первом вызове available_languages().
    _supported_languages: Optional[list[str]] = None

    def __init__(self, languages: list[str], use_gpu: bool = True):
        super().__init__(languages, use_gpu)
        self._reader = self._create_reader()

    # ------------------------------------------------------------------
    # Инициализация Reader
    # ------------------------------------------------------------------

    def _create_reader(self):
        """Создаёт easyocr.Reader. Импорт внутри — чтобы не тянуть
        тяжёлую библиотеку, пока движок не понадобился."""
        try:
            import easyocr
        except ImportError as e:
            raise ImportError(
                "EasyOCR не установлен. Установите его командой:\n"
                "    pip install easyocr\n"
                "Также понадобится PyTorch (CPU или CUDA):\n"
                "    pip install torch torchvision"
            ) from e

        # Маппим универсальные коды на коды EasyOCR
        easyocr_langs = [_map_language(code) for code in self.languages]

        # Проверка, что все языки поддерживаются
        try:
            all_langs = easyocr.config.all_lang_list
        except AttributeError:
            all_langs = None  # на всякий случай — вдруг в новой версии переименуют

        if all_langs is not None:
            unsupported = [l for l in easyocr_langs if l not in all_langs]
            if unsupported:
                raise ValueError(
                    f"EasyOCR не поддерживает языки: {unsupported}. "
                    f"Доступные: {sorted(all_langs)}"
                )

        # Создаём Reader.
        # verbose=False убирает болтливый вывод EasyOCR при загрузке.
        # download_enabled=True — модели скачаются автоматически при первом запуске.
        reader = easyocr.Reader(
            easyocr_langs,
            gpu=self.use_gpu,
            verbose=False,
            download_enabled=True,
        )

        logger.info(
            "EasyOCR инициализирован: langs=%s, gpu=%s",
            easyocr_langs, self.use_gpu,
        )
        return reader

    # ------------------------------------------------------------------
    # Основной метод
    # ------------------------------------------------------------------

    def recognize(
        self,
        image: np.ndarray,
        params: Optional[OCRParams] = None,
    ) -> list[OCRResult]:
        """
        Распознать текст на изображении.

        Args:
            image: np.ndarray RGB, shape (H, W, 3), dtype uint8.
            params: параметры OCR. None → дефолтные.

        Returns:
            Список OCRResult.
        """
        if params is None:
            params = OCRParams()

        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(
                f"Ожидается RGB-изображение (H, W, 3), "
                f"получено {image.shape}"
            )

        # Формируем kwargs для readtext
        kwargs: dict[str, Any] = params.to_easyocr_kwargs()

        # EasyOCR не принимает 'paragraph=True' вместе с некоторыми параметрами
        # (в частности, с width_ths в некоторых версиях).
        # Оставим как есть — если что, EasyOCR сам сообщит об ошибке,
        # а мы её поймаем выше.

        try:
            raw = self._reader.readtext(image, **kwargs)
        except Exception as e:
            logger.exception("Ошибка при вызове easyocr.readtext: %s", e)
            raise

        return self._convert_results(raw)

    # ------------------------------------------------------------------
    # Конвертация формата EasyOCR → OCRResult
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_results(raw: list) -> list[OCRResult]:
        """
        EasyOCR возвращает список вида:
            [
              ([[x1,y1],[x2,y2],[x3,y3],[x4,y4]], "text", 0.98),
              ...
            ]

        Преобразуем в список OCRResult.
        Отбрасываем пустые строки и мусор.
        """
        results: list[OCRResult] = []
        for item in raw:
            if len(item) != 3:
                continue
            bbox, text, conf = item

            # Приводим bbox к списку списков float
            try:
                points = [[float(p[0]), float(p[1])] for p in bbox]
            except Exception:
                continue

            if len(points) < 4:
                # EasyOCR обычно возвращает 4 точки, но на всякий случай
                # обрежем до прямоугольника.
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                x1, x2 = min(xs), max(xs)
                y1, y2 = min(ys), max(ys)
                points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

            text = (text or "").strip()
            if not text:
                continue

            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = 0.0

            results.append(OCRResult(bbox=points, text=text, confidence=conf))

        return results

    # ------------------------------------------------------------------
    # Мета-информация
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "EasyOCR"

    @property
    def device_info(self) -> str:
        """
        Строка для логов: 'CPU' или 'CUDA:0 (NVIDIA RTX 3060)'.
        Пытаемся достать имя GPU через torch.
        """
        if not self.use_gpu:
            return "CPU"

        try:
            import torch
            if torch.cuda.is_available():
                try:
                    props = torch.cuda.get_device_properties(0)
                    return f"CUDA:0 ({props.name}, {props.total_memory / 1024**3:.1f} ГБ)"
                except Exception:
                    return "CUDA:0"
            else:
                # Пользователь просил GPU, но CUDA недоступна —
                # EasyOCR молча переключится на CPU.
                return "CPU (CUDA недоступна)"
        except ImportError:
            return "CPU (torch не установлен)"

    # ------------------------------------------------------------------
    # Доступные языки
    # ------------------------------------------------------------------

    @staticmethod
    def available_languages() -> list[str]:
        """
        Список языков в универсальном формате, которые поддерживает EasyOCR.
        Кэшируется после первого вызова.
        """
        if EasyOCREngine._supported_languages is not None:
            return list(EasyOCREngine._supported_languages)

        try:
            import easyocr
            all_langs = set(easyocr.config.all_lang_list)
        except Exception:
            # Если EasyOCR не установлен, вернём базовый набор,
            # чтобы UI не падал.
            all_langs = {"ru", "en", "ko", "ja", "ch_sim", "ch_tra"}

        # Из нашего универсального набора оставляем только те,
        # что понимает EasyOCR (после маппинга).
        from .base import UNIVERSAL_LANGUAGES
        result = [
            code for code in UNIVERSAL_LANGUAGES
            if _map_language(code) in all_langs
        ]

        EasyOCREngine._supported_languages = result
        return list(result)

    # ------------------------------------------------------------------
    # Маппинг языков (переопределяем базовую реализацию)
    # ------------------------------------------------------------------

    @staticmethod
    def map_languages(universal_langs: list[str]) -> list[str]:
        return [_map_language(code) for code in universal_langs]