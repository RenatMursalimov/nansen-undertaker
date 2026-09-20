# Nansen Meridian: план на победу, а не на ещё один endpoint

Дата ревизии: 20 сентября 2026. Дедлайн: **27 сентября, 23:59 UTC**.

## Вердикт независимой ревизии

Интеграция технически широкая: 53 API-маршрута в клиенте, 25 описанных workflow, восемь
классов отказа, телеметрия, картинки, Telegram-команды и кнопки. Но ширина сама по себе конкурс
не выигрывает. Она даже мешает, если за 60 секунд судья пытается понять, что именно запомнить.

**Победный продукт — один:**

> Рынок Polymarket говорит 78% YES. Гробовщик отвечает: **чьи это 78%** — сколько денег за
> стороной принадлежит кошелькам, которые раньше угадывали, и сколько истории нам неизвестно.

Это не dashboard и не «ещё пять полей». Данные Nansen меняют аналитический вывод: одинаковые
78% становятся разными объектами в зависимости от качества денег за вероятностью.

**Два доказательства глубины, но не два конкурирующих pitch:**

1. карта ликвидаций — где по цене стоит чужое плечо;
2. smart-money buy как процент капитализации — $48K в токен на $2.1M это 2.3% всей капы,
   те же $48K в $50B токен — шум.

Семантика честных отказов, стоимость каждого экрана и воспроизводимая телеметрия — **trust
moat**, но не headline. В ролике им одна строка, в README — техническая глубина.

---

## Что требуют правила — четыре равные четверти

