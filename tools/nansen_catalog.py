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
SCENARIOS = [
    # ── SMART MONEY ───────────────────────────────────────────────────────────
    {'id': 'flows', 'title': '💹 Приток smart money по окнам',
     'cmds': ['смарт потоки'], 'btns': ['🧠 Nansen → 💹 Смарт-потоки → 1ч/24ч/7д/30д'],
     'eps': ['smart-money/netflow'], 'scene': 'smart_flows', 'menu': 'nsn_flows',
     'price': 'цена не названа в официальном списке · считаем отдельной строкой',
     'gives': 'тикеры с нетто-притоком за окно; тап по тикеру открывает карточку токена',
     'why': 'итог за окно отвечает «сколько», и это первый вопрос по любому токену',
     'hook': 'Smart money net inflow by window (1h/24h/7d/30d), straight into a Telegram chat. '
             'Tap a ticker and the full token card opens.'},
    {'id': 'trends', 'title': '🔥 Smart Money в общем экране Трендов',
     'cmds': [], 'btns': ['🔗 Ончейн → Тренды → Smart Money'],
     'eps': ['token-screener'], 'scene': 'trends', 'menu': None,
     'price': '1 кредит',
     'gives': 'токены с положительным netflow, встроенные в общий экран трендов; тап открывает '
              'карточку токена',
     'why': 'Nansen не отдельный режим, а часть ежедневного маршрута: тренд → карточка → '
            'держатели/потоки/сделки',
     'hook': 'Nansen is not a separate dashboard here. Smart-money inflow is embedded into the '
             'daily Trends screen, one tap away from the token card.'},
    {'id': 'holdings', 'title': '💼 Что копит smart money',
     'cmds': ['смарт холдинги'], 'btns': ['🧠 Nansen → 💼 Что копят'],
     'eps': ['smart-money/holdings'], 'scene': 'smart_holdings', 'menu': 'nsn_holdings',
     'price': '3 кредита',
     'gives': 'топ позиций по $ с изменением за сутки',
     'why': 'поток говорит «что берут сейчас», холдинги - «что уже держат»',
     'hook': 'What smart money already holds, not just what they bought today.'},
    {'id': 'trades', 'title': '🧠 Сделки smart money за сутки + доля от капитализации',
     'cmds': ['смарт сделки'], 'btns': ['🧠 Nansen → 🧠 Сделки smart money сейчас'],
     'eps': ['smart-money/dex-trades'], 'scene': 'smart_trades', 'menu': 'nsn_trades',
     'price': '1–5 кредитов',
     'gives': 'кто, во что и на сколько зашёл, плюс капитализация токена и ДОЛЯ сделки от неё',
     'why': '«$48K зашли в токен» - ни о чём, пока не сказано, во что: $48K в токен на $2.1M '
            'это 2.3% всей капитализации и сигнал, а в токен на $50B - шум',
     'hook': 'Smart money trades with the number that matters: $48K into a $2.1M token is '
             '2.3% of its entire market cap. The same $48K into a $50B token is noise.'},
    # ── ПЕРПЫ И ПЛЕЧО ─────────────────────────────────────────────────────────
    {'id': 'perpleaders', 'title': '🏆 Топ перп-трейдеров',
     'cmds': ['топ перпы'], 'btns': ['🧠 Nansen → 🏆 Топ перп-трейдеры'],
     'eps': ['perp-leaderboard'], 'scene': 'perp_leaders', 'menu': 'nsn_perps',
     'price': '5 кредитов',
     'gives': 'прибыльные счета на перпах; тап по трейдеру открывает его счёт',
     'why': 'кто зарабатывает на плече прямо сейчас',
     'hook': 'Top perp traders by PnL, tappable straight into their wallet.'},
    {'id': 'perppos', 'title': '💥 Позиции с плечом и ЦЕНА ЛИКВИДАЦИИ по токену',
     'cmds': ['перп позиции BTC', 'ликвидации BTC'],
     'btns': ['карточка токена (например BTC) → 💥 Ликвид.'],
     'eps': ['tgm/perp-positions'], 'scene': 'perp_positions', 'menu': 'nsn_perppos',
     'price': '5 кредитов',
     'gives': 'размер позиции, плечо, нереализованный PnL и цену ликвидации по каждому счёту',
     'why': 'до этого эндпоинта цены ликвидации у нас не было вовсе - про неё догадывались '
            'по цене входа',
     'hook': 'Leveraged positions with the one number nobody shows: the liquidation price.'},
    {'id': 'liqmap', 'title': '🗺 Карта ликвидаций: где висит чужое плечо',
     'cmds': ['карта ликвидаций BTC', 'ликвид карта BTC'],
     'btns': ['карточка токена → 💥 Ликвид. → 🗺 Карта ликвидаций'],
     'eps': ['tgm/perp-positions'], 'scene': 'liq_map', 'menu': 'nsn_liqmap',
     'price': '5 кредитов (тот же запрос, что у списка позиций)',
     'gives': 'картинку: суммы позиций по уровням цены ликвидации, красное - лонги, зелёное - '
              'шорты, пунктир - текущая цена. Плюс подпись величиной',
     'why': 'список позиций отвечает «кто стоит», а карта - «на каком уровне рынок поедет '
            'быстро»; это не строка, а распределение',
     'hook': 'A liquidation map: $22.5M of leverage stacked between $61.5K and $62.4K. '
             'The list tells you who is in. The map tells you where the market moves fast.'},
    {'id': 'walletperps', 'title': '🩺 Счёт кошелька на перпах и запас до ликвидации',
     'cmds': ['нансен перпы 0x…'], 'btns': ['🧠 Nansen → 🩺 Счёт кошелька на перпах'],
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
     'price': '4 запроса, около 12 кредитов',
     'gives': 'нетто-потоки по сегментам холдеров, Nansen Score, метки топ-холдеров, топ по PnL',
     'why': 'один экран отвечает на «кто в этом токене» четырьмя разными способами',
     'hook': 'Four Nansen lenses on one token in a single tap: segment flows, Nansen Score, '
             'labelled top holders, top PnL.'},
    {'id': 'wbs', 'title': '🔄 Кто нетто покупал и кто продавал токен',
     'cmds': ['кто входил 0x… 7', 'кто выходил 0x…'],
     'btns': ['карточка токена → 🧠 → 🔄 Кто входил'],
     'eps': ['tgm/who-bought-sold'], 'scene': 'who_bought_sold', 'menu': 'nsn_wbs',
     'price': '1 кредит за сторону',
     'gives': 'метку или адрес и объём $ по каждой стороне за период',
     'why': 'нетто-поток - это итог; здесь видно, КТО его сделал',
     'hook': 'Who net-bought and who net-sold a token over the last N days, by label.'},
    {'id': 'tinfo', 'title': '🪪 Справка по токену от Nansen',
     'cmds': ['инфо токен 0x…'], 'btns': ['🧠 Nansen → 🪪 Справка по токену'],
     'eps': ['tgm/token-information'], 'scene': 'token_info', 'menu': 'nsn_tinfo',
     'price': '1 кредит',
     'gives': 'капитализацию, объём, ликвидность, число держателей',
     'why': 'базовые метрики из того же источника, что и всё остальное - без второго вендора',
     'hook': 'Token fundamentals from the same source as the flows: one key, one story.'},
    {'id': 'flowpng', 'title': '📊 Потоки по сегментам холдеров КАРТИНКОЙ',
     'cmds': ['потоки картинкой 0x…'], 'btns': ['карточка токена → 🧠 → 📊 Потоки картинкой'],
     'eps': ['tgm/flow-intelligence'], 'scene': 'token_check', 'menu': 'nsn_flowpng',
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
     'cmds': ['контрагенты 0x…'], 'btns': ['🧠 Nansen → 🤝 С кем торгует кошелёк'],
     'eps': ['profiler/address/counterparties'], 'scene': 'counterparties',
     'menu': 'nsn_cparty', 'price': 'цена не названа в официальном списке',
     'gives': 'контрагентов за 30 дней и объёмы',
     'why': 'связи адреса говорят о нём больше, чем его баланс',
     'hook': "Who a wallet actually trades with. Its counterparties say more than its balance."},
    {'id': 'balance', 'title': '💼 Портфель кошелька по данным Nansen',
     'cmds': ['нансен баланс 0x…'], 'btns': ['🧠 Nansen → 💼 Портфель кошелька'],
     'eps': ['profiler/address/current-balance'], 'scene': 'wallet_balance',
     'menu': 'nsn_bal', 'price': 'цена не названа в официальном списке',
     'gives': 'состав портфеля по $ без спам-токенов',
     'why': 'тот же ключ вместо отдельного платного вендора по балансам',
     'hook': 'Wallet portfolio from the same API key - one vendor fewer in the stack.'},
    # ── POLYMARKET ────────────────────────────────────────────────────────────
    {'id': 'pmmarkets', 'title': '🎲 Трендовые рынки Polymarket с market_id',
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
    {'id': 'pmrep', 'title': '🎭 Кто держит рынок и как угадывал раньше',
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
     'price': '200 кредитов (fast) или 750 (expert) - САМЫЙ дорогой путь',
     'gives': 'ответ агента на вопрос словами, с подписью источника',
     'why': 'единственная дверь для вопросов, под которые нет структурного эндпоинта',
     'hook': 'The agent is the expensive path: 200 credits, or 750 in expert mode. So every '
             'screen prints what it cost.'},
    {'id': 'tally', 'title': '🧮 Мой зачёт в конкурсе',
     'cmds': ['нансен зачёт', 'мой зачёт'], 'btns': ['🧠 Nansen → 🧮 Мой зачёт в конкурсе'],
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
        for c in sc['cmds']:
            # КОМАНДУ ПРОВЕРЯЕМ РОУТЕРОМ, А НЕ ГЛАЗАМИ. Плейсхолдер `0x…` роутер не поймёт,
            # поэтому подставляем настоящий публичный адрес - проверяется ФОРМА команды.
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
        for f in ('title', 'gives', 'why', 'hook', 'price'):
            if not (sc.get(f) or '').strip():
                bad.append('%s: пустое поле %r' % (_id, f))
    return bad


def _md():
    """Собрать документ. -> str."""
    import nansen_log as T
    L = ['# Каталог сценариев на данных Nansen', '',
         'Все экраны бота, которые ходят в Nansen: что сказать, что придёт, чего это стоит и '
         'зачем это нужно.', '',
         '**Документ СОБРАН ИНСТРУМЕНТОМ** (`tools/nansen_catalog.py`), а не написан руками. '
         'Сборщик проверяет четыре класса утверждений: команда распознаётся общим роутером, '
         'эндпоинт реально присутствует в сетевой горловине клиента, сцена есть в закрытом '
         'реестре телеметрии, а подпись меню имеет кнопку/action. Это не заменяет E2E-тест '
         'связи конкретной команды с конкретным endpoint — hero-paths отдельно проходят '
         'живыми callback-тестами. Расходится хоть одна из этих проверяемых частей — документ '
         'не пишется. По каталогу создаются публичные обещания, а обещать несуществующую '
         'фичу хуже, чем не обещать ничего.', '',
         '**Про цену.** Где официальный список Nansen называет цену эндпоинта — она в '
         'кредитах. Где не называет — цена указана **числом запросов**. Это не уклонение: '
         'придуманное число кредитов в документе, по которому пишут твиты, было бы ложью в '
         'самом проверяемом месте.', '',
         '| Сценариев | Эндпоинтов задействовано | Сцен телеметрии |', '|---|---|---|']
    _eps = sorted({e for sc in SCENARIOS for e in sc['eps']})
    _scenes = sorted({sc['scene'] for sc in SCENARIOS if sc['scene']})
    user_api = [s for s in SCENARIOS if s['eps'] and not str(s.get('scene') or '').endswith('_cron')]
    background = [s for s in SCENARIOS if str(s.get('scene') or '').endswith('_cron')]
    local = [s for s in SCENARIOS if not s['eps']]
    L += ['| %d: %d пользовательских на Nansen + %d фоновый + %d локальный | %d | %d из %d в реестре |'
          % (len(SCENARIOS), len(user_api), len(background), len(local), len(_eps),
             len(_scenes), len(T.SCENES)), '']
    L += ['## Короткая таблица', '',
          '| Сценарий | Сказать боту | Кнопкой | Цена |', '|---|---|---|---|']
    for sc in SCENARIOS:
        _c = '<br>'.join('`%s`' % c for c in sc['cmds']) or '—'
        _b = '<br>'.join(sc['btns']) or '—'
        L.append('| [%s](#%s) | %s | %s | %s |'
                 % (sc['title'], sc['id'], _c, _b, sc['price']))
    L += ['', '---', '']
    for sc in SCENARIOS:
        L += ['<a name="%s"></a>' % sc['id'], '', '## %s' % sc['title'], '']
        if sc['cmds']:
            L.append('**Сказать боту:** ' + ' · '.join('`%s`' % c for c in sc['cmds']))
        if sc['btns']:
            L.append('**Кнопкой:** ' + ' · '.join(sc['btns']))
        L += ['', '**Что придёт:** %s' % sc['gives'], '',
              '**Цена:** %s' % sc['price'], '',
              '**Зачем:** %s' % sc['why'], '']
        L += ['**Эндпоинты:** ' + (', '.join('`%s`' % e for e in sc['eps']) or 'нет, читает '
                                   'свой лог'), '']
        if sc['scene']:
            L.append('**Сцена телеметрии:** `%s` — по ней считается расход этого экрана.' %
                     sc['scene'])
            L.append('')
        L += ['**Для твита (EN):**', '', '> %s' % sc['hook'], '', '---', '']
    # ═══ РАЗДЕЛ, БЕЗ КОТОРОГО КАТАЛОГ БЫЛ БЫ ПОЛОВИНОЙ ПРАВДЫ ═══
    # Запрос был «все сценарии, какие есть». Сценарии выше - те, до которых человек может
    # дойти. Но в клиенте есть эндпоинты БЕЗ двери, и молчать о них нельзя: читатель каталога
    # решит, что перечисленное - это всё, что умеет ключ. Список СЧИТАЕТСЯ (клиент минус
    # каталог), поэтому не может отстать: подключат эндпоинт без двери - он появится здесь сам.
    _src = open(os.path.join(ROOT, 'nansen_api.py'), encoding='utf-8').read()
    _all = _endpoints_in(_src)
    _noдверь = sorted(_all - set(_eps))
    L += ['## Маршруты клиента без обычного пользовательского сценария', '',
          'В каталоге выше — %d workflow, которые задействуют %d уникальных API-маршрутов. '
          'Всего клиент содержит **%d** маршрута; ещё %d не имеют обычной пользовательской '
          'двери (часть служебная/owner-only, часть — клиентский задел).'
          % (len(SCENARIOS), len(_eps), len(_all), len(_noдверь)), '',
          'Это не заявка «все работают end-to-end»: наличие клиента не равно готовому '
          'сценарию. Список вынесен именно затем, чтобы не выдавать охват API за доступную '
          'пользователю функциональность.', '',
          'Список СЧИТАЕТСЯ при сборке (клиент минус каталог): новый маршрут без workflow '
          'появится здесь автоматически.', '']
    for e in _noдверь:
        L.append('* `%s`' % e)
    L += ['', '---', '']
    L += ['## Как пересобрать', '',
          '```bash', 'python3 tools/nansen_catalog.py --write   # в приватном репозитории',
          'python3 tools/export_nansen_public.py --out <путь>  # и в публичную выжимку',
          '```', '',
          'Проверка без записи — `--check`, код возврата 1 при расхождении. Этим же ходит '
          'закон-тест, поэтому «каталог отстал от кода» становится красным тестом, а не '
          'неприятным открытием в момент, когда по нему уже написан твит.', '']
    return '\n'.join(L)


def main(argv):
    bad = _verify()
    if bad:
        print('КАТАЛОГ НЕ СОБРАН: расхождений %d' % len(bad))
        for b in bad:
            print('  ' + b)
        return 1
    txt = _md()
    if '--check' in argv:
        p = os.path.join(ROOT, 'nansen', 'CATALOG.md')
        if not os.path.exists(p):
            print('CATALOG.md ещё не собран: python3 tools/nansen_catalog.py --write')
            return 1
        if open(p, encoding='utf-8').read() != txt:
            print('CATALOG.md ОТСТАЛ от кода. Пересобрать: '
                  'python3 tools/nansen_catalog.py --write')
            return 1
        print('каталог совпадает с кодом: сценариев %d' % len(SCENARIOS))
        return 0
    if '--write' in argv:
        p = os.path.join(ROOT, 'nansen', 'CATALOG.md')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(txt)
        print('записан %s: сценариев %d, проверок пройдено %d'
              % (p, len(SCENARIOS), sum(len(s['cmds']) + len(s['eps']) for s in SCENARIOS)))
        return 0
    print(txt)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
