#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/nansen_catalog.py — СОБРАТЬ КАТАЛОГ ВСЕХ СЦЕНАРИЕВ НА ДАННЫХ NANSEN.

    python3 tools/nansen_catalog.py            # проверить и напечатать
    python3 tools/nansen_catalog.py --write    # записать в nansen/CATALOG.md
    python3 tools/nansen_catalog.py --check    # только проверка, код 1 при расхождении

ЗАЧЕМ ЭТО ГЕНЕРАТОР, А НЕ ПРОСТО ДОКУМЕНТ

Запрос владельца: «сформируй все сценарии, какие есть с Nansen, чтобы они были передо мной, и
запушить их в публичный репозиторий, на основе них ещё твиты напишу».

Документ, написанный руками, начинает врать на первой правке кода: экран переименовали, команду
убрали, эндпоинт похоронили - а в документе он остался. И врёт он молча. Особенно дорого это
здесь: по этому документу пишутся твиты, то есть ПУБЛИЧНЫЕ обещания. Обещать фичу, которой нет,
хуже, чем не обещать ничего.

Поэтому каталог - вывод инструмента, и у инструмента есть ПРОВЕРКА. Она не даёт записать в
каталог:
  * команду, которую роутер бота не узнаёт (`is_onchain_command`);
  * эндпоинт, которого нет в клиенте (значит он похоронен или переименован);
  * ключ меню, которого нет в реестре подписей;
  * сцену, которой нет в закрытом реестре телеметрии.
Нашлось - каталог НЕ пишется, и печатается, что именно разошлось. Ровно как скруббер у
публичной выжимки: проверка на выходе, а не обещание быть внимательным.

ЧТО ЗДЕСЬ РУЧНОЕ, И ЭТО ЧЕСТНО: тексты «что придёт», «зачем» и англоязычная зацепка для твита -
редакторские, автоматом их не выведешь. Но КАЖДОЕ техническое утверждение рядом с ними
проверяется, поэтому каталог не может пообещать несуществующее.

ЦЕНА НАЗЫВАЕТСЯ ТАК, КАК ИЗМЕРЕНА. Где цена эндпоинта названа официальным списком - в кредитах.
Где нет - ЧИСЛОМ ЗАПРОСОВ, и это не уклонение: придуманная цена в документе, по которому пишут
твиты, это ложь в самом проверяемом месте.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'onchain'))
os.environ.setdefault('DB_BACKEND', 'sqlite')