По [официальной странице кампании](https://nansen.ai/campaigns/meridian-buildathon) судят четыре
равные части: Data Integration, Functionality, Creativity & Originality, Documentation &
Submission. По [официальному FAQ](https://nansen.featurebase.app/help/articles/3540155-nansen-meridian-buildathon-sep-14-27)
также обязательны:

- **1,000+ API calls** именно между 14 и 27 сентября;
- публичный GitHub;
- X-пост с тегом `@nansen_ai` и ссылкой на GitHub;
- 30–60 секунд screen recording с **живыми** данными Nansen, понятная без звука;
- отправка entry form до 27 сентября 23:59 UTC.

### Наша матрица

| Критерий | Что предъявляем | Риск сейчас |
|---|---|---|
| Data Integration 25% | top holders + lifetime wallet history **сами определяют вывод** hero-screen; ещё liquidation levels и smart-money % mcap | live hero надо прогнать после hardening |
| Functionality 25% | работающий Telegram flow + live smoke + публичные offline tests | видео ещё нет; нужен стабильный market_id |
| Creativity 25% | «чьи 78%?» — в публичных примерах такого нет | нельзя размыть 25 workflow в одном pitch |
| Documentation 25% | public repo, generated catalog, exact demo script, reproducible live smoke | README надо держать hero-first, без конфликтующих счётчиков |

---

## P0: 1,050 network calls сделаны; eligibility ждёт скрин Usage Analytics

20 сентября meaningful corpus завершился ровно на hard cap: **1,050 client invocations,
1,050 network calls, 0 cache hits**. Это произошло внутри конкурсного окна. Санированный proof:
`nansen/proofs/MERIDIAN_CORPUS_2026-09-20.md`.

Авторитетный внешний артефакт получен: screenshot Usage Analytics показывает **5,484 calls
20 сентября** и 13,850 total в 30D. Один Sep 20 уже превышает обязательные 1,000 внутри окна.
Перед публикацией screenshot надо обрезать до панели Nansen: в исходнике видны browser chrome,
bookmarks и wallet-balance area.

Корпус больше НЕ запускать ради eligibility, если dashboard уже показывает ≥1,000. Он построил
настоящий 7-дневный research corpus для low-cap discovery:

```bash
# Уже выполнено 20 сентября. Команды оставлены для воспроизводимости, НЕ повторять ради порога.
./venv/bin/python3 tools/nansen_meridian_corpus.py --max-calls 1050
./venv/bin/python3 tools/nansen_meridian_corpus.py --run --max-calls 1050
```

Результат: 155 найденных токенов, 1,048 latest unique cells по 75 токенам, 414 top-100 partial
cells и 2 transient failures. В checkpoint сохраняются только агрегированные counts/volumes,
**без адресов покупателей**. Ranking явно exploratory из-за partial cells.

После запуска всё равно проверить Nansen Usage Analytics: cache hits не являются network calls,
а локальная телеметрия не знает о вызовах до её установки.

---

## Конкуренты и чему у них стоит научиться

### smartmoney.sh

[Публичный пример](https://x.com/zacxbt/status/2098107107094733016): терминал по покупкам,
продажам и PnL smart wallets по нескольким сетям. [Отзыв пользователя](https://x.com/0xsammy/status/2098400411417727302)
показывает реальную пользу: искать low-cap токены с осмысленным потоком.

**Сильная сторона:** одна понятная ежедневная задача. **Наша разница:** Telegram уже там, где
сидит человек; плюс % от капитализации, Polymarket и плечо.

### id8.markets

[Публичный пример](https://x.com/BawsaXBT/status/2098224639436808575): пользователь формулирует
тезис, инструмент его допрашивает, заставляет зафиксировать числовое условие опровержения и
потом следит за ним. Сделку не отправляет.

**Главный урок:** выигрывает не показ данных, а workflow с позицией. Причём хороший инструмент
не только помогает — он **ограничивает** человека, не позволяя взять размер без условия смерти
тезиса. Это следующий продукт после конкурса; до 27-го не начинать рядом с submission.

### Zatto

[Public repo](https://github.com/sneg55/zatto): измеряет, сколько новых покупателей пришло после
smart-money buy, и что стало с ценой через сутки; отделяет «crowded» от «quiet», имеет live demo,
CI и live proof script.

**Сильная сторона:** узкий claim, measured method, live URL. **Наша разница:** качество денег за
вероятностью Polymarket, а не crowding за токеном. **Что перенять:** live proof как отдельная
команда и один narrow claim в первой строке README.

### Общий вывод

Не побеждать количеством endpoints. Побеждать новым вопросом, на который Nansen позволяет
ответить: **who is behind this probability?**

---

## 52-секундный ролик без голоса

Перед записью:

1. Английский интерфейс/чат, никаких личных адресов и служебных чатов.
2. Один заранее проверенный активный рынок + один запасной.
3. Остаток кредитов достаточный.
4. Live proof:
   ```bash
   ./venv/bin/python3 tools/nansen_live_smoke.py --run --market-id <ID>
   ```
   До 4 read-only calls при `top=3`; нужен хотя бы один `known history` и `provider failures: 0`.
5. Записывать **живой** Telegram, не fixtures.

### Кадры

| Время | Кадр | Текст на экране |
|---:|---|---|
| 0–3 | чёрный title card | `A market says 78% YES. But whose conviction is it?` |
| 3–9 | Telegram → `polymarket markets` | live список, probability/volume, `Source: Nansen` |
| 9–12 | тап `🎭 1` | `Checking holders — up to 6 live Nansen requests` |
| 12–26 | hero result | highlight: `Of $X examined, $Y (Z%) sits with wallets below 40% win rate` |
| 26–35 | два holder rows | Yes/No, entry→current, win rate, PnL |
| 35–41 | honesty row | `N holders have no measurable history — counted on NEITHER side` |
| 41–47 | footer | `Source: Nansen · just now · requests: N` |
| 47–52 | финальная карточка | `Nansen data changes the conclusion — not just the UI` + repo URL |

**Не показывать в основном ролике:** тесты, forced failure, Agent, trading, telemetry dashboard,
24 сценария. Они доказывают глубину в README, но съедают сюжет.

**Backup-ролик**, если истории держателей нестабильны: `smart trades` → highlight `% of mcap` →
`liquidation map BTC`. Надёжнее, но менее оригинально.

---

## Roadmap до 27 сентября

### 20–21 сентября — reliability и eligibility

- [x] слить winner-hardening: exact market identity, partial-failure semantics, parallel summaries,
      separate telemetry scenes;
- [x] прогнать live smoke по primary `1130012` и backup `4323345`;
- [x] meaningful corpus завершён: 1,050 network calls, 0 cache hits, hard cap соблюдён;
- [x] Usage Analytics: 5,484 calls 20 сентября, 13,850 total 30D; threshold подтверждён;
- [ ] сохранить обрезанный screenshot Usage Analytics без browser chrome/wallet area.

### 22–23 сентября — контент, не новые фичи

- [x] выбрать основной `1130012` и запасной `4323345` рынки;
- [ ] записать 2–3 silent takes, выбрать один без сбоя;
- [ ] кадр-за-кадром проверить: нет адресов участников, ключей, служебной лички;
- [ ] сделать hero screenshot и liquidation-map screenshot.

### 24–25 сентября — X и submission

- [ ] опубликовать thread из `nansen/submission/X_THREAD.md`, первый пост с видео;
- [ ] тег `@nansen_ai` и public repo в первом посте;
- [ ] собрать числа `tools/nansen_daily.py --submission START END`;
- [ ] сверить локальные calls с Nansen Usage Analytics (для eligibility ведёт кабинет);
- [ ] заполнить entry form, не ждать последнего часа.

### 26 сентября — отправка за сутки

- [ ] submit до 27-го, лучше 26-го;
- [ ] сохранить URL подтверждения/скрин формы;
- [ ] больше не менять hero logic без критического бага.

### 27 сентября — только контроль

- [ ] public repo доступен без авторизации, CI green;
- [ ] X-видео открывается без звука и ссылка ведёт в repo;
- [ ] никаких `<TBD>` в submission draft.

---

## Что НЕ делать до дедлайна

- не добавлять ещё endpoints ради числа;
- не строить thesis-invalidation/watch-conviction до закрытия eligibility/video/form;
- не делать live trade главным demo — он уводит от уникального Polymarket insight и добавляет
  security/reliability risk;
- не демонстрировать 24 workflow подряд;
- не утверждать «1,000 calls» по локальному логу: только по Usage Analytics.

---

Источники интернета пересказаны, а не скопированы дословно. Content was rephrased for compliance
with licensing restrictions.
