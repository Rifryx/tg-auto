"""Captcha-solver для Telegram-чатов.

Критически важно для выживания аккаунтов: многие публичные чаты требуют
пройти капчу при входе (бот отправляет сообщение с кнопкой/математикой/
изображением), и если бот не прошёл — его молча кикают через N минут.

Публичный API:
 - ``CaptchaSolver`` — абстракция (interface);
 - ``ButtonCaptchaSolver`` — кликает inline-кнопку с ключевыми словами
   «Я не бот» / «✅» / «Начать» и т.п. (самый частый случай);
 - ``MathCaptchaSolver`` — находит в тексте выражение `N + N` / `N - N` и
   отправляет ответ в чат (без клика);
 - ``CaptchaSolverRegistry.default()`` — реестр по умолчанию, пробует
   solver'ы по очереди (button → math);
 - ``solve_captcha_in_chat(client, chat_id, timeout_sec)`` — высокоуровневая
   утилита: ждёт сообщение в чате (обычно от проверяющего бота после
   JoinChannelRequest) и пробует решить. True — решено, False — таймаут
   или не распознано (чат можно считать забагованным, но аккаунт не теряем).
"""

from worker.captcha.solver import (
    ButtonCaptchaSolver,
    CaptchaSolver,
    CaptchaSolverRegistry,
    MathCaptchaSolver,
    solve_captcha_in_chat,
)

__all__ = [
    "ButtonCaptchaSolver",
    "CaptchaSolver",
    "CaptchaSolverRegistry",
    "MathCaptchaSolver",
    "solve_captcha_in_chat",
]
