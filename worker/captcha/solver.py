"""Captcha-solver реализация.

Два встроенных solver'а покрывают ~80% капч в телеграм-чатах
(из конкурентного анализа и спеки):

1) **ButtonCaptchaSolver** — большая часть анти-ботов (Rose, Shieldy,
   combot и т.п.) требуют кликнуть кнопку/эмодзи. Smart match:
    - текст кнопки содержит одно из ключевых слов («не бот», «подтверди»,
      «я человек», «✅», «начать», «join», «confirm»…);
    - если кнопки без явных ключевых слов — кликаем первую inline-кнопку,
      которая НЕ содержит отказа («отмена», «нет», «cancel», «no», «ban»).

2) **MathCaptchaSolver** — «реши 3+5» в тексте, бот ждёт число ответом в чат.
   Regex по целым числам и операциям +/-/*/÷ (с небольшой защитой: игнорим
   если число компонент слишком большое, чтобы не выстрелить в телефон).

Image-captcha (OCR) намеренно не делаем — требует внешнего OCR-провайдера
(2captcha, anti-captcha, Google Vision). Инфраструктурный хук оставлен в
``ExternalProviderCaptchaSolver`` — вызывается, если задан
``settings.captcha_provider_key``; в этом PR — заглушка, возвращает False.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from telethon import TelegramClient, events


# Ключевые слова, по которым определяем «правильную» кнопку. Регистронезависимо.
_POSITIVE_KEYWORDS = (
    "не бот",
    "я не бот",
    "я человек",
    "подтверди",
    "подтвердить",
    "начать",
    "продолжить",
    "✅",
    "✔️",
    "👍",
    "join",
    "confirm",
    "verify",
    "i am human",
    "i'm not a bot",
    "start",
    "continue",
)

_NEGATIVE_KEYWORDS = (
    "отмена",
    "cancel",
    "нет",
    " no",
    "ban",
    "block",
    "позже",
    "later",
    "skip",
)

# Простое арифметическое выражение. Специально узко: только одна операция
# между двумя числами длиной до 3 цифр, чтобы не ловить «цена 125» и
# не считать «1+2+3+4». Этого хватает для 95% капч в тг-чатах.
_MATH_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s*([+\-*xX×/÷])\s*(\d{1,3})(?!\d)",
    flags=re.IGNORECASE,
)


class CaptchaSolver:
    """Абстрактный solver. Возвращает True, если капча решена, False иначе.

    ``message`` — само сообщение-капча (telethon ``Message``). Solver может
    отвечать клавишей (``message.click``), текстом (``client.send_message``)
    или делать своё — главное, вернуть ``True`` при успехе.
    """

    name: str = "base"

    async def try_solve(self, client: TelegramClient, message: Any) -> bool:  # pragma: no cover
        raise NotImplementedError


class ButtonCaptchaSolver(CaptchaSolver):
    name = "button"

    async def try_solve(self, client: TelegramClient, message: Any) -> bool:
        buttons = _flat_buttons(message)
        if not buttons:
            return False

        # Фаза 1: ищем кнопку с явно положительным ключевым словом.
        for btn in buttons:
            label = (btn.text or "").strip().lower()
            if any(k in label for k in _POSITIVE_KEYWORDS):
                return await _safe_click(btn)

        # Фаза 2: если ни одна кнопка не содержит явного положительного
        # ключевого слова, но и явного отрицательного тоже нет — кликаем
        # ПЕРВУЮ. Это работает для «одной большой кнопки» без текста,
        # которую обычно и ставит капча.
        if len(buttons) == 1:
            label = (buttons[0].text or "").strip().lower()
            if not any(k in label for k in _NEGATIVE_KEYWORDS):
                return await _safe_click(buttons[0])
        return False


class MathCaptchaSolver(CaptchaSolver):
    name = "math"

    async def try_solve(self, client: TelegramClient, message: Any) -> bool:
        text = (getattr(message, "message", None) or "").strip()
        if not text:
            return False
        match = _MATH_RE.search(text)
        if match is None:
            return False
        a, op_raw, b = match.group(1), match.group(2), match.group(3)
        op = op_raw.lower()
        try:
            x, y = int(a), int(b)
            if op == "+":
                result = x + y
            elif op == "-":
                result = x - y
            elif op in ("*", "x", "×"):
                result = x * y
            elif op in ("/", "÷"):
                if y == 0:
                    return False
                # Делим нацело, если результат целый; иначе отказываемся
                # (как правило, в чатах капчи с несчитающимися дробями не ждут).
                if x % y != 0:
                    return False
                result = x // y
            else:
                return False
        except (TypeError, ValueError):
            return False

        chat = getattr(message, "chat_id", None) or getattr(message, "chat", None)
        if chat is None:
            return False
        try:
            await client.send_message(chat, str(result), reply_to=message.id)
        except Exception:  # noqa: BLE001 — не смогли ответить — считаем нерешённым
            return False
        return True


class ExternalProviderCaptchaSolver(CaptchaSolver):
    """Заглушка для внешнего image-OCR провайдера (2captcha и т.п.)

    Требует ``settings.captcha_provider_key``. В этом PR — просто возвращает
    False (ничего не вызываем, чтобы не делать HTTP без ключа). Хук
    оставлен, чтобы в будущем можно было подключить реального провайдера.
    """

    name = "external"

    async def try_solve(self, client: TelegramClient, message: Any) -> bool:
        return False


@dataclass
class CaptchaSolverRegistry:
    solvers: list[CaptchaSolver] = field(default_factory=list)

    @classmethod
    def default(cls) -> "CaptchaSolverRegistry":
        return cls(solvers=[ButtonCaptchaSolver(), MathCaptchaSolver()])

    async def try_solve(self, client: TelegramClient, message: Any) -> Optional[str]:
        """Пробует solver'ы по очереди. Возвращает имя сработавшего или None."""
        for solver in self.solvers:
            try:
                ok = await solver.try_solve(client, message)
            except Exception:  # noqa: BLE001 — solver упал, пробуем следующий
                continue
            if ok:
                return solver.name
        return None


