"""Синхронизация реального Telegram-профиля аккаунта в нашу БД.

После логина (и по кнопке «обновить») тянем из Telegram настоящие имя/фамилию,
@username, bio и аватар, а также статус 2FA — и сохраняем. Иначе аккаунт в UI
выглядит пустым, а карточка 2FA показывает «не установлен», хотя пароль есть.

Профильные поля пишем в ``accounts`` (``AccountUpdate``), флаги (has_2fa и пр.) —
в ``account_health``. Аватар сохраняем как base64 data-URL (фронт так и рисует
``<img src=avatar_url>``), без отдельного файлового хранилища.
"""
from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Optional

from telethon.tl.functions.account import GetPasswordRequest

from core.repositories.account import AccountRepository
from core.repositories.account_health import AccountHealthRepository
from core.schemas.account import AccountUpdate
from core.schemas.account_health import AccountHealthUpdate
from worker.client_pool import ClientPool

# Плоский логгер (не worker.tasks.logging) — иначе цикл импорта: handlers → sync
# → worker.tasks.logging → worker.tasks(__init__) → handlers.
logger = logging.getLogger("worker.sync_profile")

PROFILE_UPDATED_CHANNEL = "account_profile_updated"


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


async def sync_profile_impl(ctx: dict, account_id: int) -> dict[str, Any]:
    """Подтянуть профиль + статус 2FA из Telegram и сохранить."""
    pool = _pool(ctx)
    publisher = ctx.get("publisher")
    session_factory = ctx["session_factory"]

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    has_avatar = False
    has_2fa: Optional[bool] = None
    is_premium: Optional[bool] = None
    real_phone: Optional[str] = None

    client = await pool.get(account_id)
    try:
        await client.connect()
        me = await client.get_me()
        first_name = getattr(me, "first_name", None)
        last_name = getattr(me, "last_name", None)
        username = getattr(me, "username", None)
        has_avatar = getattr(me, "photo", None) is not None
        is_premium = bool(getattr(me, "premium", False))
        # Настоящий телефон (есть в User.phone после get_me). Нужен, чтобы
        # заменить псевдо-номер (ses<hash>/tg<uid>), подставленный при
        # импорте .session/tdata, на настоящий. Без этого UI показывал
        # «ses1a2b3c4d…» вместо реального «+7900…».
        raw_phone = getattr(me, "phone", None)
        if raw_phone:
            raw_phone = str(raw_phone).strip()
            # Telegram отдаёт phone без «+», приводим к общему формату БД.
            real_phone = raw_phone if raw_phone.startswith("+") else f"+{raw_phone}"

        # bio — из full-user (get_entity('me').about).
        try:
            entity = await client.get_entity("me")
            about = getattr(entity, "about", None)
            bio = about if about else None
        except Exception as exc:  # noqa: BLE001
            logger.info("sync_profile.bio_skip acc=%s err=%r", account_id, exc)

        # Аватар → base64 data-URL (только если есть и скачался).
        if has_avatar:
            try:
                data = await client.download_profile_photo("me", file=bytes)
                if data:
                    avatar_url = (
                        "data:image/jpeg;base64," + base64.b64encode(data).decode()
                    )
            except Exception as exc:  # noqa: BLE001
                logger.info("sync_profile.avatar_skip acc=%s err=%r", account_id, exc)

        # 2FA — наличие облачного пароля (без ввода).
        try:
            pwd = await client(GetPasswordRequest())
            has_2fa = bool(getattr(pwd, "has_password", False))
        except Exception as exc:  # noqa: BLE001
            logger.info("sync_profile.2fa_skip acc=%s err=%r", account_id, exc)
    finally:
        await pool.release(account_id)

    with session_factory() as session:
        profile_kwargs: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "bio": bio,
            "is_premium": is_premium,
        }
        # avatar_url выставляем только если реально получили — чтобы не затирать
        # вручную поставленный аватар при неудачной загрузке.
        if avatar_url is not None:
            profile_kwargs["avatar_url"] = avatar_url
        # Заменяем псевдо-номер (сгенерирован при импорте .session/tdata)
        # на настоящий из get_me. Псевдо-номера имеют префиксы ses/tg и не
        # начинаются на «+», настоящие — с «+». Не трогаем номера, которые
        # пользователь ввёл сам при логине по коду.
        if real_phone:
            repo = AccountRepository(session)
            current = repo.get(account_id)
            if current is not None and current.phone and not current.phone.startswith("+"):
                # Если такой настоящий уже есть у другого аккаунта — не
                # трогаем, иначе упадёт unique-ограничение.
                existing = repo.get_by_phone(real_phone)
                if existing is None or existing.id == account_id:
                    profile_kwargs["phone"] = real_phone
        AccountRepository(session).update(account_id, AccountUpdate(**profile_kwargs))
        AccountHealthRepository(session).update(
            account_id,
            AccountHealthUpdate(
                has_2fa=has_2fa,
                has_username=bool(username),
                has_avatar=has_avatar,
                has_bio=bool(bio and bio.strip()),
            ),
        )
        session.commit()

    if publisher is not None:
        publisher.publish(PROFILE_UPDATED_CHANNEL, {"account_id": account_id})
    logger.info(
        "sync_profile.done acc=%s has_username=%s has_avatar=%s has_2fa=%s",
        account_id, bool(username), has_avatar, has_2fa,
    )
    return {"account_id": account_id, "has_2fa": has_2fa, "username": username}


