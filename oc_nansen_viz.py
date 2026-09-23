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
    ('whale',         'Киты',        'Whales',      '#49c8ff'),
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
#: ОКНО КАРТЫ ВОКРУГ ТЕКУЩЕЙ ЦЕНЫ: ±50%. Дальше лежат позиции с крошечным плечом, чья
#: ликвидация в обозримом движении не сработает, зато размах они растягивают в тысячи раз - и
#: тогда все корзины сливаются в одну (разбор TAO/NEAR, вопрос Ren). Половина цены - не догадка
#: о «нормальном» движении, а граница ЧИТАЕМОСТИ карты: при ±50% и 14 корзинах шаг ~7% цены,
#: то есть уровень, который человек может отличить от соседнего. Деньги за окном НЕ теряются:
#: они считаются отдельной величиной и называются словом.
LIQ_WINDOW = 0.5
#: МАСШТАБЫ КАРТЫ, КОТОРЫЕ ЧЕЛОВЕК МОЖЕТ ВЫБРАТЬ (проценты вокруг цены; 0 = «весь размах»).
#: Запрос владельца: «нельзя ли регулировать масштаб по уровням». Набор ЗАКРЫТЫЙ, а не любое
#: число: во-первых, произвольный процент из клиента - это свободное значение в подписанном
#: сигнале, во-вторых, четыре понятных ступени человек сравнивает между собой, а ползунок с
#: 37% сравнить не с чем. По умолчанию - `LIQ_WINDOW`, то есть ровно то, что было.
LIQ_ZOOMS = (10, 25, 50, 100, 0)


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


#: сколько символов метки кошелька показываем. 22 - предел, после которого строка подписи
#: начинает переносить самое важное (сумму) на вторую строку.
LABEL_MAX = 22


def _label_clean(s):
    """Метка кошелька в пригодный для строки вид. -> str.

    РЕЖЕМ ПО ГРАНИЦЕ СЛОВА И СТАВИМ МНОГОТОЧИЕ. Живой прогон (HYPE, скриншот Ren) показал, что
    метки Hyperliquid бывают длинными описаниями с кавычками: в подпись попадало
    `Uses "TRADEXYZ1" HL Refe` - обрубок на полуслове, который читается как испорченные данные,
    а не как сокращение. Многоточие говорит «здесь обрезано мы», а не «Nansen прислал мусор».
    """
    t = ' '.join(str(s or '').split())
    if len(t) <= LABEL_MAX:
        return t
    cut = t[:LABEL_MAX]
    if ' ' in cut[8:]:                     # ищем пробел не в самом начале - иначе останется «Uses»
        cut = cut[:cut.rfind(' ')]
    return cut.rstrip(' ,;:-"\'') + '…'


def liq_zoom_ok(z):
    """Проверить масштаб по закрытому списку. -> int (проценты) | None.

    None означает «человек масштаб не выбирал» и даёт умолчание. Чужое число НЕ подгоняется
    к ближайшему разрешённому: тихая подмена значения - это ответ на вопрос, которого не
    задавали (человек попросил 37%, получил 25% и не узнал об этом).
    """
    try:
        z = int(z)
    except (TypeError, ValueError):
        return None
    return z if z in LIQ_ZOOMS else None


