"""Бизнес-логика модуля НейроШиллинг: исключения + транзакционные операции.

Идея та же, что в commenting.api.service: роутер ловит эти исключения и
маппит их на HTTP-коды. Позднее сюда переедут attach_account /
detach_account / start_campaign — сейчас в 2.1 объявляются только классы
ошибок, чтобы роутер уже мог их обрабатывать.
"""

from __future__ import annotations


class ShillingNotFound(Exception):
    """Сущность (кампания/сценарий/роль/шаг/цель) не найдена → 404."""


class ShillingConflict(Exception):
    """Недопустимое состояние для операции → 409."""


class ShillingValidation(Exception):
    """Данные не проходят бизнес-валидацию (не путать с pydantic 422) → 400."""