#: КАТАЛОГ. Поля:
#:   id      - короткий якорь
#:   title   - заголовок сценария
#:   cmds    - команды словами (проверяются роутером)
#:   btns    - как позвать кнопкой (человеческий путь, не callback_data)
#:   eps     - эндпоинты Nansen (проверяются по клиенту)
#:   scene   - сцена телеметрии (проверяется по реестру)
#:   price   - цена так, как она ИЗМЕРЕНА
#:   gives   - что придёт
#:   why     - зачем это, одной мыслью
#:   hook    - зацепка для твита (EN), ≤200 символов
#:   menu    - ключ подписи в меню (проверяется), либо None
#:   where   - ГДЕ это можно позвать (проверяется, см. WHERE_KINDS). Нет поля = только личка.
#:   gcb     - callback-данные групповой кнопки (обязательны при where='group_btn')
#:
#: ПОЧЕМУ ПОЯВИЛОСЬ ПОЛЕ `where`. Запрос владельца: «указано ли, что множество сценариев можно
#: не только в личке, но и в группе запрашивать у агента». Ответ на момент запроса был - НЕТ, и
#: это была не забытая строчка в документе, а отсутствие самого утверждения: каталог обещал
#: «скажи боту» и «нажми кнопку», не говоря, в каком чате это работает. Человек, прочитавший
#: каталог в группе и набравший там «смарт потоки», не получал НИЧЕГО - команды словами живут
#: только в личке. Молчание документа о поверхности - это обещание, которое он не держит.
WHERE_KINDS = ('dm', 'group_btn', 'group_agent')
SCENARIOS = [
    # ── SMART MONEY ───────────────────────────────────────────────────────────
    {'id': 'flows', 'title': '💹 Приток smart money по окнам',
     'cmds': ['смарт потоки'], 'btns': ['🧠 Nansen → 🧠 Умные деньги → 💹 Смарт-потоки → 1ч/24ч/7д/30д'],
     'eps': ['smart-money/netflow'], 'scene': 'smart_flows', 'menu': 'nsn_flows',
     'price': 'цена не названа в официальном списке · считаем отдельной строкой',
     'gives': 'тикеры с нетто-притоком за окно; тап по тикеру открывает карточку токена',
     'why': 'итог за окно отвечает «сколько», и это первый вопрос по любому токену',
     'hook': 'Smart money net inflow by window (1h/24h/7d/30d), straight into a Telegram chat. '
             'Tap a ticker and the full token card opens.'},
    {'id': 'trends', 'title': '🔥 Smart Money в общем экране Трендов',
     'cmds': [], 'btns': ['🧠 Nansen → 🧠 Умные деньги → 🔥 Скринер: приток за 24ч'],
     'eps': ['token-screener'], 'scene': 'trends', 'menu': 'nsn_screener',
     'price': '1 кредит',
     'gives': 'токены с положительным netflow в формате общего экрана трендов; тап открывает '
              'карточку токена',
     'why': 'Nansen не отдельный режим, а часть ежедневного маршрута: в хабе Трендов кнопка '
            '«🧠 Nansen» открывает то же подменю, что в Ончейне, а этот экран — тренд → '
            'карточка → держатели/потоки/сделки',
     'hook': 'Nansen is not a separate dashboard here. Smart-money inflow is embedded into the '
             'daily Trends screen, one tap away from the token card.'},
    {'id': 'holdings', 'title': '💼 Что копит smart money',
     'cmds': ['смарт холдинги'], 'btns': ['🧠 Nansen → 🧠 Умные деньги → 💼 Что копят'],
     'eps': ['smart-money/holdings'], 'scene': 'smart_holdings', 'menu': 'nsn_holdings',
     'price': '3 кредита',
     'gives': 'топ позиций по $ с изменением за сутки',
     'why': 'поток говорит «что берут сейчас», холдинги - «что уже держат»',
     'hook': 'What smart money already holds, not just what they bought today.'},
    {'id': 'trades', 'app': True, 'title': '🧠 Сделки smart money за сутки + доля от капитализации',
     'cmds': ['смарт сделки'], 'btns': ['🧠 Nansen → 🧠 Умные деньги → 🧠 Сделки сейчас'],
     'eps': ['smart-money/dex-trades'], 'scene': 'smart_trades', 'menu': 'nsn_trades',
     'price': '1–5 кредитов',
     'gives': 'кто, во что и на сколько зашёл, плюс капитализация токена и ДОЛЯ сделки от неё',
     'why': '«$48K зашли в токен» - ни о чём, пока не сказано, во что: $48K в токен на $2.1M '
            'это 2.3% всей капитализации и сигнал, а в токен на $50B - шум',
     'hook': 'Smart money trades with the number that matters: $48K into a $2.1M token is '
             '2.3% of its entire market cap. The same $48K into a $50B token is noise.'},
    # ── ПЕРПЫ И ПЛЕЧО ─────────────────────────────────────────────────────────
    {'id': 'perpleaders', 'title': '🏆 Топ перп-трейдеров',
     'cmds': ['топ перпы'], 'btns': ['🧠 Nansen → ⚔️ Чужое плечо → 🏆 Топ перп-трейдеры'],
     'eps': ['perp-leaderboard'], 'scene': 'perp_leaders', 'menu': 'nsn_perps',
     'price': '5 кредитов',
     'gives': 'прибыльные счета на перпах; тап по трейдеру открывает его счёт',
     'why': 'кто зарабатывает на плече прямо сейчас',
     'hook': 'Top perp traders by PnL, tappable straight into their wallet.'},
    {'id': 'perppos', 'title': '💥 Позиции с плечом и ЦЕНА ЛИКВИДАЦИИ по токену',
     'cmds': ['перп позиции BTC', 'ликвидации BTC'],
     'btns': ['карточка токена (например BTC) → 💥 Ликвид.'],
     'eps': ['tgm/perp-positions'], 'scene': 'perp_positions', 'menu': 'nsn_perppos',
     'where': ('dm', 'group_btn'), 'gcb': 'cx:perp',
     'price': '5 кредитов',
     'gives': 'размер позиции, плечо, нереализованный PnL и цену ликвидации по каждому счёту',
     'why': 'до этого эндпоинта цены ликвидации у нас не было вовсе - про неё догадывались '
            'по цене входа',
     'hook': 'Leveraged positions with the one number nobody shows: the liquidation price.'},
    {'id': 'liqmap', 'app': True, 'title': '🗺 Карта ликвидаций: где висит чужое плечо',
     'cmds': ['карта ликвидаций BTC', 'ликвид карта BTC'],
     'btns': ['карточка токена → 💥 Ликвид. → 🗺 Карта ликвидаций',
              'мини-апп → 🗺 Liquidations → тикер кнопкой или своим вводом'],
     'eps': ['tgm/perp-positions'], 'scene': 'liq_map', 'menu': 'nsn_liqmap',
     'where': ('dm', 'group_btn'), 'gcb': 'cx:liqmap',
     'price': '5 кредитов (тот же запрос, что у списка позиций)',
     'gives': 'картинку: суммы позиций по уровням цены ликвидации, красное - лонги, зелёное - '
              'шорты, синее - деньги на кошельках с меткой Nansen, пунктир - текущая цена. '
              'Плюс подпись величиной. Тикер ЛЮБОЙ, какой есть на площадке; кнопки в '
              'мини-аппе - топ по измеренному суточному объёму Hyperliquid, а не зашитый список',
     'why': 'список позиций отвечает «кто стоит», а карта - «на каком уровне рынок поедет '
            'быстро»; это не строка, а распределение',
     'hook': 'A liquidation map: $22.5M of leverage stacked between $61.5K and $62.4K. '
             'The list tells you who is in. The map tells you where the market moves fast.'},
    {'id': 'walletperps', 'title': '🩺 Счёт кошелька на перпах и запас до ликвидации',
     'cmds': ['нансен перпы 0x…'], 'btns': ['🧠 Nansen → ⚔️ Чужое плечо → 🩺 Счёт на перпах'],
     'eps': ['profiler/perp-positions'], 'scene': 'wallet_perps', 'menu': 'nsn_wperps',
     'price': 'цена не названа в официальном списке',
     'gives': 'капитал, сколько под залогом, нереализованный PnL, здоровье счёта и позиции',
     'why': 'главный вопрос про кита с плечом - не «что он держит», а «сколько ему осталось»',
     'hook': 'How much room a leveraged whale has left before liquidation.'},
    # ── ТОКЕН ─────────────────────────────────────────────────────────────────
    {'id': 'tokencheck', 'title': '🧠 Разбор токена: потоки, Nansen Score, метки холдеров',
     'cmds': ['паспорт 0x… глубже'], 'btns': ['карточка токена/мема → 🧠'],
     'eps': ['tgm/flow-intelligence', 'tgm/indicators', 'tgm/holders',
             'tgm/pnl-leaderboard'],
     'scene': 'token_check', 'menu': 'nsn_token',
     'where': ('dm', 'group_btn'), 'gcb': 'hs:nsn',
     'price': '4 запроса, около 12 кредитов',
     'gives': 'нетто-потоки по сегментам холдеров, Nansen Score, метки топ-холдеров, топ по PnL',
     'why': 'один экран отвечает на «кто в этом токене» четырьмя разными способами',
     'hook': 'Four Nansen lenses on one token in a single tap: segment flows, Nansen Score, '
             'labelled top holders, top PnL.'},
    {'id': 'wbs', 'title': '🔄 Кто нетто покупал и кто продавал токен',
     'cmds': ['кто входил 0x… 7', 'кто выходил 0x…'],
     'btns': ['карточка токена → 🧠 → 🔄 Кто входил'],
     'eps': ['tgm/who-bought-sold'], 'scene': 'who_bought_sold', 'menu': 'nsn_wbs',
     'where': ('dm', 'group_btn'), 'gcb': 'hs:wbs',
     'price': '1 кредит за сторону',
     'gives': 'метку или адрес и объём $ по каждой стороне за период',
     'why': 'нетто-поток - это итог; здесь видно, КТО его сделал',
     'hook': 'Who net-bought and who net-sold a token over the last N days, by label.'},
    {'id': 'tinfo', 'title': '🪪 Справка по токену от Nansen',
     'cmds': ['инфо токен 0x…'], 'btns': ['🧠 Nansen → 🔎 Кошелёк и токен → 🪪 Справка по токену'],
     'eps': ['tgm/token-information'], 'scene': 'token_info', 'menu': 'nsn_tinfo',
     'price': '1 кредит',
     'gives': 'капитализацию, объём, ликвидность, число держателей',
     'why': 'базовые метрики из того же источника, что и всё остальное - без второго вендора',
     'hook': 'Token fundamentals from the same source as the flows: one key, one story.'},
    {'id': 'flowpng', 'title': '📊 Потоки по сегментам холдеров КАРТИНКОЙ',
     'cmds': ['потоки картинкой 0x…'], 'btns': ['карточка токена → 🧠 → 📊 Потоки картинкой'],
     'eps': ['tgm/flow-intelligence'], 'scene': 'token_check', 'menu': 'nsn_flowpng',
     'where': ('dm', 'group_btn'), 'gcb': 'hs:nflow',
     'price': '1 кредит',
     'gives': 'столбики по сегментам (smart money, киты, топ-PnL, публичные фигуры, биржи, '
              'свежие кошельки); цвет означает ЗНАК потока, источник вшит в полотно',
     'why': 'текст отвечает «сколько», картинка - «кто против кого»: умные деньги набирают, '
            'пока киты сливают, и на столбиках это видно за полсекунды',
     'hook': 'Holder-segment flows as a chart: smart money accumulating while whales dump is '
             'a half-second read, not a paragraph.'},
    {'id': 'backtest', 'title': '🧪 Бэктест по свечам из ончейна',
     'cmds': [], 'btns': ['карточка мема → 🧪 Бэктест'],
     'eps': ['tgm/historical-token-ohlcv'], 'scene': 'chart', 'menu': None,
     'price': '5 кредитов за 89 дневных свечей',
     'gives': 'прогон простой стратегии по историческим свечам токена',
     'why': 'у мема нет биржевого графика, а проверить идею хочется на его собственной истории',
     'hook': 'Backtest an idea on a memecoin that no exchange lists, using onchain candles.'},
    # ── КОШЕЛЁК ───────────────────────────────────────────────────────────────
    {'id': 'profile', 'title': '👤 Профиль кошелька: метки, PnL, связанные',
     'cmds': ['профиль 0x…', 'профиль 0x… глубже'],
     'btns': ['голый адрес в личку → 🕵 Досье'],
     'eps': ['profiler/address/labels', 'profiler/address/pnl-summary',
             'profiler/address/related-wallets', 'profiler/address/premium-labels'],
     'scene': 'wallet_profile', 'menu': 'nsn_profile',
     'price': '3 запроса; «глубже» добавляет премиум-метки за 150 кредитов',
     'gives': 'метки, PnL и winrate, связанные кошельки',
     'why': 'первый вопрос про незнакомый адрес - «кто это»; «меток нет» при этом НЕ значит '
            '«адрес чистый», и экран говорит это прямо',
     'hook': 'Wallet dossier: labels, PnL, related wallets. And when there are no labels it '
             'says so in words instead of showing an empty panel.'},
    {'id': 'cparty', 'title': '🤝 С кем кошелёк торгует чаще всего',
     'cmds': ['контрагенты 0x…'], 'btns': ['🧠 Nansen → 🔎 Кошелёк и токен → 🤝 Контрагенты'],
     'eps': ['profiler/address/counterparties'], 'scene': 'counterparties',
     'menu': 'nsn_cparty', 'price': 'цена не названа в официальном списке',
     'gives': 'контрагентов за 30 дней и объёмы',
     'why': 'связи адреса говорят о нём больше, чем его баланс',
     'hook': "Who a wallet actually trades with. Its counterparties say more than its balance."},
    {'id': 'balance', 'title': '💼 Портфель кошелька по данным Nansen',
     'cmds': ['нансен баланс 0x…'], 'btns': ['🧠 Nansen → 🔎 Кошелёк и токен → 💼 Портфель кошелька'],
     'eps': ['profiler/address/current-balance'], 'scene': 'wallet_balance',
     'menu': 'nsn_bal', 'price': 'цена не названа в официальном списке',
     'gives': 'состав портфеля по $ без спам-токенов',
     'why': 'тот же ключ вместо отдельного платного вендора по балансам',
     'hook': 'Wallet portfolio from the same API key - one vendor fewer in the stack.'},
    # ── POLYMARKET ────────────────────────────────────────────────────────────
    {'id': 'pmmarkets', 'app': True, 'title': '🎲 Трендовые рынки Polymarket с market_id',
     'cmds': ['полимаркет рынки', 'polymarket markets'], 'btns': ['🧠 Nansen → 🎲 Polymarket → 🎲 Трендовые рынки'],
     'eps': ['prediction-market/market-screener'], 'scene': 'pm_markets',
     'menu': 'pm_markets', 'price': 'цена не названа в официальном списке',
     'gives': 'рынки по объёму, вероятность, объём за сутки и КОПИРУЕМЫЙ market_id; под '
              'списком три ряда кнопок',
     'why': 'без печати market_id три соседних экрана существовали формально: позвать их было '
            'нечем',
     'hook': 'Trending prediction markets with the id printed, so the next three screens are '
             'one tap away instead of impossible.'},
    {'id': 'pmchart', 'title': '📈 График вероятности рынка во времени',
     'cmds': ['полимаркет график 654412'], 'btns': ['список рынков → 📈 N'],
     'eps': ['prediction-market/ohlcv'], 'scene': 'pm_chart', 'menu': 'pm_chart',
     'price': 'цена не названа в официальном списке',
     'gives': 'картинку: как менялась вероятность, линия 50% отделяет «скорее да» от «скорее '
              'нет»',
     'why': '45% после 20% и 45% после 70% - противоположные истории, а одно число их не '
            'различает',
     'hook': '45% after 20% and 45% after 70% are opposite stories. One number cannot tell '
             'them apart, so we draw the path.'},
    {'id': 'pmbook', 'title': '📖 Стакан рынка Polymarket',
     'cmds': ['полимаркет стакан 654412'], 'btns': ['список рынков → 📖 N'],
     'eps': ['prediction-market/orderbook'], 'scene': 'pm_orderbook', 'menu': 'pm_book',
     'price': 'цена не названа в официальном списке',
     'gives': 'уровни заявок по сторонам и строку глубины',
     'why': '«45%» при пустом стакане и «45%» при плотном - разные вещи: цена говорит, во что '
            'верят, стакан - сколько стоит это проверить деньгами',
     'hook': 'Price says what people believe. The order book says what it costs to test that '
             'belief with money.'},
    {'id': 'pmrep', 'app': True, 'title': '🎭 Кто держит рынок и как угадывал раньше',
     'cmds': ['репутация рынка 654412', 'кто держит рынок 654412',
              'market reputation 654412', 'who holds market 654412'],
     'btns': ['список рынков → 🎭 N'],
     'eps': ['prediction-market/top-holders', 'prediction-market/address-summary'],
     'scene': 'pm_reputation', 'menu': 'pm_rep',
     'price': '6 запросов (держатели + лайфтайм-история каждого из пяти)',
     'gives': 'сколько денег лежит у кошельков с винрейтом ниже порога, разбивку по сторонам '
              'и держателей с винрейтом, PnL и числом рынков',
     'why': '«78% Yes» - консенсус КОГО? Одно число одинаково выглядит, когда деньги поставили '
            'кошельки с винрейтом 70% и когда с винрейтом 35%; первое сигнал, второе '
            'приглашение встать против',
     'hook': '"78% Yes" - but whose 78%? $1.4M of that $2.1M sits with wallets whose win rate '
             'is below 40%. The price cannot tell a signal from a crowd.'},
    {'id': 'pmwallet', 'title': '🎰 Профиль трейдера Polymarket',
     'cmds': ['полимаркет профиль 0x…'], 'btns': ['🎲 Polymarket → 🎰 Профиль трейдера'],
     'eps': ['prediction-market/address-summary', 'prediction-market/pnl-by-address'],
     'scene': 'pm_wallet', 'menu': 'pm_profile',
     'price': '2 запроса',
     'gives': 'лайфтайм PnL, winrate, возраст кошелька и топ-рынки по PnL',
     'why': 'прежде чем копировать чью-то ставку, полезно знать, чем кончались предыдущие',
     'hook': 'Before copying a bet, check how the previous ones ended: lifetime PnL, win rate, '
             'best and worst markets.'},
    {'id': 'pmleaders', 'title': '🏆 Топ-трейдеры конкретного рынка',
     'cmds': ['топ рынка 654412'], 'btns': ['🎲 Polymarket → 🏆 Топ-трейдеры рынка'],
     'eps': ['prediction-market/pnl-by-market'], 'scene': 'pm_leaders', 'menu': 'pm_leaders',
     'price': 'цена не названа в официальном списке',
     'gives': 'кто больше всех заработал и потерял на этом рынке, с указанием стороны',
     'why': 'победители и проигравшие одного рынка - самый быстрый способ понять, кто им '
            'занимается',
     'hook': 'Winners and losers of a single prediction market, with the side they held.'},
    # ── АГЕНТ И ОБЩЕЕ ─────────────────────────────────────────────────────────
    {'id': 'agent', 'title': '🔍 Свободный вопрос агенту Nansen',
     'cmds': [], 'btns': ['биржевая карточка → 🔍 Nansen', 'вопрос в личке или в чате'],
     'eps': ['agent/fast', 'agent/expert'], 'scene': 'agent_free', 'menu': None,
     'where': ('dm', 'group_btn', 'group_agent'), 'gcb': 'cx:nansen',
     'price': '200 кредитов (fast) или 750 (expert) - САМЫЙ дорогой путь',
     'gives': 'ответ агента на вопрос словами, с подписью источника',
     'why': 'единственная дверь для вопросов, под которые нет структурного эндпоинта',
     'hook': 'The agent is the expensive path: 200 credits, or 750 in expert mode. So every '
             'screen prints what it cost.'},
    # ── ОТКРЫТО ЖИВОЙ ПРОБОЙ СХЕМ 24.09 ─────────────────────────────────────────────────
    {'id': 'dca', 'app': True, 'title': '🧊 Кто покупает по расписанию (DCA умных денег)',
     'cmds': ['dca', 'кто набирает'], 'btns': ['🧠 Nansen → 🧠 Умные деньги → 🧊 Покупают по расписанию'],
     'eps': ['smart-money/dcas'], 'scene': 'smart_dca', 'menu': 'nsn_dca',
     'price': 'цена не названа в официальном списке · 1 запрос',
     'gives': 'активные программы DCA: кто, из чего во что, размер программы и какая доля уже '
              'потрачена',
     'why': 'единственный сигнал в наборе про БУДУЩИЕ покупки: разовая сделка на $2M и '
            'программа DCA на $2M - разные утверждения о намерении',
     'hook': 'A single trade says what a wallet did. A DCA program says what it is committed to '
             'keep doing - and how much of that is still ahead.'},
    {'id': 'chains', 'app': True, 'title': '🌐 Рейтинг сетей: TVL, объём DEX, активные адреса',
     'cmds': ['рейтинг сетей', 'chain rank'], 'btns': ['🧠 Nansen → 🌐 Сети и зачёт → 🌐 Рейтинг сетей'],
     'eps': ['chains/chain-rank'], 'scene': 'chain_rank', 'menu': 'nsn_chains',
     'price': 'цена не названа в официальном списке · 1 запрос',
     'gives': 'сети по TVL с их суточным изменением, объёмом DEX и активными адресами',
     'why': 'вопрос «куда вообще смотреть сегодня» решается на уровне сети раньше, чем на '
            'уровне токена',
     'hook': 'Where to look today is a question about chains before it is a question about '
             'tokens: TVL, DEX volume and active addresses with their daily change.'},
    {'id': 'defi', 'title': '💠 DeFi-часть кошелька: активы МИНУС долги',
     'cmds': ['дефи 0x…'], 'btns': ['🧠 Nansen → 🔎 Кошелёк и токен → 💠 DeFi-часть'],
     'eps': ['portfolio/defi-holdings'], 'scene': 'defi_holdings', 'menu': 'nsn_defi',
     'price': 'цена не названа в официальном списке · 1 запрос',
     'gives': 'чистую величину (активы минус долги), незабранные награды и список протоколов '
              'по размеру',
     'why': 'кошелёк на $2M без долга и кошелёк на $2M с долгом $1.7M по списку токенов '
            'выглядят одинаково, а это разные кошельки',
     'hook': 'A wallet holding two million with one and a half million of debt looks identical '
             'to a debt-free one in a token list. Here it does not.'},
    {'id': 'pmpos', 'app': True, 'title': '🧾 Кто в рынке Polymarket и с каким PnL',
     'cmds': ['позиции рынка 654412', 'кто в рынке 654412'],
     # КНОПКА «🧾 N» ПОД СПИСКОМ РЫНКОВ - ГЛАВНЫЙ ВХОД, А КОМАНДА С НОМЕРОМ - БЫСТРЫЙ ПУТЬ
     # для того, у кого номер уже есть. До этого экран был достижим ТОЛЬКО номером руками, то
     # есть требовал работы вне бота (замечание владельца: «опять идентификатор заставляешь
     # искать»). Тот же дефект и то же лечение, что у графика и стакана рынка.
     'btns': ['🎲 Трендовые рынки → кнопка «🧾 N» под списком',
              '🧠 Nansen → 🎲 Polymarket → 🧾 Кто в рынке и с каким PnL'],
     'eps': ['prediction-market/position-detail'], 'scene': 'pm_positions',
     'menu': 'pm_posdetail',
     'price': 'цена не названа в официальном списке · 1 запрос',
     'gives': 'всех держателей рынка с их PnL именно по этому рынку: вход, текущая цена, '
              'реализованное и открытое',
     'why': 'экран репутации говорит, как держатели угадывали ВООБЩЕ; этот - как у них идёт '
            'ИМЕННО ЗДЕСЬ, и вместе они отвечают «кто умеет» против «кто пока в плюсе»',
     'hook': 'Reputation says how a holder did over a lifetime. This says how the same holder '
             'is doing in this exact market: entry, current price, realized and open.'},
    {'id': 'jupdca', 'title': '🧊 DCA на Jupiter по токену (Solana)',
     'cmds': ['jup dca <mint>'], 'btns': ['🧠 Nansen → 🧠 Умные деньги → 🧊 DCA на Jupiter'],
     'eps': ['tgm/jup-dca'], 'scene': 'jup_dca', 'menu': 'nsn_jupdca',
     'price': 'цена не названа в официальном списке · 1 запрос',
     'gives': 'программы DCA по токену: кто, из чего во что, размер вклада и доля уже '
              'потраченного',
     'why': 'на Solana расписанные покупки идут через Jupiter, и это тот же вопрос о будущих '
            'покупках, только на другой площадке',
     'hook': 'Scheduled buying on Solana runs through Jupiter. Same question as DCA elsewhere: '
             'how much of the commitment is still ahead.'},
    # ── ПОСЛЕДНЯЯ РУЧКА НАБОРА, У КОТОРОЙ ПОЯВИЛАСЬ СХЕМА (круг 4 живой пробы, 24.09) ───
    {'id': 'posintel', 'title': '⚖️ Чьё плечо стоит в токене: киты, смарт-трейдеры, фигуры',
     'cmds': ['позиционирование 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2', 'чьё плечо <адрес>'],
     'btns': ['🔍 Nansen по токену → кнопка «⚖️ Чьё плечо»',
              '🧠 Nansen → ⚔️ Чужое плечо → ⚖️ Чьё плечо стоит в токене'],
     'where': ('dm', 'group_btn'), 'gcb': 'hs:posi',
     'eps': ['tgm/position-intelligence'], 'scene': 'perp_positioning', 'menu': 'nsn_posi',
     'price': 'цена не названа в официальном списке · 1 запрос',
     'gives': 'плечо по сегментам держателей: киты, смарт-трейдеры и публичные фигуры отдельно, '
              'лонги против шортов и перевес знаком',
     'why': 'соседний экран отвечает построчно («кто стоит и где его ликвидация»), а этот - КТО '
            'ПРОТИВ КОГО: киты в лонг на $12M при смарт-трейдерах в шорт на $9M это утверждение, '
            'которого в списке позиций не видно',
     'hook': 'Whales long twelve million while smart traders are short nine. A list of positions '
             'cannot say that: it does not know which wallet belongs to which class.'},
    # ── СРАВНИТЕЛЬНЫЕ ЭКРАНЫ: не «что по этому объекту», а «какой из них выбрать» ────────
    {'id': 'sharpmarkets', 'app': True,
     'title': '🎯 Где на Polymarket деньги острые (сравнение рынков)',
     'cmds': ['острые деньги', 'sharp money'],
     'btns': ['🧠 Nansen → 🎲 Polymarket → 🎯 Где деньги острые'],
     'eps': ['prediction-market/market-screener', 'prediction-market/top-holders',
             'prediction-market/address-summary'],
     'scene': 'sharp_markets', 'menu': 'nsn_sharp',
     'price': 'цена не названа в официальном списке · 1 + N + N×H запросов (по умолчанию 13)',
     'gives': 'четыре разогретых рынка рядом: сколько денег у кошельков с винрейтом от 60% '
              'против денег тех, у кого ниже 40%, и кто крупнейший «острый» держатель',
     'why': 'разбор одного рынка не отвечает на вопрос выбора: из десяти разогретых нужен тот, '
            'где против тебя стоят не случайные люди, а это видно только рядом',
     'hook': 'Four heated Polymarket markets side by side: how much money sits with wallets '
             'that were right before, and how much with wallets that were not.'},
    {'id': 'perprisk', 'app': True, 'title': '⚔️ Борд риска: у кого плечо ближе к обрыву',
     'cmds': ['борд риска', 'risk board'],
     'btns': ['🧠 Nansen → ⚔️ Чужое плечо → ⚔️ Борд риска',
              'карта ликвидаций → ⚔️ Сравнить все четыре'],
     'eps': ['tgm/perp-positions'], 'scene': 'perp_risk', 'menu': 'nsn_board',
     'where': ('dm', 'group_btn'), 'gcb': 'cx:board',
     'price': 'цена не названа в официальном списке · по одному запросу на токен (4)',
     'gives': 'BTC/ETH/SOL/HYPE в порядке БЛИЗОСТИ цены к самому плотному скоплению '
              'ликвидаций: расстояние в процентах, сторона скопления, лонги против шортов и '
              'сколько из этого висит на кошельках с меткой Nansen',
     'why': 'карта одного токена не отвечает на вопрос «а у других как»: рынок первым проедет '
            'тот уровень, до которого путь короче, и сравнение показывает именно его',
     'hook': 'Four perp markets ranked by how close the price is to the densest liquidation '
             'cluster - not by how big that cluster is.'},
    {'id': 'tally', 'title': '🧮 Мой зачёт в конкурсе',
     'cmds': ['нансен зачёт', 'мой зачёт'], 'btns': ['🧠 Nansen → 🌐 Сети и зачёт → 🧮 Мой зачёт'],
     'eps': [], 'scene': None, 'menu': 'nsn_tally', 'price': 'бесплатно, читает свой лог',
     'gives': 'сколько вызовов и кредитов на человеке и его место; лидерборд БЕЗ имён и ID',
     'why': 'многопользовательский бот: вклад считается, а приватность при этом не тратится',
     'hook': 'A multi-user bot counts who asked what - and publishes the leaderboard with no '
             'names and no IDs at all.'},
    {'id': 'digest', 'title': '📰 Утренний дайджест и твит-джобы',
     'cmds': [], 'btns': ['по расписанию, без человека'],
     'eps': ['smart-money/netflow'], 'scene': 'digest_cron', 'menu': None,
     'price': 'считается отдельно от людей: у джобы нет человека, и в зачёт она не идёт',
     'gives': 'секцию smart money в утреннем дайджесте',
     'why': 'фоновые вызовы обязаны быть отделены от людских, иначе расход нельзя объяснить',
     'hook': 'Background jobs are counted separately from humans. Otherwise the monthly spend '
             'cannot be explained to anyone.'},
]


