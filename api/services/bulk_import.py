"""Массовый импорт аккаунтов из архива + CSV-мапы (этап 1).

Пользователь загружает:
* ``archive`` — ZIP c ``.session``-файлами; имя файла = телефон (напр. ``+70000000001.session``).
* ``mapping`` — CSV с обязательными полями ``phone,proxy_id`` и опциональными
  ``warming_profile,persona_id,project_id,role,tags`` (tags через ``|``).

Импорт — best-effort: ошибки одного аккаунта не роняют импорт остальных.
Возвращается отчёт: что успешно, что пропущено, что упало.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.services.accounts import (
    ProxyNotFoundError,
    SessionImportError,
    import_account_from_session,
    session_file_to_string,
)
from core.enums import AccountRole, WarmingProfile


@dataclass
class ImportedItem:
    phone: str
    account_id: int


@dataclass
class SkippedItem:
    phone: str
    reason: str


@dataclass
class ImportReport:
    imported: list[ImportedItem]
    skipped: list[SkippedItem]

    def as_dict(self) -> dict:
        return {
            "imported": [it.__dict__ for it in self.imported],
            "skipped": [it.__dict__ for it in self.skipped],
            "totals": {
                "imported": len(self.imported),
                "skipped": len(self.skipped),
            },
        }


def _parse_row(
    row: dict[str, str],
) -> tuple[str, dict[str, object]]:
    """Возвращает (phone, kwargs для import_account_from_session + post-fields).

    Бросает ValueError на некорректных данных.
    """
    phone = (row.get("phone") or "").strip()
    if not phone:
        raise ValueError("phone is empty")
    proxy_id_raw = (row.get("proxy_id") or "").strip()
    if not proxy_id_raw:
        raise ValueError("proxy_id is empty")
    proxy_id = int(proxy_id_raw)

    profile_raw = (row.get("warming_profile") or "medium").strip() or "medium"
    try:
        warming_profile = WarmingProfile(profile_raw)
    except ValueError:
        raise ValueError(f"unknown warming_profile: {profile_raw!r}")

    persona_id = _parse_optional_int(row.get("persona_id"))
    project_id = _parse_optional_int(row.get("project_id"))

    role_raw = (row.get("role") or "").strip()
    role: Optional[str] = None
    if role_raw:
        try:
            role = AccountRole(role_raw).value
        except ValueError:
            raise ValueError(f"unknown role: {role_raw!r}")

    tags_raw = (row.get("tags") or "").strip()
    tags = [t.strip() for t in tags_raw.split("|") if t.strip()] if tags_raw else []

    return phone, {
        "proxy_id": proxy_id,
        "persona_id": persona_id,
        "warming_profile": warming_profile,
        "project_id": project_id,
        "role": role,
        "tags": tags,
    }


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    s = (raw or "").strip()
    if not s:
        return None
    return int(s)


def bulk_import(
    session: Session,
    *,
    archive_bytes: bytes,
    csv_bytes: bytes,
) -> ImportReport:
    """Импортирует всё что смог. Не бросает при ошибках отдельных строк."""

    # ZIP: сложим в память ``{filename_lower: bytes}``. Ищем ``<phone>.session``
    # регистронезависимо (пользователь мог написать имя как угодно).
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"archive is not a valid ZIP: {exc}") from exc

    session_files: dict[str, bytes] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.rsplit("/", 1)[-1]
        if not name.lower().endswith(".session"):
            continue
        # ключ = имя без расширения, нормализованное к нижнему регистру.
        key = name[: -len(".session")].lower()
        session_files[key] = zf.read(info)

    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8", errors="replace")))
    if reader.fieldnames is None or "phone" not in reader.fieldnames:
        raise ValueError("csv must have header with at least 'phone,proxy_id'")

    imported: list[ImportedItem] = []
    skipped: list[SkippedItem] = []

    for row_number, row in enumerate(reader, start=2):
        try:
            phone, kwargs = _parse_row(row)
        except ValueError as exc:
            skipped.append(SkippedItem(phone=row.get("phone") or f"row {row_number}", reason=str(exc)))
            continue

        # Ищем файл сессии по телефону (регистронезависимо).
        blob = session_files.get(phone.lower())
        # Разрешаем и без ведущего плюса.
        if blob is None and phone.startswith("+"):
            blob = session_files.get(phone[1:].lower())
        if blob is None:
            skipped.append(SkippedItem(phone=phone, reason="session file not found in archive"))
            continue

        try:
            string = session_file_to_string(blob)
        except SessionImportError as exc:
            skipped.append(SkippedItem(phone=phone, reason=str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001
            skipped.append(SkippedItem(phone=phone, reason=f"parse failed: {exc}"))
            continue

        try:
            account = import_account_from_session(
                session,
                phone=phone,
                proxy_id=int(kwargs["proxy_id"]),
                persona_id=kwargs["persona_id"],
                warming_profile=kwargs["warming_profile"],
                session_string=string,
            )
        except ProxyNotFoundError as exc:
            skipped.append(SkippedItem(phone=phone, reason=str(exc)))
            session.rollback()
            continue
        except IntegrityError as exc:
            # чаще всего — дубликат phone (UNIQUE).
            session.rollback()
            skipped.append(SkippedItem(phone=phone, reason=f"duplicate: {exc.orig}"))
            continue
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            skipped.append(SkippedItem(phone=phone, reason=f"import failed: {exc}"))
            continue

        # Post-fields: project_id / role / tags выставляются отдельно, потому
        # что import_account_from_session ими не занимается.
        touched = False
        if kwargs["project_id"] is not None:
            account.project_id = int(kwargs["project_id"])
            touched = True
        if kwargs["role"] is not None:
            account.role = kwargs["role"]
            touched = True
        if kwargs["tags"]:
            account.tags = list(kwargs["tags"])
            touched = True
        if touched:
            session.commit()

        imported.append(ImportedItem(phone=phone, account_id=account.id))

    return ImportReport(imported=imported, skipped=skipped)
