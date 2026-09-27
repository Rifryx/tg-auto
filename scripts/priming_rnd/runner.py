"""Оркестратор R&D-прогона.

Роль скрипта: на двух живых тестовых аккаунтах (уже загруженных в БД штатным
способом, с прокси) поочерёдно проверить каждый кандидат ``trigger_action`` и
сохранить JSON-отчёт со всей телеметрией + ответом оператора «пришёл ли push
у второй стороны».

Скрипт **не пишет** в модуль ``modules/priming/`` и **не создаёт**
``TelegramClient`` напрямую — использует существующий
:class:`worker.client_pool.ClientPool` и обёртку
:func:`worker.health.around_telethon_call`, поэтому все вызовы уходят через
тот же rate-limit / health-контур, что и в продакшне.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy.orm import Session as OrmSession

from core.repositories.account import AccountRepository
from worker.client_pool import ClientPool
from worker.health import around_telethon_call

from scripts.priming_rnd import actions as action_mod


REPORTS_DIR = Path(__file__).parent / "reports"


# --- session/DB glue --------------------------------------------------------

@contextmanager
def _session_factory() -> Iterator[OrmSession]:
    """Использует тот же session-фабричный контракт, что и продакшн-воркер."""
    # Импорт локальный: скрипт не должен тянуть БД, пока его не запустили.
    from worker.tasks.db import session_scope

    with session_scope() as session:  # type: ignore[misc]
        yield session


# --- CLI ассистент ----------------------------------------------------------

def _prompt_yes_no(question: str) -> bool:
    while True:
        answer = input(f"{question} [y/n] ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("  ответьте 'y' или 'n'.")


def _prompt_free_text(question: str) -> str:
    return input(f"{question}: ").strip()


# --- сам прогон -------------------------------------------------------------

async def run_probe(
    pool: ClientPool,
    driver_account_id: int,
    target_ref: str,
    action_name: str,
) -> dict[str, Any]:
    """Один пробный вызов: подключить клиент → resolve peer → action → замер."""
    if action_name not in action_mod.REGISTRY:
        raise SystemExit(
            f"unknown action '{action_name}'; known: {sorted(action_mod.REGISTRY)}"
        )
    action = action_mod.REGISTRY[action_name]

    client = await pool.get(driver_account_id)
    await client.connect()
    try:
        # target_ref может быть username или числовым id — get_input_entity сам разберётся.
        parsed_target = int(target_ref) if target_ref.lstrip("-").isdigit() else target_ref
        peer = await client.get_input_entity(parsed_target)

        async def _do() -> action_mod.ActionResult:
            return await action(client, peer)

        # around_telethon_call даёт нам health/flood-инструментацию бесплатно.
        result: action_mod.ActionResult = await around_telethon_call(
            _do,
            account_id=driver_account_id,
            session_factory=_session_factory,
        )
    finally:
        await pool.release(driver_account_id)

    return result.to_dict()


def _resolve_target_username(session: OrmSession, account_id: int) -> str | None:
    """Возвращает username аккаунта B, чтобы аккаунт A мог его адресовать."""
    account = AccountRepository(session).get(account_id)
    if account is None:
        return None
    return getattr(account, "username", None)


async def _main_async(args: argparse.Namespace) -> int:
    pool = ClientPool(_session_factory)

    with _session_factory() as session:
        target_username = _resolve_target_username(session, args.account_b)
    if not target_username:
        raise SystemExit(
            f"account B ({args.account_b}) has no username — set one or pass --target"
        )
    target_ref = args.target or f"@{target_username}"

    print()
    print(f"R&D-прогон  action={args.action!r}")
    print(f"  driver (A) : account_id={args.account_a}")
    print(f"  target (B) : {target_ref}  (account_id={args.account_b})")
    print(
        "  Держите под рукой второй телефон/клиент на аккаунте B — сразу после\n"
        "  вызова я спрошу, пришёл ли push и остался ли в чате артефакт."
    )
    print()

    try:
        probe = await run_probe(pool, args.account_a, target_ref, args.action)
    except Exception as exc:  # pragma: no cover — R&D-инструмент
        probe = {
            "action": args.action,
            "ok": False,
            "runner_error": f"{type(exc).__name__}: {exc}",
        }
        print(f"!! исключение вне action-обёртки: {probe['runner_error']}")

    print(json.dumps(probe, indent=2, ensure_ascii=False))
    print()
    push_seen = _prompt_yes_no("Пришёл ли push у аккаунта B?")
    chat_artifact = _prompt_yes_no("Появилось ли в чате видимое сообщение/событие?")
    operator_notes = _prompt_free_text("Заметки оператора (опционально)")

    now = datetime.now(timezone.utc)
    report = {
        "timestamp_utc": now.isoformat(),
        "driver_account_id": args.account_a,
        "target_account_id": args.account_b,
        "target_ref": target_ref,
        "probe": probe,
        "operator": {
            "push_seen": push_seen,
            "chat_artifact": chat_artifact,
            "notes": operator_notes,
        },
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = REPORTS_DIR / f"{now.strftime('%Y%m%dT%H%M%S')}_{args.action}.json"
    filename.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nотчёт: {filename.relative_to(Path.cwd())}")

    await pool.close_all()
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.priming_rnd",
        description="R&D-проба одного MTProto-триггера прайминга.",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=sorted(action_mod.REGISTRY),
        help="какой триггер проверяем (см. modules.priming spec §5)",
    )
    parser.add_argument(
        "--account-a",
        type=int,
        required=True,
        dest="account_a",
        help="account_id аккаунта-инициатора (уже загружен в БД, с прокси)",
    )
    parser.add_argument(
        "--account-b",
        type=int,
        required=True,
        dest="account_b",
        help="account_id аккаунта-цели",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="переопределить peer вручную (например @username или числовой id)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
