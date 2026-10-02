# Priming soak harness

Гоняет 7-дневный dry-run прайминг+humanizer в оффлайне: без Telethon,
без Redis, только фиктивные события через `TriggerRunner(dry_run=True)`
+ `humanizer_beat`. Считает агрегированную статистику и падает с
non-zero кодом, если результат выходит за допуски.

## Запуск

```bash
python scripts/priming_soak/soak.py --days 7 --accounts 5
```

Опции:

- `--days N` — сколько «дней» симулировать. Одна итерация = один час
  симуляции; при `--days 7` цикл прогоняет 168 итераций и занимает
  ~секунды.
- `--accounts N` — количество аккаунтов в кампании.
- `--warmup-profile {cold,warm,hot}` — стартовый профиль (default `warm`).
- `--seed N` — сид случайного генератора (детерминизм).
- `--json` — вывести отчёт JSON'ом, а не человечьим текстом (для CI).

## Допуски (fail-thresholds)

- Доля `primed` < 30% — падаем (в dry-run по фикс-распределению
  ~78% primed, любые крупные проседания = регрессия).
- Доля `flood_wait` > 20% — падаем.
- Ни одного вызова humanizer в BALANCED/AGGRESSIVE режиме — падаем.

Пороги подкручиваются в `soak.py` (`FAIL_THRESHOLDS`).
