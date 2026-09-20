# Meridian final gate — пройти сверху вниз

Дедлайн: **27 сентября 2026, 23:59 UTC**. Отправить лучше 26-го.

## 0. Eligibility — раньше всего остального

- [x] Meaningful corpus completed locally: **1,050 network calls**, 0 cache hits, hard cap respected.
- [ ] Nansen Usage Analytics показывает **1,000+ API calls между 14 и 27 сентября**.
- [ ] Сохранён скрин Usage Analytics без ключа/PII.
- [x] Corpus run completed; **не запускать повторно для eligibility**, если Usage Analytics
      подтверждает ≥1,000. Два transient failures не влияют на порог.
- [ ] После корпуса Usage Analytics проверен снова. Локальная телеметрия не заменяет кабинет.

## 1. Hero live proof

- [x] Primary live proof passed: 4 requests, 3 known histories, 0 provider failures.
- [ ] A backup active market also passes:
  ```bash
  ./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id <ID>
  ```
- [x] Основной live smoke: `LIVE PROOF: PASS`, known histories 3, provider failures 0.
- [ ] Запасной live smoke: `LIVE PROOF: PASS`, known histories 1+, provider failures 0.
- [ ] Кнопка `🎭 N` открывает тот же market_id, который был в строке списка.
- [ ] Экран укладывается примерно в 20 секунд на холодном кэше (10с holders + 10с summaries;
      обычно быстрее).

## 2. Проверяемые числа

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_daily.py --submission 2026-09-14 2026-09-27
./venv/bin/python3 tools/nansen_daily.py --range 2026-09-14 2026-09-27 --csv > /tmp/nansen_window.csv
./venv/bin/python3 tools/nansen_daily.py --contrib
```

- [ ] Короткая `--submission START END` и явная `--range START END` показывают одно окно.
- [ ] «Суток с данными» названо честно; пропуски не замазаны средним.
- [ ] Таблица сцен сходится с общим числом вызовов/кредитов — строка `сходится с итогом`.
- [ ] `вызовов без сцены = 0`. Не ноль — исправить или объяснить до заявки.
- [ ] `pm_reputation`, `liq_map`, `pm_chart`, `pm_orderbook` видны отдельными сценами.
- [ ] Неизмеренные цены идут отдельной строкой и не подмешаны в measured credits.
- [ ] CSV не содержит `u` и 0x-адресов.
- [ ] Local network calls сверены с Usage Analytics; для eligibility ведёт Usage Analytics.

## 3. Видео — строго 30–60 секунд

Сценарий рядом с этим чеклистом: `DEMO_SCRIPT.md`.

- [ ] Target 52 секунды, без голоса понятно.
- [ ] Один сюжет: `A market says 78% YES. But whose conviction is it?`
- [ ] `polymarket markets` → `🎭 N` → headline → holder rows → unknown coverage → footer.
- [ ] Live Nansen data visibly loads; не fixture и не заранее вставленная картинка.
- [ ] В кадре нет личных адресов, участников, admin screen, ключа, служебной лички.
- [ ] Не показывать tests, forced failure, Agent, trading, telemetry и все 25 workflow.
- [ ] Если основной рынок не проходит — записать заново с заранее проверенным запасным.

## 4. Public repo

```bash
cd <BOT_DIR>
./venv/bin/python3 tools/nansen_catalog.py --write
./venv/bin/python3 tools/export_nansen_public.py --out ~/nansen-undertaker
cd ~/nansen-undertaker
python3 tests/test_public.py
python3 scrub.py
git status --short
```

- [ ] https://github.com/RenatMursalimov/nansen-undertaker открывается в incognito.
- [ ] CI green.
- [ ] README начинается с hero question, не с no-key/tests/counts.
- [ ] `docs/CATALOG.md`, `docs/WINNER_PLAN.md`, `docs/DEMO_SCRIPT.md`, `docs/X_THREAD.md`,
      `docs/submission.md` есть.
- [ ] `.env`, `nansen_tele/`, cache/schema/credits/refs/corpus/db отсутствуют.
- [ ] `tools/telemetry_rollup.py` отсутствует (legacy reader другого формата не экспортируется).
- [ ] `MANIFEST.md` совпадает, stale managed files удалены exporter-ом.

## 5. X thread

Текст рядом с этим чеклистом: `X_THREAD.md`.

- [ ] Видео прикреплено к посту 1.
- [ ] `@nansen_ai` и repo URL находятся в посте 1, не только в последнем reply.
- [ ] Число calls взято из Usage Analytics и ≥1,000; placeholder не опубликован.
- [ ] Hero screenshot — reputation; второй screenshot — liquidation map.
- [ ] Thread не продаёт «53 endpoints» как hero. Hero — **who is behind this probability?**

## 6. Official entry form

- [ ] Email.
- [ ] X post URL.
- [ ] Public GitHub URL.
- [ ] Отправлено 26 сентября, не в последний час 27-го.
- [ ] Сохранён screenshot/confirmation URL.
- [ ] В соседнем `README.md` (`docs/submission.md` в public repo) заменены `<ADD ...>` и
      статус изменён только после подтверждения.

## 7. Freeze

- [ ] После записи не добавлять новые фичи.
- [ ] Только критические fixes; после каждого — новый live smoke и проверка видео/repo links.