def liq_clusters(rows, mark=None, zoom=None):
    """Позиции -> скопления плеча по цене ликвидации. -> dict | None.

    Считает ОТДЕЛЬНО от рисования, и это принципиально: числа нужны и тексту (заголовок
    «между $61K и $63K висит $184M»), и картинке. Посчитай я их внутри `savefig`, текст и
    картинка разошлись бы на первой правке - тот же класс, что две копии одной логики.

    -> {'buckets': [(низ, верх, сумма, сторона, деньги_с_меткой, главная_метка)], 'total',
        'top', 'longs', 'shorts', 'no_liq', 'shown', 'mark', 'named', 'named_n', 'named_who'}
    либо None, если считать нечего.

    `side` у корзины - ПРЕОБЛАДАЮЩАЯ сторона, а не единственная: на одном уровне могут висеть
    и лонги, и шорты, и врать про это нельзя, поэтому рядом лежат обе суммы.

    МЕТКИ КОШЕЛЬКОВ СЧИТАЮТСЯ ЗДЕСЬ ЖЕ, И ЭТО ГЛАВНОЕ ДОБАВЛЕНИЕ КАРТЫ. `tgm/perp-positions`
    отдаёт `address_label` - то, как Nansen называет кошелёк («Smart Money», имя фонда). Без
    этого карта отвечала «сколько плеча висит», но не «чьё оно»: $300M толпы с мелкими плечами
    и $300M одного фонда читаются одинаково, а решение по ним разное. Считаем ВЕЛИЧИНУ
    (сколько денег в корзине у кошельков с меткой), а не флаг «метки есть»: флаг наличия не
    равен пользе - за это в проекте уже трижды получали. Метки нет ни у кого - так и скажем
    числом (ноль), потому что «мы посмотрели и не нашли» и «мы не смотрели» - разные ответы.
    """
    if not rows:
        return None
    pts, no_liq, sides = [], 0, {'LONG': 0.0, 'SHORT': 0.0}
    named_who = {}
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
        # МЕТКА - ТОЛЬКО ТА, ЧТО ПРИЕХАЛА. Обрезанный адрес меткой НЕ считается (в отличие от
        # `_who`, где он нужен как подпись строки): «0x1f90…326» не говорит, чей это кошелёк,
        # и посчитать его в «деньги с меткой» значило бы выдать незнание за знание.
        _lbl = str(r.get('address_label') or r.get('trader_address_label')
                   or r.get('label') or '').strip()
        if _lbl[:2].lower() == '0x' and len(_lbl) > 12:
            # В ПОЛЕ МЕТКИ ПРИЕХАЛ АДРЕС - ЭТО НЕ ИМЯ. Такой «метки» не бывает по смыслу
            # (имени у кошелька нет, площадка вернула сам адрес), и посчитать её значило бы
            # объявить деньги «известными» ни за что. Плюс адрес не имеет права ехать в
            # мини-апп: экран показывает только то, что прошло `_strip_private`.
            _lbl = ''
        # ЧИСТИМ ПОСЛЕ проверки на адрес: обрезанный адрес проверку бы прошёл, а в мини-апп ему
        # нельзя и обрубком (скруббер справедливо ловит форму адреса, а не только полный).
        _lbl = _label_clean(_lbl)
        pts.append((liq, val, _sd, _lbl))
        if _lbl:
            named_who[_lbl] = named_who.get(_lbl, 0.0) + val
        if _sd:
            sides[_sd] = sides.get(_sd, 0.0) + val
    if not pts:
        return None
    # ═══ ОКНО ВОКРУГ ЦЕНЫ: БЕЗ НЕГО КАРТА МЕНЕЕ ЛИКВИДНОГО ТОКЕНА БЕССМЫСЛЕННА ═══
    # Живой разбор (вопрос Ren по TAO и NEAR): у TAO при цене $316 крайние цены ликвидации
    # приехали от $0.48 до $17.3K. Четырнадцать РАВНЫХ корзин на таком размахе дают первую
    # корзину «от $0.48 до $1.2K», и заголовок читался как «самое плотное скопление между
    # $0.48 и $1.2K» - то есть диапазон в две тысячи раз, внутри которого лежит и текущая цена,
    # и всё остальное. Это не свойство данных Nansen: строки честные, крайние позиции реальны
    # (крошечное плечо ликвидируется почти в нуле). Это наша арифметика: равные корзины по всему
    # размаху. У BTC размах естественно узкий, поэтому дефект и не был виден.
    # ЛЕЧЕНИЕ: считаем внутри окна ±LIQ_WINDOW от текущей цены, а деньги ЗА окном НЕ выбрасываем
    # молча - считаем отдельной величиной и называем словом. Цены нет - окна нет (выдуманное
    # окно от выдуманной цены было бы хуже), тогда обрезаем по краевым процентилям.
    off_usd, off_n, win = 0.0, 0, None
    _mk = _num(mark)
    _wl = _wh = None
    # МАСШТАБ: выбранный человеком или умолчание. Ноль - это «весь размах», и он НЕ равен
    # «умолчанию»: человек мог попросить именно всё, и тогда окна не будет вовсе.
    _z = liq_zoom_ok(zoom)
    _wfrac = (float(_z) / 100.0) if _z else (None if _z == 0 else LIQ_WINDOW)
    if _mk and _mk > 0 and _wfrac:
        _wl, _wh = _mk * (1.0 - _wfrac), _mk * (1.0 + _wfrac)
    elif _wfrac and len(pts) >= 8:
        # ЦЕНЫ НЕТ - ОКНО ОТ ЦЕНЫ НЕВОЗМОЖНО, и выдумывать её нельзя. Обрезаем по краевым
        # процентилям: это не «нормальное движение», а отсечение выбросов по самим данным.
        _srt = sorted(p[0] for p in pts)
        _q = max(1, int(len(_srt) * 0.05))
        _wl, _wh = _srt[_q], _srt[-1 - _q]
    win_empty = False
    if _wl is not None and _wh is not None and _wh > _wl:
        _in = [p for p in pts if _wl <= p[0] <= _wh]
        # НИ ОДНОЙ ПОЗИЦИИ В ОКНЕ - карту рисуем по всему размаху и ГОВОРИМ ОБ ЭТОМ СЛОВОМ.
        # Пустая карта читалась бы как «плеча нет», а оно есть, просто далеко; а молча
        # нарисованный полный размах даёт «скопление в 2144% выше цены» - число, которое
        # выглядит как измерение, но означает «сюда цена не дойдёт никогда».
        win_empty = not _in
        if _in:
            win = (_wl, _wh)
            off_n = len(pts) - len(_in)
            off_usd = sum(p[1] for p in pts) - sum(p[1] for p in _in)
            pts = _in
    # СТОРОНЫ И МЕТКИ ПЕРЕСЧИТЫВАЮТСЯ ПО ОКНУ, А НЕ ПО ВСЕМ СТРОКАМ. Иначе «лонги + шорты»
    # оказались бы БОЛЬШЕ, чем «всего на карте», и человек не смог бы сложить экран в голове -
    # худший вид расхождения: каждое число по отдельности верное.
    sides = {'LONG': 0.0, 'SHORT': 0.0}
    named_who = {}
    for _liq, _val, _sd2, _lbl2 in pts:
        if _sd2:
            sides[_sd2] = sides.get(_sd2, 0.0) + _val
        if _lbl2:
            named_who[_lbl2] = named_who.get(_lbl2, 0.0) + _val
    _named_tot = sum(v for v in named_who.values())
    _named_n = sum(1 for p in pts if p[3])
    _who_top = sorted(named_who.items(), key=lambda kv: -kv[1])[:3]
    lo, hi = min(p[0] for p in pts), max(p[0] for p in pts)
    if hi <= lo:
        # ВСЕ ЛИКВИДАЦИИ НА ОДНОМ УРОВНЕ - корзины не нужны, и растягивать диапазон нельзя:
        # выдуманная ширина нарисовала бы распределение там, где его нет.
        _s = sum(p[1] for p in pts)
        return {'buckets': [(lo, hi, _s, _dom_side(pts), _named_tot,
                             _who_top[0][0] if _who_top else '')],
                'total': _s, 'top': (lo, hi, _s),
                'longs': sides.get('LONG', 0.0), 'shorts': sides.get('SHORT', 0.0),
                'no_liq': no_liq, 'shown': len(pts), 'mark': _num(mark),
                'named': _named_tot, 'named_n': _named_n, 'named_who': _who_top,
                'window': win, 'off_usd': off_usd, 'off_n': off_n,
                'win_empty': win_empty,
                # ЧТО ПРОСИЛИ, а не что получилось: когда в окне пусто, окна в ответе нет,
                # но назвать процент всё равно надо - иначе фраза «в пределах 50%» соврёт
                # человеку, который просил 10%.
                'req_pct': ((_wfrac * 100) if _wfrac else None),
                'win_pct': ((_wfrac * 100) if (_mk and win and _wfrac) else None),
                'zoom': _z}
    step = (hi - lo) / float(LIQ_BUCKETS)
    acc = {}
    for liq, val, sd, lbl in pts:
        i = min(int((liq - lo) / step), LIQ_BUCKETS - 1)
        b = acc.setdefault(i, {'sum': 0.0, 'LONG': 0.0, 'SHORT': 0.0, 'named': 0.0,
                               'n_named': 0, 'who': {}})
        b['sum'] += val
        if sd:
            b[sd] += val
        if lbl:
            b['named'] += val
            b['n_named'] += 1
            b['who'][lbl] = b['who'].get(lbl, 0.0) + val
    buckets, drawn_who, drawn_named_n = [], {}, 0
    for i in sorted(acc):
        b = acc[i]
        if b['sum'] < LIQ_MIN_USD:
            continue
        for _k, _v in b['who'].items():
            drawn_who[_k] = drawn_who.get(_k, 0.0) + _v
        drawn_named_n += b['n_named']
        _sd = 'LONG' if b['LONG'] > b['SHORT'] else ('SHORT' if b['SHORT'] > b['LONG'] else '')
        # ГЛАВНАЯ МЕТКА КОРЗИНЫ - ТА, ЗА КОТОРОЙ БОЛЬШЕ ДЕНЕГ, а не первая по порядку строк:
        # порядок ответа Nansen нам ничего не обещает, а величина - обещает.
        _top_lbl = max(b['who'].items(), key=lambda kv: kv[1])[0] if b['who'] else ''
        buckets.append((lo + i * step, lo + (i + 1) * step, b['sum'], _sd, b['named'], _top_lbl))
    if not buckets:
        return None
    top = max(buckets, key=lambda x: x[2])
    return {'buckets': buckets, 'total': sum(b[2] for b in buckets),
            'top': (top[0], top[1], top[2]),
            'longs': sides.get('LONG', 0.0), 'shorts': sides.get('SHORT', 0.0),
            'no_liq': no_liq, 'shown': len(pts), 'mark': _num(mark),
            # СУММЫ С МЕТКАМИ СЧИТАЕМ ПО ВСЕМ ТОЧКАМ, А НЕ ПО КОРЗИНАМ: корзина ниже
            # `LIQ_MIN_USD` в карту не попадает, и её метки тоже не попадают - иначе итог по
            # меткам оказался бы больше, чем сумма нарисованного, и человек не смог бы сверить.
            'named': sum(b[4] for b in buckets), 'named_n': drawn_named_n,
            'named_who': sorted(drawn_who.items(), key=lambda kv: -kv[1])[:3],
            # ОКНО И ДЕНЬГИ ЗА ЕГО ПРЕДЕЛАМИ - ОБЯЗАТЕЛЬНЫЕ ПОЛЯ ОТВЕТА: карта по части позиций
            # и карта по всем - разные карты, и человек обязан знать, какую смотрит.
            'window': win, 'off_usd': off_usd, 'off_n': off_n, 'win_empty': win_empty,
            'req_pct': ((_wfrac * 100) if _wfrac else None),
            'win_pct': ((_wfrac * 100) if (_mk and win and _wfrac) else None), 'zoom': _z}