#: АНГЛИЙСКИЕ ПЕРЕВОДЫ РЕДАКТОРСКИХ ПОЛЕЙ, КЛЮЧ = id сценария.
#: ЗАЧЕМ ОТДЕЛЬНЫМ СЛОВАРЁМ, А НЕ ПОЛЯМИ В SCENARIOS. Каталог уезжает в публичный репозиторий
#: конкурса, а конкурс англоязычный: judge-facing документ обязан быть на английском, и он —
#: основной (`CATALOG.md`). Русский аналог живёт рядом (`CATALOG_ru.md`) для владельца. Держать
#: перевод отдельной таблицей, а не дублировать каждое поле внутри SCENARIOS, — чтобы русский и
#: английский правились в ОДНОМ месте на сценарий и не разъезжались молча. `hook` уже английский
#: в обоих языках и здесь не повторяется. `_verify` требует, чтобы у КАЖДОГО сценария был полный
#: перевод: пустое поле тут — та же ложь в судейском документе, что и выдуманная цена.
_EN = {
    'flows': {'cmds': ['smart flows'],
              'btns': ['🧠 Nansen → 🧠 Smart money → 💹 Smart flows (1h/24h/7d/30d)'],
              'title': '💹 Smart money inflow by window',
              'price': 'price not named in the official list · counted on a separate line',
              'gives': 'tickers with net inflow over the window; tapping a ticker opens the '
                       'token card',
              'why': 'the window total answers "how much", the first question about any token'},
    'trends': {'cmds': [], 'btns': ['🧠 Nansen → 🧠 Smart money → 🔥 Screener: 24h inflow'],
               'title': '🔥 Smart Money inside the shared Trends screen',
               'price': '1 credit',
               'gives': 'tokens with positive netflow in the shared Trends screen format; '
                        'a tap opens the token card',
               'why': 'Nansen is not a separate mode but part of the daily route: the Trends '
                      'hub button "🧠 Nansen" opens the very same submenu as Onchain does, and '
                      'this screen is trend → card → holders/flows/trades'},
    'holdings': {'cmds': ['smart holdings'], 'btns': ['🧠 Nansen → 🧠 Smart money → 💼 What they hold'],
                 'title': '💼 What smart money accumulates',
                 'price': '3 credits',
                 'gives': 'top positions by $ with the 24h change',
                 'why': 'flow says "what they are buying now", holdings say "what they already '
                        'hold"'},
    'trades': {'cmds': ['smart trades'], 'btns': ['🧠 Nansen → 🧠 Smart money → 🧠 Trades now'],
               'title': '🧠 Smart money trades over 24h + share of market cap',
               'price': '1–5 credits',
               'gives': 'who entered what and for how much, plus the token market cap and the '
                        "trade's SHARE of it",
               'why': '"$48K went into a token" says nothing until it says into what: $48K into '
                      'a $2.1M token is 2.3% of the entire market cap and a signal, while into '
                      'a $50B token it is noise'},
    'perpleaders': {'cmds': ['top perps'], 'btns': ['🧠 Nansen → ⚔️ Leverage → 🏆 Top perp traders'],
                    'title': '🏆 Top perp traders',
                    'price': '5 credits',
                    'gives': 'profitable perp accounts; tapping a trader opens their account',
                    'why': 'who is making money on leverage right now'},
    'perppos': {'cmds': ['perp positions BTC', 'liquidations BTC'],
                'btns': ['token card (e.g. BTC) → 💥 Liq.'],
                'title': '💥 Leveraged positions and the LIQUIDATION PRICE by token',
                'price': '5 credits',
                'gives': 'position size, leverage, unrealized PnL and the liquidation price for '
                         'each account',
                'why': 'before this endpoint we had no liquidation price at all — it was guessed '
                       'from the entry price'},
    'liqmap': {'cmds': ['liquidation map BTC', 'liq map BTC'],
               'btns': ['token card → 💥 Liq. → 🗺 Liquidation map',
                        'mini-app → 🗺 Liquidations → a ticker button or your own input'],
               'title': "🗺 Liquidation map: where other people's leverage hangs",
               'price': '5 credits (the same request as the position list)',
               'gives': 'an image: position sizes by liquidation-price level, red is longs, '
                        'green is shorts, blue is the money on wallets Nansen has a name for, '
                        'the dashed line is the current price. Plus a caption with the '
                        'magnitude. ANY ticker the venue has; the mini-app buttons are the top '
                        'by measured 24h Hyperliquid volume, not a list kept by hand',
               'why': 'the position list answers "who is in", the map answers "at which level '
                      'the market moves fast"; it is not a line but a distribution'},
    'walletperps': {'cmds': ['nansen perp 0x…'], 'btns': ['🧠 Nansen → ⚔️ Leverage → 🩺 Wallet perp account'],
                    'title': "🩺 A wallet's perp account and room to liquidation",
                    'price': 'price not named in the official list',
                    'gives': 'capital, how much is collateralized, unrealized PnL, account '
                             'health and positions',
                    'why': 'the main question about a leveraged whale is not "what do they hold" '
                           'but "how much room is left"'},
    'tokencheck': {'cmds': ['passport 0x… deep'], 'btns': ['token/meme card → 🧠'],
                   'title': '🧠 Token breakdown: flows, Nansen Score, holder labels',
                   'price': '4 requests, about 12 credits',
                   'gives': 'net flows by holder segment, Nansen Score, top-holder labels, top '
                            'by PnL',
                   'why': 'one screen answers "who is in this token" in four different ways'},
    'wbs': {'cmds': ['who bought 0x… 7', 'who bought sold 0x…'],
            'btns': ['token card → 🧠 → 🔄 Who bought and sold'],
            'title': '🔄 Who net-bought and who sold a token',
            'price': '1 credit per side',
            'gives': 'a label or address and the $ volume for each side over the period',
            'why': 'net flow is the total; here you see WHO made it'},
    'tinfo': {'cmds': ['token info 0x…'], 'btns': ['🧠 Nansen → 🔎 Wallet and token → 🪪 Token information'],
              'title': '🪪 Token info sheet from Nansen',
              'price': '1 credit',
              'gives': 'market cap, volume, liquidity, holder count',
              'why': 'basic metrics from the same source as everything else — no second vendor'},
    'flowpng': {'cmds': ['flows chart 0x…'], 'btns': ['token card → 🧠 → 📊 Flows chart'],
                'title': '📊 Holder-segment flows AS A CHART',
                'price': '1 credit',
                'gives': 'bars by segment (smart money, whales, top-PnL, public figures, '
                         'exchanges, fresh wallets); color means the SIGN of the flow, the '
                         'source is baked into the canvas',
                'why': 'text answers "how much", the chart answers "who against whom": smart '
                       'money accumulating while whales dump is a half-second read on the bars'},
    'backtest': {'cmds': [], 'btns': ['meme card → 🧪 Backtest'],
                 'title': '🧪 Backtest on onchain candles',
                 'price': '5 credits for 89 daily candles',
                 'gives': "a run of a simple strategy over the token's historical candles",
                 'why': 'a meme has no exchange chart, yet you want to test an idea on its own '
                        'history'},
    'profile': {'cmds': ['profile 0x…', 'profile 0x… deep'],
                'btns': ['bare address in DM → 🕵 Dossier'],
                'title': '👤 Wallet profile: labels, PnL, related',
                'price': '3 requests; "deeper" adds premium labels for 150 credits',
                'gives': 'labels, PnL and win rate, related wallets',
                'why': 'the first question about an unknown address is "who is this"; "no '
                       'labels" does NOT mean "clean address", and the screen says so directly'},
    'cparty': {'cmds': ['counterparties 0x…'], 'btns': ['🧠 Nansen → 🔎 Wallet and token → 🤝 Counterparties'],
               'title': '🤝 Who a wallet trades with most',
               'price': 'price not named in the official list',
               'gives': 'counterparties over 30 days and volumes',
               'why': "an address's connections say more about it than its balance"},
    'balance': {'cmds': ['nansen balance 0x…'], 'btns': ['🧠 Nansen → 🔎 Wallet and token → 💼 Wallet portfolio'],
                'title': '💼 Wallet portfolio per Nansen data',
                'price': 'price not named in the official list',
                'gives': 'portfolio composition by $ without spam tokens',
                'why': 'the same key instead of a separate paid balance vendor'},
    'pmmarkets': {'cmds': ['polymarket markets'],
                  'btns': ['🧠 Nansen → 🎲 Polymarket → 🎲 Trending markets'],
                  'title': '🎲 Trending Polymarket markets with market_id',
                  'price': 'price not named in the official list',
                  'gives': 'markets by volume, probability, 24h volume and a COPYABLE '
                           'market_id; three rows of buttons under the list',
                  'why': 'without printing the market_id three neighbouring screens existed '
                         'only formally: there was nothing to call them with'},
    'pmchart': {'cmds': ['polymarket chart 654412'], 'btns': ['markets list → 📈 N'],
                'title': '📈 Market probability chart over time',
                'price': 'price not named in the official list',
                'gives': 'an image: how the probability changed, the 50% line separating "more '
                         'likely yes" from "more likely no"',
                'why': '45% after 20% and 45% after 70% are opposite stories, and one number '
                       'cannot tell them apart'},
    'pmbook': {'cmds': ['polymarket orderbook 654412'], 'btns': ['markets list → 📖 N'],
               'title': '📖 Polymarket order book',
               'price': 'price not named in the official list',
               'gives': 'order levels by side and a depth line',
               'why': '"45%" with an empty book and "45%" with a dense one are different '
                      'things: the price says what people believe, the book says how much it '
                      'costs to test that with money'},
    'pmrep': {'cmds': ['market reputation 654412', 'who holds market 654412'],
              'btns': ['markets list → 🎭 N'],
              'title': '🎭 Who holds the market and how they guessed before',
              'price': '6 requests (holders + lifetime history of each of the five)',
              'gives': 'how much money sits with wallets below the win-rate threshold, a '
                       'breakdown by side, and holders with win rate, PnL and market count',
              'why': '"78% Yes" — a consensus of WHOM? One number looks the same when the money '
                     'was staked by wallets with a 70% win rate and by wallets with a 35% one; '
                     'the first is a signal, the second an invitation to stand against'},
    'pmwallet': {'cmds': ['polymarket profile 0x…'], 'btns': ['🎲 Polymarket → 🎰 Trader profile'],
                 'title': '🎰 Polymarket trader profile',
                 'price': '2 requests',
                 'gives': 'lifetime PnL, win rate, wallet age and top markets by PnL',
                 'why': "before copying someone's bet, it helps to know how the previous ones "
                        'ended'},
    'pmleaders': {'cmds': ['market leaders 654412'], 'btns': ['🎲 Polymarket → 🏆 Market leaders'],
                  'title': '🏆 Top traders of a specific market',
                  'price': 'price not named in the official list',
                  'gives': 'who made and lost the most on this market, with the side indicated',
                  'why': 'the winners and losers of a single market are the fastest way to see '
                         'who trades it'},
    'agent': {'cmds': [], 'btns': ['exchange card → 🔍 Nansen', 'a question in DM or chat'],
              'title': '🔍 Free-form question to the Nansen agent',
              'price': '200 credits (fast) or 750 (expert) — the MOST expensive path',
              'gives': "the agent's answer in words, with a source attribution",
              'why': 'the only door for questions that have no structural endpoint'},
    'dca': {'cmds': ['dca'], 'btns': ['🧠 Nansen → 🧠 Smart money → 🧊 Buying on a schedule'],
            'title': '🧊 Who buys on a schedule (smart money DCA)',
            'price': 'price not named in the official list · 1 request',
            'gives': 'active DCA programs: who, from which token into which, the size of the '
                     'program and the share already spent',
            'why': 'the only signal here about FUTURE buying: a single $2M trade and a $2M DCA '
                   'program are different statements of intent'},
    'chains': {'cmds': ['chain rank'], 'btns': ['🧠 Nansen → 🌐 Chains and tally → 🌐 Chain ranking'],
               'title': '🌐 Chain ranking: TVL, DEX volume, active addresses',
               'price': 'price not named in the official list · 1 request',
               'gives': 'chains by TVL with their daily change, DEX volume and active addresses',
               'why': '"where to look today" is a question about chains before it is a question '
                      'about tokens'},
    'pmpos': {'cmds': ['market positions 654412'],
              'btns': ['🎲 Trending markets → the «🧾 N» button under the list',
                       '🧠 Nansen → 🎲 Polymarket → 🧾 Who is in the market and their PnL'],
              'title': '🧾 Who is in a Polymarket market, and their PnL',
              'price': 'price not named in the official list · 1 request',
              'gives': 'every holder of the market with their PnL in that market: entry, current '
                       'price, realized and open',
              'why': 'reputation says how a holder did over a lifetime; this says how the same '
                     'holder is doing right here, and together they separate skill from luck'},
    'posintel': {'cmds': ['positioning 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
                          'who is positioned <address>'],
                 'btns': ['🔍 Nansen on a token → the «⚖️ Who is positioned» button',
                          '🧠 Nansen → ⚔️ Other people\u2019s leverage → ⚖️ Who is positioned'],
                 'title': '⚖️ Who is positioned on a token: whales, smart traders, public figures',
                 'price': 'price not named in the official list · 1 request',
                 'gives': 'leverage split by holder segment: whales, smart traders and public '
                          'figures separately, longs against shorts and the net skew',
                 'why': 'the neighbouring screen answers row by row (who stands where, and where '
                        'their liquidation is); this one answers WHO AGAINST WHOM - whales long '
                        'twelve million while smart traders are short nine is a statement a list '
                        'of positions cannot make'},
    'jupdca': {'cmds': ['jup dca <mint>'],
               'btns': ['🧠 Nansen → 🧠 Smart money → 🧊 Jupiter DCA by token'],
               'title': '🧊 Jupiter DCA by token (Solana)',
               'price': 'price not named in the official list · 1 request',
               'gives': 'DCA programs for a token: who, from which token into which, the deposit '
                        'and the share already spent',
               'why': 'on Solana scheduled buying runs through Jupiter, and it is the same '
                      'question about future purchases on a different venue'},
    'defi': {'cmds': ['defi 0x…'], 'btns': ['🧠 Nansen → 🔎 Wallet and token → 💠 DeFi part'],
             'title': '💠 The DeFi part of a wallet: assets MINUS debts',
             'price': 'price not named in the official list · 1 request',
             'gives': 'the net figure (assets minus debts), unclaimed rewards and the protocols '
                      'by size',
             'why': 'a wallet holding $2M with no debt and one holding $2M against $1.7M of debt '
                    'look identical in a token list, and they are not the same wallet'},
    'sharpmarkets': {'cmds': ['sharp money'],
                     'btns': ['🧠 Nansen → 🎲 Polymarket → 🎯 Where money is sharp'],
                     'title': '🎯 Where the money on Polymarket is sharp (market comparison)',
                     'price': 'price not named in the official list · 1 + N + N×H requests '
                              '(13 by default)',
                     'gives': 'four heated markets side by side: how much money sits with '
                              'wallets whose win rate is at or above 60% against the money of '
                              'those below 40%, plus the biggest sharp holder',
                     'why': 'a single-market breakdown does not answer the question of choice: '
                            'out of ten heated markets you want the one where the other side '
                            'is not random people, and that only shows up side by side'},
    'perprisk': {'cmds': ['risk board'],
                 'btns': ['🧠 Nansen → ⚔️ Leverage → ⚔️ Perp risk board',
                          'liquidation map → ⚔️ Compare all four'],
                 'title': '⚔️ Risk board: whose leverage is closest to the edge',
                 'price': 'price not named in the official list · one request per token (4)',
                 'gives': 'BTC/ETH/SOL/HYPE ordered by how CLOSE the price is to the densest '
                          'liquidation cluster: distance in per cent, the side of that cluster, '
                          'longs against shorts, and how much of it sits on wallets Nansen has '
                          'a name for',
                 'why': 'a single map does not answer "and how about the others": the market '
                        'runs through the nearest level first, and only a comparison shows '
                        'which one that is'},
    'tally': {'cmds': ['nansen stats'], 'btns': ['🧠 Nansen → 🌐 Chains and tally → 🧮 My contest tally'],
              'title': '🧮 My contest tally',
              'price': 'free, reads its own log',
              'gives': 'how many calls and credits per person and their rank; a leaderboard '
                       'WITHOUT names and IDs',
              'why': 'a multi-user bot: contribution is counted while privacy is not spent'},
    'digest': {'cmds': [], 'btns': ['on a schedule, no human'],
               'title': '📰 Morning digest and tweet jobs',
               'price': 'counted separately from people: a job has no person and does not go '
                        'into the tally',
               'gives': 'the smart money section in the morning digest',
               'why': 'background calls must be separated from human ones, otherwise the spend '
                      'cannot be explained'},
}


