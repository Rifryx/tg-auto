"""Probe Telemetr.io API, чтобы подтвердить точные параметры каталога и поля
ответа (нужен ключ). Вывод НЕ содержит секретов — его можно прислать для
финализации провайдера.

Запуск:
    TELEMETRIO_API_KEY=xxxx .venv/Scripts/python.exe scripts/telemetrio_probe.py
или:
    .venv/Scripts/python.exe scripts/telemetrio_probe.py <API_KEY>
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = "https://api.tlmtr.io"


def _dump(title: str, obj) -> None:
    print(f"\n===== {title} =====")
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    except TypeError:
        text = str(obj)
    print(text[:4000])


def main() -> int:
    key = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TELEMETRIO_API_KEY", "")).strip()
    if not key:
        print("Нет ключа. Задай TELEMETRIO_API_KEY или передай аргументом.")
        return 2

    headers = {"x-api-key": key, "Accept": "application/json"}
    with httpx.Client(timeout=25.0, headers=headers) as c:
        # 1) usage/info — тип ключа и остаток квоты
        try:
            r = c.get(f"{BASE}/v1/usage/info")
            _dump(f"GET /v1/usage/info [{r.status_code}]", r.json())
        except Exception as exc:  # noqa: BLE001
            _dump("usage/info FAILED", repr(exc))

        # 2) OpenAPI-схема — точные параметры /v1/catalog/search
        for spec_path in ("/api-docs", "/v1/openapi.json", "/v3/api-docs"):
            try:
                r = c.get(f"{BASE}{spec_path}")
                if r.status_code != 200:
                    continue
                spec = r.json()
                paths = spec.get("paths", {})
                for p in ("/v1/catalog/search", "/v1/channels/search", "/v1/channel/info"):
                    node = paths.get(p)
                    if node:
                        params = node.get("get", {}).get("parameters", [])
                        _dump(f"PARAMS {p} (из {spec_path})",
                              [{"name": x.get("name"), "in": x.get("in"),
                                "type": (x.get("schema") or {}).get("type"),
                                "enum": (x.get("schema") or {}).get("enum")} for x in params])
                break
            except Exception as exc:  # noqa: BLE001
                _dump(f"spec {spec_path} FAILED", repr(exc))

        # 3) Пример поиска по ключевику — реальные поля ответа
        try:
            r = c.get(f"{BASE}/v1/channels/search", params={"term": "crypto", "limit": 3})
            data = r.json()
            first = (data if isinstance(data, list) else
                     (data.get("items") or data.get("data") or data.get("results") or [None]))[0] \
                if data else None
            _dump(f"GET /v1/channels/search?term=crypto [{r.status_code}] — первый элемент", first)
        except Exception as exc:  # noqa: BLE001
            _dump("channels/search FAILED", repr(exc))

        # 4) Пример каталога — проверяем, какие параметры принимает
        try:
            r = c.get(f"{BASE}/v1/catalog/search",
                      params={"limit": 3, "subscribers_from": 1000})
            _dump(f"GET /v1/catalog/search?subscribers_from=1000 [{r.status_code}]",
                  r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:1000])
        except Exception as exc:  # noqa: BLE001
            _dump("catalog/search FAILED", repr(exc))

    print("\nГотово. Пришли вывод выше (секретов в нём нет) — финализирую провайдер.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
