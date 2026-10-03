"""Детерминированное распределение аккаунтов кампании на A/B bucket'ы
(prompt 7.3, spec §11.5).

Функция чистая: одна и та же пара (campaign_id, account_id) всегда
даёт один и тот же bucket, чтобы повторный attach не перекидывал
аккаунт из группы в группу. Ratio — доля 'a' в общем распределении
(0 < ratio < 1).
"""

from __future__ import annotations

import hashlib


BUCKET_A = "a"
BUCKET_B = "b"


def assign_ab_bucket(
    campaign_id: int,
    account_id: int,
    *,
    ratio: float = 0.5,
) -> str:
    """Возвращает 'a' или 'b' по стабильному хешу пары.

    * ``ratio`` — доля bucket A (0 < ratio < 1). При 0.5 распределение
      ≈ 50/50 на большом наборе аккаунтов; отклонение падает как 1/√N.
    """
    if not (0 < ratio < 1):
        raise ValueError("ratio must be in (0, 1)")
    payload = f"{campaign_id}:{account_id}".encode("ascii")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    fraction = int.from_bytes(digest, "big") / (1 << 64)
    return BUCKET_A if fraction < ratio else BUCKET_B


__all__ = ["BUCKET_A", "BUCKET_B", "assign_ab_bucket"]