def _f(sc, field, lang):
    """Редакторское поле сценария на нужном языке. RU — из самого SCENARIOS, EN — из `_EN`.

    `hook` не языковой (в обоих документах английский), поэтому берётся напрямую. Отсутствие
    английского перевода — не «падение в русский по-тихому», а KeyError: судейский документ без
    перевода одного экрана хуже, чем красный тест на сборке.
    """
    if lang not in ('en', 'ru'):
        raise ValueError('неизвестный язык поля: %r (ожидается en/ru)' % (lang,))
    if lang == 'en' and field != 'hook':
        return _EN[sc['id']][field]
    return sc[field]


#: ЭНДПОИНТЫ, ПУТЬ К КОТОРЫМ СОБИРАЕТСЯ В РАНТАЙМЕ, - и потому их нельзя найти литералом.
#: Проверяем ПО КУСКАМ: оба куска должны быть в исходнике. Это слабее прямого литерала, и
#: поэтому список короткий и назван здесь явно - чтобы «не нашлось» не превратилось в
#: «ну, наверное, где-то есть».
#:   `ask_agent` строит URL так: f"{_BASE}/agent/{'expert' if expert else 'fast'}"
_DYNAMIC_EPS = {
    'agent/fast': ('/agent/', "'fast'"),
    'agent/expert': ('/agent/', "'expert'"),
    # Единственный GET строит URL как `_TRADE + '/quote'`, мимо четырёх POST-горловин.
    'trade/quote': ('httpx.get', '_TRADE', '/quote'),
}


