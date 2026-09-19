# -*- coding: utf-8 -*-
"""oc_nansen_viz.py — картинки по данным Nansen (визуализация, пункт хакатона).

ЗАЧЕМ КАРТИНКА, ЕСЛИ ЕСТЬ ТЕКСТ. Текстовая строка «🧠SM +$231.9K · 🐳киты -$88.1K · 🏦биржи
+$12.4K» отвечает на вопрос «сколько», но не отвечает на «кто против кого». Ровно этот вопрос
и задают, глядя на потоки: важно не абсолютное число, а то, что умные деньги набирают, пока
киты сливают. На столбиках это видно за полсекунды, в строке - после чтения и сравнения в
голове.

СТИЛЬ БЕРЁТСЯ ИЗ oc_chart, А НЕ ЗАВОДИТСЯ СВОЙ. Там уже выбраны фон карточек, шрифт с
кириллицей (Oswald) и палитра; вторая палитра рядом означала бы, что через месяц у нас два
разных «фирменных» вида на соседних экранах.

ЧЕГО ЗДЕСЬ НЕТ: своих запросов к Nansen. Данные приходят аргументом от вызывающего, который
уже поставил сцену телеметрии и обработал отказ. Картинка - это представление, и ходить за
данными она не должна: иначе один экран сходил бы в API дважды, а отказ пришлось бы
обрабатывать в двух местах по-разному.
"""

import os
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: подписи сегментов: ключ ответа Nansen -> (RU, EN, цвет-резерв). Порядок задаёт порядок
#: столбцов. ЦВЕТ СТОЛБИКА БЕРЁТСЯ НЕ ОТСЮДА, а от знака потока (см. flows_png): цвет,
#: означающий сегмент, врал про направление. Поле оставлено для легенды, где сегменты правда
#: надо различать между собой.
_SEGMENTS = (
    ('smart_trader',  'Smart Money', 'Smart Money', '#2ea043'),
    ('whale',         'Киты',        'Whales',      '#58a6ff'),
    ('top_pnl',       'Топ по PnL',  'Top PnL',     '#a371f7'),
    ('public_figure', 'Публ. фигуры', 'Public figs', '#d29922'),
    ('exchange',      'Биржи',       'Exchanges',   '#f85149'),
    ('fresh_wallets', 'Свежие',      'Fresh',       '#8b949e'),
)