UPLOAD_AVATAR_CHANNEL = "account_avatar_uploaded"
AVATAR_SYNC_FAILED_CHANNEL = "account_avatar_sync_failed"


def _decode_avatar_data_url(data_url: str) -> Optional[bytes]:
    """data:image/<ext>;base64,<base64> → bytes. Возвращает None если это
    не data URL или не декодируется. Обычные HTTP(S)-ссылки не обрабатываем
    здесь — для них вызывающий код должен передать url=... в upload_avatar."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        header, _, b64 = data_url.partition(",")
        if ";base64" not in header:
            return None
        return base64.b64decode(b64)
    except (ValueError, binascii.Error):
        return None


async def _delete_all_profile_photos(client, account_id: int, session_factory, publisher) -> dict[str, Any]:
    """Удаляет ВСЕ аватарки аккаунта в Telegram. Пользователь жмёт
    «Удалить фото» в UI → это должно убрать картинку и у собеседников,
    а не только обнулить поле в нашей БД (баг-репорт «в боте удаляешь
    аватарку то в тг она не пропадает»).

    GetUserPhotosRequest отдаёт все фото профиля, DeletePhotosRequest
    принимает их InputPhoto-id'ы. Делаем одной транзакцией. При пустой
    выдаче (у аккаунта и так нет аватаров) — считаем ok=True."""
    from telethon.tl.functions.photos import DeletePhotosRequest, GetUserPhotosRequest
    from telethon.tl.types import InputPeerSelf, InputPhoto
    from worker.health import around_telethon_call

    try:
        photos = await around_telethon_call(
            lambda: client(GetUserPhotosRequest(
                user_id=InputPeerSelf(), offset=0, max_id=0, limit=100,
            )),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"get_photos_failed: {exc!r}"}

    photo_list = list(getattr(photos, "photos", None) or [])
    if not photo_list:
        return {"ok": True, "deleted": 0}

    inputs = [
        InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
        for p in photo_list
        if getattr(p, "id", None) is not None and getattr(p, "access_hash", None) is not None
    ]
    if not inputs:
        return {"ok": True, "deleted": 0}

    try:
        await around_telethon_call(
            lambda: client(DeletePhotosRequest(id=inputs)),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"delete_failed: {exc!r}"}
    return {"ok": True, "deleted": len(inputs)}


async def upload_avatar_impl(
    ctx: dict,
    account_id: int,
    *,
    delete: bool = False,
) -> dict[str, Any]:
    """Синхронизирует состояние аватара аккаунта с Telegram.

    * ``delete=False`` (дефолт) — читает ``accounts.avatar_url`` (должен быть
      ``data:image/*;base64,...``, как шлёт AvatarPicker), декодирует в
      bytes и загружает как профильное фото. При успехе дёргает
      ``sync_profile_impl``, чтобы в БД попал РЕАЛЬНЫЙ ``avatar_url``
      (data-URL из Telegram-превью), а не тот огромный, что пришёл с
      устройства — так собеседники видят ровно ту же картинку, что мы
      показываем в UI (баг «в апке одна ава, а по факту другая»).
    * ``delete=True`` — удаляет ВСЕ фото профиля в Telegram
      (DeletePhotosRequest по полному списку из GetUserPhotos). Без
      этого шага «Удалить фото» в UI только обнуляло поле в нашей БД, а
      собеседники в TG продолжали видеть старое фото.

    При любой ошибке Telethon — не роняем, пишем warning, публикуем
    ``account_avatar_sync_failed`` и возвращаем ``ok=False``. Фронт
    инвалидирует кэш аккаунта и покажет текущее реальное состояние
    (sync_profile).
    """
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")

    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            return {"account_id": account_id, "ok": False, "error": "no_account"}
        data_url: Optional[str] = account.avatar_url

    pool = _pool(ctx)
    client = await pool.get(account_id)
    result: dict[str, Any]
    try:
        if delete:
            result = await _delete_all_profile_photos(
                client, account_id, session_factory, publisher,
            )
        else:
            if not data_url:
                return {"account_id": account_id, "ok": False, "error": "no_avatar"}
            blob = _decode_avatar_data_url(data_url)
            if blob is None:
                logger.info("upload_avatar.skip acc=%s reason=not_data_url", account_id)
                return {"account_id": account_id, "ok": False, "error": "not_data_url"}

            from worker.profiles.apply import upload_avatar  # ленивый — циклы

            result = await upload_avatar(
                client,
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
                binary=blob,
            )
    finally:
        await pool.release(account_id)

    if not result.get("ok"):
        logger.warning(
            "upload_avatar.failed acc=%s delete=%s err=%s",
            account_id, delete, result.get("error"),
        )
        if publisher is not None:
            try:
                publisher.publish(
                    AVATAR_SYNC_FAILED_CHANNEL,
                    {
                        "account_id": account_id,
                        "action": "delete" if delete else "upload",
                        "error": str(result.get("error")),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("upload_avatar.publish_failed acc=%s err=%r", account_id, exc)
        return {"account_id": account_id, "ok": False, "error": result.get("error")}

    # Обновляем БД под факт:
    # - при delete — avatar_url=null и has_avatar=False сразу (+ sync не
    #   нужен: уже знаем точное состояние);
    # - при upload — дёргаем sync_profile_impl. Он перезаписывает
    #   avatar_url data-URL'ом Telegram-превью + has_avatar=True из me.photo.
    if delete:
        with session_factory() as session:
            AccountRepository(session).update(
                account_id, AccountUpdate(avatar_url=None),
            )
            AccountHealthRepository(session).update(
                account_id, AccountHealthUpdate(has_avatar=False),
            )
            session.commit()
    else:
        try:
            await sync_profile_impl(ctx, account_id)
        except Exception as exc:  # noqa: BLE001 — sync может упасть на 2FA/network,
            # upload сам по себе уже успешен; в худшем случае avatar_url в
            # БД останется большой data URL от AvatarPicker, UI рендерит
            # его, собеседники видят тот же файл. Логируем и идём дальше.
            logger.info("upload_avatar.sync_after_upload_failed acc=%s err=%r", account_id, exc)

    if publisher is not None:
        try:
            publisher.publish(UPLOAD_AVATAR_CHANNEL, {
                "account_id": account_id,
                "action": "delete" if delete else "upload",
            })
        except Exception as exc:  # noqa: BLE001
            logger.info("upload_avatar.publish_failed acc=%s err=%r", account_id, exc)

    logger.info("upload_avatar.done acc=%s delete=%s", account_id, delete)
    return {"account_id": account_id, "ok": True, "action": "delete" if delete else "upload"}