def _endpoints_in(src):
    """Эндпоинты, которые клиент РЕАЛЬНО зовёт. -> set.

    ПО AST, А НЕ ПО РЕГУЛЯРКЕ `_post("…")`, и это исправление ошибки: первая редакция искала
    только литерал прямо в вызове и «не нашла» четыре живых эндпоинта. Два из них клиент зовёт
    через переменную (`path = "profiler/address/labels"`), два - через f-строку у агента.
    Проверка, которая краснеет на верном коде, учит игнорировать проверки.
    Но и «искать любую строку в файле» нельзя: тогда путь из таблицы цен или из комментария о
    ПОХОРОНЕННОМ эндпоинте считался бы подключённым. Поэтому берём строки, которые стоят
    АРГУМЕНТОМ вызова либо присваиваются переменной, - то есть участвуют в исполнении.
    """
    import ast as _ast
    import re as _re
    # ФОРМА ПУТИ: либо есть слэш (`smart-money/netflow`), либо путь ОДНОСЕГМЕНТНЫЙ, но с
    # дефисом (`perp-leaderboard`, `perp-screener`, `token-screener`) - такие у Nansen тоже
    # есть, и первая редакция их не видела, требуя слэш. Дефис здесь - не украшение, а способ
    # отличить эндпоинт от обычной строки вроде 'ethereum' или 'main'.
    shape = _re.compile(r'^[a-z0-9][a-z0-9\-]*(?:/[a-z0-9][a-z0-9\-]*)+$'
                        r'|^[a-z0-9]+(?:-[a-z0-9]+)+$')
    out = set()
    tree = _ast.parse(src)
    # СОБИРАЕМ ТОЛЬКО ИЗ ТЕХ МЕСТ, ГДЕ ПУТЬ ПРАВДА УХОДИТ В СЕТЬ, и это ужесточение после
    # замера: первая редакция брала строку из ЛЮБОГО вызова, и в список эндпоинтов попали
    # теги логирования (`_shape('sm-dex-trades', row)`), имя кодировки ('utf-8') и куски
    # путей. Тридцать три «эндпоинта» из шестидесяти одного оказались не эндпоинтами -
    # то есть проверка каталога приняла бы обещание про `wallet-perp`, которого не существует.
    # Детектор, который находит лишнее, не строже - он просто врёт в другую сторону.
    _THROATS = ('_post', '_post_fix', '_post_beta', '_http_post')
    for n in _ast.walk(tree):
        vals = []
        if isinstance(n, _ast.Call):
            _f = n.func
            _nm = (_f.attr if isinstance(_f, _ast.Attribute)
                   else (_f.id if isinstance(_f, _ast.Name) else ''))
            if _nm == '_http_post' and len(n.args) > 1 and isinstance(n.args[0], _ast.Name) \
                    and n.args[0].id == '_TRADE' and isinstance(n.args[1], _ast.Constant):
                # `_http_post(_TRADE, 'prepare', ...)` — реальный маршрут `trade/prepare`,
                # а не однословный «prepare» и не голый «bridge-status».
                out.add('trade/' + str(n.args[1].value).strip('/'))
            elif _nm in _THROATS:
                vals = [a for a in n.args if isinstance(a, _ast.Constant)]
        elif isinstance(n, _ast.Assign):
            # присваивание пути переменной: `path = "profiler/address/labels"`. Имя переменной
            # проверяем - иначе сюда попадёт любая строка-константа модуля.
            _names = [t.id for t in n.targets if isinstance(t, _ast.Name)]
            if any(('path' in x or 'url' in x) for x in (s.lower() for s in _names)):
                if isinstance(n.value, _ast.Constant):
                    vals = [n.value]
                elif isinstance(n.value, _ast.IfExp):
                    vals = [v for v in (n.value.body, n.value.orelse)
                            if isinstance(v, _ast.Constant)]
        for v in vals:
            if isinstance(v.value, str) and shape.match(v.value):
                out.add(v.value)
    for ep, parts in _DYNAMIC_EPS.items():
        if all(p in src for p in parts):
            out.add(ep)
    return out


