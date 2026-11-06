"""Тесты параметров запуска НейроШиллинга (функционал «как у конкурента»).

Покрывают то, чего раньше в модуле не было вовсе:
* режимы целей (чат / конкретный пост / мониторинг канала);
* раздача ролей по аккаунтам и переключатель «менять состав между чатами»;
* отдельная «пауза до первой реплики»;
* темп «по одному» против «до 3 сразу»;
* поллер мониторинга каналов.

БД настоящая; Telethon/ClientPool — фейки, now/rng инъектируются (как в
test_orchestrator.py).
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.models import Account
from core.queue.task_names import TaskName
from modules.shilling.api import service
from modules.shilling.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import (
    CampaignCreate,
    CampaignUpdate,
    RoleCreate,
    ScenarioCreate,
    StepCreate,
    TargetCreate,
)
from modules.shilling.worker import orchestrator

# Маркер вешаем точечно на async-тесты: модульный pytestmark в strict-режиме
# pytest-asyncio сыплет предупреждениями на каждый синхронный тест рядом.

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
_PHONE = itertools.count(98_000_000_000)


class _Rng:
    """Детерминированный rng: uniform → нижняя граница, choice → первый."""

    def uniform(self, a, b):
        return a

    def choice(self, seq):
        return seq[0]

    def shuffle(self, seq):
        seq.reverse()  # детерминированная «перетасовка»


class _SpyTaskQueue:
    def __init__(self):
        self.scheduled = []

    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, run_at, args, kwargs))
        return "job"

    async def enqueue(self, name, *args, **kwargs):
        self.scheduled.append((name, None, args, kwargs))
        return "job"


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.released = []

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        self.released.append(account_id)


class _ChannelClient:
    """Канал с discussion-группой. Помнит, какой пост спрашивали."""

    def __init__(self, *, linked=-200, latest_post=42, root_id=777, megagroup=False):
        self._linked = linked
        self._latest = latest_post
        self._root = root_id
        self._megagroup = megagroup
        self.discussion_asked_for: list[int] = []
        self.history_calls = 0

    async def get_entity(self, ref):
        return SimpleNamespace(
            id=-100, title="Channel", username="chan", megagroup=self._megagroup
        )

    async def get_messages(self, entity, limit=1):
        self.history_calls += 1
        # Отдаём limit последних постов по убыванию id, как Telethon.
        return [SimpleNamespace(id=self._latest - i) for i in range(limit)]

    async def __call__(self, request):
        name = type(request).__name__
        if "GetFullChannel" in name:
            return SimpleNamespace(
                full_chat=SimpleNamespace(linked_chat_id=self._linked)
            )
        if "GetDiscussionMessage" in name:
            self.discussion_asked_for.append(request.msg_id)
            return SimpleNamespace(messages=[SimpleNamespace(id=self._root)])
        return None


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _acc(session) -> int:
    acc = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="assigned",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc.id


def _setup(session, *, targets=(), pin_roles=True, n_accounts=2, **campaign_kw):
    """Кампания с 2 ролями/шагами. ``targets`` — список kwargs для TargetCreate.

    Значения задержек — дефолты теста, любое из них перекрывается через
    ``campaign_kw`` (поэтому собираем словарь, а не передаём их позиционно:
    иначе `**campaign_kw` с тем же ключом даёт TypeError).
    """
    params = {
        "name": "c", "brand_name": "B",
        "target_delay_min_sec": 100, "target_delay_max_sec": 100,
        "reply_delay_min_sec": 5, "reply_delay_max_sec": 5,
    }
    params.update(campaign_kw)
    campaign = CampaignRepository(session).create(CampaignCreate(**params))
    session.flush()
    scenario = ScenarioRepository(session).create(
        ScenarioCreate(campaign_id=campaign.id, persons_count=2)
    )
    session.flush()
    r1 = ScenarioRoleRepository(session).create(scenario.id, RoleCreate(name="Инициатор"))
    r2 = ScenarioRoleRepository(session).create(scenario.id, RoleCreate(name="Ответчик"))
    session.flush()
    ScenarioStepRepository(session).create(
        scenario.id, StepCreate(role_id=r1.id, step_type="message", text="вопрос?")
    )
    ScenarioStepRepository(session).create(
        scenario.id, StepCreate(role_id=r2.id, step_type="message", text="ответ про B")
    )
    link_repo = CampaignAccountRepository(session)
    account_ids = [_acc(session) for _ in range(n_accounts)]
    roles = [r1.id, r2.id]
    for i, aid in enumerate(account_ids):
        link_repo.attach(
            campaign.id, aid,
            role_id=(roles[i] if pin_roles and i < len(roles) else None),
            is_reserve=False,
        )
    target_ids = []
    for kw in targets:
        t = CampaignTargetRepository(session).create(campaign.id, TargetCreate(**kw))
        session.flush()
        target_ids.append(t.id)
    CampaignRepository(session).set_status(campaign.id, "running")
    session.commit()
    return {
        "campaign_id": campaign.id,
        "role_ids": roles,
        "account_ids": account_ids,
        "target_ids": target_ids,
    }


def _ctx(session, *, client=None, task_queue=None):
    return {
        "session_factory": _factory(session),
        "now": NOW,
        "rng": _Rng(),
        "task_queue": task_queue or _SpyTaskQueue(),
        "client_pool": _FakePool(client) if client is not None else None,
        "publisher": None,
    }


# --- разбор ссылок -----------------------------------------------------------


def test_normalize_target_extracts_post_id():
    assert service.normalize_target("https://t.me/durov/123") == ("durov", "username", 123)
    assert service.normalize_target("t.me/c/1234567890/55") == ("1234567890", "chat_id", 55)
    # Обычная ссылка на канал поста не содержит.
    assert service.normalize_target("@durov") == ("durov", "username", None)
    assert service.normalize_target("t.me/durov") == ("durov", "username", None)
    # Инвайт c "+" не должен приниматься за пост.
    raw, kind, post = service.normalize_target("t.me/+AbCdEf")
    assert (kind, post) == ("invite", None)


def test_add_targets_bulk_post_link_wins_over_tab_mode(session):
    """Ссылка на конкретный пост остаётся channel_post, даже если добавляют
    со вкладки «Мониторинг каналов» — иначе мы бы молча делали не то."""
    ids = _setup(session)
    created = service.add_targets_bulk(
        session, ids["campaign_id"],
        ["t.me/durov/777", "@somechannel"],
        mode="channel_monitor",
    )
    session.commit()
    by_raw = {t.raw_input: t for t in created}
    assert by_raw["durov"].mode == "channel_post"
    assert by_raw["durov"].post_id == 777
    assert by_raw["somechannel"].mode == "channel_monitor"
    assert by_raw["somechannel"].post_id is None


def test_add_targets_bulk_same_channel_monitor_and_posts(session):
    """Один канал можно добавить и на мониторинг, и отдельными постами."""
    ids = _setup(session)
    service.add_targets_bulk(session, ids["campaign_id"], ["@durov"], mode="channel_monitor")
    created = service.add_targets_bulk(
        session, ids["campaign_id"], ["t.me/durov/1", "t.me/durov/2", "t.me/durov/1"],
    )
    session.commit()
    # Третья ссылка — дубль второй, отсекается.
    assert sorted(t.post_id for t in created) == [1, 2]
    all_targets = CampaignTargetRepository(session).list_by_campaign(ids["campaign_id"])
    assert len(all_targets) == 3


# --- раздача ролей -----------------------------------------------------------


class _LinkRepoStub:
    def __init__(self, links):
        self._links = links

    def list_primary_by_role(self, campaign_id, role_id):
        return [l for l in self._links if l.role_id == role_id and not l.is_reserve]

    def list_by_campaign(self, campaign_id):
        return self._links


def _link(account_id, role_id, reserve=False):
    return SimpleNamespace(account_id=account_id, role_id=role_id, is_reserve=reserve)


def test_assign_lineup_respects_pinned_roles_even_when_shuffling():
    repo = _LinkRepoStub([_link(1, 10), _link(2, 11), _link(3, 12)])
    for shuffle in (False, True):
        lineup = orchestrator._assign_lineup(
            repo, 1, [10, 11, 12], rng=random.Random(0), shuffle=shuffle
        )
        assert lineup == {10: 1, 11: 2, 12: 3}, "закреплённая роль не должна меняться"


def test_assign_lineup_is_stable_without_shuffle_and_varies_with_it():
    repo = _LinkRepoStub([_link(1, None), _link(2, None), _link(3, None)])
    stable_a = orchestrator._assign_lineup(
        repo, 1, [10, 11, 12], rng=random.Random(1), shuffle=False
    )
    stable_b = orchestrator._assign_lineup(
        repo, 1, [10, 11, 12], rng=random.Random(2), shuffle=False
    )
    assert stable_a == stable_b, "без перемешивания состав обязан повторяться"

    seen = {
        tuple(
            sorted(
                orchestrator._assign_lineup(
                    repo, 1, [10, 11, 12], rng=random.Random(seed), shuffle=True
                ).items()
            )
        )
        for seed in range(12)
    }
    assert len(seen) > 1, "с перемешиванием состав обязан меняться между чатами"


def test_assign_lineup_never_gives_one_account_two_roles():
    repo = _LinkRepoStub([_link(1, None), _link(2, None), _link(3, None)])
    for seed in range(8):
        lineup = orchestrator._assign_lineup(
            repo, 1, [10, 11, 12], rng=random.Random(seed), shuffle=True
        )
        assert len(set(lineup.values())) == len(lineup)


def test_assign_lineup_fills_unpinned_roles_from_spare_accounts():
    """Роль без закреплённого аккаунта раньше просто пропускалась (шаг не
    выполнялся вовсе) — теперь её играет свободный аккаунт кампании."""
    repo = _LinkRepoStub([_link(1, 10), _link(2, None)])
    lineup = orchestrator._assign_lineup(
        repo, 1, [10, 11], rng=random.Random(0), shuffle=False
    )
    assert lineup == {10: 1, 11: 2}


# --- режимы целей ------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_chat_posts_directly_without_discussion(session):
    """Режим «Чаты»: пишем прямо в чат, корень обсуждения не ищем вовсе."""
    ids = _setup(session, targets=[{"raw_input": "mychat", "mode": "chat"}])
    spy = _SpyTaskQueue()
    client = _ChannelClient()
    count = await orchestrator.process_target(
        _ctx(session, client=client, task_queue=spy), ids["campaign_id"], ids["target_ids"][0]
    )
    assert count == 2
    # Ни одного запроса за обсуждением — это и есть «прямо в чат».
    assert client.discussion_asked_for == []
    # thread_msg_id отсутствует → executor отправит обычное сообщение.
    assert all(kw["thread_msg_id"] is None for _, _, _, kw in spy.scheduled)
    target = CampaignTargetRepository(session).get(ids["target_ids"][0])
    assert target.resolved_chat_id == -100, "постим в сам чат, не в linked-группу"


@pytest.mark.asyncio
async def test_mode_channel_post_comments_under_requested_post(session):
    """Режим «Посты каналов»: комментируем указанный пост, а не последний."""
    ids = _setup(
        session,
        targets=[{"raw_input": "chan", "mode": "channel_post", "post_id": 11}],
    )
    spy = _SpyTaskQueue()
    client = _ChannelClient(latest_post=999)
    count = await orchestrator.process_target(
        _ctx(session, client=client, task_queue=spy), ids["campaign_id"], ids["target_ids"][0]
    )
    assert count == 2
    assert client.discussion_asked_for == [11], "должен быть запрошен пост 11, не 999"
    assert client.history_calls == 0, "последний пост не нужен — он задан явно"


@pytest.mark.asyncio
async def test_mode_link_falls_back_to_latest_post(session):
    """Режим «Ссылки» (авто) сохраняет прежнее поведение: последний пост."""
    ids = _setup(session, targets=[{"raw_input": "chan", "mode": "link"}])
    client = _ChannelClient(latest_post=42)
    await orchestrator.process_target(
        _ctx(session, client=client), ids["campaign_id"], ids["target_ids"][0]
    )
    assert client.discussion_asked_for == [42]


@pytest.mark.asyncio
async def test_mode_link_writes_into_megagroup_without_discussion(session):
    """Обычная супергруппа без linked_chat — не «комментарии закрыты», а чат."""
    ids = _setup(session, targets=[{"raw_input": "group", "mode": "link"}])
    spy = _SpyTaskQueue()
    client = _ChannelClient(linked=None, megagroup=True)
    count = await orchestrator.process_target(
        _ctx(session, client=client, task_queue=spy), ids["campaign_id"], ids["target_ids"][0]
    )
    assert count == 2
    target = CampaignTargetRepository(session).get(ids["target_ids"][0])
    assert target.status == "resolved"
    assert target.resolved_chat_id == -100


# --- пауза до первой реплики -------------------------------------------------


@pytest.mark.asyncio
async def test_first_reply_delay_applies_only_to_first_step(session):
    ids = _setup(
        session,
        targets=[{"raw_input": "chan", "mode": "link"}],
        first_reply_delay_min_sec=600, first_reply_delay_max_sec=600,
        reply_delay_min_sec=5, reply_delay_max_sec=5,
    )
    spy = _SpyTaskQueue()
    await orchestrator.process_target(
        _ctx(session, client=_ChannelClient(), task_queue=spy),
        ids["campaign_id"], ids["target_ids"][0],
    )
    offsets = [(run_at - NOW).total_seconds() for _, run_at, _, _ in spy.scheduled]
    # Первая реплика — через 600с (пауза до первой), вторая — ещё +5с.
    assert offsets == [600, 605]


# --- темп --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_chats_spreads_targets_across_lanes(session):
    """«До 3 сразу»: три первые цели стартуют одновременно, пауза копится
    внутри каждой дорожки отдельно."""
    ids = _setup(
        session,
        targets=[{"raw_input": f"c{i}"} for i in range(6)],
        max_parallel_chats=3,
    )
    spy = _SpyTaskQueue()
    count = await orchestrator.start_campaign(
        _ctx(session, task_queue=spy), ids["campaign_id"]
    )
    assert count == 6
    offsets = [(run_at - NOW).total_seconds() for _, run_at, _, _ in spy.scheduled]
    assert offsets == [0, 0, 0, 100, 100, 100]


@pytest.mark.asyncio
async def test_single_chat_mode_keeps_targets_sequential(session):
    ids = _setup(
        session,
        targets=[{"raw_input": f"c{i}"} for i in range(3)],
        max_parallel_chats=1,
    )
    spy = _SpyTaskQueue()
    await orchestrator.start_campaign(_ctx(session, task_queue=spy), ids["campaign_id"])
    offsets = [(run_at - NOW).total_seconds() for _, run_at, _, _ in spy.scheduled]
    assert offsets == [0, 100, 200]


@pytest.mark.asyncio
async def test_start_campaign_skips_monitor_targets(session):
    """Цели-«мониторы» планирует не старт кампании, а cron-поллер: поста,
    под которым нужно комментировать, на момент запуска ещё не существует."""
    ids = _setup(
        session,
        targets=[
            {"raw_input": "plain"},
            {"raw_input": "watched", "mode": "channel_monitor"},
        ],
    )
    spy = _SpyTaskQueue()
    count = await orchestrator.start_campaign(_ctx(session, task_queue=spy), ids["campaign_id"])
    assert count == 1
    assert len(spy.scheduled) == 1


# --- мониторинг каналов ------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_first_pass_only_sets_cursor(session):
    """Первый проход не должен лезть в архив канала — только запомнить, где
    мы сейчас. Иначе включение мониторинга = заход во все старые посты."""
    ids = _setup(session, targets=[{"raw_input": "watched", "mode": "channel_monitor"}])
    spy = _SpyTaskQueue()
    scheduled = await orchestrator.poll_channel_monitors(
        _ctx(session, client=_ChannelClient(latest_post=500), task_queue=spy)
    )
    assert scheduled == 0
    assert spy.scheduled == []
    target = CampaignTargetRepository(session).get(ids["target_ids"][0])
    assert target.last_seen_post_id == 500


@pytest.mark.asyncio
async def test_monitor_second_pass_enqueues_new_posts_only(session):
    ids = _setup(session, targets=[{"raw_input": "watched", "mode": "channel_monitor"}])
    target_id = ids["target_ids"][0]
    CampaignTargetRepository(session).set_last_seen_post(target_id, 500)
    session.commit()

    spy = _SpyTaskQueue()
    # Канал выдал посты 501 и 502 (get_messages отдаёт их по убыванию).
    scheduled = await orchestrator.poll_channel_monitors(
        _ctx(session, client=_ChannelClient(latest_post=502), task_queue=spy)
    )
    assert scheduled == 2
    names = {n for n, _, _, _ in spy.scheduled}
    assert names == {TaskName.SHILLING_PROCESS_TARGET}
    # В задачу уходит конкретный пост — третьим аргументом.
    post_args = sorted(args[2] for _, _, args, _ in spy.scheduled)
    assert post_args == [501, 502]
    assert CampaignTargetRepository(session).get(target_id).last_seen_post_id == 502


@pytest.mark.asyncio
async def test_monitor_ignores_campaigns_that_are_not_running(session):
    ids = _setup(session, targets=[{"raw_input": "watched", "mode": "channel_monitor"}])
    CampaignRepository(session).set_status(ids["campaign_id"], "paused")
    session.commit()
    spy = _SpyTaskQueue()
    scheduled = await orchestrator.poll_channel_monitors(
        _ctx(session, client=_ChannelClient(), task_queue=spy)
    )
    assert scheduled == 0
    assert spy.scheduled == []


@pytest.mark.asyncio
async def test_monitor_post_override_comments_under_that_post(session):
    """process_target с явным post_id (так его зовёт поллер) комментирует
    именно этот пост, хотя у самой цели post_id пустой."""
    ids = _setup(session, targets=[{"raw_input": "watched", "mode": "channel_monitor"}])
    client = _ChannelClient(latest_post=999)
    count = await orchestrator.process_target(
        _ctx(session, client=client), ids["campaign_id"], ids["target_ids"][0], 501
    )
    assert count == 2
    assert client.discussion_asked_for == [501]


# --- тумблер «мониторить всё, что на аккаунте» -------------------------------


class _DialogsClient:
    """Фейк: подписки аккаунта. get_dialogs() отдаёт каналы и группы."""

    def __init__(self, dialogs):
        # dialogs: список (id, username|None, broadcast)
        self._dialogs = dialogs

    async def get_dialogs(self):
        out = []
        for cid, username, broadcast in self._dialogs:
            ent = SimpleNamespace(
                id=cid, username=username, broadcast=broadcast,
                megagroup=not broadcast, title=f"ch{cid}",
            )
            out.append(SimpleNamespace(entity=ent, name=f"ch{cid}"))
        return out


async def _reconcile(session, client):
    # _reconcile_monitor_all(ctx, session_factory, pool, log)
    await orchestrator._reconcile_monitor_all(
        None, _factory(session), _FakePool(client), orchestrator.get_logger()
    )


@pytest.mark.asyncio
async def test_monitor_all_discovers_account_channels(session):
    ids = _setup(session, monitor_all_dialogs=True)
    client = _DialogsClient([
        (-111, "news", True),      # канал → берём
        (-222, None, True),        # приватный канал (без username) → берём по id
        (-333, "chatgroup", False),  # группа → НЕ берём (мониторим каналы)
    ])
    await _reconcile(session, client)
    targets = CampaignTargetRepository(session).list_monitors(ids["campaign_id"])
    raws = sorted(t.raw_input for t in targets)
    assert raws == ["-222", "@news"]
    assert all(t.auto_discovered and t.mode == "channel_monitor" for t in targets)


@pytest.mark.asyncio
async def test_monitor_all_does_not_duplicate_manual_targets(session):
    ids = _setup(
        session, monitor_all_dialogs=True,
        targets=[{"raw_input": "@news", "mode": "channel_monitor"}],
    )
    client = _DialogsClient([(-111, "news", True), (-222, "other", True)])
    await _reconcile(session, client)
    targets = CampaignTargetRepository(session).list_monitors(ids["campaign_id"])
    news = [t for t in targets if t.raw_input == "@news"]
    assert len(news) == 1, "ручной @news не должен дублироваться авто-целью"
    assert not news[0].auto_discovered, "ручная цель остаётся ручной"
    assert {t.raw_input for t in targets} == {"@news", "@other"}


@pytest.mark.asyncio
async def test_monitor_all_off_removes_auto_targets_keeps_manual(session):
    ids = _setup(
        session, monitor_all_dialogs=True,
        targets=[{"raw_input": "@manual", "mode": "channel_monitor"}],
    )
    # Сначала дискавери добавил авто-цели.
    await _reconcile(session, _DialogsClient([(-111, "auto1", True), (-222, "auto2", True)]))
    assert len(CampaignTargetRepository(session).list_monitors(ids["campaign_id"])) == 3

    # Выключаем тумблер и реконсайлим — авто-цели уходят, ручная остаётся.
    CampaignRepository(session).update(
        ids["campaign_id"], CampaignUpdate(monitor_all_dialogs=False)
    )
    session.commit()
    await _reconcile(session, _DialogsClient([]))
    left = CampaignTargetRepository(session).list_monitors(ids["campaign_id"])
    assert [t.raw_input for t in left] == ["@manual"]
    assert not left[0].auto_discovered


@pytest.mark.asyncio
async def test_auto_target_without_discussion_skips_without_blacklist(session):
    """Авто-канал без комментариев — не ошибка пользователя: тихо пропускаем,
    в ЧС не заносим."""
    ids = _setup(
        session,
        targets=[{"raw_input": "chan", "mode": "channel_monitor", "auto_discovered": True}],
    )
    # Клиент без linked-группы (комментарии закрыты).
    client = _ChannelClient(linked=None, megagroup=False)
    count = await orchestrator.process_target(
        _ctx(session, client=client), ids["campaign_id"], ids["target_ids"][0], 501
    )
    assert count == 0
    from modules.shilling.repositories import BlacklistRepository
    assert BlacklistRepository(session).list_by_campaign(ids["campaign_id"]) == []