def _dom_side(pts):
    _l = sum(v for _p, v, s, _lbl in pts if s == 'LONG')
    _s = sum(v for _p, v, s, _lbl in pts if s == 'SHORT')
    return 'LONG' if _l > _s else ('SHORT' if _s > _l else '')


def liq_board(by_token):
    """СРАВНЕНИЕ ТОКЕНОВ: где чужое плечо ближе к обрыву. -> dict | None.

    `by_token` - {ТИКЕР: {'rows': строки tgm/perp-positions, 'mark': цена или None}}. Сеть
    здесь НЕ ТРОГАЕТСЯ нарочно: считает эта функция, спрашивает вызывающий (чат или шлюз), и
    тогда одни и те же числа приходят и в текст, и в картинку, и в мини-апп.

    -> {'rows': [{'tok','total','longs','shorts','named','top_usd','top_lo','top_hi',
        'top_side','mark','gap_pct','shown','no_liq'}], 'tokens', 'no_mark', 'age_sec': None}

    ГЛАВНОЕ ЧИСЛО ЗДЕСЬ - РАССТОЯНИЕ ДО СКОПЛЕНИЯ, А НЕ ЕГО РАЗМЕР. «$300M висит» - факт;
    «$300M висит в 4% ниже цены» - величина, по которой принимают решение: чем короче путь до
    плотного уровня, тем быстрее рынок проедет его на чужих стопах. Поэтому порядок строк - по
    близости, а не по сумме.

    ЦЕНЫ НЕТ - РАССТОЯНИЯ НЕТ, и строка уезжает в конец со словом. Посчитать «расстояние» от
    выдуманной цены значило бы выдать догадку за замер в том самом числе, которое ведёт экран.
    """
    if not isinstance(by_token, dict) or not by_token:
        return None
    out, no_mark = [], 0
    for tok, d in by_token.items():
        if not isinstance(d, dict):
            continue
        cl = liq_clusters(d.get('rows'), d.get('mark'), d.get('zoom'))
        if not cl:
            # ТОКЕН БЕЗ КАРТЫ НЕ ВЫБРАСЫВАЕТСЯ МОЛЧА: его строка остаётся со словом «карты
            # нет». Выброси мы её - борд выглядел бы полным, умалчивая, что по одному из
            # токенов мы ничего не знаем.
            out.append({'tok': str(tok)[:12], 'total': None, 'longs': None, 'shorts': None,
                        'named': None, 'top_usd': None, 'top_lo': None, 'top_hi': None,
                        'top_side': '', 'mark': _num(d.get('mark')), 'gap_pct': None,
                        'shown': 0, 'no_liq': 0,
                        # ДВА РАЗНЫХ «НЕТ»: позиций не отдали вовсе или позиции есть, а цен
                        # ликвидации в них нет. Первое - про площадку, второе - про схему
                        # ответа, и чинятся они по-разному.
                        'status': 'norows' if not d.get('rows') else 'nomap'})
            continue
        if cl.get('win_empty'):
            # НИЧЕГО НЕ ЛИКВИДИРУЕТСЯ В ПРЕДЕЛАХ ОКНА - ЭТО ОТДЕЛЬНОЕ СОСТОЯНИЕ, А НЕ БОЛЬШОЕ
            # ЧИСЛО. Иначе борд печатает «скопление в 2144% выше цены»: арифметически верно,
            # по смыслу - «сюда цена не дойдёт», и в сортировке по близости такой токен не
            # участвует вовсе. Поймано рендером борда на несогласованных данных.
            out.append({'tok': str(tok)[:12], 'total': cl['total'], 'longs': cl['longs'],
                        'shorts': cl['shorts'], 'named': cl.get('named') or 0.0,
                        'top_usd': cl['top'][2], 'top_lo': cl['top'][0], 'top_hi': cl['top'][1],
                        'top_side': '', 'mark': cl.get('mark'), 'gap_pct': None,
                        'shown': cl['shown'], 'no_liq': cl['no_liq'], 'status': 'far',
                        'req_pct': cl.get('req_pct')})
            continue
        _lo, _hi, _sum = cl['top']
        _mark = cl.get('mark')
        _gap = None
        if _mark:
            _mid = (_lo + _hi) / 2.0
            _gap = 100.0 * (_mid - _mark) / _mark          # знак = сторона: минус это ниже цены
        else:
            no_mark += 1
        out.append({'tok': str(tok)[:12], 'total': cl['total'], 'longs': cl['longs'],
                    'shorts': cl['shorts'], 'named': cl.get('named') or 0.0,
                    'top_usd': _sum, 'top_lo': _lo, 'top_hi': _hi,
                    'top_side': (cl['buckets'][max(range(len(cl['buckets'])),
                                                   key=lambda i: cl['buckets'][i][2])][3]
                                 if cl['buckets'] else ''),
                    'mark': _mark, 'gap_pct': _gap, 'shown': cl['shown'],
                    'no_liq': cl['no_liq'], 'status': 'ok'})
    if not out:
        return None
    out.sort(key=lambda r: (r['gap_pct'] is None, abs(r['gap_pct'] or 0)))
    return {'rows': out, 'tokens': len(out), 'no_mark': no_mark, 'age_sec': None}


