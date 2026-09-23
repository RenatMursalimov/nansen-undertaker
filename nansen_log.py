# -*- coding: utf-8 -*-
"""nansen_log.py — телеметрия вызовов Nansen, честный учёт кредитов и зачёт вклада людей.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ СТРОКИ В `bot.log`
Разбор бота живёт grep-ом по `bot.log` (закон №1), и строка на каждый структурный вызов
сломала бы главный инструмент диагностики. Плюс существующие строки не годятся по существу:
`nansen_api` печатает `[nansen] …` ТОЛЬКО при ошибке (успешный вызов следа не оставляет),
`bot.py` печатает имя человека, `pub_tools` печатает uid. То есть у нас нет ни числителя,
ни выгрузки, из которой можно что-то показать наружу.

ГДЕ СТОИТ ВРЕЗКА: В ГОРЛОВИНАХ КЛИЕНТА, А НЕ У ВЫЗЫВАЮЩИХ
Точек вызова Nansen около двадцати, и доказательство цены «врезки по местам» уже есть:
`cost_tracker.track('nansen')` был заведён в ОДНОЙ из них, поэтому все наши цифры расхода
были занижены систематически. Здесь пишут четыре функции `nansen_api` — `_post`,
`_post_beta`, `ask_agent`, `smart_money_netflow`, — через которые проходит КАЖДЫЙ сетевой
вызов. Новая точка вызова попадает в телеметрию сама, без строки в реестре (закон №5).

ЧЕЛОВЕК В ЛОГЕ ЕСТЬ, В ВЫГРУЗКЕ ЕГО НЕТ
- В посуточном логе живёт `u` — СУТОЧНЫЙ HMAC от uid. Нужен ровно для одного: отличить
  «двадцать человек по разу» от «один человек двадцать раз». Хэш меняется каждые сутки,
  поэтому сквозного идентификатора за период не существует по построению.
- В выгрузке (`--csv`, сводка, сабмишен) `u` не появляется ни в каком виде, даже обрезанным.
- Зачёт вклада (B4) ведётся в БАЗЕ по настоящему uid, потому что «твоё место» иначе не
  посчитать. База НЕ ПОКИДАЕТ СЕРВЕР: наружу уходят агрегаты и порядковые места. Таблица
  заведена в `consent.HARD_DELETE` тем же PR (закон №12) — «удали всё моё» уносит и её.

Ключа Nansen, токенов, адресов кошельков и тикеров в логе нет: пишем ПУТЬ эндпоинта,
аргументы в лог не идут.

Запуск сводки: python3 tools/nansen_daily.py [дата|--range A B] [--csv]
"""

import contextlib
import contextvars
import hashlib
import hmac
import json
import os
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
TELE_DIR = os.path.join(BASE, 'nansen_tele')
CREDITS_FILE = os.path.join(BASE, 'nansen_credits.json')

#: сколько суток держим посуточные файлы телеметрии
KEEP_DAYS = 30

#: АНТИНАКРУТКА: повтор ТОГО ЖЕ запроса ТОГО ЖЕ человека чаще, чем раз в это время, в
#: зачёт вклада не идёт. Не блокируем — именно не засчитываем, и это объявлено заранее.
REPEAT_MIN = int(os.getenv('NANSEN_REPEAT_MIN') or 10)

# ═══════════════════════════════════════════════════════════════════════════
# ЗАКРЫТЫЙ РЕЕСТР СЦЕН. Чужое имя -> `scene=?` и громкая строка в сводке: список, в
# который молча дописывают, перестаёт быть списком. Имена — ровно по nansen/scenarios.md.
# ═══════════════════════════════════════════════════════════════════════════
SCENES = (
    # ИМЯ 'bare_address' УБРАНО, А НЕ ОСТАВЛЕНО «на всякий случай»: голый адрес в личке и
    # команда «профиль 0x…» ходят ОДНОЙ дверью (закон №40), и эта дверь ставит сцену
    # 'wallet_profile'. Имя в реестре, которым никто не зовёт, - такая же ложь, как сцена
    # вне реестра: читаешь список и думаешь, что такой разрез в сводке есть. Ниже инвариант
    # держит ОБА направления: реестр ⊇ вызовы И реестр ⊆ вызовы (плюс явный список
    # зарезервированных, если он однажды понадобится).
    'wallet_profile',          # «профиль 0x…» + тап по голому адресу в личке
    'wallet_profile_premium',  # «профиль 0x… глубже» (премиум-метки, 150 кр)
    'smart_flows',             # «смарт потоки» / меню ocm:sm:*
    'smart_holdings',          # «смарт холдинги»
    'perp_leaders',            # «топ перпы»
    'token_check',             # кнопка 🧠 / «паспорт … глубже»
    # POLYMARKET РАЗДЕЛЁН ПО ЭКРАНАМ. Раньше всё ложилось одной сценой `polymarket`, и
    # submission не мог доказать, что hero-screen репутации вообще кто-то открывал.
    'pm_markets',              # список рынков
    'pm_chart',                # вероятность во времени
    'pm_orderbook',            # стакан
    'pm_reputation',           # кто держит и как угадывал раньше
    'pm_wallet',               # профиль трейдера
    'pm_leaders',              # топ конкретного рынка
    'agent_free',              # свободный вопрос (личка, паблик, Хаб)
    'who_bought_sold',         # «кто входил/выходил 0x…»   (подключено ТЗ B, B3)
    'token_info',              # «инфо токен 0x…»            (B3)
    'counterparties',          # «контрагенты 0x…»           (B3)
    'wallet_balance',          # «нансен баланс 0x…»         (B3)
    # ═══ ЗАБЫТАЯ ТРОЙКА. Двери были написаны и работали, а имена в реестр не внесли, и
    # каждый их вызов ложился в сводку строкой `? N кр`: расход виден, ЧЕЙ он - нет.
    # Ren прочитал это на живой «нансен стата» 15.09 («? 5 кр» рядом с named-сценами).
    # Класс бага ровно тот, от которого закрытый реестр и защищает, - поэтому ниже
    # инвариант: тест сверяет ВСЕ scene(...) в репозитории с этим списком (test_nansen_contest).
    'perp_positions',          # «перп позиции BTC» / кнопка 💥 Ликвид. на карточке токена
    'liq_map',                 # карта скоплений по цене ликвидации
    'smart_trades',            # «смарт сделки» (отдельные сделки, не агрегат netflow)
    # ИМЯ 'wallet_perps' СНАЧАЛА УБРАЛИ 19.09 (эндпоинт отвечал 404), а 20.09 ВЕРНУЛИ: проба
    # путей нашла ту же ручку живой по адресу `profiler/perp-positions`. Цена ошибки - один
    # день без экрана; вывод записан в nansen_api рядом с ручкой: «404» не равно «фичи нет»,
    # сперва перебор соседних путей, потом похороны.
    'wallet_perps',            # «нансен перпы 0x…» (здоровье счёта, запас до ликвидации)
    'digest_cron',             # утренний дайджест
    'tweet_cron',              # твит-джобы
    'endpoint_sweep',          # fresh server sweep: all safe client routes, no person
    'trade_probe',             # isolated human-gated quote/prepare/status diagnostics
    'admin_backfill',          # бэкфилл истории потоков (владелец)
    'chart',                   # свечи для графика/бэктеста
    'trends',                  # секция smart money в Трендах
    # ДВА СРАВНИТЕЛЬНЫХ ЭКРАНА. Отдельные имена, а не «pm_reputation ×4»: экран сравнения
    # стоит 13-17 запросов, и слипнись он в сводке с одиночным разбором рынка - самая дорогая
    # строка расхода стала бы невидимой ровно там, где на неё смотрят.
    'sharp_markets',           # «острые деньги»: трендовые рынки по составу держателей
    'perp_risk',               # «борд риска»: у кого плечо ближе к обрыву
)
_SCENES = frozenset(SCENES)