def _verify():
    """Проверить КАЖДОЕ техническое утверждение каталога. -> список расхождений."""
    bad = []
    import nansen_log as T
    src = open(os.path.join(ROOT, 'nansen_api.py'), encoding='utf-8').read()
    eps = _endpoints_in(src)
    try:
        import oc_dm
    except Exception as e:                       # noqa: BLE001
        bad.append('роутер не импортируется (%s) - команды не проверить' % str(e)[:80])
        oc_dm = None
    try:
        import oc_menu
        phrases = oc_menu.OC_PHRASES
        menu_src = open(os.path.join(ROOT, 'oc_menu.py'), encoding='utf-8').read()
    except Exception as e:                       # noqa: BLE001
        bad.append('меню не импортируется (%s)' % str(e)[:80])
        phrases = {}
        menu_src = ''
    seen = set()
    for sc in SCENARIOS:
        _id = sc['id']
        if _id in seen:
            bad.append('%s: id повторяется' % _id)
        seen.add(_id)
        # КОМАНДЫ ОБОИХ ЯЗЫКОВ ПРОВЕРЯЕМ РОУТЕРОМ, А НЕ ГЛАЗАМИ. В английском каталоге стоят
        # английские команды, и judge, набравший `smart flows`/`liq map BTC`, обязан получить
        # экран - иначе английский документ обещает то, чего роутер не понимает. Плейсхолдер
        # `0x…` роутер не поймёт, поэтому подставляем настоящий публичный адрес.
        _ru_cmds = list(sc['cmds'])
        _en_cmds = list((_EN.get(_id) or {}).get('cmds') or [])
        for c in _ru_cmds + _en_cmds:
            probe = c.replace('0x…', '0x1f9090aaE28b8a3dCeaDf281B0F12828e676c326')
            if oc_dm is not None and not oc_dm.is_onchain_command(probe):
                bad.append('%s: команду %r роутер НЕ узнаёт' % (_id, c))
        for ep in sc['eps']:
            if ep not in eps:
                bad.append('%s: эндпоинта %r нет в клиенте (похоронен или переименован?)'
                           % (_id, ep))
        if sc['scene'] and sc['scene'] not in T.SCENES:
            bad.append('%s: сцены %r нет в закрытом реестре' % (_id, sc['scene']))
        if sc['menu'] and sc['menu'] not in phrases:
            bad.append('%s: ключа меню %r нет в реестре подписей' % (_id, sc['menu']))
        if sc['menu'] and menu_src:
            # НАЛИЧИЕ ПОДПИСИ ≠ НАЛИЧИЕ КНОПКИ. Раньше verifier проверял только словарь
            # OC_PHRASES: можно было удалить кнопку из клавиатуры, оставить перевод, и
            # каталог продолжал обещать «Кнопкой: …». Ищем ключ ещё раз вне его объявления —
            # в keyboard/_RUN/_HINT; один occurrence означает мёртвую подпись.
            occurrences = menu_src.count('"%s"' % sc['menu'])
            if occurrences < 2:
                bad.append('%s: подпись меню %r есть, но кнопка/action не найдены'
                           % (_id, sc['menu']))
        if len(sc['hook']) > 260:
            bad.append('%s: зацепка для твита длиннее 260 символов (%d)'
                       % (_id, len(sc['hook'])))
        # hook общий для обоих языков и стоит под меткой «For a tweet (EN)»/«Для твита (EN)»:
        # он ОБЯЗАН быть английским. Кириллица здесь утекла бы в английский каталог молча.
        import re as _re
        if _re.search(r'[\u0400-\u04FF]', sc['hook'] or ''):
            bad.append('%s: hook содержит кириллицу — он должен быть английским' % _id)
        for f in ('title', 'gives', 'why', 'hook', 'price'):
            if not (sc.get(f) or '').strip():
                bad.append('%s: пустое поле %r' % (_id, f))
        # АНГЛИЙСКИЙ ПЕРЕВОД ОБЯЗАТЕЛЕН И ПОЛНЫЙ. Английский каталог — основной judge-facing
        # документ; сценарий без перевода одного поля уехал бы в публичный репозиторий с дырой.
        _en = _EN.get(_id)
        if _en is None:
            bad.append('%s: нет английского перевода в _EN' % _id)
        else:
            for f in ('title', 'gives', 'why', 'price'):
                if not (_en.get(f) or '').strip():
                    bad.append('%s: пустое английское поле %r в _EN' % (_id, f))
            # cmds/btns ОБЯЗАНЫ БЫТЬ (даже пустым списком) и совпадать по числу с русскими -
            # иначе английский и русский каталоги разойдутся по строкам, а _f('cmds','en')
            # упал бы KeyError на сценарии без английских команд.
            if 'cmds' not in _en or 'btns' not in _en:
                bad.append('%s: в _EN нет cmds/btns' % _id)
            else:
                # Число АЛИАСОВ команды может отличаться (у русского «карта ликвидаций» два
                # варианта, у английского один), но НАЛИЧИЕ команды обязано совпасть: если у
                # сценария есть русская команда, должна быть и английская, иначе английский
                # каталог оставит экран без текстового входа.
                if bool(_en['cmds']) != bool(sc['cmds']):
                    bad.append('%s: команда есть на одном языке и отсутствует на другом'
                               % _id)
                # Кнопочные пути — описательные, их число обязано совпадать (та же форма
                # документа на обоих языках).
                if len(_en['btns']) != len(sc['btns']):
                    bad.append('%s: число английских кнопок (%d) != русских (%d)'
                               % (_id, len(_en['btns']), len(sc['btns'])))
    # ПОМЕТКА «ЕСТЬ ЭКРАН В МИНИ-АППЕ» ПРОВЕРЯЕТСЯ ПО КОДУ, А НЕ НА СЛОВО. Сцена, объявленная
    # в каталоге как экран мини-аппа, обязана быть в закрытом списке `nansen_scene.SCENES` -
    # иначе каталог обещает экран, которого шлюз не обслуживает. И наоборот: сцена, которую
    # шлюз обслуживает, обязана быть помечена, иначе документ скрывает половину поверхностей.
    try:
        import nansen_scene as _NS
        _app_ids = {s['id'] for s in SCENARIOS if s.get('app')}
        _by_scene = {s['scene']: s['id'] for s in SCENARIOS if s.get('scene')}
        for _scene in _NS.SCENES:
            _sid = _by_scene.get(_scene)
            if _sid is None:
                bad.append('сцену %r обслуживает мини-апп, но её нет в каталоге' % _scene)
            elif _sid not in _app_ids:
                bad.append('сцена %r есть в мини-аппе, а в каталоге не помечена app=True'
                           % _scene)
        for _sid in _app_ids:
            _sc2 = next(s for s in SCENARIOS if s['id'] == _sid)
            if _sc2.get('scene') not in _NS.SCENES:
                bad.append('%s помечен app=True, но шлюз мини-аппа его не обслуживает' % _sid)
    except ImportError as e:                       # noqa: BLE001
        bad.append('nansen_scene не импортируется (%s) - пометки мини-аппа не проверить'
                   % str(e)[:60])
    # ═══ «ГДЕ ЭТО РАБОТАЕТ» ПРОВЕРЯЕТСЯ ПО КОДУ, А НЕ НА СЛОВО ═══
    # Утверждение «это можно позвать в группе» - самое опасное в каталоге: человек читает его,
    # идёт в группу и либо получает ответ, либо не получает ничего и решает, что бот сломан.
    # Поэтому у групповой кнопки обязаны найтись ТРИ вещи: сама кнопка в коде карточки,
    # обработчик её действия и регистрация префикса в боте. Нет любой из трёх - каталог не
    # пишется.
    try:
        _cards = ''
        for _f2 in ('onchain/hub_scanner.py', 'onchain/oc_major.py', 'onchain/oc_dm.py'):
            _cards += open(os.path.join(ROOT, _f2), encoding='utf-8').read()
        _cbs = open(os.path.join(ROOT, 'onchain', 'oc_callbacks.py'), encoding='utf-8').read()
        _bot = open(os.path.join(ROOT, 'bot.py'), encoding='utf-8').read()
        _pub = open(os.path.join(ROOT, 'pub_tools.py'), encoding='utf-8').read()
    except OSError as e:                           # noqa: BLE001
        bad.append('файлы кнопок/роутера не читаются (%s) - поверхности не проверить'
                   % str(e)[:60])
        _cards = _cbs = _bot = _pub = ''
    for sc in SCENARIOS:
        _id, _w = sc['id'], _where(sc)
        for _k in _w:
            if _k not in WHERE_KINDS:
                bad.append('%s: поверхность %r вне закрытого списка' % (_id, _k))
        if 'group_btn' in _w:
            _g = sc.get('gcb') or ''
            if not _g:
                bad.append('%s: обещана групповая кнопка, но её callback не назван (gcb)' % _id)
            elif _cards:
                if _g not in _cards:
                    bad.append('%s: кнопки %r нет ни в одной клавиатуре карточки' % (_id, _g))
                _act = _g.split(':', 1)[1] if ':' in _g else _g
                if ('"%s"' % _act) not in _cbs and ("'%s'" % _act) not in _cbs:
                    bad.append('%s: действие %r не разбирается обработчиком' % (_id, _act))
                _pref = _g.split(':', 1)[0]
                if ("^%s:" % _pref) not in _bot:
                    bad.append('%s: префикс %r не раздаётся обработчику в bot.py'
                               % (_id, _pref))
        if 'group_agent' in _w and _pub:
            # АГЕНТСКАЯ ДВЕРЬ В ГРУППЕ - ЭТО РОВНО ОДИН ИНСТРУМЕНТ. Не станет его в наборе -
            # каталог не имеет права продолжать обещать вопрос словами в группе.
            if 'def nansen_lookup' not in _pub or 'nansen_lookup' not in _bot:
                bad.append('%s: обещан вопрос агенту в группе, но инструмента nansen_lookup '
                           'нет в наборе' % _id)
    # В _EN не должно быть лишних ключей: удалили сценарий — перевод не может остаться сиротой.
    _orphans = sorted(set(_EN) - {s['id'] for s in SCENARIOS})
    if _orphans:
        bad.append('в _EN есть перевод для несуществующих сценариев: %s' % ', '.join(_orphans))
    return bad


