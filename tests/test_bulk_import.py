"""Тесты массового импорта аккаунтов (этап 1).

Юнит-тесты парсера CSV не требуют БД. Интеграционный тест на полный поток
опирается на моки ``session_file_to_string`` и ``import_account_from_session``
— в CI мы не имеем настоящих .session-файлов Telethon.
"""

from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest

from api.services import bulk_import as bi


# ── парсер строк CSV ───────────────────────────────────────────────────────


def test_parse_row_minimal():
    phone, kwargs = bi._parse_row({"phone": "+7000", "proxy_id": "1"})
    assert phone == "+7000"
    assert kwargs["proxy_id"] == 1
    assert kwargs["warming_profile"].value == "medium"
    assert kwargs["persona_id"] is None
    assert kwargs["tags"] == []


def test_parse_row_all_optional_fields():
    phone, kwargs = bi._parse_row({
        "phone": "+7000",
        "proxy_id": "5",
        "warming_profile": "minimal",
        "persona_id": "3",
        "project_id": "7",
        "role": "burner",
        "tags": "vip|seo|new",
    })
    assert kwargs["persona_id"] == 3
    assert kwargs["project_id"] == 7
    assert kwargs["role"] == "burner"
    assert kwargs["tags"] == ["vip", "seo", "new"]
    assert kwargs["warming_profile"].value == "minimal"


def test_parse_row_bad_profile():
    with pytest.raises(ValueError, match="warming_profile"):
        bi._parse_row({"phone": "+7", "proxy_id": "1", "warming_profile": "boom"})


def test_parse_row_bad_role():
    with pytest.raises(ValueError, match="role"):
        bi._parse_row({"phone": "+7", "proxy_id": "1", "role": "godlike"})


def test_parse_row_missing_phone():
    with pytest.raises(ValueError, match="phone"):
        bi._parse_row({"phone": "", "proxy_id": "1"})


def test_parse_row_missing_proxy_id():
    with pytest.raises(ValueError, match="proxy_id"):
        bi._parse_row({"phone": "+7", "proxy_id": ""})


# ── полный поток: bulk_import ───────────────────────────────────────────────


def _make_zip(files: dict[str, bytes]) -> bytes:
    """Собирает ZIP-архив из имён файлов и байт содержимого."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, blob in files.items():
            zf.writestr(name, blob)
    return buf.getvalue()


def test_bulk_import_invalid_zip():
    with pytest.raises(ValueError, match="not a valid ZIP"):
        bi.bulk_import(session=None, archive_bytes=b"not zip", csv_bytes=b"phone,proxy_id\n")


def test_bulk_import_missing_csv_header():
    zip_bytes = _make_zip({})
    with pytest.raises(ValueError, match="header"):
        bi.bulk_import(session=None, archive_bytes=zip_bytes, csv_bytes=b"nothing\n")


def test_bulk_import_missing_session_file_is_skipped():
    """CSV указывает phone, но в архиве нет соответствующего .session."""
    zip_bytes = _make_zip({"+1000.session": b"sess-a"})
    csv_bytes = b"phone,proxy_id\n+1000,1\n+2000,1\n"

    with patch.object(bi, "session_file_to_string", return_value="STRING"), \
         patch.object(bi, "import_account_from_session") as import_mock:
        # Фейковая сессия SQLAlchemy — bulk_import вызывает .rollback только
        # при ошибке, а при успехе не касается session.commit (это делает
        # import_account_from_session, который мокнут).
        class _FakeAccount:
            id = 42
        import_mock.return_value = _FakeAccount()

        report = bi.bulk_import(
            session=_FakeSession(),
            archive_bytes=zip_bytes,
            csv_bytes=csv_bytes,
        )

    assert len(report.imported) == 1
    assert report.imported[0].phone == "+1000"
    assert len(report.skipped) == 1
    assert report.skipped[0].phone == "+2000"
    assert "not found" in report.skipped[0].reason


def test_bulk_import_case_insensitive_and_no_plus():
    """Файл в архиве может называться как угодно: с плюсом/без, регистр — не важен."""
    zip_bytes = _make_zip({"1000.SESSION": b"sess-a"})
    csv_bytes = b"phone,proxy_id\n+1000,1\n"

    with patch.object(bi, "session_file_to_string", return_value="STRING"), \
         patch.object(bi, "import_account_from_session") as import_mock:
        class _FakeAccount:
            id = 42
        import_mock.return_value = _FakeAccount()

        report = bi.bulk_import(
            session=_FakeSession(),
            archive_bytes=zip_bytes,
            csv_bytes=csv_bytes,
        )
    assert len(report.imported) == 1


class _FakeSession:
    """Минимум для bulk_import: rollback() и commit() no-op."""

    def rollback(self):
        pass

    def commit(self):
        pass