#: ЦЕНА ВЫЗОВА В КРЕДИТАХ ПО ЭНДПОИНТУ - ТОЛЬКО ТАМ, ГДЕ ОНА НАЗВАНА ИСТОЧНИКОМ (см. ниже),
#: а не из общей константы `cost_tracker.PRICES['nansen']['avg_units']`: там стоит 200 - цена
#: АГЕНТА, и структурный вызов за 1-5 кредитов записался бы как 200, то есть ошибка в 40-200
#: раз, и весь расчёт стоимости ответа уехал бы.
#:
#: ПРЕЖНЯЯ РЕДАКЦИЯ ЭТОГО АБЗАЦА ГОВОРИЛА «числа взяты из докстрингов `nansen_api` (то есть
#: с живого ключа на проде)», и это НЕВЕРНО в обе половины: докстринги писались по
#: документации годичной давности, живым ключом не сверялись, и врали (разбор ниже). Абзац
#: переписан, а не стёрт: комментарий, ставший ложным после чужой правки, закрывает разбор
#: надёжнее своего отсутствия - читаешь, веришь, ищешь причину в другом месте.
#:
#: ГДЕ ЦЕНА НЕ ИЗМЕРЕНА - ПИШЕМ НОЛЬ И СЧИТАЕМ ОТДЕЛЬНОЙ СТРОКОЙ. «184 вызова с неизвестной
#: ценой» полезнее красивой суммы, собранной из догадок (закон №22). Когда Ren снимет Usage
#: Analytics, клетки заполняются, и сводка пересчитывается по ТОМУ ЖЕ логу.
#: ИСТОЧНИК ЦЕН - ОФИЦИАЛЬНАЯ СТРАНИЦА docs.nansen.ai/api/overview (снято 14.09.2026), а не
#: докстринги клиента. Докстринги писались по документации годичной давности и в двух местах
#: разошлись с реальностью НЕ в нашу пользу:
#:   * `agent/expert` стоит 750, а не 200. Ошибка в 3.75 раза на самом дорогом пути, и он
#:     доступен человеку словами «глубок», «детальн», «подробно разбери» - то есть случайно.
#:   * `tgm/indicators` стоит 5, а не 25. Ошибка в другую сторону: мы завышали расход на
#:     кнопке 🧠 и считали её дороже, чем она есть.
#: Обе цифры теперь отсюда. Расхождение с Usage Analytics закрывается сверкой по эндпоинтам.
_EP_EST = {
    'agent/fast': 200, 'agent/expert': 750,
    'profiler/address/premium-labels': 150,
    'tgm/indicators': 5, 'tgm/holders': 5, 'tgm/pnl-leaderboard': 5, 'perp-leaderboard': 5,
    'tgm/historical-token-ohlcv': 5, 'tgm/historical-token-flow-summary': 5,
    'token-screener': 1, 'tgm/flow-intelligence': 1,
    'tgm/who-bought-sold': 1, 'tgm/token-information': 1,
    'smart-money/holdings': 3,                     # в overview числа нет, докстринг «1-5»
}

#: ЦЕНА НЕ ИЗМЕРЕНА: ни в docs/api/overview, ни в докстрингах клиента числа нет. Ноль вместо
#: выдумки - в сводке такие вызовы идут отдельной строкой «вызовов с неизвестной ценой».
#: Раздел Profiler в overview цен не печатает вовсе, поэтому все profiler/* кроме премиум-меток
#: остаются здесь: подставить им «примерно 1» значило бы выдать догадку за факт.
#: про что уже сказали в лог - чтобы не повторять одну и ту же строку на каждый вызов
_SAID_UNKNOWN = set()
_SAID_ONCE = set()
_EP_UNKNOWN = frozenset((
    'smart-money/netflow',
    'profiler/address/labels', 'profiler/address/pnl-summary',
    'profiler/address/related-wallets', 'profiler/address/counterparties',
    'profiler/address/current-balance',
    'prediction-market/market-screener', 'prediction-market/address-summary',
    'prediction-market/pnl-by-address', 'prediction-market/pnl-by-market',
))


def est_credits(ep):
    """Цена вызова эндпоинта в кредитах по docs.nansen.ai/api/overview. -> int (0 = не измерена).

    НЕ по докстрингам клиента: они разошлись с площадкой в двух местах и в разные стороны
    (`agent/expert` 750 против 200, `tgm/indicators` 5 против 25) - см. комментарий над
    `_EP_EST`."""
    return _EP_EST.get(str(ep or '').strip('/'), 0)


def price_known(ep):
    """Известна ли цена этого эндпоинта. -> bool.

    Отдельная функция, а не `est_credits(ep) > 0`: ноль у нас означает РОВНО «не измерено», и
    читателю кода это должно быть видно на месте, а не выводиться из совпадения."""
    ep = str(ep or '').strip('/')
    if ep in _EP_EST:
        return True
    if ep in _EP_UNKNOWN:
        return False
    # ОДИН РАЗ НА ИМЯ, А НЕ НА ВЫЗОВ. Строка полезна («цену этого эндпоинта пора внести»), но
    # печаталась на КАЖДЫЙ вызов: один экран давал её десять раз, суточный лог - тысячу. Шум
    # такого рода не нейтрален, он учит не читать лог вообще, а рядом в том же логе лежат
    # строки, из-за которых слой и писался (снятая схема, тело отвергнутого запроса).
    if ep not in _SAID_UNKNOWN:
        _SAID_UNKNOWN.add(ep)
        print('[nansen_log] эндпоинт %r не в таблице цен - считаю неизвестным' % ep)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# КОРОБКА ВЫЗОВА: сцена, человек и КАНАЛ ПРИЧИН ОТКАЗА
#
# ПОЧЕМУ ИМЕННО КОРОБКА (изменяемый dict), А НЕ ЗНАЧЕНИЕ В ContextVar. Половина живых
# вызовов уезжает в `asyncio.to_thread(fn, ...)`, а он исполняет функцию в КОПИИ контекста:
# присваивание ContextVar внутри потока наружу НЕ ВИДНО. Поэтому в переменной лежит ссылка
# на словарь, созданный ДО ухода в поток, — мутации этого словаря видит и поток, и
# дождавшийся его вызывающий. Ровно так причина отказа (429/402/таймаут) доезжает от `_post`
# до экрана человека, не меняя сигнатуру двадцати функций.
# ═══════════════════════════════════════════════════════════════════════════
_BOX = contextvars.ContextVar('nansen_box', default=None)
_TL = threading.local()          # запасной канал для чисто синхронных путей (без scene())
_LOCK = threading.Lock()
_REP = {}                        # 'YYYY-MM-DD' -> {u: сколько запросов за сутки}
_FLIGHT = {'n': 0, 'rem': None, 'overlap_seq': 0}  # + поколение любого пересечения

#: тяжесть классов исхода: чем больше, тем «главнее» причина в смешанном блоке.
#: `badreq` (400/422 - площадка отвергла НАШ запрос) стоит выше общего `http`, потому что он
#: КОНКРЕТНЕЕ: у него есть адресат правки, и в смешанном блоке сказать надо именно его.
#: Ниже внешних ограничений (частота, кредиты) - те блокируют всё и узнать о них надо первым.
# ТЯЖЕСТЬ ИСХОДОВ. `outcome()` отдаёт САМЫЙ ТЯЖЁЛЫЙ из коробки, поэтому порядок здесь - это
# решение о том, о чём человеку скажут, когда в одном блоке случилось два разных отказа.
#
# 'unsupported' СТОИТ ВЫШЕ 'empty' И НИЖЕ ВСЕГО ОСТАЛЬНОГО, и это не на глаз:
#   * выше 'empty', потому что «эндпоинт не покрывает стейблкоины» - конкретный ответ, а
#     «данных нет» рядом с ним звучит как свойство токена, то есть врёт;
#   * ниже 'http'/'badreq'/таймаута, потому что те означают «мы не знаем вообще ничего», а
#     здесь мы знаем много: запрос верный, площадка жива, покрытия по этому активу нет.
# Класс появился из живой пробы 19.09 - до неё мы такой ответ читали как свой баг.
_SEV = {'ok': 0, 'empty': 1, 'unsupported': 2, 'http': 3, 'badreq': 4, 'timeout': 5,
        'ratelimit': 6, 'nocredits': 7, 'nokey': 8}


