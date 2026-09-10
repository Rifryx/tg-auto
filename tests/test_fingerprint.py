from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from core.enums import AccountStatus
from core.repositories.account import AccountRepository
from core.schemas.account import AccountCreate
from worker.fingerprint import (
    Fingerprint,
    FingerprintGenerator,
    NoFreeFingerprintsError,
)
from worker.fingerprint.generator import _POOL_PATH

_PHONE = iter(range(50_000_000_000, 50_000_100_000))

_POOL = json.loads(Path(_POOL_PATH).read_text(encoding="utf-8"))


def _persist(session, fp: Fingerprint) -> None:
    """Создаёт активный аккаунт (статус created) с данной связкой."""
    AccountRepository(session).create(
        AccountCreate(
            phone=f"+{next(_PHONE)}",
            session_enc=b"enc",
            device_model=fp.device_model,
            system_version=fp.system_version,
            app_version=fp.app_version,
            lang_code=fp.lang_code,
            system_lang_code=fp.system_lang_code,
        )
    )


def _persist_entry(session, entry: dict) -> None:
    AccountRepository(session).create(
        AccountCreate(
            phone=f"+{next(_PHONE)}",
            session_enc=b"enc",
            device_model=entry["device_model"],
            system_version=entry["system_version"],
            app_version=entry["app_version"],
            lang_code="en",
            system_lang_code="en-US",
        )
    )


# --------------------------------------------------------------------------- #
# 1. Две генерации подряд не дают одинаковую связку.
# --------------------------------------------------------------------------- #
def test_two_generations_are_distinct(session):
    gen = FingerprintGenerator(AccountRepository(session), rng=random.Random(1))

    fp1 = gen.generate(None)
    _persist(session, fp1)  # первая связка теперь занята активным аккаунтом
    fp2 = gen.generate(None)

    triple1 = (fp1.device_model, fp1.system_version, fp1.app_version)
    triple2 = (fp2.device_model, fp2.system_version, fp2.app_version)
    assert triple1 != triple2


# --------------------------------------------------------------------------- #
# 2. proxy_geo='UA' -> uk / uk-UA.
# --------------------------------------------------------------------------- #
def test_geo_ua_maps_to_ukrainian(session):
    gen = FingerprintGenerator(AccountRepository(session), rng=random.Random(2))
    fp = gen.generate("UA")
    assert fp.lang_code == "uk"
    assert fp.system_lang_code == "uk-UA"


@pytest.mark.parametrize(
    "geo,lang,sys_lang",
    [
        ("RU", "ru", "ru-RU"),
        ("US", "en", "en-US"),
        ("DE", "de", "de-DE"),
        ("PL", "pl", "pl-PL"),
        ("xx", "en", "en-US"),  # неизвестное гео -> дефолт
    ],
)
def test_geo_language_mapping(session, geo, lang, sys_lang):
    gen = FingerprintGenerator(AccountRepository(session), rng=random.Random(3))
    fp = gen.generate(geo)
    assert (fp.lang_code, fp.system_lang_code) == (lang, sys_lang)


# --------------------------------------------------------------------------- #
# 3. proxy_geo=None -> дефолт en/en-US, не падает.
# --------------------------------------------------------------------------- #
def test_geo_none_defaults_to_english(session):
    gen = FingerprintGenerator(AccountRepository(session), rng=random.Random(4))
    fp = gen.generate(None)
    assert fp.lang_code == "en"
    assert fp.system_lang_code == "en-US"


# --------------------------------------------------------------------------- #
# 4. Все 25 заняты активными аккаунтами -> NoFreeFingerprintsError.
# --------------------------------------------------------------------------- #
def test_raises_when_pool_exhausted(session):
    for entry in _POOL:
        _persist_entry(session, entry)

    gen = FingerprintGenerator(AccountRepository(session), rng=random.Random(5))
    with pytest.raises(NoFreeFingerprintsError):
        gen.generate("UA")


def test_retired_and_banned_do_not_hold_fingerprints(session):
    # заняли все 25, но перевели один в retired -> его связка снова свободна
    for entry in _POOL:
        _persist_entry(session, entry)
    repo = AccountRepository(session)
    freed = repo.list_by_status(AccountStatus.CREATED)[0]
    freed.status = AccountStatus.RETIRED.value
    session.flush()

    gen = FingerprintGenerator(repo, rng=random.Random(6))
    fp = gen.generate("UA")
    assert (fp.device_model, fp.system_version, fp.app_version) == (
        freed.device_model,
        freed.system_version,
        freed.app_version,
    )


# --------------------------------------------------------------------------- #
# 5. Схема JSON: 25 записей, обязательные непустые строковые поля.
# --------------------------------------------------------------------------- #
def test_device_pool_schema():
    assert isinstance(_POOL, list)
    assert len(_POOL) == 25

    required = ("platform", "device_model", "system_version", "app_version")
    triples = set()
    counts = {"android": 0, "ios": 0, "desktop": 0}
    for entry in _POOL:
        for field in required:
            assert field in entry, f"нет поля {field} в {entry}"
            assert isinstance(entry[field], str) and entry[field].strip(), (
                f"поле {field} пустое/не строка в {entry}"
            )
        assert entry["platform"] in counts, f"неизвестная платформа {entry['platform']}"
        counts[entry["platform"]] += 1
        triples.add((entry["device_model"], entry["system_version"], entry["app_version"]))

    # связки уникальны
    assert len(triples) == 25
    # заявленный разброс платформ
    assert counts == {"android": 10, "ios": 8, "desktop": 7}