def _where(sc):
    """Поверхности сценария. -> tuple.

    ПО УМОЛЧАНИЮ ТОЛЬКО ЛИЧКА, и это не лень, а факт кода: команды словами разбирает
    `oc_dm.is_onchain_command`, которого групповой обработчик (`group_chat.handle_group_message`)
    не зовёт ВООБЩЕ, а меню `ocm:*` в группу никто не отправляет. Поэтому «группа» - это
    исключение, которое надо назвать и доказать, а не наоборот.
    """
    return tuple(sc.get('where') or ('dm',))


def _where_txt(sc, lang='en'):
    """Человеческая строка «где это работает». -> str."""
    _en = (lang == 'en')
    w = _where(sc)
    bits = []
    if 'dm' in w:
        bits.append('in DM' if _en else 'в личке')
    if 'group_btn' in w:
        _g = sc.get('gcb', '?')
        bits.append(('in a group — by the button on a card the bot itself posted (`%s`)' % _g)
                    if _en else
                    ('в группе — кнопкой на карточке, которую бот прислал сам (`%s`)' % _g))
    if 'group_agent' in w:
        bits.append('in a group — by asking the agent in words (address the bot: a mention by '
                    'username, the nickname "гроб"/"undertaker", or a reply)' if _en else
                    'в группе — словами у агента (нужно обратиться: упоминание по имени '
                    'бота, кличка «гроб»/«гробовщик» или реплай)')
    if 'group_btn' not in w and 'group_agent' not in w:
        bits.append('**not in a group**: the word command is parsed only by the DM router'
                    if _en else
                    '**не в группе**: команду словами разбирает только личный роутер')
    return ' · '.join(bits)


def _doors_md(lang='en'):
    """Раздел «три двери»: где вообще можно спросить Nansen. -> [str] строк документа.

    ЭТОТ РАЗДЕЛ - ОТВЕТ НА ЖИВОЙ ВОПРОС ВЛАДЕЛЬЦА и на дефект документа: каталог перечислял
    команды, не говоря, что словами они работают ТОЛЬКО в личке. В группе у Nansen две своих
    двери, и у каждой свои условия - молчать о них значит либо терять половину функциональности
    в глазах читателя, либо обещать ему то, чего в группе нет.
    """
    _en = (lang == 'en')
    if _en:
        return ['## Three doors: where Nansen can be asked at all', '',
                '**💬 In DM** — every scenario. Word commands are parsed by the private router '
                '(`oc_dm.is_onchain_command`), and the inline menus (`ocm:*`) and the mini-app '
                'button live here too. No mode needs to be switched on.', '',
                '**👥🔘 In a group, by a button** — the bot posts a card by itself (a bare '
                'contract address, `график BTC`), and the Nansen buttons on that card answer '
                'INTO THE GROUP. This is not the agent: these are the same structured screens '
                'as in DM, with the same numbers.', '',
                '**👥🤖 In a group, by asking the agent in words** — the agent tool '
                '`nansen_lookup` (the Nansen AI agent). It needs the bot to be addressed: a '
                'mention by username, the nickname ("гроб"/"гробовщик"/"undertaker") or a reply to the '
                "bot's message. The group also has to be approved, and there is a per-person "
                'daily cap on agent questions (the agent is the expensive path).', '',
                '**Word commands do NOT work in a group.** The group handler never calls the '
                'private router at all, so `smart flows` typed in a group reaches the agent at '
                'best — a different, more expensive path with a different answer. This is a '
                'property of the code, not an oversight of this document.', '',
                '**The mini-app is DM-only.** Telegram rejects a message carrying a `web_app` '
                'button if it goes to a group, and the bot posts no Nansen mini-app link there '
                'either.', '']
    return ['## Три двери: где вообще можно спросить Nansen', '',
            '**💬 В личке** — все сценарии. Команды словами разбирает личный роутер '
            '(`oc_dm.is_onchain_command`), здесь же живут меню (`ocm:*`) и кнопка мини-аппа. '
            'Режим включать не нужно.', '',
            '**👥🔘 В группе, кнопкой** — бот сам присылает карточку (голый контракт, '
            '`график BTC`), и Nansen-кнопки на этой карточке отвечают В ГРУППУ. Это не агент: '
            'это те же структурные экраны, что в личке, с теми же числами.', '',
            '**👥🤖 В группе, словами у агента** — инструмент `nansen_lookup` (ИИ-агент '
            'Nansen). Нужно обратиться к боту: упоминание по имени бота, кличка («гроб»/«гробовщик»/'
            '«undertaker») или реплай на его сообщение. Плюс группа должна быть одобрена, а у '
            'человека есть суточный лимит агентских вопросов (агент - самый дорогой путь).', '',
            '**Команды словами в группе НЕ работают.** Групповой обработчик личный роутер не '
            'зовёт вовсе, поэтому «смарт потоки», набранные в группе, в лучшем случае дойдут до '
            'агента - это другой, более дорогой путь и другой ответ. Это свойство кода, а не '
            'недосмотр документа.', '',
            '**Мини-апп только в личке.** Telegram отвергает сообщение с кнопкой `web_app`, '
            'если оно уходит в группу, и ссылку на Nansen-мини-апп бот в группу тоже не '
            'присылает.', '']