def _new_box(scene_name=None, uid=None, surface=None):
    # `fails` - ЧТО ИМЕННО НЕ ПРИЕХАЛО, парами (эндпоинт, код). Одного `outcomes` мало:
    # блок из трёх запросов, где два упали 422, а третий ответил, СОБИРАЕТСЯ и выглядит
    # целым. Худший исход не «пусто», а «непустой блок без двух третей данных»: человек не
    # узнаёт, что метки и PnL не приезжали вовсе. Поймано живым прогоном 14.09 на профиле
    # кошелька.
    return {'scene': scene_name, 'uid': uid, 'outcomes': [], 'age': None,
            'http': 0, 'cache_only': True, 'fails': [], 'calls': 0,
            'surface': surface if surface in _SURFACES else DEFAULT_SURFACE}


#: ПОВЕРХНОСТИ: где человек увидел экран. Мини-апп - НОВАЯ ПОВЕРХНОСТЬ СТАРОЙ СЦЕНЫ, а не
#: новая сцена: заведи ему отдельные имена сцен, и расход по сценам перестанет складываться -
#: «репутация рынка» оказалась бы в двух строках сводки, и ни одна не отвечала бы на вопрос
#: «сколько всего стоил этот экран». Поэтому сцена одна, а поверхность - отдельная колонка.
SURFACES = ('chat', 'miniapp', 'cron')
_SURFACES = frozenset(SURFACES)
DEFAULT_SURFACE = 'chat'


@contextlib.contextmanager
def scene(name, uid=None, surface=DEFAULT_SURFACE):
    """Пометить участок кода сценарием (и человеком, если он есть). Контекстный менеджер.

    Имя ставит ВЫЗЫВАЮЩИЙ, а не аргумент клиента: клиент не знает и не должен знать, каким
    словом человек его позвал, а между гейтом и точкой вызова лежат чужие слои.

        with nansen_log.scene('smart_flows', uid):
            block = await asyncio.to_thread(_n.sm_netflow_block, ...)

    Сцену НЕ УГАДЫВАЕМ: чужое имя и отсутствие имени дают `scene=?` и отдельную строку
    «БЕЗ СЦЕНЫ» в суточной сводке.

    `surface` - ГДЕ человек это увидел: 'chat' (по умолчанию, ответ в Telegram), 'miniapp'
    (экран мини-аппа), 'cron' (фоновая джоба). Чужое значение молча падает в 'chat': поверхность
    это разрез отчёта, и ломать запись строки из-за опечатки в нём нельзя.
    """
    nm = name if name in _SCENES else None
    if name and nm is None:
        print('[nansen_log] сцена %r не в реестре -> scene=?' % (name,))
    if surface not in _SURFACES:
        print('[nansen_log] поверхность %r не в реестре -> %s' % (surface, DEFAULT_SURFACE))
    box = _new_box(nm, uid, surface)
    tok = _BOX.set(box)
    prev = getattr(_TL, 'box', None)
    _TL.box = box
    try:
        yield box
    finally:
        _TL.box = prev
        try:
            _BOX.reset(tok)
        except ValueError:
            pass                      # сброс в другом контексте (to_thread) — не беда


def surface():
    """Поверхность текущей сцены: где человек увидит результат. -> str.

    Отдельной функцией, потому что читают её двое (`record` и `note_quota`), и «взять из
    коробки, а если её нет - по умолчанию» - правило, которому положено жить в одном месте.
    """
    try:
        return (box() or {}).get('surface') or DEFAULT_SURFACE
    except Exception:
        return DEFAULT_SURFACE


def box():
    """Текущая коробка вызова. Если сцены нет — своя на поток, чтобы причина отказа всё
    равно доехала до синхронного вызывающего."""
    b = _BOX.get()
    if b is not None:
        return b
    b = getattr(_TL, 'box', None)
    if b is None:
        b = _new_box()
        _TL.box = b
    return b


def fails():
    """Что не приехало в текущей коробке. -> [(эндпоинт, код, класс)]."""
    return list(box().get('fails') or ())


def calls():
    """Сколько сетевых исходов отмечено в текущей коробке. -> int."""
    return int(box().get('calls') or 0)


def clear():
    """Начать новый счёт причин В ТОЙ ЖЕ коробке. -> коробка.

    Чистим НА МЕСТЕ, а не подменяем объект: коробку уже держит вызывающий (в него уезжает
    ссылка через copy_context), и подмена оборвала бы канал причин ровно посередине.
    Нужно дверям, которые собирают ответ из нескольких запросов и сами объявляют вердикт
    (`token_nansen_block_ex` и родня): без чистки в них попали бы причины прошлого запроса,
    висящие в коробке этого потока."""
    b = box()
    b['outcomes'] = []
    b['age'] = None
    b['cache_only'] = True
    b['http'] = 0
    b['fails'] = []
    b['calls'] = 0
    return b


def note(outcome, http=0, ep=''):
    """Отметить исход одного сетевого вызова в текущей коробке.

    `ep` нужен ЧАСТИЧНЫМ блокам: без имени эндпоинта строка «не приехало 2 запроса» не
    говорит, какие именно, и чинить её нечем."""
    b = box()
    if outcome not in _SEV:
        outcome = 'http'
    b['outcomes'].append(outcome)
    b['calls'] = b.get('calls', 0) + 1
    if outcome not in ('ok', 'empty'):
        b.setdefault('fails', []).append((str(ep or '?'), int(http or 0), outcome))
    if http:
        b['http'] = http


def note_age(sec):
    """Возраст данных, попавших в ответ (0 — только что из сети, >0 — из кэша).

    Берём МАКСИМУМ: блок из четырёх запросов свеж настолько, насколько свеж самый старый
    его кусок. Обратное («покажем самое свежее») врало бы человеку в лучшую сторону."""
    b = box()
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return
    if b['age'] is None or sec > b['age']:
        b['age'] = sec
    if sec <= 0:
        b['cache_only'] = False


def outcome():
    """Худший исход в текущей коробке. -> 'ok'|'empty'|'http'|'timeout'|'ratelimit'|
    'nocredits'|'nokey'|None (вызовов не было вовсе)."""
    b = box()
    if not b['outcomes']:
        return None
    return max(b['outcomes'], key=lambda o: _SEV.get(o, 2))


def age():
    """Возраст данных в секундах или None, если не измерен."""
    return box().get('age')


def cache_only():
    """True, если в этой коробке ВСЁ пришло из кэша (ни одного сетевого ответа)."""
    b = box()
    return bool(b['outcomes']) and b.get('cache_only', True)


# ═══════════════════════════════════════════════════════════════════════════
# ОСТАТОК КРЕДИТОВ ПЕРЕЖИВАЕТ РЕСТАРТ
# Раньше остаток жил в памяти процесса и умирал вместе с ним: до первого структурного
# запроса бот не знал об остатке ничего и показывал владельцу пустоту.
# ═══════════════════════════════════════════════════════════════════════════
def credits_read():
    """Persisted credit snapshot, including invalidity that must survive restart."""
    pending = CREDITS_FILE + '.pending'
    # A process may have died while writing the next snapshot. Trusting the previous number as
    # fresh would fail open; the mere pending marker makes the balance invalid until a later
    # successful atomic replace removes it.
    if os.path.exists(pending):
        return {'remaining': None, 'used': None, 'ts': 0, 'invalid': True}
    try:
        with open(CREDITS_FILE, encoding='utf-8') as f:
            d = json.loads(f.read().strip() or '{}')
        if isinstance(d, dict):
            return {'remaining': d.get('remaining'), 'used': d.get('used'),
                    'ts': d.get('ts') or 0, 'invalid': bool(d.get('invalid'))}
    except FileNotFoundError:
        pass
    except Exception:
        # A legacy/torn target file is unknown credit state, never a clean empty snapshot.
        return {'remaining': None, 'used': None, 'ts': 0, 'invalid': True}
    return {'remaining': None, 'used': None, 'ts': 0, 'invalid': False}