def _style():
    """Общий стиль карточек. Импорт внутри функции: matplotlib тяжёлый, и модуль обязан
    импортироваться даже там, где картинки не рисуют."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


def _font():
    """Шрифт с кириллицей из assets. Без него подписи станут квадратиками, и картинка
    окажется бесполезной ровно на русском - то есть у большинства наших людей."""
    try:
        from matplotlib import font_manager
        p = os.path.join(_ROOT, 'assets', 'fonts', 'Oswald.ttf')
        if os.path.exists(p):
            font_manager.fontManager.addfont(p)
            return font_manager.FontProperties(fname=p)
    except Exception as e:
        print('[viz] шрифт не подхватился (%s) - подписи возможны квадратиками' % str(e)[:80])
    return None


def _num(x):
    try:
        v = float(x)
        return v if v == v else None      # NaN отсекаем
    except (TypeError, ValueError):
        return None


def _short(v):
    a = abs(v)
    if a >= 1e9:
        return '%.1fB' % (v / 1e9)
    if a >= 1e6:
        return '%.1fM' % (v / 1e6)
    if a >= 1e3:
        return '%.0fK' % (v / 1e3)
    return '%.0f' % v


def flows_png(flow, symbol='', chain='', lang='ru', out_dir=None):
    """Столбики нетто-потоков по сегментам холдеров. -> (путь_к_png, подпись) | (None, причина).

    `flow` - строка ответа `tgm/flow-intelligence` (та же, что уже используется текстом).

    ПУСТОТА НЕ РИСУЕТСЯ. Картинка с шестью нулевыми столбиками выглядит как измерение и врёт
    сильнее, чем отсутствие картинки: человек читает «потоков нет», хотя мы просто не получили
    данных. Нет ни одного значимого сегмента - возвращаем причину словом, и вызывающий скажет
    её текстом.
    """
    if not isinstance(flow, dict):
        return None, 'empty'
    vals = []
    for key, ru, en, color in _SEGMENTS:
        v = _num(flow.get('%s_net_flow_usd' % key))
        if v is None or abs(v) < 1000:      # мелочь ниже $1K - шум, а не сигнал
            continue
        vals.append(((ru if lang != 'en' else en), v, color))
    if not vals:
        return None, 'empty'

    plt = _style()
    fp = _font()
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=170)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')

    names = [v[0] for v in vals]
    nums = [v[1] for v in vals]
    # ЦВЕТ ОЗНАЧАЕТ ЗНАК, А НЕ СЕГМЕНТ - И ЭТО НЕ ВКУСОВЩИНА. Первая редакция красила столбик
    # цветом сегмента (биржи - красным по палитре), и приток $12K на биржи выглядел ровно как
    # отток: человек читал «биржи сливают» на данных «биржи набирают». Картинка врала тем же
    # способом, каким врут тексты, которые мы в этой работе и чиним, - только молча и быстрее,
    # потому что цвет считывается раньше подписи.
    colors = ['#2ea043' if v >= 0 else '#f85149' for v in nums]
    bars = ax.bar(range(len(nums)), nums, color=colors, width=0.62)

    # НОЛЬ - ЯВНАЯ ЛИНИЯ. На потоках знак и есть весь смысл: без оси нуля «плюс» и «минус»
    # различаются только направлением столбика, а это читается хуже, чем кажется.
    ax.axhline(0, color='#8b949e', linewidth=1.0, alpha=0.8)

    for i, (b, v) in enumerate(zip(bars, nums)):
        _va = 'bottom' if v >= 0 else 'top'
        _off = (max(map(abs, nums)) * 0.03) * (1 if v >= 0 else -1)
        ax.text(i, v + _off, ('+$' if v >= 0 else '-$') + _short(abs(v)),
                ha='center', va=_va, color='#c9d1d9', fontsize=9,
                fontproperties=fp)

    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, color='#c9d1d9', fontsize=9, fontproperties=fp)
    ax.tick_params(axis='y', colors='#8b949e', labelsize=8)
    # ОСЬ В ДЕНЬГАХ, А НЕ В «300000»: подпись оси читают глазом мимоходом, и шесть нулей
    # заставляют считать разряды вместо того, чтобы смотреть на картинку.
    try:
        from matplotlib.ticker import FuncFormatter
        ax.yaxis.set_major_formatter(FuncFormatter(
            # МИНУС ПЕРЕД ЗНАКОМ ВАЛЮТЫ, а не после: «$-100K» это не запись суммы, а опечатка
            lambda v, _p: ('' if v == 0 else
                           (('-$%s' if v < 0 else '$%s') % _short(abs(v))))))
    except Exception as _fe:
        print('[viz] формат оси не применён: %s' % str(_fe)[:80])
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color('#30363d')
    ax.grid(axis='y', color='#30363d', alpha=0.35, linewidth=0.6)
    ax.margins(y=0.22)

    _t = ('Потоки за 24ч по сегментам' if lang != 'en' else 'Net flows 24h by segment')
    _head = '%s%s · %s' % (('%s · ' % symbol) if symbol else '', _t, chain or '')
    ax.set_title(_head, color='#e6edf3', fontsize=12, pad=12, fontproperties=fp)
    # ИСТОЧНИК НА САМОЙ КАРТИНКЕ. Картинку пересылают без сообщения, и подпись из текста при
    # пересылке теряется - а на конкурсе Nansen источник обязан быть назван.
    fig.text(0.99, 0.02, 'Nansen', ha='right', color='#8b949e', fontsize=8,
             fontproperties=fp)
    fig.tight_layout()

    out_dir = out_dir or tempfile.gettempdir()
    path = os.path.join(out_dir, 'nansen_flows_%s_%d.png'
                        % ((symbol or 'tok').replace('/', '_')[:12], int(time.time())))
    try:
        plt.savefig(path, facecolor='#0d1117')
    except Exception as e:
        print('[viz] потоки не сохранились: %s' % str(e)[:120])
        plt.close(fig)
        return None, 'http'
    plt.close(fig)

    _pos = [v for v in nums if v > 0]
    _neg = [v for v in nums if v < 0]
    if lang == 'en':
        cap = ('Net flows 24h%s. Buying: %d segments, selling: %d. Source: Nansen.'
               % ((' · %s' % symbol) if symbol else '', len(_pos), len(_neg)))
    else:
        cap = ('Потоки за 24ч%s. Набирают: %d сегментов, сливают: %d. Источник: Nansen.'
               % ((' · %s' % symbol) if symbol else '', len(_pos), len(_neg)))
    return path, cap


def pm_probability_png(rows, question='', lang='ru', out_dir=None):
    """Вероятность рынка Polymarket во времени. -> (путь, подпись) | (None, причина).

    `rows` - ответ `prediction-market/ohlcv` (часовые свечи рынка).

    ЭТО ТОТ ГРАФИК, КОТОРОГО У НАС НЕ БЫЛО ВООБЩЕ: цену рынка мы показывали одним числом
    («45%»), а вопрос у людей другой - «куда она шла». Одно число на предсказательном рынке
    почти не значит ничего: 45% после 20% и 45% после 70% это противоположные истории.
    """
    if not rows:
        return None, 'empty'
    ys, xs = [], []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        c = _num(r.get('close') or r.get('price') or r.get('last_trade_price'))
        if c is None:
            continue
        ys.append(c * 100 if c <= 1 else c)     # приходит и долей, и процентом
        xs.append(i)
    if len(ys) < 3:
        return None, 'empty'

    plt = _style()
    fp = _font()
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=170)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    ax.plot(xs, ys, color='#2ea043', linewidth=2.0)
    ax.fill_between(xs, ys, color='#2ea043', alpha=0.12)
    # 50% - ОСМЫСЛЕННАЯ ЛИНИЯ, а не украшение: она отделяет «скорее да» от «скорее нет»
    ax.axhline(50, color='#8b949e', linewidth=0.9, alpha=0.7, linestyle='--')
    ax.set_ylim(0, 100)
    ax.set_ylabel('%', color='#8b949e', fontsize=9, fontproperties=fp)
    ax.tick_params(axis='y', colors='#8b949e', labelsize=8)
    ax.set_xticks([])
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#30363d')
    ax.grid(axis='y', color='#30363d', alpha=0.35, linewidth=0.6)
    _q = (question or ('Рынок' if lang != 'en' else 'Market'))[:64]
    ax.set_title('%s · %s%%' % (_q, ('%.0f' % ys[-1])), color='#e6edf3', fontsize=11, pad=10,
                 fontproperties=fp)
    fig.text(0.99, 0.02, 'Nansen', ha='right', color='#8b949e', fontsize=8, fontproperties=fp)
    fig.tight_layout()
    out_dir = out_dir or tempfile.gettempdir()
    path = os.path.join(out_dir, 'nansen_pm_%d.png' % int(time.time()))
    try:
        plt.savefig(path, facecolor='#0d1117')
    except Exception as e:
        print('[viz] график рынка не сохранился: %s' % str(e)[:120])
        plt.close(fig)
        return None, 'http'
    plt.close(fig)
    _delta = ys[-1] - ys[0]
    if lang == 'en':
        cap = 'Now %.0f%%, %+.0f pp over the window. Source: Nansen.' % (ys[-1], _delta)
    else:
        cap = 'Сейчас %.0f%%, %+.0f п.п. за окно. Источник: Nansen.' % (ys[-1], _delta)
    return path, cap


def bought_sold_png(buys, sells, symbol='', lang='ru', out_dir=None, top=5):
    """Встречные полосы «кто входил / кто выходил». -> (путь, подпись) | (None, причина).

    Две стороны на ОДНОЙ оси нарочно: вопрос «кто входил» без «кто выходил» отвечает половину,
    и именно сравнение объёмов делает картинку решением, а не сводкой.
    """
    def _pick(rows, keys):
        out = []
        for r in (rows or [])[:top]:
            if not isinstance(r, dict):
                continue
            who = (r.get('address_label') or r.get('trader_address_label') or '').strip()
            if not who:
                a = str(r.get('address') or r.get('trader_address') or '')
                who = ('%s…%s' % (a[:5], a[-3:])) if len(a) > 10 else (a or '?')
            v = None
            for k in keys + ('volume_usd', 'total_volume_usd'):
                v = _num(r.get(k))
                if v is not None:
                    break
            if v:
                out.append((who[:18], abs(v)))
        return out

    b = _pick(buys, ('bought_volume_usd', 'buy_volume_usd'))
    s = _pick(sells, ('sold_volume_usd', 'sell_volume_usd'))
    if not b and not s:
        return None, 'empty'

    plt = _style()
    fp = _font()
    n = max(len(b), len(s))
    fig, ax = plt.subplots(figsize=(7.2, max(2.6, 0.52 * n + 1.4)), dpi=170)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    for i, (who, v) in enumerate(b):
        ax.barh(i, v, color='#2ea043', height=0.42)
        ax.text(v, i, ' ' + who + ' $' + _short(v), va='center', ha='left',
                color='#c9d1d9', fontsize=8, fontproperties=fp)
    for i, (who, v) in enumerate(s):
        ax.barh(i, -v, color='#f85149', height=0.42)
        ax.text(-v, i, who + ' $' + _short(v) + ' ', va='center', ha='right',
                color='#c9d1d9', fontsize=8, fontproperties=fp)
    ax.axvline(0, color='#8b949e', linewidth=1.0)
    ax.set_yticks([])
    ax.set_xticks([])
    for sp in ('top', 'right', 'left', 'bottom'):
        ax.spines[sp].set_visible(False)
    _t = ('Кто входил и кто выходил' if lang != 'en' else 'Who bought and who sold')
    ax.set_title('%s%s' % (('%s · ' % symbol) if symbol else '', _t),
                 color='#e6edf3', fontsize=11, pad=10, fontproperties=fp)
    fig.text(0.99, 0.02, 'Nansen', ha='right', color='#8b949e', fontsize=8, fontproperties=fp)
    fig.tight_layout()
    out_dir = out_dir or tempfile.gettempdir()
    path = os.path.join(out_dir, 'nansen_wbs_%d.png' % int(time.time()))
    try:
        plt.savefig(path, facecolor='#0d1117')
    except Exception as e:
        print('[viz] полосы не сохранились: %s' % str(e)[:120])
        plt.close(fig)
        return None, 'http'
    plt.close(fig)
    if lang == 'en':
        cap = 'Green bought, red sold. Source: Nansen.'
    else:
        cap = 'Зелёные набирали, красные сливали. Источник: Nansen.'
    return path, cap



# ═══════════════════════════════════════════════════════════════════════════════
# КАРТА ЛИКВИДАЦИЙ: ГДЕ ВИСИТ ЧУЖОЕ ПЛЕЧО
#
# ЗАЧЕМ ЭТО, ЕСЛИ ЕСТЬ СПИСОК ПОЗИЦИЙ. Список отвечает «кто и с каким плечом стоит» - двенадцать
# строк, которые надо прочитать и сложить в голове. А вопрос, ради которого на плечо вообще
# смотрят, другой: НА КАКОМ УРОВНЕ ЦЕНЫ РЫНОК ПОЕДЕТ БЫСТРО. Ответ на него - не строка, а
# распределение: сумма позиций, сгруппированная по цене ликвидации. На картинке скопление видно
# мгновенно, в списке - никогда.
#
# И ЭТО РОВНО ЗАКОН «ВЕЛИЧИНА ВМЕСТО ФЛАГА»: «у BTC есть позиции с плечом 20x» - факт,
# «между $61K и $63K висит $184M» - величина, по которой принимают решение.
#
# ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ: предсказаний. Карта показывает, где стоят чужие стопы, и молчит о
# том, пойдёт ли туда цена. Подпись говорит это словами - иначе картинка читается как прогноз.
# ═══════════════════════════════════════════════════════════════════════════════

#: сколько столбиков на карте. Меньше - теряются скопления, больше - шум вместо картины.
LIQ_BUCKETS = 14
#: минимальная сумма в корзине, ниже которой это пыль, а не скопление
LIQ_MIN_USD = 1000.0


def _price(v):
    """Цена для ПОДПИСИ ДИАПАЗОНА. -> str.

    Отдельно от `_short`, и вот почему: `_short` округляет до целых K, и границы корзины
    $61 500 и $62 393 обе превращались в «$62K». Заголовок карты выглядел как «скопление между
    $62K и $62K» - то есть главная строка экрана читалась как бессмыслица. Диапазону нужна та
    точность, при которой его концы РАЗЛИЧАЮТСЯ, иначе это не диапазон.
    """
    a = abs(v)
    if a >= 1e9:
        return '%.2fB' % (v / 1e9)
    if a >= 1e6:
        return '%.2fM' % (v / 1e6)
    if a >= 1e3:
        return '%.1fK' % (v / 1e3)
    if a >= 1:
        return '%.2f' % v
    return '%.4f' % v


def liq_clusters(rows, mark=None):
    """Позиции -> скопления плеча по цене ликвидации. -> dict | None.

    Считает ОТДЕЛЬНО от рисования, и это принципиально: числа нужны и тексту (заголовок
    «между $61K и $63K висит $184M»), и картинке. Посчитай я их внутри `savefig`, текст и
    картинка разошлись бы на первой правке - тот же класс, что две копии одной логики.

    -> {'buckets': [(низ, верх, сумма, сторона)], 'total', 'top', 'longs', 'shorts',
        'no_liq', 'shown', 'mark'} либо None, если считать нечего.

    `side` у корзины - ПРЕОБЛАДАЮЩАЯ сторона, а не единственная: на одном уровне могут висеть
    и лонги, и шорты, и врать про это нельзя, поэтому рядом лежат обе суммы.
    """
    if not rows:
        return None
    pts, no_liq, sides = [], 0, {'LONG': 0.0, 'SHORT': 0.0}
    for r in rows:
        if not isinstance(r, dict):
            continue
        liq = _num(r.get('liquidation_price') if 'liquidation_price' in r
                   else r.get('liq_price'))
        val = None
        for k in ('position_value_usd', 'notional_usd', 'value_usd'):
            val = _num(r.get(k))
            if val is not None:
                break
        if liq is None or liq <= 0 or val is None or val <= 0:
            # ПОЗИЦИЯ БЕЗ ЦЕНЫ ЛИКВИДАЦИИ НЕ ВЫБРАСЫВАЕТСЯ МОЛЧА: её считаем и называем в
            # подписи. «Карта по 8 позициям из 20» и «карта по 20 из 20» - разные карты, и
            # человек обязан знать, какую из них он смотрит.
            no_liq += 1
            continue
        _sd = str(r.get('side') or r.get('direction') or '').upper()
        _sd = 'SHORT' if _sd.startswith('S') else ('LONG' if _sd.startswith('L') else '')
        pts.append((liq, val, _sd))
        if _sd:
            sides[_sd] = sides.get(_sd, 0.0) + val
    if not pts:
        return None
    lo, hi = min(p[0] for p in pts), max(p[0] for p in pts)
    if hi <= lo:
        # ВСЕ ЛИКВИДАЦИИ НА ОДНОМ УРОВНЕ - корзины не нужны, и растягивать диапазон нельзя:
        # выдуманная ширина нарисовала бы распределение там, где его нет.
        _s = sum(p[1] for p in pts)
        return {'buckets': [(lo, hi, _s, _dom_side(pts))], 'total': _s, 'top': (lo, hi, _s),
                'longs': sides.get('LONG', 0.0), 'shorts': sides.get('SHORT', 0.0),
                'no_liq': no_liq, 'shown': len(pts), 'mark': _num(mark)}
    step = (hi - lo) / float(LIQ_BUCKETS)
    acc = {}
    for liq, val, sd in pts:
        i = min(int((liq - lo) / step), LIQ_BUCKETS - 1)
        b = acc.setdefault(i, {'sum': 0.0, 'LONG': 0.0, 'SHORT': 0.0})
        b['sum'] += val
        if sd:
            b[sd] += val
    buckets = []
    for i in sorted(acc):
        b = acc[i]
        if b['sum'] < LIQ_MIN_USD:
            continue
        _sd = 'LONG' if b['LONG'] > b['SHORT'] else ('SHORT' if b['SHORT'] > b['LONG'] else '')
        buckets.append((lo + i * step, lo + (i + 1) * step, b['sum'], _sd))
    if not buckets:
        return None
    top = max(buckets, key=lambda x: x[2])
    return {'buckets': buckets, 'total': sum(b[2] for b in buckets),
            'top': (top[0], top[1], top[2]),
            'longs': sides.get('LONG', 0.0), 'shorts': sides.get('SHORT', 0.0),
            'no_liq': no_liq, 'shown': len(pts), 'mark': _num(mark)}


def _dom_side(pts):
    _l = sum(v for _p, v, s in pts if s == 'LONG')
    _s = sum(v for _p, v, s in pts if s == 'SHORT')
    return 'LONG' if _l > _s else ('SHORT' if _s > _l else '')


def liq_map_png(rows, token='', mark=None, lang='ru', out_dir=None):
    """Карта ликвидаций: сумма плеча по уровням цены. -> (путь_к_png, подпись) | (None, причина).

    `rows` - строки `tgm/perp-positions` (те же, что показывает текстовый экран).
    `mark` - текущая цена, если вызывающий её знает. НЕОБЯЗАТЕЛЬНА: без неё карта остаётся
    честной картой уровней, просто без отметки «мы здесь». Выдумывать цену нельзя - подпись
    «вот сюда осталось 3%» на выдуманной цене хуже отсутствия отметки.
    """
    cl = liq_clusters(rows, mark)
    if not cl:
        return None, 'empty'

    plt = _style()
    fp = _font()
    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=170)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')

    ys = range(len(cl['buckets']))
    vals = [b[2] for b in cl['buckets']]
    # ЦВЕТ = СТОРОНА, И ЗДЕСЬ ЭТО ЧЕСТНО (в отличие от потоков, где цвет означал сегмент и
    # врал про знак): у ликвидации сторона и есть её смысл. Лонги сносит вниз, шорты - вверх,
    # поэтому красный и зелёный читаются так же, как на свечах.
    colors = ['#f85149' if b[3] == 'LONG' else
              ('#2ea043' if b[3] == 'SHORT' else '#8b949e') for b in cl['buckets']]
    ax.barh(list(ys), vals, color=colors, height=0.72)

    _labels = []
    for b in cl['buckets']:
        _labels.append('$%s' % _price((b[0] + b[1]) / 2.0))
    ax.set_yticks(list(ys))
    ax.set_yticklabels(_labels, color='#c9d1d9', fontsize=8, fontproperties=fp)
    ax.tick_params(axis='x', colors='#8b949e', labelsize=8)
    _mx = max(vals)
    for i, v in enumerate(vals):
        ax.text(v + _mx * 0.02, i, '$' + _short(v), va='center', color='#c9d1d9',
                fontsize=8, fontproperties=fp)

    # ТЕКУЩАЯ ЦЕНА ЛИНИЕЙ - ТОЛЬКО ЕСЛИ ОНА ПРАВДА ИЗВЕСТНА И ПОПАДАЕТ В ДИАПАЗОН.
    # Линия за краем графика читается как «до ликвидаций далеко», и это вывод, которого мы
    # не делали.
    _m = cl.get('mark')
    if _m:
        _los = [b[0] for b in cl['buckets']]
        _his = [b[1] for b in cl['buckets']]
        if min(_los) <= _m <= max(_his):
            _span = max(_his) - min(_los)
            _pos = ((_m - min(_los)) / _span * (len(cl['buckets']) - 1)) if _span else 0
            ax.axhline(_pos, color='#d29922', linewidth=1.2, linestyle='--', alpha=0.9)
            ax.text(_mx * 0.98, _pos, ('сейчас $%s' if lang != 'en' else 'now $%s')
                    % _price(_m), ha='right', va='bottom', color='#d29922', fontsize=8,
                    fontproperties=fp)

    try:
        from matplotlib.ticker import FuncFormatter
        ax.xaxis.set_major_formatter(FuncFormatter(
            lambda v, _p: '' if v == 0 else ('$%s' % _short(v))))
    except Exception as _fe:
        print('[viz] формат оси карты не применён: %s' % str(_fe)[:80])
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color('#30363d')
    ax.grid(axis='x', color='#30363d', alpha=0.35, linewidth=0.6)
    ax.margins(x=0.14)

    _t = ('Карта ликвидаций' if lang != 'en' else 'Liquidation map')
    ax.set_title('%s%s' % (('%s · ' % token) if token else '', _t),
                 color='#e6edf3', fontsize=12, pad=12, fontproperties=fp)
    # ЛЕГЕНДА - СЛОВА, ОКРАШЕННЫЕ В ТОТ ЖЕ ЦВЕТ, что и столбики. Эмодзи-кружки (🔴🟢) здесь
    # СТОЯЛИ И БЫЛИ УБРАНЫ: в Oswald их нет, matplotlib честно предупреждал «Glyph missing», и
    # на картинке вместо легенды выходили квадратики - то есть легенда, не читаемая ровно там,
    # где она нужна. Цвет самого слова эту работу делает без шрифтовых зависимостей.
    fig.text(0.01, 0.02, ('лонги' if lang != 'en' else 'longs'), ha='left',
             color='#f85149', fontsize=8, fontproperties=fp)
    fig.text(0.075, 0.02, ('шорты' if lang != 'en' else 'shorts'), ha='left',
             color='#2ea043', fontsize=8, fontproperties=fp)
    fig.text(0.99, 0.02, 'Nansen', ha='right', color='#8b949e', fontsize=8, fontproperties=fp)
    fig.tight_layout()

    out_dir = out_dir or tempfile.gettempdir()
    path = os.path.join(out_dir, 'nansen_liqmap_%s_%d.png'
                        % ((token or 'tok').replace('/', '_')[:12], int(time.time())))
    try:
        plt.savefig(path, facecolor='#0d1117')
    except Exception as e:
        print('[viz] карта ликвидаций не сохранилась: %s' % str(e)[:120])
        plt.close(fig)
        return None, 'http'
    plt.close(fig)
    return path, liq_caption(cl, token, lang)


def liq_caption(cl, token='', lang='ru'):
    """Подпись к карте: ВЕЛИЧИНА, потом оговорки. -> str.

    Отдельной функцией, потому что ту же строку показывает текстовый экран, когда картинка не
    собралась (нет matplotlib). Две копии этой фразы разошлись бы на первой правке, и человек
    получал бы разные числа на одних данных в зависимости от того, нарисовалось ли.
    """
    if not cl:
        return ''
    _lo, _hi, _sum = cl['top']
    _tot, _shown, _no = cl['total'], cl['shown'], cl['no_liq']
    if lang == 'en':
        L = ['%s liquidation map. Biggest cluster: $%s between $%s and $%s.'
             % (token or 'Token', _short(_sum), _price(_lo), _price(_hi)),
             'Total on the map: $%s across %d position(s).' % (_short(_tot), _shown)]
        if cl['longs'] or cl['shorts']:
            L.append('Longs $%s vs shorts $%s.' % (_short(cl['longs']), _short(cl['shorts'])))
        if _no:
            L.append('%d position(s) had no liquidation price and are NOT on the map.' % _no)
        L.append('This is where other people stop out, not a forecast. Source: Nansen.')
    else:
        L = ['%s: карта ликвидаций. Самое плотное скопление: $%s между $%s и $%s.'
             % (token or 'Токен', _short(_sum), _price(_lo), _price(_hi)),
             'Всего на карте $%s по %d позици(ям).' % (_short(_tot), _shown)]
        if cl['longs'] or cl['shorts']:
            L.append('Лонги $%s против шортов $%s.' % (_short(cl['longs']),
                                                       _short(cl['shorts'])))
        if _no:
            # ЧЕСТНАЯ ОГОВОРКА, А НЕ МЕЛКИЙ ШРИФТ: карта по 8 позициям из 20 и карта по 20 из
            # 20 - разные карты, и человек обязан знать, какую смотрит.
            L.append('У %d позиц(ий) цены ликвидации не было - их на карте НЕТ.' % _no)
        L.append('Это уровни чужих стопов, а не прогноз. Источник: Nansen.')
    return ' '.join(L)