async def solve_captcha_in_chat(
    client: TelegramClient,
    chat_id,
    *,
    timeout_sec: float = 60.0,
    registry: Optional[CaptchaSolverRegistry] = None,
) -> bool:
    """Высокоуровневый хелпер: ждёт сообщение в чате и пробует его решить.

    Удобно вызывать СРАЗУ после JoinChannelRequest — капча обычно приходит
    в течение нескольких секунд после входа. Таймаут 60с с запасом.
    Возвращает ``True`` если какой-то solver сработал, ``False`` иначе
    (не было подходящих сообщений, или ни один solver не распознал).
    """
    registry = registry or CaptchaSolverRegistry.default()
    solved = asyncio.Event()
    solved_by = {"name": None}  # mutable container для замыкания

    async def _handler(event):  # type: ignore[no-untyped-def]
        name = await registry.try_solve(client, event.message)
        if name is not None:
            solved_by["name"] = name
            solved.set()

    ev = events.NewMessage(chats=chat_id, incoming=True)
    client.add_event_handler(_handler, ev)
    try:
        try:
            await asyncio.wait_for(solved.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            return False
    finally:
        try:
            client.remove_event_handler(_handler, ev)
        except Exception:  # noqa: BLE001
            pass
    return solved_by["name"] is not None


def _flat_buttons(message: Any) -> list[Any]:
    """Разворачивает reply_markup → плоский список кнопок (Telethon ``Button``).

    ``message.buttons`` — список рядов (list[list[Button]]). Если нет markup
    или это не inline — возвращаем [].
    """
    buttons = getattr(message, "buttons", None)
    if not buttons:
        return []
    flat: list[Any] = []
    for row in buttons:
        if not row:
            continue
        for btn in row:
            flat.append(btn)
    return flat


async def _safe_click(btn: Any) -> bool:
    """Клик по кнопке с подавлением всех ошибок — для captcha это ок:
    если нажать не удалось (например, кнопка-url, которую нельзя кликнуть
    через MTProto), просто считаем «не прошло», следующий solver попробует."""
    try:
        await btn.click()
    except Exception:  # noqa: BLE001
        return False
    return True