def credits_write(remaining=None, used=None, invalid=False):
    """Persist a credit snapshot atomically; a torn pending write remains fail-closed."""
    d = credits_read()
    if invalid:
        d['remaining'] = None
        d['invalid'] = True
    elif remaining is not None:
        d['remaining'] = remaining
        d['invalid'] = False
    if used is not None:
        d['used'] = used
    d['ts'] = int(time.time())
    pending = CREDITS_FILE + '.pending'
    try:
        with open(pending, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(pending, CREDITS_FILE)
    except Exception as e:
        # Do not delete pending: its presence is the restart-safe invalidity marker.
        print('[nansen_log] остаток не записался атомарно: %s' % str(e)[:120])
    return d


# ═══════════════════════════════════════════════════════════════════════════
# ЗАПИСЬ СТРОКИ
# ═══════════════════════════════════════════════════════════════════════════
def _day(ts=None):
    return time.strftime('%Y-%m-%d', time.gmtime(ts or time.time()))


def _bot_key():
    try:
        import worker_deploy
        k = worker_deploy.bot_key()
        if k:
            return k.encode()
    except Exception:
        pass
    t = (os.getenv('BOT_TOKEN') or '').strip()
    return t.encode() if t else b'nansen-tele-no-token'


def daily_u(uid, day=None):
    """Суточный HMAC от uid. 8 hex. Меняется каждые сутки -> сквозного идентификатора нет.

    Приём не из головы: так же собран `who` у моста (HMAC от uid И ДАТЫ), заведённый ровно
    затем, чтобы в чужой базе не лежало идентификаторов."""
    if not uid:
        return 'job'
    return hmac.new(_bot_key(), ('%s|%s' % (uid, day or _day())).encode(),
                    hashlib.sha256).hexdigest()[:8]


def _bump_rep(u, day):
    # Reputation-screen пишет пять summaries параллельно. Без lock два потока могли оба
    # прочитать rep=3 и записать rep=4 — потерянный инкремент в конкурсной телеметрии.
    with _LOCK:
        d = _REP.setdefault(day, {})
        d[u] = d.get(u, 0) + 1
        for k in [k for k in _REP if k != day]:
            _REP.pop(k, None)
        return d[u]


def flight_begin():
    """Вызов ушёл в сеть. -> (остаток до, число в полёте, поколение пересечений).

    Если новый вызов встречает уже активный, overlap_seq растёт. Так ПЕРВЫЙ вызов тоже
    узнает при завершении, что позже с ним пересеклись; одного `parallel` на старте было
    недостаточно и позволяло первому присвоить себе расход второго.
    """
    with _LOCK:
        if _FLIGHT['n'] > 0:
            _FLIGHT['overlap_seq'] += 1
        _FLIGHT['n'] += 1
        return (_FLIGHT['rem'], _FLIGHT['n'], _FLIGHT['overlap_seq'])


def flight_end(rem=None):
    """Вызов вернулся. -> текущее поколение пересечений."""
    with _LOCK:
        n = _FLIGHT['n']
        _FLIGHT['n'] = max(0, n - 1)
        if rem is not None:
            _FLIGHT['rem'] = rem
        return _FLIGHT['overlap_seq']


def record(ep, ms=0, http=0, ok=False, empty=False, cache=False, rem=None, used=None,
           rem_before=None, parallel=1, sig=None, cls=None, overlap=False):
    """Одна строка на один вызов. -> dict записанных полей (для тестов и сводки).

    `ok` и `empty` — РАЗНЫЕ вопросы, и склеивать их нельзя: `ok=0,empty=0` (сбой) и
    `ok=1,empty=1` (ответ пришёл и он пуст) это разные миры, а схлопнув их, мы получили бы
    ровно тот сторож пустоты, который чиним."""
    b = box()
    ts = int(time.time())
    day = _day(ts)
    ep = str(ep or '?').strip('/')
    uid = b.get('uid')
    u = daily_u(uid, day)
    rep = _bump_rep(u, day)
    # ЦЕНА: замер дельты остатка, если он известен и вызов был ОДИН в полёте. Иначе оценка.
    d = None
    if (not cache) and (not overlap) and rem is not None and rem_before is not None \
            and parallel <= 1:
        try:
            d = int(rem_before) - int(rem)
        except (TypeError, ValueError):
            d = None
        if d is not None and (d < 0 or d > 5000):
            d = None                 # чужой вызов между замерами: выдуманная дельта хуже пустой
    # ЦЕНА: три состояния, а не два. 0 - замер (дельта остатка), 1 - оценка по таблице,
    # 2 - ЦЕНА НЕИЗВЕСТНА, и в сводке такие вызовы идут отдельной строкой.
    if cache:
        est, credits = 0, 0
    elif d is not None:
        est, credits = 0, d
    elif price_known(ep):
        est, credits = 1, est_credits(ep)
    else:
        est, credits = 2, 0
    row = {'ts': ts, 'scene': b.get('scene') or '?', 'ep': ep, 'ms': int(ms or 0),
           'http': int(http or 0), 'ok': 1 if ok else 0, 'empty': 1 if empty else 0,
           'cache': 1 if cache else 0,
           'out': _outcome_slug(cache, http, ok, empty, cls),
           'rem': rem, 'used': used, 'd': d,
           'est': est, 'cr': credits, 'u': u, 'rep': rep,
           # ПОВЕРХНОСТЬ БЕРЁТСЯ ИЗ КОРОБКИ, А НЕ ИЗ АРГУМЕНТА: её знает тот, кто открыл
           # сцену (чат/мини-апп/крон), а не клиент на дне стека.
           'srf': b.get('surface') or DEFAULT_SURFACE}
    _write(day, row)
    _ledger(day, ts, uid, row, sig)
    _track_cost(ep, credits, uid, cache)
    return row


#: КЛАСС ИСХОДА ОДНИМ СЛОВОМ - ФИКСИРОВАННЫЙ СПИСОК. Он дублирует то, что уже выводимо из
#: `ok/empty/cache/http`, и это сделано нарочно: читателю лога и сводке нужен ОДИН словарь
#: классов, иначе каждый читающий соберёт свой - и они разойдутся на первом же 402.
OUTCOMES = ('ok', 'empty', 'cache', 'http_error', 'bad_request', 'rate_limited',
            'no_credits', 'timeout', 'nokey', 'quota_user', 'unsupported')


def _outcome_slug(cache, http, ok, empty, cls=None):
    """Класс исхода одним словом для строки телеметрии. -> str.

    `cls` - УЖЕ ВЫЧИСЛЕННЫЙ класс из горловины, и он нужен ровно для одного случая: 'unsupported'
    («эндпоинт не покрывает этот актив») отличается от 'bad_request' ТОЛЬКО ТЕКСТОМ ответа, а
    сюда текст не доезжает - здесь есть лишь код. Без этого аргумента граница покрытия легла бы
    в сводку как «наш кривой запрос», и месячная строка «41 bad_request» смешала бы то, что
    чиним мы, с тем, чего у площадки нет вовсе. Решения по этим числам противоположные.
    """
    if cls == 'unsupported':
        return 'unsupported'
    if cache:
        return 'cache'
    if ok:
        return 'empty' if empty else 'ok'
    if http == 402:
        return 'no_credits'
    if http == 429:
        return 'rate_limited'
    if http in (400, 422):
        # ОТДЕЛЬНЫМ КЛАССОМ, А НЕ В ОБЩЕЙ КУЧЕ ОШИБОК: это единственный класс, который чиним
        # МЫ, а не ждём площадку. В сводке он обязан быть виден числом, иначе неверная схема
        # запроса живёт месяцами под видом «ну, иногда падает».
        return 'bad_request'
    if not http:
        return 'timeout'
    return 'http_error'


def note_quota(scene_name, uid, ep='-'):
    """ОТКАЗ ПО СУТОЧНОМУ ЛИМИТУ ЧЕЛОВЕКА - тоже строка телеметрии, и пишется она ДО обращения
    к Nansen. -> dict записанных полей.

    Без этого класса не посчитать, сколько людей упёрлось в лимит, а это главный аргумент за
    докупку кредитов: «сто человек получили отказ по лимиту» и «сто человек не пришли» с виду
    одинаковы, а решения у них противоположные. Кредитов такой отказ не стоит - в сеть мы не
    ходили, - поэтому `cr=0` и `est=0`."""
    ts = int(time.time())
    day = _day(ts)
    u = daily_u(uid, day)
    row = {'ts': ts, 'scene': scene_name if scene_name in _SCENES else '?', 'ep': ep,
           'ms': 0, 'http': 0, 'ok': 0, 'empty': 0, 'cache': 0, 'out': 'quota_user',
           'rem': None, 'used': None, 'd': None, 'est': 0, 'cr': 0,
           'u': u, 'rep': _bump_rep(u, day), 'srf': surface()}
    _write(day, row)
    return row


def _fmt(row):
    out = []
    # ПОРЯДОК КЛЮЧЕЙ ЗАФИКСИРОВАН, А `srf` ДОПИСАН В КОНЕЦ. Разбор идёт по `k=v`, поэтому
    # новая колонка в конце не ломает чтение старых файлов: у строк до этой правки её просто
    # нет, и читатель подставит значение по умолчанию. Вставь её в середину - и старые файлы
    # пришлось бы читать вторым способом.
    for k in ('ts', 'scene', 'ep', 'ms', 'http', 'ok', 'empty', 'cache', 'out', 'rem', 'used',
              'd', 'est', 'cr', 'u', 'rep', 'srf'):
        v = row.get(k)
        out.append('%s=%s' % (k, '' if v is None else v))
    return ' '.join(out)


def _write(day, row):
    try:
        os.makedirs(TELE_DIR, exist_ok=True)
        # Reputation-screen пишет до пяти address-summary параллельно. Без lock строки из
        # разных TextIO могли перемешаться, и один испорченный k=v ломал суточную сводку.
        with _LOCK:
            with open(os.path.join(TELE_DIR, '%s.log' % day), 'a', encoding='utf-8') as f:
                f.write(_fmt(row) + '\n')
    except Exception as e:
        print('[nansen_log] строка не записалась: %s' % str(e)[:120])
    _sweep()


_SWEPT = {'day': ''}


def _sweep():
    """Уборка файлов старше KEEP_DAYS. Раз в сутки на процесс, не на каждую строку."""
    today = _day()
    if _SWEPT['day'] == today:
        return
    _SWEPT['day'] = today
    try:
        edge = time.time() - KEEP_DAYS * 86400
        for nm in os.listdir(TELE_DIR):
            p = os.path.join(TELE_DIR, nm)
            if nm.endswith('.log') and os.path.getmtime(p) < edge:
                os.remove(p)
    except Exception:
        pass


def _track_cost(ep, credits, uid, cache):
    """Расход в ОБЩИЙ котёл `cost_tracker`. ПОСЛЕ фактического сетевого вызова и НЕ на кэше.

    Раньше единственная врезка стояла ДО вызова и списывала 200 кредитов даже при попадании
    в кэш, когда площадка не списала ничего.

    UID СЮДА НЕ ПЕРЕДАЁТСЯ СОЗНАТЕЛЬНО, И ЭТО НЕ ПОТЕРЯ УЧЁТА. `cost_tracker.track(uid=...)`
    пишет в `api_usage_user`, откуда `user_report` собирает ЛИЧНУЮ СЕБЕСТОИМОСТЬ человека в
    долларах. На время конкурса Nansen для человека БЕСПЛАТЕН - ни звёзд, ни списаний, - и
    показывать ему (или владельцу про него) доллары за фичу, которую мы сами попросили
    гонять, значит выставить счёт за приглашение.
    Расход при этом не исчезает и по людям тоже виден: общий котёл `api_usage` получает
    кредиты как раньше, а разрез по людям ведёт `nansen_contrib` - там и кредиты, и сценарии,
    и места. Два учёта на две задачи: котёл отвечает «сколько стоило нам», зачёт - «кто
    сколько сделал». Вернуть в личный счёт - одна строка `uid=uid or None`, если после
    конкурса Nansen станет платным для людей."""
    if cache or not credits:
        return
    try:
        import cost_tracker
        cost_tracker.track('nansen', units=credits, calls=1,
                           uid=(uid or None) if _count_user_cost() else None)
    except Exception as e:
        # ТОЖЕ ОДИН РАЗ НА ПРИЧИНУ. В боте общий учёт себестоимости есть, и тогда эта ветка не
        # срабатывает вовсе; а в публичной выжимке модуля учёта нет по определению - и строка
        # печаталась на КАЖДЫЙ вызов, превращая вывод в стену одинакового текста. Причину
        # сказать надо (молча терять учёт нельзя), но ровно один раз.
        _k = 'cost_tracker:' + type(e).__name__
        if _k not in _SAID_ONCE:
            _SAID_ONCE.add(_k)
            print('[nansen_log] cost_tracker: %s (дальше об этом молчу)' % str(e)[:100])


def _count_user_cost():
    """Считать ли Nansen в личную себестоимость человека. -> bool. Ручка админа.

    Дефолт ВЫКЛЮЧЕН, и это не «на всякий случай»: на время конкурса фича бесплатна для людей.
    Ручка нужна, чтобы после конкурса включить платность без правки кода."""
    try:
        import admin_config as _ac
        return bool(_ac.int_value(_ac.K_NANSEN_USER_COST, 0))
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# ЗАЧЁТ ВКЛАДА (B4): локальная база по настоящему uid, наружу только агрегаты
# ═══════════════════════════════════════════════════════════════════════════
def _ensure(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS nansen_contrib (
        ts INTEGER, day TEXT, user_id INTEGER, scene TEXT, ep TEXT,
        credits REAL DEFAULT 0, outcome TEXT, sig TEXT, counted INTEGER DEFAULT 1,
        cached INTEGER DEFAULT 0)''')
    # ЛЕНИВЫЙ ALTER ДЛЯ УЖЕ ЖИВОЙ ТАБЛИЦЫ: на проде она заведена без `cached`, и просто
    # поменять CREATE недостаточно - IF NOT EXISTS на существующей таблице ничего не делает,
    # а INSERT с новой колонкой упал бы. Ошибку «колонка уже есть» глотаем: это норма второго
    # запуска, а не сбой.
    try:
        conn.execute('ALTER TABLE nansen_contrib ADD COLUMN cached INTEGER DEFAULT 0')
    except Exception:
        pass
    conn.execute('CREATE INDEX IF NOT EXISTS ix_ncontrib_user ON nansen_contrib(user_id, day)')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_ncontrib_day ON nansen_contrib(day)')


def _conn():
    import db
    return db.ready('nansen_contrib', _ensure)


def sig_of(path, body):
    """Подпись запроса для антинакрутки. Сам запрос НЕ ХРАНИМ: только хэш.
    -> 12 hex."""
    try:
        s = '%s|%s' % (path, json.dumps(body, sort_keys=True, ensure_ascii=False,
                                        default=str))
    except Exception:
        s = '%s|%r' % (path, body)
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:12]


def _ledger(day, ts, uid, row, sig):
    """Запись вклада. Фоновые джобы (uid пуст) в зачёт не идут вовсе: у них нет человека.

    АКТИВНОСТЬ И РАСХОД - РАЗНЫЕ ВЕЛИЧИНЫ, И Я ИХ СКЛЕИЛ. Первая редакция ВООБЩЕ не писала
    попадания в кэш: «кэш не стоит кредитов, значит в зачёт не идёт». Для расхода это верно, а
    для активности - нет, и живой случай показал цену ошибки: человек из чата нажал Nansen на
    карточке ETH, ответ пришёл из 30-минутного кэша (кто-то спрашивал про ETH раньше),
    и он ПРОПАЛ из статистики целиком - как будто не спрашивал. Владелец считает
    активность людей, а не только деньги; «спросил и попал в кэш» это участие, а не пустота.
    Теперь пишем ВСЕ вызовы человека, а кредиты у кэша остаются нулём - и накрутка по-прежнему
    невыгодна, потому что доля считается по КРЕДИТАМ, а не по числу строк."""
    if not uid:
        return
    counted = 1
    try:
        conn = _conn()
        if sig and not row.get('cache'):
            # КЭШ ИЗ АНТИНАКРУТКИ ИСКЛЮЧЁН НАРОЧНО: он не стоит кредитов, значит накручивать им
            # нечего, а помеченный `counted=0` кэш-хит выпал бы и из активности - то есть мы
            # вернули бы ровно ту ошибку, которую этой правкой чиним.
            r = conn.execute('''SELECT MAX(ts) FROM nansen_contrib
                WHERE user_id=? AND sig=? AND cached=0''', (uid, sig)).fetchone()
            last = (r[0] if r else None) or 0
            if last and ts - int(last) < REPEAT_MIN * 60:
                counted = 0
        _out = 'ok' if row['ok'] and not row['empty'] else (
            'empty' if row['empty'] else (outcome() or 'http'))
        conn.execute('''INSERT INTO nansen_contrib
            (ts, day, user_id, scene, ep, credits, outcome, sig, counted, cached)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (ts, day, uid, row['scene'], row['ep'], row['cr'], _out, sig or '', counted,
             1 if row.get('cache') else 0))
        conn.commit()
    except Exception as e:
        print('[nansen_log] зачёт не записался: %s' % str(e)[:140])


def my_stats(uid, days=30):
    """Личная сводка человека. -> dict.

    Числа ведут ВЕЛИЧИНОЙ, а не флагом: «кредитов сожжено» и «сценариев разных» это то, из
    чего считается доля, а «вызовы есть» не измеряет ничего."""
    out = {'calls': 0, 'credits': 0.0, 'scenes': 0, 'skipped': 0, 'place': None,
           'total_people': 0, 'fails': 0, 'cached': 0}
    try:
        since = _day(time.time() - (days - 1) * 86400)
        conn = _conn()
        r = conn.execute('''SELECT COUNT(*), COALESCE(SUM(credits),0), COUNT(DISTINCT scene),
            COALESCE(SUM(cached),0)
            FROM nansen_contrib WHERE user_id=? AND day>=? AND counted=1''',
            (uid, since)).fetchone()
        if r:
            out['calls'], out['credits'], out['scenes'] = int(r[0] or 0), float(r[1] or 0), int(r[2] or 0)
            out['cached'] = int(r[3] or 0)      # сколько из них ответил кэш (бесплатно)
        r = conn.execute('''SELECT COUNT(*) FROM nansen_contrib
            WHERE user_id=? AND day>=? AND counted=0''', (uid, since)).fetchone()
        out['skipped'] = int((r or [0])[0] or 0)
        r = conn.execute('''SELECT COUNT(*) FROM nansen_contrib
            WHERE user_id=? AND day>=? AND counted=1 AND outcome NOT IN ('ok','empty')''',
            (uid, since)).fetchone()
        out['fails'] = int((r or [0])[0] or 0)
        board = _board_rows(conn, since)
        out['total_people'] = len(board)
        for i, (u2, _c, _cr, _s, _cch) in enumerate(board, 1):
            if int(u2) == int(uid):
                out['place'] = i
                break
    except Exception as e:
        print('[nansen_log] личная сводка: %s' % str(e)[:140])
    return out


def _board_rows(conn, since):
    """Отсортированный вклад по людям. Внутренняя функция: uid НАРУЖУ не отдаём."""
    rows = conn.execute('''SELECT user_id, COUNT(*), COALESCE(SUM(credits),0),
        COUNT(DISTINCT scene), COALESCE(SUM(cached),0) FROM nansen_contrib
        WHERE day>=? AND counted=1 GROUP BY user_id''', (since,)).fetchall()
    out = [(r[0], int(r[1] or 0), float(r[2] or 0), int(r[3] or 0), int(r[4] or 0))
           for r in rows]
    # порядок: кредиты, потом разнообразие сценариев, потом вызовы. Разнообразие выше
    # количества нарочно: гонять один дорогой вызов в цикле не должно быть выгоднее, чем
    # попробовать разное.
    out.sort(key=lambda x: (-x[2], -x[3], -x[1]))
    return out


def leaderboard(days=30, top=10):
    """Лидерборд БЕЗ ИМЁН И БЕЗ ID: только место и числа. -> [(место, вызовы, кредиты, сцен)].

    Ников здесь нет ни в каком виде. Ник можно показать только по явному согласию человека,
    и такого согласия мы пока не спрашивали, поэтому его нет и в выдаче."""
    try:
        since = _day(time.time() - (days - 1) * 86400)
        board = _board_rows(_conn(), since)
    except Exception as e:
        print('[nansen_log] лидерборд: %s' % str(e)[:140])
        return []
    return [(i, c, cr, s, cch) for i, (_u, c, cr, s, cch) in enumerate(board[:top], 1)]


#: окно зачёта: столько дней идёт конкурс. Меняется переменной окружения, а не правкой кода.
CONTEST_DAYS = int(os.getenv('NANSEN_CONTEST_DAYS') or 13)


def contrib_text(uid, lang='ru', days=None):
    """Личная сводка человека + лидерборд БЕЗ ИМЁН. -> str.

    Текст живёт здесь, рядом с данными, а не в `oc_dm`: считает и печатает одно и то же
    место, и разъехаться цифре с подписью тут не с чем.

    ВЕДЁМ ВЕЛИЧИНОЙ, А НЕ ФЛАГОМ (закон проекта): в строке стоят кредиты и число разных
    сценариев - то, из чего считается доля, - а не «вызовы есть». Флаг присутствия человек
    прочитал бы как «я в деле», ничего при этом не сделав."""
    days = days or CONTEST_DAYS
    st = my_stats(uid, days)
    board = leaderboard(days, top=10)
    if lang == 'en':
        L = ['🧮 <b>Your Nansen contest tally</b> (last %d days)' % days, '',
             'Your calls: <b>%d</b>' % st['calls'],
             'Your credits burned: <b>%d</b>' % int(st['credits']),
             'Distinct scenarios: <b>%d</b>' % st['scenes'],
             'Your place: <b>%s</b> of %d' % (st['place'] or '-', st['total_people'])]
        if st['skipped']:
            L.append('Not counted (same request repeated within %d min): %d'
                     % (REPEAT_MIN, st['skipped']))
        if st['fails']:
            L.append('Honest refusals you saw: %d' % st['fails'])
        L += ['', '🏅 <b>Leaderboard</b> (places only, no names):']
        for place, calls, cr, sc, _cch in board:
            mine = ' ← you' if place == st['place'] else ''
            L.append('%d. %d credits · %d scenarios · %d calls%s'
                     % (place, int(cr), sc, calls, mine))
        if not board:
            L.append('nobody has run a Nansen scenario yet')
        L += ['', '<i>No names and no IDs here or in any export: only places and numbers '
                  'leave this server. Spamming the same request does not count.</i>']
        return '\n'.join(L)
    L = ['🧮 <b>Твой зачёт по Nansen</b> (за %d дней)' % days, '',
         'Твои вызовы: <b>%d</b>' % st['calls'],
         'Твои кредиты: <b>%d</b>' % int(st['credits']),
         'Разных сценариев: <b>%d</b>' % st['scenes'],
         'Твоё место: <b>%s</b> из %d' % (st['place'] or '-', st['total_people'])]
    if st['skipped']:
        L.append('Не в зачёт (повтор того же запроса чаще %d мин): %d'
                 % (REPEAT_MIN, st['skipped']))
    if st['fails']:
        L.append('Честных отказов Nansen ты видел: %d' % st['fails'])
    L += ['', '🏅 <b>Лидерборд</b> (только места, без имён):']
    for place, calls, cr, sc, _cch in board:
        mine = ' ← ты' if place == st['place'] else ''
        L.append('%d. %d кредитов · %d сценариев · %d вызовов%s'
                 % (place, int(cr), sc, calls, mine))
    if not board:
        L.append('пока никто не запускал ни один сценарий Nansen')
    L += ['', '<i>Ни имён, ни ID здесь и ни в одной выгрузке: за пределы сервера уходят '
              'только места и числа. Накрутка одинаковых запросов в зачёт не идёт.</i>']
    return '\n'.join(L)


def owner_stats(days=None, top=30):
    """РАЗРЕЗ ПО ЛЮДЯМ ДЛЯ ВЛАДЕЛЬЦА, с именами. -> str.

    ЗАЧЕМ ОТДЕЛЬНО ОТ ЛИДЕРБОРДА. Лидерборд (`contrib_text`) идёт БЕЗ имён нарочно: он виден
    людям, и чужие ники там - это чужие данные. Владельцу в личку нужно обратное: понять, кто
    именно гоняет и на что, иначе решение о дележе приза принимается на ощупь.
    ЭТО НЕ ВЫГРУЗКА: имена живут здесь и только здесь. В `--csv`, в сводку служебного чата, в
    заявку и в посты уходят ТОЛЬКО числа и места (проверяется тестом).

    Имя берётся общей дверью `people.label` (закон №40): три копии формата подписи в этом
    проекте уже успели разойтись, и заводить четвёртую нельзя."""
    days = days or CONTEST_DAYS
    try:
        since = _day(time.time() - (days - 1) * 86400)
        conn = _conn()
        board = _board_rows(conn, since)
        rows = conn.execute('''SELECT user_id, scene, COUNT(*), COALESCE(SUM(credits),0)
            FROM nansen_contrib WHERE day>=? AND counted=1 GROUP BY user_id, scene''',
            (since,)).fetchall()
        skipped = conn.execute('''SELECT user_id, COUNT(*) FROM nansen_contrib
            WHERE day>=? AND counted=0 GROUP BY user_id''', (since,)).fetchall()
    except Exception as e:
        return 'Стата Nansen не собралась: %s' % str(e)[:160]
    if not board:
        return ('🧮 Nansen, разрез по людям за %d дней: НИ ОДНОГО вызова с человеком.\n'
                'Это не ноль расхода - фоновые джобы считаются отдельно (они без человека).'
                % days)
    _sk = dict((int(r[0]), int(r[1] or 0)) for r in skipped)
    _by_user = {}
    for r in rows:
        _by_user.setdefault(int(r[0]), []).append((r[1], int(r[2] or 0), float(r[3] or 0)))
    try:
        import people
        _info = people.info_map([int(b[0]) for b in board[:top]])
    except Exception as e:
        print('[nansen_log] имена не подтянулись (%s) - покажу id' % str(e)[:80])
        _info = {}
    L = ['🧮 <b>Nansen по людям</b> за %d дней (только для тебя, наружу не уходит)' % days, '']
    _tc = sum(b[2] for b in board)
    for i, (uid, calls, cr, scenes, cached) in enumerate(board[:top], 1):
        try:
            import people
            who = people.label(int(uid), _info)
        except Exception:
            who = 'id%s' % uid
        _share = (100.0 * cr / _tc) if _tc else 0
        # АКТИВНОСТЬ И РАСХОД РЯДОМ, НО РАЗНЫМИ ЧИСЛАМИ: человек мог спросить десять раз и
        # почти ничего не сжечь, потому что отвечал кэш. По одному числу это неотличимо от
        # «не приходил», а решения у этих случаев разные.
        L.append('%d. %s — <b>%d кр</b> (%.0f%%) · вызовов %d%s · сценариев %d'
                 % (i, who, int(cr), _share, calls,
                    (' (из кэша %d)' % cached) if cached else '', scenes))
        _mine = sorted(_by_user.get(int(uid)) or [], key=lambda x: -x[2])[:4]
        if _mine:
            L.append('    ' + ' · '.join('%s %d кр' % (sc, int(c)) for sc, _n, c in _mine))
        if _sk.get(int(uid)):
            L.append('    не в зачёт (повторы): %d' % _sk[int(uid)])
    L.append('')
    L.append('Итого по людям: %d кредитов, человек %d' % (int(_tc), len(board)))
    _cap = None
    try:
        import nansen_limits as _nl
        _cap = _nl.cap_left()
        L.append('Лимит вопросов агенту: %d/сутки на человека%s'
                 % (_nl.asks_daily(),
                    (' · общий кап: осталось %d кр' % _cap) if _cap is not None
                    else ' · общий кап выключен'))
        L.append('Считать в расходы юзера: %s' % ('ДА' if _count_user_cost() else 'нет'))
    except Exception:
        pass
    return '\n'.join(L)


def contrib_totals(days=30):
    """Агрегаты для заявки и постов: людей, вызовов, кредитов, распределение по сценариям.
    Ни одного идентификатора."""
    out = {'people': 0, 'calls': 0, 'credits': 0.0, 'by_scene': {}, 'skipped': 0}
    try:
        since = _day(time.time() - (days - 1) * 86400)
        conn = _conn()
        board = _board_rows(conn, since)
        out['people'] = len(board)
        out['calls'] = sum(b[1] for b in board)
        out['credits'] = sum(b[2] for b in board)
        out['cached'] = sum(b[4] for b in board)
        rows = conn.execute('''SELECT scene, COUNT(*), COALESCE(SUM(credits),0)
            FROM nansen_contrib WHERE day>=? AND counted=1 GROUP BY scene''',
            (since,)).fetchall()
        out['by_scene'] = dict((r[0], (int(r[1] or 0), float(r[2] or 0))) for r in rows)
        r = conn.execute('SELECT COUNT(*) FROM nansen_contrib WHERE day>=? AND counted=0',
                         (since,)).fetchone()
        out['skipped'] = int((r or [0])[0] or 0)
    except Exception as e:
        print('[nansen_log] агрегаты: %s' % str(e)[:140])
    return out


# ═══════════════════════════════════════════════════════════════════════════
# ЧТЕНИЕ ЛОГА И СУТОЧНАЯ СВОДКА
# ═══════════════════════════════════════════════════════════════════════════
def read_day(day):
    """Разобранные строки за сутки. -> [dict] | None, если файла нет.

    None и [] РАЗЛИЧАЮТСЯ НАРОЧНО: «телеметрия не собралась» и «за сутки не было ни одного
    вызова» — разные миры, и действия у них противоположные."""
    p = os.path.join(TELE_DIR, '%s.log' % day)
    if not os.path.exists(p):
        return None
    rows = []
    try:
        with open(p, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = {}
                for part in line.split(' '):
                    if '=' not in part:
                        continue
                    k, v = part.split('=', 1)
                    d[k] = v
                rows.append(d)
    except Exception as e:
        print('[nansen_log] чтение %s: %s' % (day, str(e)[:120]))
        return None
    return rows


def _i(row, key, default=0):
    v = row.get(key)
    if v in (None, ''):
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def summary(day):
    """Сводка за сутки. -> dict | None (файла нет — ВЕРДИКТА НЕТ, а не нули)."""
    rows = read_day(day)
    if rows is None:
        return None
    per = {}
    for r in rows:
        sc = r.get('scene') or '?'
        s = per.setdefault(sc, {'calls': 0, 'net': 0, 'cache': 0, 'empty': 0, 'fail': 0,
                                'ms': [], 'credits': 0.0, 'est': 0, 'unpriced': 0,
                                'users': set()})
        s['calls'] += 1
        cache = _i(r, 'cache')
        s['cache' if cache else 'net'] += 1
        if _i(r, 'empty'):
            s['empty'] += 1
        if not _i(r, 'ok'):
            s['fail'] += 1
        s['ms'].append(_i(r, 'ms'))
        if not cache:
            s['credits'] += _i(r, 'cr')
            if _i(r, 'est') == 1:
                s['est'] += 1
            elif _i(r, 'est') == 2:
                s['unpriced'] += 1
        u = r.get('u') or ''
        if u and u != 'job':
            s['users'].add(u)
    out = {'day': day, 'lines': len(rows), 'per_scene': {}}
    for sc, s in per.items():
        ms = sorted(s['ms'])
        med = ms[len(ms) // 2] if ms else 0
        out['per_scene'][sc] = {'calls': s['calls'], 'users': len(s['users']),
                                'net': s['net'], 'cache': s['cache'], 'empty': s['empty'],
                                'fail': s['fail'], 'median_ms': med, 'p95_ms': _pct(ms, 95),
                                'credits': int(s['credits']), 'est_calls': s['est'],
                                'unpriced': s['unpriced']}
    # ИТОГ СОБИРАЕТСЯ ИЗ ТЕХ ЖЕ ЧИСЕЛ, ЧТО НАПЕЧАТАНЫ ПО СЦЕНАМ, а не отдельными
    # счётчиками: оба вранья `transport_probe` пришли ровно оттуда (закон №48).
    p = out['per_scene']
    out['calls'] = sum(v['calls'] for v in p.values())
    out['net'] = sum(v['net'] for v in p.values())
    out['cache'] = sum(v['cache'] for v in p.values())
    out['empty'] = sum(v['empty'] for v in p.values())
    out['fail'] = sum(v['fail'] for v in p.values())
    out['credits'] = sum(v['credits'] for v in p.values())
    out['est_calls'] = sum(v['est_calls'] for v in p.values())
    out['unpriced'] = sum(v['unpriced'] for v in p.values())
    out['users'] = len(set(r.get('u') for r in rows if (r.get('u') or 'job') != 'job'))
    out['noscene'] = p.get('?', {}).get('calls', 0)
    # ИСХОДЫ ПО КЛАССАМ, а не только коды: «придержали по частоте», «кончились кредиты» и
    # «человек упёрся в свой суточный лимит» это три разных решения, и в одном числе «ошибок»
    # они неразличимы.
    outs = {}
    for r in rows:
        k = r.get('out') or '?'
        outs[k] = outs.get(k, 0) + 1
    out['outcomes'] = outs
    out['honest_refusals'] = sum(outs.get(k, 0) for k in
                                 ('no_credits', 'rate_limited', 'timeout', 'http_error',
                                  'bad_request', 'quota_user'))
    codes = {}
    for r in rows:
        if _i(r, 'ok') or (r.get('out') == 'quota_user'):
            continue
        codes[_i(r, 'http')] = codes.get(_i(r, 'http'), 0) + 1
    out['fail_codes'] = codes
    rem = [_i(r, 'rem', -1) for r in rows if _i(r, 'rem', -1) >= 0]
    out['rem_last'] = rem[-1] if rem else None
    # САМЫЙ ЧАСТЫЙ СЦЕНАРИЙ ДНЯ И САМЫЙ ДОРОГОЙ ЗАПРОС ДНЯ - для постов и для статьи (ТЗ C2)
    _top = sorted(p.items(), key=lambda kv: -kv[1]['calls'])
    out['top_scene'] = _top[0][0] if _top else None
    _dear = max(rows, key=lambda r: _i(r, 'cr')) if rows else None
    out['dearest'] = ({'scene': _dear.get('scene'), 'ep': _dear.get('ep'),
                       'credits': _i(_dear, 'cr')} if _dear and _i(_dear, 'cr') else None)
    out['p95_ms'] = _pct(sorted(_i(r, 'ms') for r in rows), 95)
    return out


def _pct(vals, pct):
    """Персентиль по отсортированному списку. -> int.

    p95 рядом с медианой нужен потому, что медиана прячет хвост: у агента она 8 секунд, а
    хвост уходит за минуту, и человек в чате видит именно хвост."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return 0
    vals = sorted(vals)
    i = int(round((pct / 100.0) * (len(vals) - 1)))
    return int(vals[max(0, min(i, len(vals) - 1))])


def daily_text(day=None):
    """Суточная сводка ТЕКСТОМ (для служебного чата и для tools/nansen_daily.py)."""
    day = day or _day(time.time() - 86400)
    s = summary(day)
    if s is None:
        return ('Nansen, сутки %s: ВЕРДИКТА НЕТ — файла телеметрии нет (%s).\n'
                'Ноль запросов и несобравшаяся телеметрия по нулям неразличимы, а действия '
                'у них противоположные.' % (day, os.path.join(TELE_DIR, '%s.log' % day)))
    if not s['lines']:
        return 'Nansen, сутки %s: ВЕРДИКТА НЕТ — файл есть, но он пуст.' % day
    L = ['Nansen, сутки %s (строк %d)' % (day, s['lines']), '', 'По сценариям:',
         '  %-22s %7s %6s %5s %5s %6s %5s %8s %7s %9s'
         % ('сцена', 'запрос', 'уник', 'сеть', 'кэш', 'пусто', 'сбой', 'мед.мс',
            'p95 мс', 'кредитов')]
    for sc, v in sorted(s['per_scene'].items(), key=lambda kv: -kv[1]['calls']):
        nm = 'БЕЗ СЦЕНЫ' if sc == '?' else sc
        L.append('  %-22s %7d %6s %5d %5d %6d %5d %8d %7d %9d'
                 % (nm, v['calls'], v['users'] or '-', v['net'], v['cache'], v['empty'],
                    v['fail'], v['median_ms'], v['p95_ms'], v['credits']))
    if '?' not in s['per_scene']:
        # печатается ВСЕГДА, даже нулём: молча пропавшая строка и «контекст везде
        # проставлен» - разные вещи (закон №16)
        L.append('  %-22s %7d %6s %5d %5d %6d %5d %8d %7d %9d'
                 % ('БЕЗ СЦЕНЫ', 0, '-', 0, 0, 0, 0, 0, 0, 0))
    L.append('')
    _cpct = int(100.0 * s['cache'] / s['calls']) if s['calls'] else 0
    L.append('Итого: запросов %d, по сети %d (кэш снял %d%%)' % (s['calls'], s['net'], _cpct))
    L.append('Уникальных за сутки: %d' % s['users'])
    L.append('Кредитов за сутки: %d (замером %d вызовов, по таблице %d)'
             % (s['credits'], max(0, s['net'] - s['est_calls'] - s['unpriced']),
                s['est_calls']))
    if s['unpriced']:
        # ЦЕНА НЕ ВЫДУМЫВАЕТСЯ. Строка «столько-то вызовов с неизвестной ценой» полезнее
        # красивой суммы из догадок: она называет, чего мы не знаем, и её закрывает один
        # взгляд в Usage Analytics.
        L.append('ВЫЗОВОВ С НЕИЗВЕСТНОЙ ЦЕНОЙ: %d — в сумму выше они вошли НУЛЁМ. Цена этих '
                 'эндпоинтов в докстрингах не написана; закрывается Usage Analytics.'
                 % s['unpriced'])
    if s['rem_last'] is not None:
        L.append('Остаток по заголовку последнего ответа: %d' % s['rem_last'])
    L.append('Латентность по всем вызовам: p95 %d мс' % s['p95_ms'])
    if s['fail_codes']:
        L.append('Сбоев: %d (%s)' % (s['fail'], ', '.join(
            '%s: %d' % ('таймаут/сеть' if k == 0 else k, v)
            for k, v in sorted(s['fail_codes'].items()))))
    else:
        L.append('Сбоев: 0')
    L.append('Честных отказов человеку: %d (%s)'
             % (s['honest_refusals'],
                ', '.join('%s: %d' % (k, v) for k, v in sorted(s['outcomes'].items())
                          if k in ('no_credits', 'rate_limited', 'timeout', 'http_error',
                                   'bad_request', 'quota_user')) or 'ни одного'))
    L.append('Пустых ответов при успешном запросе: %d' % s['empty'])
    if s['top_scene']:
        L.append('Самый частый сценарий дня: %s'
                 % ('БЕЗ СЦЕНЫ' if s['top_scene'] == '?' else s['top_scene']))
    if s['dearest']:
        L.append('Самый дорогой запрос дня: %s (%s) — %d кредитов'
                 % (s['dearest']['scene'], s['dearest']['ep'], s['dearest']['credits']))
    if s['noscene']:
        L.append('ВНИМАНИЕ: %d вызовов без сцены — где-то забыт контекст.' % s['noscene'])
    return '\n'.join(L)


def _seed_flight():
    """Холодный старт: «предыдущий известный остаток» берём с диска, иначе первая дельта
    после каждого рестарта была бы пустой и первый вызов считался бы оценкой."""
    try:
        r = credits_read().get('remaining')
        if isinstance(r, int):
            _FLIGHT['rem'] = r
    except Exception:
        pass


_seed_flight()


def csv_rows(days):
    """Выгрузка для сабмишена и статьи. Колонки ТОЛЬКО числовые: поля `u` здесь нет ни в
    каком виде, и это проверяется тестом."""
    head = ['day', 'scene', 'calls', 'users', 'net', 'cache', 'empty', 'fail',
            'median_ms', 'p95_ms', 'credits', 'unpriced_calls']
    out = [head]
    for d in days:
        s = summary(d)
        if s is None:
            continue
        for sc, v in sorted(s['per_scene'].items()):
            out.append([d, 'no_scene' if sc == '?' else sc, v['calls'], v['users'],
                        v['net'], v['cache'], v['empty'], v['fail'], v['median_ms'],
                        v['p95_ms'], v['credits'], v['unpriced']])
    return out
