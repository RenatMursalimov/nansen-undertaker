# -*- coding: utf-8 -*-
"""nansen_scene.py — СЛОЙ «СЦЕНА → СЛОВАРЬ». Один источник чисел для текста бота и мини-аппа.

ЗАКОН 0: МИНИ-АПП НЕ СЧИТАЕТ, МИНИ-АПП РИСУЕТ.

Каждый экран мини-аппа получает ТОТ ЖЕ словарь, из которого бот строит свой текстовый ответ.
Не второй форматтер, не своя логика, не свои пороги.

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ФУНКЦИЯ В КАЖДОМ ЭКРАНЕ. Порог 40% винрейта, правило
«неизвестная история не считается ни в одну сторону», подпись «это не прогноз», цена экрана в
запросах - всё это утверждения, за которые отвечает ОДНО место. Продублируй их в мини-аппе, и
на первой правке текст бота и картинка разойдутся МОЛЧА: бот скажет 58%, экран нарисует 61%, и
увидит это жюри, а не мы. Этот класс бага в проекте ловили трижды (китайский словарь, публичная
выжимка, обработчик кнопки со своей копией разбора), поэтому здесь он закрыт архитектурно:
считает `*_data`, рисуют двое.

ЧТО ЗДЕСЬ ЕСТЬ, А ЧЕГО НЕТ
  * есть: конверт сцены (числа + служебные поля), диспетчер по имени сцены, `rendered_text` -
    ровно та фраза, которую человек увидел бы в чате;
  * нет: HTTP, авторизации, лимитов. Они на слое шлюза (`worker_bridge`), потому что этот
    модуль зовут и из бота, и из инструментов, и из тестов - без сети.

СЛУЖЕБНЫЕ ПОЛЯ КОНВЕРТА, И ПОЧЕМУ КАЖДОЕ ОБЯЗАТЕЛЬНО
  `source`             - имя источника. В текстах проекта называется ОДИН источник, и экран
                         без подписи источника выглядит как наше собственное знание.
  `freshness_seconds`  - сколько секунд назад снято. Цифра без времени на торговых данных
                         бесполезна: «58%» минуту назад и сутки назад - разные утверждения.
  `cost_requests`      - сколько запросов стоил экран. Всегда известно.
  `cost_credits`       - кредиты, если цена НАЗВАНА официальным списком, иначе None. None
                         означает «цена не названа», и мини-апп обязан показать запросы, а не
                         выдумывать кредиты (та же честность, что в каталоге).
  `outcome`            - одно из восьми состояний (`nansen_api` их и определяет). Мини-апп
                         рисует СОСТОЯНИЕ, а не пустой график: шесть нулевых столбиков
                         выглядят как измерение и врут сильнее, чем отсутствие картинки.
  `caveats`            - список оговорок величинами («по 2 держателям истории нет»). Считается
                         из тех же чисел, поэтому не может отстать от заголовка.
  `payload`            - сами числа сцены. None при отказе.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_OC = os.path.join(ROOT, 'onchain')
if _OC not in sys.path:
    sys.path.insert(0, _OC)

#: СЦЕНЫ, ДОСТУПНЫЕ ЧЕРЕЗ ЭТОТ СЛОЙ. Закрытый список, как реестр сцен телеметрии: имя вне
#: списка не обслуживается, а не «наверное сработает». Ключ = имя сцены телеметрии, поэтому
#: расход мини-аппа складывается с расходом чата по ОДНОЙ сцене (мини-апп - новая ПОВЕРХНОСТЬ
#: старой сцены, а не новая сцена).
SCENES = ('pm_markets', 'pm_reputation', 'liq_map', 'smart_trades')

#: ПОВЕРХНОСТИ. 'chat' - ответ в Telegram-чате, 'miniapp' - экран мини-аппа.
SURFACES = ('chat', 'miniapp')


def _n():
    import nansen_api as N
    return N


def _tele():
    import nansen_log as T
    return T


def _viz():
    import oc_nansen_viz as V
    return V


def _envelope(scene, payload, outcome, lang='ru', cost_requests=0, cost_credits=None,
              freshness_seconds=None, caveats=(), refusal_what=None, extra=None):
    """Собрать конверт сцены. -> dict.

    `outcome` == 'ok' - есть payload. Иначе payload None, а `refusal` несёт человеческую
    причину ИЗ ТОГО ЖЕ канала, что у бота (`nansen_api.refusal`): два текста на одну причину
    разошлись бы, и мини-апп однажды сказал бы «данных нет» там, где кончились кредиты.
    """
    env = {
        'scene': scene,
        'outcome': outcome,
        'source': 'Nansen',
        'freshness_seconds': freshness_seconds,
        'cost_requests': int(cost_requests or 0),
        'cost_credits': cost_credits,
        'caveats': [c for c in (caveats or ()) if c],
        'payload': payload,
        'lang': 'en' if lang == 'en' else 'ru',
    }
    if outcome != 'ok':
        env['refusal'] = _n().refusal(outcome, env['lang'], what=refusal_what)
    if extra:
        env.update(extra)
    return env


def _credits_for(eps):
    """Кредиты экрана, если цена НАЗВАНА официальным списком. -> int | None.

    None означает «цена не названа» и это не уклонение: придуманное число кредитов в экране,
    по которому человек принимает решение, было бы ложью в самом проверяемом месте. Если хотя
    бы у одного эндпоинта экрана цены нет, у экрана её тоже нет - складывать известное с
    неизвестным и печатать сумму значит выдавать догадку за замер.
    """
    T = _tele()
    total = 0
    for ep in eps:
        if not T.price_known(ep):
            return None
        total += int(T.est_credits(ep) or 0)
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# СЦЕНА 0. pm_markets - ВХОД В HERO. Список рынков, по которому человек ТАПАЕТ
#
# ЗАЧЕМ ЭТА СЦЕНА ПОЯВИЛАСЬ ОТДЕЛЬНО. Первая редакция мини-аппа просила ввести `market_id`
# руками, и это неверно по существу: чтобы узнать id, человеку пришлось бы идти на Polymarket и
# выискивать идентификатор - то есть экран требовал работы ВНЕ себя. Идентификатор вообще не
# должен попадать человеку на глаза: он служебный, его дело - ездить между экранами.
# Тот же дефект уже ловили в чате: команды «полимаркет график <id>» существовали формально,
# пока список рынков не начал печатать id, - и лечение было такое же, списком с кнопками.
# ═══════════════════════════════════════════════════════════════════════════════
def pm_markets_data(lang='ru', top=12, rows=None):
    """Трендовые рынки Polymarket с id для перехода. -> конверт.

    ЧЕЛОВЕК ВИДИТ ВОПРОС И ВЕРОЯТНОСТЬ, А НЕ НОМЕР. Номер едет в словаре отдельным полем,
    чтобы экран повесил его на тап, - ровно как кнопки «🎭 N» под списком в чате.
    """
    N = _n()
    if rows is None:
        rows = N.pm_market_screener(per_page=int(top))
    _what = ('рынков Polymarket' if lang != 'en' else 'Polymarket markets')
    _cr = _credits_for(('prediction-market/market-screener',))
    if not rows:
        return _envelope('pm_markets', None, N.fail_reason('empty'), lang, cost_requests=1,
                         cost_credits=_cr, refusal_what=_what)
    out, no_id = [], 0
    for r in rows[:int(top)]:
        if not isinstance(r, dict):
            continue
        _mid = N.pm_market_id(r)
        if not _mid:
            # РЫНОК БЕЗ ID НЕ ВЫБРАСЫВАЕТСЯ МОЛЧА: он попадёт в список без тапа, и это
            # названо числом ниже. Тихо убрать его значило бы показать список короче, чем он
            # есть, и человек не понял бы, почему.
            no_id += 1
        _pr = N._num_or_none(r.get('last_trade_price'))
        out.append({'id': str(_mid or ''), 'q': str(r.get('question') or '?')[:120],
                    'prob': (round(_pr * 100) if (_pr is not None and _pr <= 1) else
                             (round(_pr) if _pr is not None else None)),
                    'vol24': N._num_or_none(r.get('volume_24hr'))})
    if not out:
        return _envelope('pm_markets', None, N.fail_reason('empty'), lang, cost_requests=1,
                         cost_credits=_cr, refusal_what=_what)
    _cav = []
    if no_id:
        _cav.append(('%d market(s) came without an id: they cannot be opened by a tap'
                     if lang == 'en' else
                     'у %d рынк(ов) не приехал id: по тапу их не открыть') % no_id)
    _cav.append('price is what people believe, not what is true' if lang == 'en' else
                'цена это во что верят, а не то, что верно')
    return _envelope('pm_markets', {'rows': out, 'no_id': no_id}, 'ok', lang,
                     cost_requests=1, cost_credits=_cr, freshness_seconds=_tele().age(),
                     caveats=_cav)


# ═══════════════════════════════════════════════════════════════════════════════
# СЦЕНА 1. pm_reputation - hero. «Чьи 90%»
# ═══════════════════════════════════════════════════════════════════════════════
def pm_reputation_data(market_id, top=None, lang='ru'):
    """Кто держит рынок и как угадывал раньше. -> конверт.

    Числа целиком считает `nansen_api.pm_reputation`: порог винрейта, доли × цена, серые
    держатели. Здесь только конверт - иначе порог оказался бы в двух местах.
    """
    N = _n()
    _top = int(top or N.PM_REP_TOP)
    rep = N.pm_reputation(market_id, _top)
    if not rep:
        _what = ('держателей этого рынка' if lang != 'en' else 'holders of this market')
        return _envelope('pm_reputation', None, N.fail_reason('empty'), lang,
                         cost_requests=1, cost_credits=_credits_for(
                             ('prediction-market/top-holders',)),
                         refusal_what=_what)
    return _envelope('pm_reputation', rep, 'ok', lang,
                     cost_requests=int(rep.get('calls') or 0),
                     cost_credits=_credits_for(('prediction-market/top-holders',
                                                'prediction-market/address-summary')),
                     freshness_seconds=rep.get('age_sec'),
                     caveats=_pm_caveats(rep, _top, lang),
                     extra={'threshold_weak_wr': N.PM_WEAK_WR, 'top': _top,
                            'market_id': str(market_id)})


def _pm_caveats(rep, top, lang):
    """Оговорки hero величинами, из тех же чисел, что заголовок. -> [str].

    ГЛАВНАЯ ИЗ НИХ - ПРО СЕРЫХ ДЕРЖАТЕЛЕЙ. Их деньги не попадают ни в одну сторону, и это
    надо сказать ЧИСЛОМ, а не умолчать: «разобрано 5 из 10» и «разобрано 10 из 10» - разные
    утверждения, и на втором вывод сильнее.
    """
    en = (lang == 'en')
    out = []
    _nat = int(rep.get('no_history') or 0) + int(rep.get('no_winrate') or 0)
    if _nat:
        out.append(('%d holder(s) have no measurable win rate - their money is counted on '
                    'NEITHER side' if en else
                    'по %d держател(ям) нет измеримого винрейта - их деньги НЕ посчитаны ни в '
                    'одну сторону') % _nat)
    if rep.get('failed'):
        out.append(('history for %d holder(s) was NOT delivered due to a failure - our '
                    'partial response, not a property of those wallets' if en else
                    'история %d держател(ей) НЕ приехала из-за сбоя - это наш неполный ответ, '
                    'а не свойство кошельков') % int(rep['failed']))
    if rep.get('unexamined'):
        out.append(('%d more holder(s) were not examined: this screen caps wallet history '
                    'lookups at %d' if en else
                    'ещё %d держател(ей) не разобраны из-за лимита %d историй на один экран')
                   % (int(rep['unexamined']), int(top)))
    if any(h.get('shares') and h.get('px') for h in (rep.get('holders') or [])[:int(top)]):
        out.append('dollars are computed as shares × current price: the response has no ready '
                   'total' if en else
                   'доллары посчитаны как доли × текущая цена: готовой суммы в ответе нет')
    out.append('past win rate does not promise the future: this is the composition of the '
               'money, not a forecast or advice' if en else
               'винрейт в прошлом не обещает будущего: это состав денег, а не прогноз и не '
               'совет')
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# СЦЕНА 2. liq_map - где висит чужое плечо
# ═══════════════════════════════════════════════════════════════════════════════
def liq_map_data(token, mark=None, lang='ru', rows=None):
    """Карта ликвидаций по перп-токену. -> конверт.

    `mark` (текущая цена) НЕОБЯЗАТЕЛЕН и передаётся снаружи: он приезжает не из Nansen, а с
    Hyperliquid, и его сбой не имеет права рушить карту. Без него карта остаётся честной
    картой уровней, просто без отметки «мы здесь»; выдуманная цена дала бы отметку, которой
    никто не мерил.
    """
    N, V = _n(), _viz()
    _tok = str(token or '').upper()[:12]
    if rows is None:
        rows = N.perp_positions(_tok, 50)
    _what = (('позиций с плечом по %s' % _tok) if lang != 'en'
             else ('leveraged positions on %s' % _tok))
    _cr = _credits_for(('tgm/perp-positions',))
    if not rows:
        return _envelope('liq_map', None, N.fail_reason('empty'), lang, cost_requests=1,
                         cost_credits=_cr, refusal_what=_what)
    cl = V.liq_clusters(rows, mark)
    if not cl:
        # СТРОКИ ЕСТЬ, А ЦЕН ЛИКВИДАЦИИ В НИХ НЕТ - это расхождение схемы, а не «пусто».
        # Отдаём отдельным состоянием: иначе человек прочтёт отсутствие карты как отсутствие
        # плеча, то есть пустоту как измерение.
        return _envelope('liq_map', None, 'badreq', lang, cost_requests=1, cost_credits=_cr,
                         refusal_what=_what,
                         extra={'token': _tok,
                                'schema_gap': N.schema_gap_note(
                                    rows[0] if isinstance(rows[0], dict) else {},
                                    'Цена ликвидации' if lang != 'en' else 'Liquidation price',
                                    lang)})
    return _envelope('liq_map', cl, 'ok', lang, cost_requests=1, cost_credits=_cr,
                     freshness_seconds=_tele().age(),
                     caveats=_liq_caveats(cl, lang),
                     extra={'token': _tok})


def _liq_caveats(cl, lang):
    """Оговорки карты величинами. -> [str]."""
    en = (lang == 'en')
    out = []
    if cl.get('no_liq'):
        out.append(('%d position(s) had no liquidation price and are NOT on the map' if en else
                    'у %d позиц(ий) цены ликвидации не было - их на карте НЕТ')
                   % int(cl['no_liq']))
    if cl.get('mark') is None:
        out.append('current price did not load: the map has no "you are here" marker' if en else
                   'текущая цена не взялась: на карте нет отметки «мы здесь»')
    # МЕТКИ КОШЕЛЬКОВ НАЗЫВАЕМ ЧИСЛОМ В ОБЕ СТОРОНЫ. Ноль здесь - тоже ответ: «Nansen не знает
    # по имени никого из этой карты» и «мы не спрашивали про имена» человек прочтёт одинаково,
    # если промолчать, а это разные утверждения.
    if not (cl.get('named') or 0):
        out.append('no wallet on this map has a Nansen label: the named-money bar is absent '
                   'because there is none, not because it was not asked for' if en else
                   'ни у одного кошелька на карте нет метки Nansen: полосы «деньги с меткой» '
                   'нет потому, что их нет, а не потому, что мы не спросили')
    out.append('these are where other people stop out, not a forecast' if en else
               'это уровни чужих стопов, а не прогноз')
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# СЦЕНА 3. smart_trades - что берут прямо сейчас и какая это доля капитализации
# ═══════════════════════════════════════════════════════════════════════════════
def smart_trades_data(lang='ru', top=12, rows=None):
    """Сделки smart money за сутки + доля от капитализации. -> конверт."""
    N = _n()
    if rows is None:
        rows = N.sm_dex_trades(None, 15)
    _what = ('сделок smart money' if lang != 'en' else 'smart money trades')
    _cr = _credits_for(('smart-money/dex-trades',))
    d = N.sm_trades_data(rows, top) if rows else None
    if not d:
        return _envelope('smart_trades', None, N.fail_reason('empty'), lang, cost_requests=1,
                         cost_credits=_cr, refusal_what=_what)
    return _envelope('smart_trades', d, 'ok', lang, cost_requests=1, cost_credits=_cr,
                     freshness_seconds=_tele().age(),
                     caveats=_sm_caveats(d, lang),
                     extra={'pct_min': N.MCAP_PCT_MIN})


def _sm_caveats(d, lang):
    """Оговорки сделок. -> [str]."""
    en = (lang == 'en')
    out = []
    if d.get('shown') and not d.get('with_val'):
        out.append('trade size did not arrive in any row: this is a schema gap, not a property '
                   'of the trades' if en else
                   'объём сделки не приехал ни в одной строке: это расхождение схемы, а не '
                   'свойство сделок')
    _no_mc = sum(1 for r in d['rows'] if r.get('mcap_num') in (None, 0))
    if _no_mc:
        out.append(('%d row(s) have no market cap: the share of mcap is not computed for them'
                    if en else
                    'у %d строк(и) нет капитализации: доля от капы для них не посчитана')
                   % _no_mc)
    out.append('a share of market cap is the magnitude, the dollar amount alone is not' if en
               else 'величина здесь - доля от капитализации, а не сама сумма в долларах')
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# ДИСПЕТЧЕР И РЕНДЕР
# ═══════════════════════════════════════════════════════════════════════════════
#: КАКИЕ ПАРАМЕТРЫ ЖДЁТ СЦЕНА. Нужен шлюзу, чтобы отказать по форме ДО любого вызова Nansen.
SCENE_PARAMS = {
    'pm_markets': (),
    'pm_reputation': ('market',),
    'liq_map': ('token',),
    'smart_trades': (),
}


def rendered_text(env, bot_un=None):
    """Ровно та фраза, которую человек увидел бы в чате. -> str | None.

    ЗАЧЕМ ЭТО В КОНВЕРТЕ. Мини-апп показывает её под графиком, и человек может сверить
    картинку со словами. Если бы экран писал свою подпись, расхождение стало бы невидимым.
    """
    if not env:
        return None
    if env.get('outcome') != 'ok':
        return env.get('refusal')
    N, sc, lang = _n(), env.get('scene'), env.get('lang', 'ru')
    p = env.get('payload')
    if sc == 'pm_markets':
        # Текстовый рендер списка у бота уже есть и принимает СЫРЫЕ строки скринера. Здесь он
        # не нужен: список в мини-аппе - это навигация, а не ответ, и подписывать её фразой
        # бота незачем. Отдаём None честно, а не собираем текст, которого бот не пишет.
        return None
    if sc == 'pm_reputation':
        return N.pm_reputation_block(p, env.get('market_id') or '', lang,
                                     env.get('top') or N.PM_REP_TOP)
    if sc == 'liq_map':
        return _viz().liq_caption(p, env.get('token') or '', lang)
    if sc == 'smart_trades':
        # РЕНДЕР ПОЛУЧАЕТ ГОТОВЫЙ СЛОВАРЬ, а не сырые строки: так текст и экран физически
        # читают одни и те же числа, без пересчёта.
        return N.sm_trades_block(p, bot_un, lang)
    return None


def scene_data(scene, params=None, lang='ru', bot_un=None, with_text=True):
    """ЕДИНАЯ ДВЕРЬ: имя сцены + параметры -> конверт (+ `rendered_text`). -> dict.

    Сцена вне закрытого списка не обслуживается: неизвестное имя это отказ по форме, а не
    «попробуем и посмотрим». Телеметрию ставит ВЫЗЫВАЮЩИЙ (шлюз/бот), потому что только он
    знает человека и поверхность.
    """
    params = params or {}
    if scene not in SCENES:
        return {'scene': str(scene)[:40], 'outcome': 'badreq', 'source': 'Nansen',
                'freshness_seconds': None, 'cost_requests': 0, 'cost_credits': 0,
                'caveats': [], 'payload': None, 'lang': 'en' if lang == 'en' else 'ru',
                'refusal': ('Unknown screen.' if lang == 'en' else 'Неизвестный экран.')}
    if scene == 'pm_markets':
        env = pm_markets_data(lang, int(params.get('top') or 12))
    elif scene == 'pm_reputation':
        env = pm_reputation_data(params.get('market'), params.get('top'), lang)
    elif scene == 'liq_map':
        env = liq_map_data(params.get('token'), params.get('mark'), lang)
    else:
        env = smart_trades_data(lang, int(params.get('top') or 12))
    if with_text:
        try:
            env['rendered_text'] = rendered_text(env, bot_un)
        except Exception as e:                      # noqa: BLE001
            # ПОДПИСЬ НЕ СОБРАЛАСЬ - ЭКРАН ВСЁ РАВНО ЕДЕТ, но молчать об этом нельзя.
            print('[nansen_scene] rendered_text %s: %s: %s'
                  % (scene, type(e).__name__, str(e)[:120]))
            env['rendered_text'] = None
    return env
