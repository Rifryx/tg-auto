"""Пул прокси: автоопределение гео номера + подбор свободного прокси
(этап 3, backlog #1).

«Свободный» = ``proxies.status='alive'`` и ни один аккаунт не ссылается через
``accounts.proxy_id``. «Гео совпадает» = ISO-2 гео прокси и гео номера равны;
если у номера нет распознанного гео — берём любой alive свободный.

Хранит минимальный E.164-мэп префиксов → ISO-2. Не заводим ``phonenumbers`` в
зависимости ради одной таблицы — покрываем основные направления, недостающие
префиксы возвращают None (fallback на «любое гео»).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from core.enums import ProxyStatus
from core.models import Account, Proxy


# Наивный E.164 → ISO-2 mapping. Достаточно для MVP; при расширении переезд
# на ``phonenumbers`` тривиален (тот же вход, другой backend).
# Порядок важен: длинные префиксы проверяем ПЕРВЫМИ, чтобы 380 не спутался с 3.
_PHONE_PREFIX_TO_GEO: list[tuple[str, str]] = [
    ("380", "UA"),
    ("375", "BY"),
    ("373", "MD"),
    ("371", "LV"),
    ("372", "EE"),
    ("370", "LT"),
    ("353", "IE"),
    ("358", "FI"),
    ("351", "PT"),
    ("352", "LU"),
    ("356", "MT"),
    ("357", "CY"),
    ("359", "BG"),
    ("354", "IS"),
    ("998", "UZ"),
    ("996", "KG"),
    ("994", "AZ"),
    ("993", "TM"),
    ("992", "TJ"),
    ("995", "GE"),
    ("977", "NP"),
    ("880", "BD"),
    ("670", "TL"),
    ("852", "HK"),
    ("853", "MO"),
    ("855", "KH"),
    ("856", "LA"),
    ("886", "TW"),
    ("966", "SA"),
    ("971", "AE"),
    ("972", "IL"),
    ("974", "QA"),
    ("973", "BH"),
    ("962", "JO"),
    ("961", "LB"),
    ("968", "OM"),
    ("965", "KW"),
    ("964", "IQ"),
    ("963", "SY"),
    ("34", "ES"),
    ("39", "IT"),
    ("40", "RO"),
    ("41", "CH"),
    ("43", "AT"),
    ("44", "GB"),
    ("45", "DK"),
    ("46", "SE"),
    ("47", "NO"),
    ("48", "PL"),
    ("49", "DE"),
    ("30", "GR"),
    ("31", "NL"),
    ("32", "BE"),
    ("33", "FR"),
    ("36", "HU"),
    ("52", "MX"),
    ("54", "AR"),
    ("55", "BR"),
    ("56", "CL"),
    ("57", "CO"),
    ("60", "MY"),
    ("61", "AU"),
    ("62", "ID"),
    ("63", "PH"),
    ("64", "NZ"),
    ("65", "SG"),
    ("66", "TH"),
    ("81", "JP"),
    ("82", "KR"),
    ("84", "VN"),
    ("86", "CN"),
    ("90", "TR"),
    ("91", "IN"),
    ("92", "PK"),
    ("93", "AF"),
    ("94", "LK"),
    ("95", "MM"),
    ("98", "IR"),
    ("20", "EG"),
    ("27", "ZA"),
    ("7", "RU"),  # 7 в конце — самый короткий, чтобы 380 не совпал раньше.
    ("1", "US"),  # 1 — США/Канада; по-хорошему разделяем по area code, пока
                  # трактуем как один пул.
]


def detect_geo(phone: str) -> Optional[str]:
    """Достать ISO-2 из E.164-номера. Возвращает None для нераспознанного."""
    digits = phone.strip().lstrip("+").replace(" ", "").replace("-", "")
    if not digits:
        return None
    for prefix, iso in _PHONE_PREFIX_TO_GEO:
        if digits.startswith(prefix):
            return iso
    return None


def pick_free_proxy(
    session: Session,
    *,
    geo: Optional[str] = None,
    strict_geo: bool = True,
) -> Optional[Proxy]:
    """Один свободный alive-прокси. При ``geo`` — с совпадающим гео.

    * ``strict_geo=True`` (default): если ``geo`` не None, ищем ТОЛЬКО с
      совпадающим гео. Не нашли — None (не подставляем прокси другой страны:
      инвариант §0.4 «гео прокси = гео номера»).
    * ``strict_geo=False``: если matching-гео нет, отдаём любой свободный
      alive (полезно для админского override).
    * «Свободный» — NOT EXISTS accounts.proxy_id == proxy.id.
    """
    base = select(Proxy).where(
        Proxy.status == ProxyStatus.ALIVE.value,
        ~exists().where(Account.proxy_id == Proxy.id),
    )

    if geo:
        matched = session.execute(base.where(Proxy.geo == geo).limit(1)).scalar_one_or_none()
        if matched is not None:
            return matched
        if strict_geo:
            return None
    return session.execute(base.limit(1)).scalar_one_or_none()


def pick_for_phone(
    session: Session,
    phone: str,
    *,
    strict_geo: bool = True,
) -> Optional[Proxy]:
    """Автопик прокси под конкретный номер: detect_geo + pick_free_proxy."""
    return pick_free_proxy(session, geo=detect_geo(phone), strict_geo=strict_geo)