def liq_board_caption(d, lang='ru'):
    """Подпись борда риска: у кого путь до плотного уровня короче. -> str.

    Та же функция для чата и для мини-аппа: две копии этой фразы разошлись бы на первой правке
    (тот же разбор, что у `liq_caption`).
    """
    if not isinstance(d, dict) or not d.get('rows'):
        return ''
    en = (lang == 'en')
    L = [('⚔️ <b>Where other people\'s leverage is closest to the edge</b>' if en
          else '⚔️ <b>У кого чужое плечо ближе к обрыву</b>')]
    L.append(('Order is by distance from the current price to the densest liquidation cluster, '
              'not by its size: $300M three per cent away and $300M forty per cent away are '
              'different situations.' if en else
              'Порядок - по расстоянию от текущей цены до самого плотного скопления '
              'ликвидаций, а не по его размеру: $300M в трёх процентах и $300M в сорока - '
              'разные ситуации.'))
    L.append('')
    for i, r in enumerate(d['rows'], 1):
        if r.get('status') == 'far':
            L.append(('%d. <b>%s</b> - nothing liquidates within %.0f%% of the price: $%s of '
                      'leverage sits further out' if en else
                      '%d. <b>%s</b> - в пределах %.0f%% от цены не ликвидируется ничего: $%s '
                      'плеча лежит дальше')
                     % (i, r['tok'], r.get('req_pct') or LIQ_WINDOW * 100,
                        _short(r['total'])))
            continue
        if r.get('status') == 'norows':
            L.append(('%d. <b>%s</b> - no open positions came back for this token' if en else
                      '%d. <b>%s</b> - открытых позиций по этому токену не отдали')
                     % (i, r['tok']))
            continue
        if r.get('status') != 'ok':
            L.append(('%d. <b>%s</b> - no map: the positions carry no liquidation price'
                      if en else
                      '%d. <b>%s</b> - карты нет: в позициях нет цены ликвидации')
                     % (i, r['tok']))
            continue
        if r.get('gap_pct') is None:
            _where = ('distance not measured: no current price' if en
                      else 'расстояние не измерено: нет текущей цены')
        else:
            _g = r['gap_pct']
            _where = (('%.1f%% %s the price' % (abs(_g), 'below' if _g < 0 else 'above'))
                      if en else
                      ('%.1f%% %s цены' % (abs(_g), 'ниже' if _g < 0 else 'выше')))
        _side = r.get('top_side') or ''
        # СТОРОНА СТОИТ СРАЗУ ЗА СУММОЙ, А НЕ В КОНЦЕ СТРОКИ. В конце она прилипала к фразе
        # «расстояние не измерено: нет текущей цены (лонги)» и читалась как уточнение к ЦЕНЕ,
        # хотя относится к скоплению.
        _side_txt = ''
        if _side:
            _side_txt = ((' (%s)' % ('longs' if _side == 'LONG' else 'shorts')) if en
                         else (' (%s)' % ('лонги' if _side == 'LONG' else 'шорты')))
        L.append(('%d. <b>%s</b>: $%s in the densest cluster%s, %s' if en else
                  '%d. <b>%s</b>: $%s в самом плотном скоплении%s, %s')
                 % (i, r['tok'], _short(r['top_usd']), _side_txt, _where))
        L.append(('    on the map $%s across %d position(s) · longs $%s vs shorts $%s' if en
                  else '    на карте $%s по %d позици(ям) · лонги $%s против шортов $%s')
                 % (_short(r['total']), int(r['shown'] or 0), _short(r['longs']),
                    _short(r['shorts'])))
        if r.get('named'):
            L.append(('    of that $%s sits on wallets Nansen has a name for' if en else
                      '    из этого $%s висит на кошельках, которых Nansen знает по имени')
                     % _short(r['named']))
    L.append('')
    if d.get('no_mark'):
        L.append((('<i>For %d token(s) the current price did not load, so their distance is '
                   'not measured and they are last in the list - not safest.</i>') if en else
                  ('<i>По %d токен(ам) текущая цена не взялась, поэтому расстояние не '
                   'измерено и они стоят в конце списка - это не «там безопаснее».</i>'))
                 % int(d['no_mark']))
    # ИСТОЧНИК ДОПИСЫВАЕТСЯ ЗДЕСЬ ЖЕ, как в `liq_caption`: у этого модуля нет доступа к
    # `nansen_api.with_source` (клиент импортирует картинки, а не наоборот), и заводить
    # обратный импорт ради одной фразы значило бы закольцевать модули.
    L.append(('<i>These are where other people stop out, not a forecast and not advice. '
              'Source: Nansen.</i>' if en else
              '<i>Это уровни чужих стопов, а не прогноз и не совет. Источник: Nansen.</i>'))
    return '\n'.join(L)


