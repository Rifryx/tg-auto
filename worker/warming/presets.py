"""Константы движка прогрева (PROJECT-STAGES §3, §5).

Реестра модулей/настроек пока нет, а core.config трогать нельзя — поэтому
пресеты и пороги готовности живут здесь, в слое воркера. Пороги готовности
вынесены отдельными константами (кандидаты на перенос в config позднее).
"""

from __future__ import annotations

from core.enums import WarmingProfile

# Интервал между действиями (часы, диапазон) по пресету.
PRESET_INTERVAL_HOURS: dict[str, tuple[float, float]] = {
    WarmingProfile.MINIMAL.value: (48.0, 72.0),
    WarmingProfile.MEDIUM.value: (20.0, 28.0),
    WarmingProfile.DENSE.value: (6.0, 10.0),
}

# Сколько действий планировать за один заход (диапазон) по пресету.
PRESET_ACTION_COUNT: dict[str, tuple[int, int]] = {
    WarmingProfile.MINIMAL.value: (1, 2),
    WarmingProfile.MEDIUM.value: (2, 5),
    WarmingProfile.DENSE.value: (5, 10),
}

# Джиттер планирования: ±30% от выбранного интервала.
JITTER_FRACTION = 0.30

# Критерий готовности warming → pool (кандидаты в config).
WARMING_READY_ACTIONS = 50          # успешных initial-действий
WARMING_READY_DAYS = 14             # либо столько суток в прогреве
# Профиль «средних настроек» для стартовой пачки первичного прогрева.
INITIAL_BATCH_PROFILE = WarmingProfile.MEDIUM.value
