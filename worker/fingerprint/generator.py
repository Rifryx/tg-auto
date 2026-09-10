"""Генератор фингерпринтов устройств (PROJECT-STAGES §3).

Берёт неиспользованную связку из статичного справочника ``device_pool.json`` и
дополняет её языками по гео прокси. Никакого автосборщика и походов в сеть —
только JSON. Иммутабельность фингерпринта после стадии ``created`` обеспечивает
``AccountRepository`` (здесь ничего дополнительно не делаем).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.enums import AccountStatus
from core.repositories.account import AccountRepository

_POOL_PATH = Path(__file__).with_name("device_pool.json")

# Статусы, в которых аккаунт считается активным и «держит» свою связку.
_ACTIVE_STATUSES = (
    AccountStatus.CREATED,
    AccountStatus.WARMING,
    AccountStatus.POOL,
    AccountStatus.ASSIGNED,
    AccountStatus.COOLDOWN,
)

# proxy_geo (ISO страна) -> (lang_code, system_lang_code)
_LANG_MAP: dict[str, tuple[str, str]] = {
    "RU": ("ru", "ru-RU"),
    "UA": ("uk", "uk-UA"),
    "US": ("en", "en-US"),
    "DE": ("de", "de-DE"),
    "PL": ("pl", "pl-PL"),
}
_DEFAULT_LANG: tuple[str, str] = ("en", "en-US")

_pool_cache: Optional[list[dict[str, Any]]] = None


class NoFreeFingerprintsError(Exception):
    """Все связки справочника заняты активными аккаунтами.

    Сигнал расширить ``device_pool.json``, а не переиспользовать связку.
    """


@dataclass(frozen=True)
class Fingerprint:
    device_model: str
    system_version: str
    app_version: str
    lang_code: str
    system_lang_code: str


def _load_pool() -> list[dict[str, Any]]:
    global _pool_cache
    if _pool_cache is None:
        with open(_POOL_PATH, encoding="utf-8") as fh:
            _pool_cache = json.load(fh)
    return _pool_cache


def _triple(entry: Any) -> tuple[str, str, str]:
    if isinstance(entry, dict):
        return (entry["device_model"], entry["system_version"], entry["app_version"])
    return (entry.device_model, entry.system_version, entry.app_version)


class FingerprintGenerator:
    def __init__(
        self,
        account_repo: AccountRepository,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._accounts = account_repo
        self._rng = rng or random.Random()

    def generate(self, proxy_geo: Optional[str]) -> Fingerprint:
        pool = _load_pool()
        used = self._used_triples()
        free = [entry for entry in pool if _triple(entry) not in used]
        if not free:
            raise NoFreeFingerprintsError(
                f"all {len(pool)} device fingerprints are in use by active accounts; "
                "extend device_pool.json"
            )
        choice = self._rng.choice(free)
        lang_code, system_lang_code = self._lang_for(proxy_geo)
        return Fingerprint(
            device_model=choice["device_model"],
            system_version=choice["system_version"],
            app_version=choice["app_version"],
            lang_code=lang_code,
            system_lang_code=system_lang_code,
        )

    def _used_triples(self) -> set[tuple[str, str, str]]:
        used: set[tuple[str, str, str]] = set()
        for status in _ACTIVE_STATUSES:
            for account in self._accounts.list_by_status(status):
                used.add(_triple(account))
        return used

    @staticmethod
    def _lang_for(proxy_geo: Optional[str]) -> tuple[str, str]:
        if not proxy_geo:
            return _DEFAULT_LANG
        return _LANG_MAP.get(proxy_geo.upper(), _DEFAULT_LANG)