def liq_map_png(rows, token='', mark=None, lang='ru', out_dir=None, zoom=None):
    """Карта ликвидаций: сумма плеча по уровням цены. -> (путь_к_png, подпись) | (None, причина).

    `rows` - строки `tgm/perp-positions` (те же, что показывает текстовый экран).
    `mark` - текущая цена, если вызывающий её знает. НЕОБЯЗАТЕЛЬНА: без неё карта остаётся
    честной картой уровней, просто без отметки «мы здесь». Выдумывать цену нельзя - подпись
    «вот сюда осталось 3%» на выдуманной цене хуже отсутствия отметки.
    """
    cl = liq_clusters(rows, mark, zoom)
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

    # ДЕНЬГИ С МЕТКОЙ - ПОЛОСКОЙ ВНУТРИ СТОЛБИКА, А НЕ ЗВЁЗДОЧКОЙ РЯДОМ. Значок сказал бы
    # «тут есть кто-то с именем» (признак наличия), а вложенная полоса показывает СКОЛЬКО
    # из этой суммы за именем (величину) - её можно сверить глазом с общей длиной столбика.
    # Метки нет ни в одной корзине - ничего не рисуем: пустая полоса шириной ноль читалась бы
    # как «мы не смогли», хотя мы посмотрели и не нашли (это сказано в подписи словами).
    _named = [(b[4] if len(b) > 4 else 0.0) or 0.0 for b in cl['buckets']]
    if any(_named):
        # ЦВЕТ СИНИЙ, А НЕ ЗОЛОТОЙ, И ЭТО НЕ ВКУСОВЩИНА: золотым на этой же картинке нарисован
        # ПУНКТИР ТЕКУЩЕЙ ЦЕНЫ (ниже, `axhline`). Первый прогон дал полосу и пунктир одного
        # цвета - две разные величины стали читаться как одна, а легенда объясняла обе одним
        # словом. Один цвет = один смысл на картинке.
        ax.barh(list(ys), _named, color='#49c8ff', height=0.34, zorder=3)
        _wide = max(_named) if _named else 0.0
        for i, b in enumerate(cl['buckets']):
            _lbl = (b[5] if len(b) > 5 else '') or ''
            # ИМЯ ПИШЕМ ВНУТРИ ПОЛОСЫ И ОТ ЛЕВОГО КРАЯ, И ТОЛЬКО ЕСЛИ ПОЛОСА ШИРОКАЯ. Вариант
            # «по правому краю полосы» на первом прогоне налез на золотую подпись «сейчас $X»
            # у пунктира цены: два разных числа слиплись в одну строку. Узкой полосе имя не
            # влезает вовсе - писать его поверх фона значит рисовать тёмным по тёмному, а имена
            # крупнейших кошельков и так названы в подписи под картинкой.
            if _lbl and _named[i] >= 0.22 * (_wide or 1):
                ax.text(_named[i] * 0.02, i, _lbl[:18], va='center', ha='left',
                        color='#0d1117', fontsize=7, fontproperties=fp, zorder=4)

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
            # ПОДПИСЬ ЦЕНЫ УЕХАЛА ЗА КОНЕЦ САМОГО ДЛИННОГО СТОЛБИКА (было `_mx * 0.98`, то
            # есть ПОВЕРХ него). На тёмном фоне это ещё читалось, а поверх полосы «с меткой
            # Nansen» золотое по синему слилось - и два разных числа выглядели одной строкой.
            # Место справа есть: `ax.margins(x=0.14)` его и оставляет.
            # И ПОДНЯТА НА ЧЕТВЕРТЬ РЯДА: на самой линии она садилась ровно туда, где стоит
            # подпись суммы этого ряда ($11.8M) - две подписи наезжали друг на друга.
            ax.text(_mx * 1.15, _pos + 0.25, ('сейчас $%s' if lang != 'en' else 'now $%s')
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
    if any(_named):
        fig.text(0.15, 0.02, ('с меткой Nansen' if lang != 'en' else 'named by Nansen'),
                 ha='left', color='#49c8ff', fontsize=8, fontproperties=fp)
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
    # ЧЬЁ ЭТО ПЛЕЧО - ВТОРОЙ ВОПРОС ПОСЛЕ «СКОЛЬКО», И ОТВЕТ ТОЖЕ ВЕЛИЧИНА. $300M толпы и
    # $300M одного фонда с именем - разные карты; метка приезжает полем `address_label`.
    # Метки не нашлось ни у кого - говорим это прямо: молчание читалось бы как «не смотрели».
    _nmd, _nn, _who = cl.get('named') or 0.0, cl.get('named_n') or 0, cl.get('named_who') or []
    _names = ', '.join(k for k, _v in _who)
    # ДЕНЬГИ ЗА ОКНОМ НАЗЫВАЕМ ВСЕГДА, КОГДА ОНИ ЕСТЬ. Карта показывает уровни вокруг цены, и
    # умолчать про остальное значило бы сказать «всего на карте $X» там, где плеча больше.
    _off, _offn, _wp = cl.get('off_usd') or 0.0, cl.get('off_n') or 0, cl.get('win_pct')
    if lang == 'en':
        L = ['%s liquidation map. Biggest cluster: $%s between $%s and $%s.'
             % (token or 'Token', _short(_sum), _price(_lo), _price(_hi)),
             'Total on the map: $%s across %d position(s).' % (_short(_tot), _shown)]
        if cl['longs'] or cl['shorts']:
            L.append('Longs $%s vs shorts $%s.' % (_short(cl['longs']), _short(cl['shorts'])))
        if _nmd and _names and _nmd >= _tot * 0.999:
            # ВСЯ КАРТА ИМЕНОВАНА - ТАК И СКАЖЕМ. Живой HYPE: метка есть у всех 45 позиций, и
            # фраза «$1.01B из $1.01B» заставляет человека сверять два одинаковых числа глазами.
            L.append('Every position on this map sits on a wallet Nansen has a name for; the '
                     'biggest: %s.' % _names)
        elif _nmd and _names:
            L.append('$%s of it sits on wallets Nansen has a name for (%d position(s)): %s.'
                     % (_short(_nmd), _nn, _names))
        elif _nmd:
            L.append('$%s of it sits on labelled wallets (%d position(s)).'
                     % (_short(_nmd), _nn))
        else:
            L.append('Nansen has no label for a single wallet on this map.')
        if cl.get('win_empty'):
            L.append('Nothing liquidates within %.0f%% of the current price, so the map shows '
                     'the full range: these levels are far away.' % (cl.get('req_pct') or
                                                                     LIQ_WINDOW * 100))
        if _off:
            L.append(('A further $%s (%d position(s)) liquidates more than %.0f%% away from the '
                      'price and is off this map.' % (_short(_off), _offn, _wp)) if _wp else
                     ('A further $%s (%d position(s)) sits outside the plotted range and is off '
                      'this map.' % (_short(_off), _offn)))
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
        if _nmd and _names and _nmd >= _tot * 0.999:
            L.append('Все позиции этой карты - на кошельках, которых Nansen знает по имени; '
                     'крупнейшие: %s.' % _names)
        elif _nmd and _names:
            L.append('Из них $%s висит на кошельках, которых Nansen знает по имени '
                     '(%d позици(й)): %s.' % (_short(_nmd), _nn, _names))
        elif _nmd:
            L.append('Из них $%s висит на кошельках с меткой (%d позици(й)).'
                     % (_short(_nmd), _nn))
        else:
            L.append('Ни у одного кошелька на этой карте метки Nansen нет.')
        if cl.get('win_empty'):
            L.append('В пределах %.0f%% от текущей цены не ликвидируется ничего, поэтому карта '
                     'показывает весь размах: эти уровни далеко.' % (cl.get('req_pct') or
                                                                     LIQ_WINDOW * 100))
        if _off:
            L.append(('Ещё $%s (%d позиц(ий)) ликвидируется дальше %.0f%% от цены - этого на '
                      'карте НЕТ.' % (_short(_off), _offn, _wp)) if _wp else
                     ('Ещё $%s (%d позиц(ий)) лежит вне нарисованного диапазона - этого на '
                      'карте НЕТ.' % (_short(_off), _offn)))
        if _no:
            # ЧЕСТНАЯ ОГОВОРКА, А НЕ МЕЛКИЙ ШРИФТ: карта по 8 позициям из 20 и карта по 20 из
            # 20 - разные карты, и человек обязан знать, какую смотрит.
            L.append('У %d позиц(ий) цены ликвидации не было - их на карте НЕТ.' % _no)
        L.append('Это уровни чужих стопов, а не прогноз. Источник: Nansen.')
    return ' '.join(L)