def _md(lang='en'):
    """Собрать документ на языке lang ('en' — основной, 'ru' — аналог). -> str.

    ЗАЧЕМ ДВА ЯЗЫКА. Каталог — судейский документ англоязычного конкурса, поэтому основной файл
    `CATALOG.md` английский. Русский `CATALOG_ru.md` остаётся для владельца, по нему он и пишет.
    Оба СОБИРАЮТСЯ одним инструментом из одних SCENARIOS: разъехаться молча им нечем.
    """
    if lang not in ('en', 'ru'):
        # Тихо отдать русский на опечатке `'EN'` значило бы собрать судейский документ не на
        # том языке и не заметить. Лучше громко упасть на сборке.
        raise ValueError('неизвестный язык каталога: %r (ожидается en/ru)' % (lang,))
    import nansen_log as T
    _en = (lang == 'en')
    if _en:
        L = ['# Nansen data scenario catalog', '',
             'Every bot screen that talks to Nansen: what to say, what comes back, what it '
             'costs and why it matters.', '',
             '**This document is GENERATED BY A TOOL** (`tools/nansen_catalog.py`), not written '
             "by hand. The generator verifies four classes of claim: the command is recognized "
             "by the shared router, the endpoint actually exists in the client's network "
             'throat, the scene is in the closed telemetry registry, and the menu label has a '
             'button/action. This does not replace an E2E test linking a specific command to a '
             'specific endpoint — hero paths pass live callback tests separately. If any of '
             'these verifiable parts diverges, the document is not written. Public promises are '
             'made from this catalog, and promising a feature that does not exist is worse than '
             'promising nothing.', '',
             '**About price.** Where the official Nansen list names an endpoint price — it is '
             'in credits. Where it does not — the price is given **by the number of requests**. '
             'This is not evasion: a made-up credit number in a document that tweets are '
             'written from would be a lie in the most verifiable place.', '',
             '**Russian version:** [`CATALOG_ru.md`](CATALOG_ru.md).', '',
             '| Scenarios | Endpoints used | Telemetry scenes |', '|---|---|---|']
    else:
        L = ['# Каталог сценариев на данных Nansen', '',
             'Все экраны бота, которые ходят в Nansen: что сказать, что придёт, чего это стоит '
             'и зачем это нужно.', '',
             '**Документ СОБРАН ИНСТРУМЕНТОМ** (`tools/nansen_catalog.py`), а не написан '
             'руками. Сборщик проверяет четыре класса утверждений: команда распознаётся общим '
             'роутером, эндпоинт реально присутствует в сетевой горловине клиента, сцена есть '
             'в закрытом реестре телеметрии, а подпись меню имеет кнопку/action. Это не '
             'заменяет E2E-тест связи конкретной команды с конкретным endpoint — hero-paths '
             'отдельно проходят живыми callback-тестами. Расходится хоть одна из этих '
             'проверяемых частей — документ не пишется. По каталогу создаются публичные '
             'обещания, а обещать несуществующую фичу хуже, чем не обещать ничего.', '',
             '**Про цену.** Где официальный список Nansen называет цену эндпоинта — она в '
             'кредитах. Где не называет — цена указана **числом запросов**. Это не уклонение: '
             'придуманное число кредитов в документе, по которому пишут твиты, было бы ложью в '
             'самом проверяемом месте.', '',
             '**Английский оригинал — основной файл:** [`CATALOG.md`](CATALOG.md).', '',
             '| Сценариев | Эндпоинтов задействовано | Сцен телеметрии |', '|---|---|---|']
    _eps = sorted({e for sc in SCENARIOS for e in sc['eps']})
    _scenes = sorted({sc['scene'] for sc in SCENARIOS if sc['scene']})
    user_api = [s for s in SCENARIOS if s['eps'] and not str(s.get('scene') or '').endswith('_cron')]
    background = [s for s in SCENARIOS if str(s.get('scene') or '').endswith('_cron')]
    local = [s for s in SCENARIOS if not s['eps']]
    if _en:
        L += ['| %d: %d user-facing on Nansen + %d background + %d local | %d | %d of %d in registry |'
              % (len(SCENARIOS), len(user_api), len(background), len(local), len(_eps),
                 len(_scenes), len(T.SCENES)), '']
        L += _doors_md('en')
        L += ['## Short table', '',
              '| Scenario | Say to the bot | By button | Where | Price |',
              '|---|---|---|---|---|']
    else:
        L += ['| %d: %d пользовательских на Nansen + %d фоновый + %d локальный | %d | %d из %d в реестре |'
              % (len(SCENARIOS), len(user_api), len(background), len(local), len(_eps),
                 len(_scenes), len(T.SCENES)), '']
        L += _doors_md('ru')
        L += ['## Короткая таблица', '',
              '| Сценарий | Сказать боту | Кнопкой | Где | Цена |', '|---|---|---|---|---|']
    for sc in SCENARIOS:
        _c = '<br>'.join('`%s`' % c for c in _f(sc, 'cmds', lang)) or '—'
        _b = '<br>'.join(_f(sc, 'btns', lang)) or '—'
        _w = _where(sc)
        # В КОРОТКОЙ ТАБЛИЦЕ - ЗНАЧКАМИ, чтобы колонка не разорвала строку; расшифровка стоит
        # выше, в разделе про двери, и полная фраза - у каждого сценария ниже.
        _wt = ' '.join([x for x in (('💬' if 'dm' in _w else ''),
                                    ('👥🔘' if 'group_btn' in _w else ''),
                                    ('👥🤖' if 'group_agent' in _w else '')) if x])
        L.append('| [%s](#%s) | %s | %s | %s | %s |'
                 % (_f(sc, 'title', lang), sc['id'], _c, _b, _wt, _f(sc, 'price', lang)))
    L += ['', '---', '']
    for sc in SCENARIOS:
        L += ['<a name="%s"></a>' % sc['id'], '', '## %s' % _f(sc, 'title', lang), '']
        _cmds = _f(sc, 'cmds', lang)
        _btns = _f(sc, 'btns', lang)
        if _cmds:
            _say = '**Say to the bot:** ' if _en else '**Сказать боту:** '
            L.append(_say + ' · '.join('`%s`' % c for c in _cmds))
        if _btns:
            _by = '**By button:** ' if _en else '**Кнопкой:** '
            L.append(_by + ' · '.join(_btns))
        # ГДЕ ЭТО РАБОТАЕТ - СТРОКОЙ У КАЖДОГО СЦЕНАРИЯ. Без неё каталог обещал «скажи боту»
        # не уточняя, в каком чате: набравший команду в группе не получал НИЧЕГО.
        L.append(('**Where:** ' if _en else '**Где:** ') + _where_txt(sc, lang))
        if sc.get('app'):
            # МИНИ-АПП - НОВАЯ ПОВЕРХНОСТЬ СТАРОЙ СЦЕНЫ, и каталог обязан это показать, иначе
            # читатель решит, что экранов на телефоне нет вовсе. Сцена телеметрии та же (ниже),
            # поэтому расход по ней складывается из обеих поверхностей.
            L.append('**In the mini-app:** a screen of its own — it renders this same '
                     'dictionary, so the chart cannot drift from the sentence.' if _en else
                     '**В мини-аппе:** свой экран — рисует ЭТОТ ЖЕ словарь, поэтому график не '
                     'может разойтись с фразой бота.')
        if _en:
            L += ['', '**What you get:** %s' % _f(sc, 'gives', lang), '',
                  '**Price:** %s' % _f(sc, 'price', lang), '',
                  '**Why:** %s' % _f(sc, 'why', lang), '']
            L += ['**Endpoints:** ' + (', '.join('`%s`' % e for e in sc['eps'])
                                       or 'none, reads its own log'), '']
        else:
            L += ['', '**Что придёт:** %s' % _f(sc, 'gives', lang), '',
                  '**Цена:** %s' % _f(sc, 'price', lang), '',
                  '**Зачем:** %s' % _f(sc, 'why', lang), '']
            L += ['**Эндпоинты:** ' + (', '.join('`%s`' % e for e in sc['eps'])
                                       or 'нет, читает свой лог'), '']
        if sc['scene']:
            if _en:
                L.append("**Telemetry scene:** `%s` — this screen's spend is counted under it." %
                         sc['scene'])
            else:
                L.append('**Сцена телеметрии:** `%s` — по ней считается расход этого экрана.' %
                         sc['scene'])
            L.append('')
        _tw = '**For a tweet (EN):**' if _en else '**Для твита (EN):**'
        L += [_tw, '', '> %s' % sc['hook'], '', '---', '']
    # ═══ РАЗДЕЛ, БЕЗ КОТОРОГО КАТАЛОГ БЫЛ БЫ ПОЛОВИНОЙ ПРАВДЫ ═══
    # Запрос был «все сценарии, какие есть». Сценарии выше - те, до которых человек может
    # дойти. Но в клиенте есть эндпоинты БЕЗ двери, и молчать о них нельзя: читатель каталога
    # решит, что перечисленное - это всё, что умеет ключ. Список СЧИТАЕТСЯ (клиент минус
    # каталог), поэтому не может отстать: подключат эндпоинт без двери - он появится здесь сам.
    _src = open(os.path.join(ROOT, 'nansen_api.py'), encoding='utf-8').read()
    _all = _endpoints_in(_src)
    _no_door = sorted(_all - set(_eps))
    if _en:
        L += ['## Client routes with no ordinary user scenario', '',
              'The catalog above has %d workflows that use %d unique API routes. The client '
              'contains **%d** routes in total; another %d have no ordinary user door (some '
              'service/owner-only, some client groundwork).'
              % (len(SCENARIOS), len(_eps), len(_all), len(_no_door)), '',
              'This is not a claim that all work end-to-end: having a client is not the same as '
              'a ready scenario. The list is broken out precisely so as not to pass API '
              'coverage off as user-available functionality.', '',
              'The list is COMPUTED at build time (client minus catalog): a new route with no '
              'workflow appears here automatically.', '']
    else:
        L += ['## Маршруты клиента без обычного пользовательского сценария', '',
              'В каталоге выше — %d workflow, которые задействуют %d уникальных API-маршрутов. '
              'Всего клиент содержит **%d** маршрута; ещё %d не имеют обычной пользовательской '
              'двери (часть служебная/owner-only, часть — клиентский задел).'
              % (len(SCENARIOS), len(_eps), len(_all), len(_no_door)), '',
              'Это не заявка «все работают end-to-end»: наличие клиента не равно готовому '
              'сценарию. Список вынесен именно затем, чтобы не выдавать охват API за доступную '
              'пользователю функциональность.', '',
              'Список СЧИТАЕТСЯ при сборке (клиент минус каталог): новый маршрут без workflow '
              'появится здесь автоматически.', '']
    for e in _no_door:
        L.append('* `%s`' % e)
    L += ['', '---', '']
    if _en:
        L += ['## How to rebuild', '',
              '```bash', 'python3 tools/nansen_catalog.py --write   # in the private repository',
              'python3 tools/export_nansen_public.py --out <path>  # and into the public extract',
              '```', '',
              'A no-write check is `--check`, exit code 1 on a mismatch. The law test walks the '
              'same path, so "the catalog fell behind the code" becomes a red test rather than '
              'an unpleasant discovery at the moment a tweet has already been written from it.',
              '']
    else:
        L += ['## Как пересобрать', '',
              '```bash', 'python3 tools/nansen_catalog.py --write   # в приватном репозитории',
              'python3 tools/export_nansen_public.py --out <путь>  # и в публичную выжимку',
              '```', '',
              'Проверка без записи — `--check`, код возврата 1 при расхождении. Этим же ходит '
              'закон-тест, поэтому «каталог отстал от кода» становится красным тестом, а не '
              'неприятным открытием в момент, когда по нему уже написан твит.', '']
    return '\n'.join(L)


#: ДВА ВЫВОДА ОДНОГО ГЕНЕРАТОРА: основной английский и русский аналог. Оба под проверкой
#: `--check`, поэтому «отстал один из языков» — тоже красный тест.
_OUTPUTS = [('en', os.path.join('nansen', 'CATALOG.md')),
            ('ru', os.path.join('nansen', 'CATALOG_ru.md'))]


def main(argv):
    bad = _verify()
    if bad:
        print('КАТАЛОГ НЕ СОБРАН: расхождений %d' % len(bad))
        for b in bad:
            print('  ' + b)
        return 1
    if '--check' in argv:
        drift = []
        for lang, rel in _OUTPUTS:
            p = os.path.join(ROOT, rel)
            if not os.path.exists(p):
                drift.append('%s ещё не собран' % rel)
            elif open(p, encoding='utf-8').read() != _md(lang):
                drift.append('%s ОТСТАЛ от кода' % rel)
        if drift:
            for d in drift:
                print('  ' + d)
            print('Пересобрать: python3 tools/nansen_catalog.py --write')
            return 1
        print('каталог совпадает с кодом: сценариев %d, языков %d'
              % (len(SCENARIOS), len(_OUTPUTS)))
        return 0
    if '--write' in argv:
        for lang, rel in _OUTPUTS:
            p = os.path.join(ROOT, rel)
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write(_md(lang))
            print('записан %s (%s)' % (p, lang))
        print('сценариев %d, проверок пройдено %d'
              % (len(SCENARIOS), sum(len(s['cmds']) + len(s['eps']) for s in SCENARIOS)))
        return 0
    print(_md('en'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
