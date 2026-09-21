# -*- coding: utf-8 -*-
"""test_public.py — ПРОГОН БЕЗ КЛЮЧА И БЕЗ СЕТИ. Одна команда, ничего настраивать не нужно.

    python3 tests/test_public.py

ЗАЧЕМ ОН ЗДЕСЬ. Публичная выжимка, которую нельзя запустить, - это папка с текстом. Ключ есть не
у каждого, кто откроет ссылку, а проверить утверждения README хочется сразу. Поэтому здесь
подменён РОВНО ПРОВОД (`httpx.post`) - граница процесса. Всё остальное боевое: разбор ответа,
классификация отказа, форматтеры, подпись источника, запись телеметрии, зачёт вклада.

Подмени я `_post` или `nansen_log.record`, тест проверял бы сам себя - и был бы зелёным ровно
настолько, насколько зелёной его написали.

ЧТО ЗДЕСЬ ОХРАНЯЕТСЯ (то же, что в приватном наборе на 507 проверок, но без бот-слоя):
  1. восемь классов отказа дают восемь РАЗНЫХ текстов, и ни один не читается как «всё чисто»;
  2. пустой ответ 200 и отказ площадки - разные состояния;
  3. один вызов = одна строка телеметрии с верной сценой; попадание в кэш бесплатно;
  4. 422 чинится инструкцией самой площадки, а не нашей догадкой, и ремонт ограничен;
  5. сумма в долларах ищется по соглашению имён, а цена одного токена под неё НЕ берётся;
  6. источник назван под каждым ответом;
  7. реестр сцен закрыт: чужое имя даёт scene=? и громкую строку в сводке;
  8. зачёт вклада считает людей, а повтор того же запроса в зачёт не идёт;
  9. каждая команда терминала без ключа говорит ПРИЧИНУ, а не падает и не молчит.
"""

import json
import os
import shutil
import sys
import tempfile
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

OK, FAIL = [], []


def check(name, cond, note=''):
    OK.append(name) if cond else FAIL.append(
        name + ((' — ' + str(note)[:300]) if note else ''))


# ═══════════════════════════════════════════════════════════════════════════
# СТЕНД: подменяем ПРОВОД, всё остальное боевое
# ═══════════════════════════════════════════════════════════════════════════
class Resp(object):
    """Ответ провода. Заголовки настоящие по форме: остаток кредитов приезжает в них."""

    def __init__(self, status=200, payload=None, remaining=None, text=''):
        self.status_code = status
        self._payload = payload if payload is not None else []
        self.text = text or json.dumps(self._payload)
        self.headers = {}
        if remaining is not None:
            self.headers['x-nansen-credits-remaining'] = str(remaining)

    def json(self):
        return self._payload


class Wire(object):
    """Подставной провод. Помнит, сколько раз его звали и каким телом."""

    def __init__(self, plan):
        self.plan = plan
        self.bodies = []

    def post(self, url, headers=None, json=None, timeout=None, **kw):
        self.bodies.append(dict(json or {}))
        r = self.plan(str(url).split('/api/')[-1], json)
        if isinstance(r, Exception):
            raise r
        return r


def env():
    """Свежее окружение: своя база зачёта, свой каталог телеметрии, свой кэш.

    КАЖДАЯ ПРОВЕРКА НАЧИНАЕТ С ЧИСТОГО ЛИСТА, иначе «одна строка на вызов» превратилась бы в
    проверку остатков предыдущей.
    """
    tmp = tempfile.mkdtemp(prefix='nansen_public_test_')
    for m in ('nansen_api', 'nansen_log', 'db'):
        sys.modules.pop(m, None)
    os.environ['NANSEN_API_KEY'] = 'test-key-not-a-real-one'
    os.environ['NANSEN_DB_PATH'] = os.path.join(tmp, 'ledger.db')
    import db
    db.set_path('main', os.path.join(tmp, 'ledger.db'))
    import nansen_log as T
    T.TELE_DIR = os.path.join(tmp, 'tele')
    T.CREDITS_FILE = os.path.join(tmp, 'credits.json')
    import nansen_api as N
    N._CACHE = os.path.join(tmp, 'cache.json')
    N.SCHEMA_FILE = os.path.join(tmp, 'schema.json')
    N._SCHEMA = None
    N._CREDITS['remaining'] = None
    return N, T, tmp


def rows(T):
    return T.read_day(T._day()) or []


# ═══════════════════════════════════════════════════════════════════════════
def t_eight_refusals_are_eight_texts():
    """ВОСЕМЬ СОСТОЯНИЙ - ВОСЕМЬ ТЕКСТОВ, ни один сбой не читается как «всё чисто».

    Исходная поломка, из которой вырос весь слой: клиент возвращал `None` на любой не-200,
    список пустел, и «кончились кредиты», «придержали по частоте», «таймаут», «наш кривой
    запрос» и «данных правда нет» становились неразличимы. Человек читал одно и то же
    «ничего не найдено» - то есть ПУСТОТА ВЫДАВАЛАСЬ ЗА ПРОВЕРКУ. На метках кошелька это
    прямо опасно: «меток нет» звучит как «адрес чистый».
    """
    N, T, tmp = env()
    try:
        seen = {}
        for cls in ('nokey', 'nocredits', 'ratelimit', 'timeout', 'badreq', 'unsupported',
                    'http', 'empty'):
            txt = N.refusal(cls, 'ru', what='меток по этому адресу')
            check('REFUSAL: %s непустой' % cls, bool(txt and len(txt) > 20), txt)
            seen[cls] = txt
        check('REFUSAL: восемь РАЗНЫХ текстов', len(set(seen.values())) == 8,
              'совпали: %d уникальных из 8' % len(set(seen.values())))
        # НИ ОДИН ОТКАЗ НЕ ИМЕЕТ ПРАВА ЧИТАТЬСЯ КАК ЧИСТОТА
        for cls, txt in seen.items():
            if cls == 'empty':
                continue
            check('REFUSAL: %s не выглядит как «чисто»' % cls,
                  'чист' not in txt.lower(), txt[:120])
        check('REFUSAL: кончившиеся кредиты названы прямо',
              'кредит' in seen['nocredits'].lower(), seen['nocredits'])
        check('REFUSAL: 422 назван НАШЕЙ виной, а не отказом площадки',
              'запрос' in seen['badreq'].lower(), seen['badreq'])
        check('REFUSAL: и на английском тоже есть',
              N.refusal('nocredits', 'en') != N.refusal('nocredits', 'ru'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_empty_is_not_error_and_error_is_not_empty():
    """ПУСТОЙ ОТВЕТ 200 И ОТКАЗ ПЛОЩАДКИ - РАЗНЫЕ СОСТОЯНИЯ, и они не имеют права слипнуться."""
    N, T, tmp = env()
    import httpx
    keep = httpx.post
    try:
        httpx.post = Wire(lambda p, b: Resp(200, [])).post
        with T.scene('smart_flows'):
            out = N.smart_money_netflow(per_page=3)
            why_empty = T.outcome()
        check('STATE: пусто это пусто', out == [] and why_empty == 'empty', (out, why_empty))
        N._CACHE = os.path.join(tmp, 'c2.json')
        httpx.post = Wire(lambda p, b: Resp(402, text='{"error":"no credits"}')).post
        with T.scene('smart_flows'):
            N.smart_money_netflow(per_page=3)
            why_402 = T.outcome()
        check('STATE: 402 это кончившиеся кредиты', why_402 == 'nocredits', why_402)
        N._CACHE = os.path.join(tmp, 'c3.json')
        httpx.post = Wire(lambda p, b: httpx.TimeoutException('слишком долго')).post
        with T.scene('smart_flows'):
            N.smart_money_netflow(per_page=3)
            why_to = T.outcome()
        check('STATE: таймаут это таймаут', why_to == 'timeout', why_to)
        check('STATE: три состояния не слиплись',
              len({why_empty, why_402, why_to}) == 3, (why_empty, why_402, why_to))
    finally:
        httpx.post = keep
        shutil.rmtree(tmp, ignore_errors=True)


def t_one_call_one_row_and_cache_is_free():
    """ОДИН ВЫЗОВ = ОДНА СТРОКА С ВЕРНОЙ СЦЕНОЙ. Повтор из кэша - строка с cache=1 и НОЛЬ
    кредитов: иначе расход рос бы от бесплатных попаданий, и планировать его было бы нельзя."""
    N, T, tmp = env()
    import httpx
    keep = httpx.post
    try:
        w = Wire(lambda p, b: Resp(200, [{'token_symbol': 'AAA', 'chain': 'base',
                                          'net_flow_24h_usd': 12345}], remaining=70000))
        httpx.post = w.post
        with T.scene('smart_flows', 4242):
            N.smart_money_netflow(per_page=3)
        r = rows(T)
        check('TELE: ровно одна строка', len(r) == 1, len(r))
        check('TELE: сцена записана верно', r and r[0].get('scene') == 'smart_flows', r[:1])
        check('TELE: провод дёрнули один раз', len(w.bodies) == 1, len(w.bodies))
        with T.scene('smart_flows', 4242):
            N.smart_money_netflow(per_page=3)
        r2 = rows(T)
        check('TELE: попадание в кэш тоже записано', len(r2) == 2, len(r2))
        check('TELE: и помечено как кэш', r2 and str(r2[-1].get('cache')) in ('1', 'True'),
              r2[-1:])
        check('TELE: провод НЕ дёрнули второй раз', len(w.bodies) == 1, len(w.bodies))
        # ЧУЖОГО ИДЕНТИФИКАТОРА В ВЫГРУЗКЕ НЕТ: телеметрия уезжает наружу, люди - нет
        raw = json.dumps(r2, ensure_ascii=False)
        check('TELE: в строках нет человека', '4242' not in raw, raw[:200])
    finally:
        httpx.post = keep
        shutil.rmtree(tmp, ignore_errors=True)


def t_scene_registry_is_closed():
    """РЕЕСТР СЦЕН ЗАКРЫТ. Список, в который можно молча дописать, перестаёт быть списком:
    расход виден, а ЧЕЙ он - нет. Живой случай: три экрана работали и жгли кредиты, а их имён
    в реестре не было - в суточной сводке они лежали строкой «? 5 кр»."""
    N, T, tmp = env()
    try:
        check('SCENES: реестр непустой', len(T.SCENES) >= 15, len(T.SCENES))
        with T.scene('чужое-имя-которого-нет-в-реестре', 9):
            b = T.box()
        check('SCENES: чужое имя не принято', (b or {}).get('scene') in (None, ''), b)
        with T.scene('smart_flows', 9):
            b2 = T.box()
        check('SCENES: своё имя принято', (b2 or {}).get('scene') == 'smart_flows', b2)
        txt = T.daily_text()
        check('SCENES: сводка собирается', bool(txt), txt)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_422_is_repaired_by_the_providers_own_words():
    """422 ЧИНИТСЯ ИНСТРУКЦИЕЙ ПЛОЩАДКИ, А НЕ НАШЕЙ ДОГАДКОЙ.

    У части эндпоинтов схема тела написана по образцу соседей: живым ключом её никто не
    снимал. Nansen при этом сообщает, что не так, машиночитаемо («Field 'x' is not
    recognized», «Required field 'body -> date' is missing», «Did you mean 'BUY'?»). Это
    инструкция, а не жалоба, и она исполняется. Границы: потолок кругов, обязательное поле
    подставляем только из тех, что умеем построить сами, не-422 не ремонтируется вовсе.
    """
    N, T, tmp = env()
    import httpx
    keep = httpx.post
    try:
        seen = []

        def plan(p, b):
            seen.append(dict(b or {}))
            if len(seen) == 1:
                return Resp(422, text=json.dumps(
                    {'error': 'Unknown field',
                     'message': "Field 'order_by' is not recognized"}))
            if len(seen) == 2:
                return Resp(422, text=json.dumps(
                    {'error': 'Missing field',
                     'message': "Required field 'body -> date' is missing"}))
            return Resp(200, [{'address_label': 'Whale 1', 'side': 'LONG',
                               'position_value_usd': 1200000, 'leverage': 5,
                               'liquidation_price': 48000}])
        httpx.post = Wire(plan).post
        got = N.perp_positions('BTC')
        check('FIX: после ремонта данные приехали', len(got) == 1, got)
        check('FIX: лишнее поле убрано по слову площадки', 'order_by' not in seen[-1], seen[-1])
        check('FIX: обязательное подставлено', 'date' in seen[-1], seen[-1])
        # ПОЛЕ НАЗЫВАЕТСЯ token_symbol - снято живой пробой 19.09 (мы посылали `token` по
        # образцу соседних эндпоинтов и получали 422 на каждом тапе). Ремонт обязан сохранять
        # НАШ аргумент, что бы он ни правил в остальном теле.
        check('FIX: наш аргумент не потерян',
              seen[-1].get('token_symbol') == 'BTC', seen[-1])
        blk = N.perp_positions_block(got, 'BTC', 'ru')
        check('FIX: человек видит цену ликвидации', blk and 'ликв' in blk, blk)
        # ПОТОЛОК КРУГОВ: вечное 422 не молотит кредиты бесконечно
        N._CACHE = os.path.join(tmp, 'c2.json')
        N._SCHEMA = None
        cnt = []

        def plan_bad(p, b):
            cnt.append(1)
            return Resp(422, text=json.dumps(
                {'error': 'Unknown field', 'message': "Field 'order_by' is not recognized"}))
        httpx.post = Wire(plan_bad).post
        with T.scene('perp_positions'):
            out = N.perp_positions('ETH')
            why = T.outcome()
        check('FIX: вечное 422 отдаёт пусто', out == [], out)
        check('FIX: число попыток ограничено', len(cnt) <= N._FIX_ROUNDS + 1, len(cnt))
        check('FIX: и причина названа нашей', why == 'badreq', why)
        # ПОДСКАЗКУ ЗНАЧЕНИЯ ТОЖЕ ИСПОЛНЯЕМ
        b5, _why5 = N._apply_hint({'buy_or_sell': 'buy'}, json.dumps(
            {'error': 'Invalid value',
             'message': "Invalid value 'buy' for body -> buy_or_sell. Did you mean 'BUY'?"}))
        check('FIX: подсказка значения применена', b5 == {'buy_or_sell': 'BUY'}, b5)
    finally:
        httpx.post = keep
        shutil.rmtree(tmp, ignore_errors=True)


def t_money_field_is_found_or_named():
    """СУММА: либо число, либо СЛОВА о том, что поля нет. Прочерк в каждой строке - не ответ.

    Живой случай: экран сделок вернул двенадцать строк, тикеры и адреса читались, а объём во
    всех двенадцати был прочерком - значит имя денежного поля у эндпоинта другое, чем мы
    читали. Теперь сумма ищется по соглашению имён Nansen (денежные поля кончаются на `_usd`),
    а если её нет ни у одной строки, блок говорит это словом и печатает реальные поля ответа.
    """
    N, T, tmp = env()
    try:
        r = [{'token_bought_symbol': 'AAA', 'chain': 'base',
              'token_bought_amount_usd': 48250, 'address_label': 'Smart Trader 1'}]
        blk = N.sm_trades_block(r, None, 'ru')
        check('MONEY: сумма найдена по соглашению', blk and '$?' not in blk, blk)
        check('MONEY: и это она', blk and '48' in blk, blk)
        blk2 = N.sm_trades_block([{'token_bought_symbol': 'B', 'tx_hash': '0xdead'}], None, 'ru')
        check('MONEY: отсутствие поля названо словом', blk2 and 'не приехал' in blk2, blk2)
        check('MONEY: и названы реальные поля', blk2 and 'tx_hash' in blk2, blk2)
        # ЦЕНА ОДНОГО ТОКЕНА - НЕ ОБЪЁМ СДЕЛКИ. Подставить её значит показать НЕВЕРНОЕ число,
        # а это хуже видимого прочерка: $0.99 читается как настоящий объём.
        v, f = N._usd_any({'token_symbol': 'C', 'price_usd': 0.9998})
        check('MONEY: price_usd не выдаётся за объём', v is None and f is None, (v, f))
        v2, _ = N._usd_any({'unrealized_pnl_usd': 1000, 'fee_usd': 3})
        check('MONEY: pnl и комиссия тоже не объём', v2 is None, v2)
        v3, f3 = N._usd_any({'value_usd': 10, 'zzz_usd': 999}, ('value_usd',))
        check('MONEY: названное поле в приоритете', (v3, f3) == (10, 'value_usd'), (v3, f3))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_source_is_named():
    """ИСТОЧНИК НАЗВАН ПОД КАЖДЫМ ОТВЕТОМ, и вместе с ним - свежесть. Ответ из кэша обязан
    говорить, что он старше: цифра без времени на торговых данных бесполезна."""
    N, T, tmp = env()
    try:
        t1 = N.with_source('строка', 'ru')
        check('SRC: имя источника есть', 'Nansen' in t1, t1)
        t2 = N.with_source('строка', 'ru', age_sec=1800)
        check('SRC: старый ответ помечен', t2 != t1, (t1, t2))
        t3 = N.with_source('line', 'en')
        check('SRC: и на английском', 'Nansen' in t3, t3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_ledger_counts_people_not_spam():
    """ЗАЧЁТ ВКЛАДА: место считается по кредитам, а повтор того же запроса в зачёт не идёт.

    Антинакрутка не блокирует - именно не засчитывает, и это объявлено заранее. Наружу при
    этом не уходит ни один идентификатор: лидерборд без имён, имена видит только владелец.
    """
    N, T, tmp = env()
    import httpx
    keep = httpx.post
    try:
        httpx.post = Wire(lambda p, b: Resp(200, [{'token_symbol': 'A', 'chain': 'base',
                                                   'net_flow_24h_usd': 1}], remaining=70000)).post
        for uid in (111, 111, 222):
            N._CACHE = os.path.join(tmp, 'c%d.json' % uid)
            with T.scene('smart_flows', uid):
                N.smart_money_netflow(per_page=uid)
        board = T.leaderboard() if hasattr(T, 'leaderboard') else None
        mine = T.my_stats(111)
        check('LEDGER: человек посчитан', mine and mine.get('calls', 0) >= 1, mine)
        txt = T.contrib_text(111, 'ru')
        check('LEDGER: личный зачёт собирается', bool(txt), txt)
        if board is not None:
            raw = json.dumps(board, ensure_ascii=False, default=str)
            check('LEDGER: в лидерборде нет id людей',
                  '111' not in raw and '222' not in raw, raw[:200])
        # ПОВТОР ТОГО ЖЕ ЗАПРОСА НЕ ЗАСЧИТЫВАЕТСЯ
        N._CACHE = os.path.join(tmp, 'again.json')
        with T.scene('smart_flows', 333):
            N.smart_money_netflow(per_page=777)
        N._CACHE = os.path.join(tmp, 'again2.json')
        with T.scene('smart_flows', 333):
            N.smart_money_netflow(per_page=777)
        st = T.my_stats(333)
        check('LEDGER: повтор в зачёт не пошёл', (st or {}).get('skipped', 0) >= 1, st)
    finally:
        httpx.post = keep
        shutil.rmtree(tmp, ignore_errors=True)


def t_cli_without_key_says_why():
    """КАЖДАЯ КОМАНДА ТЕРМИНАЛА БЕЗ КЛЮЧА ГОВОРИТ ПРИЧИНУ, а не падает и не молчит.

    Это проверка ровно того, что увидит человек, открывший ссылку и запустивший выжимку
    первый раз: ключа у него нет. «Упало с трейсбеком» и «напечатало пустоту» - два способа
    соврать про причину; должен быть текст «ключа нет, запрос не ушёл».
    """
    N, T, tmp = env()
    import httpx
    keep = httpx.post
    keep_key = os.environ.pop('NANSEN_API_KEY', None)
    try:
        sys.modules.pop('nansen_api', None)
        sys.modules.pop('cli', None)
        import nansen_api as N2
        N2._CACHE = os.path.join(tmp, 'cli.json')

        def _boom(*a, **k):
            raise AssertionError('без ключа НИ ОДИН запрос уходить не должен')
        httpx.post = _boom
        import cli
        cli.N = N2
        import io
        names = [c[0] for c in cli.CMDS]
        check('CLI: команд достаточно', len(names) >= 15, names)
        bad = []
        for name, fn, _ru, _en in cli.CMDS:
            buf, old = io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                fn(['base', '0x0000000000000000000000000000000000000000', '7'])
            except SystemExit:
                pass
            except Exception as e:
                bad.append('%s: %s: %s' % (name, type(e).__name__, str(e)[:80]))
            finally:
                sys.stdout = old
            out = buf.getvalue()
            if name in ('doctor', 'scenes', 'cost'):
                continue
            if not out.strip():
                bad.append('%s: НИЧЕГО не напечатал' % name)
            # И ПРИЧИНА ОБЯЗАНА БЫТЬ ИМЕННО «НЕТ КЛЮЧА», а не «данных нет».
            # Это поймало живую ошибку: картиночные команды читали причину ПОСЛЕ выхода из
            # сцены, коробка причин к тому моменту уже пуста, и без ключа человек видел
            # «Nansen ответил, но данных нет» - то есть выжимка делала ровно то, против чего
            # написана: выдавала пустоту за проверку.
            elif 'NANSEN_API_KEY' not in out:
                bad.append('%s: причина не «нет ключа», а %r' % (name, out.strip()[:90]))
        check('CLI: ни одна команда не упала, не промолчала и назвала ВЕРНУЮ причину',
              not bad, bad[:6])
        buf, old = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            cli.c_doctor([])
        finally:
            sys.stdout = old
        check('CLI: doctor честно говорит про отсутствие ключа',
              'НЕТ' in buf.getvalue(), buf.getvalue()[:200])
    finally:
        httpx.post = keep
        if keep_key:
            os.environ['NANSEN_API_KEY'] = keep_key
        shutil.rmtree(tmp, ignore_errors=True)


def t_docs_are_here_and_name_prices():
    """DOCS/ASSETS ARE COMPLETE. The public package must contain every path promised by README,
    including the reproducible social card and version-controlled Wiki source."""
    required = (
        'README.md', 'MANIFEST.md', 'docs/scenarios.md', 'docs/telemetry_spec.md',
        'docs/PROJECT_STATUS.md', 'docs/RECORDING_RUNBOOK.md', 'docs/ENDPOINT_SWEEP.md',
        'docs/wiki/Home.md', 'docs/wiki/Status.md', 'docs/wiki/Roadmap.md',
        'docs/wiki/Demo.md', 'docs/wiki/Architecture.md', 'docs/wiki/_Sidebar.md',
        'tools/render_social_preview.py', 'tools/nansen_endpoint_sweep.py',
        'tools/nansen_trade_probe.py', 'tools/nansen_catalog.py',
        'assets/social-preview.png',
    )
    for rel in required:
        p = os.path.join(_ROOT, rel)
        check('DOCS: %s exists' % rel, os.path.exists(p), 'missing file')
    sc = os.path.join(_ROOT, 'docs', 'scenarios.md')
    if os.path.exists(sc):
        txt = open(sc, encoding='utf-8').read()
        check('DOCS: prices are named', txt.count('**Цена:**') >= 6, txt.count('**Цена:**'))
        check('DOCS: reasons are named', txt.count('**Зачем:**') >= 5, txt.count('**Зачем:**'))
    readme = os.path.join(_ROOT, 'README.md')
    if os.path.exists(readme):
        txt = open(readme, encoding='utf-8').read()
        for rel in ('docs/PROJECT_STATUS.md', 'docs/RECORDING_RUNBOOK.md',
                    'docs/ENDPOINT_SWEEP.md', 'assets/social-preview.png', 'docs/wiki/'):
            check('DOCS: README maps %s' % rel, rel in txt, rel)
    preview = os.path.join(_ROOT, 'assets', 'social-preview.png')
    if os.path.exists(preview):
        import struct
        data = open(preview, 'rb').read(24)
        check('DOCS: social preview is PNG', data.startswith(b'\x89PNG\r\n\x1a\n'), data[:8])
        check('DOCS: social preview is exactly 1280x640',
              len(data) >= 24 and struct.unpack('>II', data[16:24]) == (1280, 640),
              data[16:24])
    man = os.path.join(_ROOT, 'MANIFEST.md')
    if os.path.exists(man):
        txt = open(man, encoding='utf-8').read()
        check('DOCS: manifest says byte-for-byte', 'байт-в-байт' in txt, txt[:200])
        for rel in required[4:]:
            check('DOCS: manifest tracks %s' % rel, ('`%s`' % rel) in txt, rel)


def t_public_hygiene_and_live_tools_are_safe_by_default():
    """Публичный repo не только чист сейчас — защиты ловят runtime state и tools не тратят
    calls без явного человеческого флага."""
    import importlib.util
    import io

    # .gitignore: комментарий только отдельной строкой. Inline `pattern # comment` git не
    # понимает, и прежние runtime files не игнорировались вообще.
    gi = open(os.path.join(_ROOT, '.gitignore'), encoding='utf-8').read().splitlines()
    required = {'nansen_tele/', 'nansen_credits.json', 'nansen_credits.json.pending',
                'nansen_schema.json',
                'nansen_asks.json', 'nansen_cache.json', 'nansen_pm_refs.json',
                'nansen_meridian_corpus.jsonl', 'nansen_endpoint_sweep_state.json',
                'nansen_local.db'}
    check('PUBLIC: all runtime patterns are ignored', required <= set(gi),
          sorted(required - set(gi)))
    check('PUBLIC: generated social preview is explicitly tracked',
          '!assets/social-preview.png' in gi, gi)
    check('PUBLIC: patterns have no inline comments',
          not [x for x in gi if x and not x.startswith('#') and ' #' in x], gi)

    # Scrubber обязан ловить сам ФАКТ runtime file, а не пропускать его содержимое.
    sp = os.path.join(_ROOT, 'scrub.py')
    spec = importlib.util.spec_from_file_location('_scrub_test', sp)
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    old_here = S.HERE
    temp = tempfile.mkdtemp(prefix='scrub_runtime_')
    try:
        S.HERE = temp
        open(os.path.join(temp, 'nansen_cache.json'), 'w').write('{}')
        open(os.path.join(temp, 'nansen_credits.json.pending'), 'w').write('{')
        open(os.path.join(temp, 'nansen_endpoint_sweep_state.json'), 'w').write('{}')
        check('PUBLIC: scrubber ловит runtime state',
              S._runtime_state() == ['nansen_cache.json', 'nansen_credits.json.pending',
                                     'nansen_endpoint_sweep_state.json'], S._runtime_state())
    finally:
        S.HERE = old_here
        shutil.rmtree(temp, ignore_errors=True)

    # Live tools: без --run только plan. Провод подменён на взрыв — если вызов уйдёт, тест
    # упадёт, а не поверит напечатанному «nothing sent».
    import httpx
    keep, keep_get = httpx.post, httpx.get
    httpx.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network call without --run'))
    httpx.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network GET without --run'))
    loaded = {}
    try:
        for rel, args in (('tools/nansen_live_smoke.py', []),
                          ('tools/nansen_meridian_corpus.py', ['--max-calls', '10']),
                          ('tools/nansen_endpoint_sweep.py', ['--profile', 'complete']),
                          ('tools/nansen_trade_probe.py', ['quote', '--wallet',
                                                           '0x1f9090aaE28b8a3dCeaDf281B0F12828e676c326'])):
            spec = importlib.util.spec_from_file_location('_tool_' + os.path.basename(rel),
                                                          os.path.join(_ROOT, rel))
            M = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(M)
            loaded[rel] = M
            buf, old = io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                rc = M.main(args)
            finally:
                sys.stdout = old
            check('PUBLIC: %s без --run не ходит в сеть' % rel, rc == 0, buf.getvalue())
            check('PUBLIC: %s печатает план' % rel,
                  'PLAN' in buf.getvalue() or 'Nothing sent' in buf.getvalue(), buf.getvalue())
        # CORPUS RESUME: временный failure не считается done, иначе нулевой cell навсегда
        # отравляет ranking; ok/empty завершены. И page=100 помечается partial, не «все».
        corpus = loaded['tools/nansen_meridian_corpus.py']
        old_out = corpus.OUT
        ctmp = tempfile.mkdtemp(prefix='corpus_state_')
        try:
            corpus.OUT = os.path.join(ctmp, 'c.jsonl')
            base = {'day': '2026-09-19', 'chain': 'base', 'token': '0xabc', 'side': 'BUY'}
            corpus._append(dict(base, reason='timeout'))
            check('PUBLIC: временный corpus failure будет retry', not corpus._done(),
                  corpus._done())
            corpus._append(dict(base, reason='ok'))
            check('PUBLIC: успешный cell завершён', bool(corpus._done()), corpus._done())
            agg = corpus._aggregate([{'value_usd': 1}] * 100)
            check('PUBLIC: top-100 cell помечен partial', agg['partial_top100'] == 1, agg)
            check('PUBLIC: hard cap меньше discovery отвергается',
                  corpus.main(['--run', '--max-calls', '1']) == 1)
            # Минимальный разрешённый cap=2 включает РОВНО оба discovery-вызова. `sm_dex_trades`
            # использует обычный _post (схема live-verified), не repair-loop до четырёх сетевых
            # попыток: иначе hard cap существовал только в печати.
            keep_key = corpus.N._key
            keep_net = corpus.N.smart_money_netflow
            keep_dex = corpus.N.sm_dex_trades
            calls = []
            try:
                corpus.N._key = lambda: 'test'
                corpus.N.smart_money_netflow = lambda per_page=100: (calls.append('net'), [])[-1]
                corpus.N.sm_dex_trades = lambda chains=None, per_page=100: (calls.append('dex'), [])[-1]
                corpus.main(['--run', '--max-calls', '2'])
            finally:
                corpus.N._key = keep_key
                corpus.N.smart_money_netflow = keep_net
                corpus.N.sm_dex_trades = keep_dex
            check('PUBLIC: cap=2 делает не больше двух client/network attempts',
                  calls == ['net', 'dex'], calls)
            src = open(os.path.join(_ROOT, 'nansen_api.py'), encoding='utf-8').read()
            _frag = src[src.index('def sm_dex_trades'):src.index('def sm_perp_trades')]
            check('PUBLIC: capped discovery не использует repair retries',
                  '_post_fix(' not in _frag and '_post(' in _frag, _frag[:200])
        finally:
            corpus.OUT = old_out
            shutil.rmtree(ctmp, ignore_errors=True)

        # LIVE SMOKE: строка screener без market_id должна остановиться ДО holder request.
        spec = importlib.util.spec_from_file_location('_smoke_id_test',
                    os.path.join(_ROOT, 'tools/nansen_live_smoke.py'))
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        keep_key, keep_scr, keep_rep = smoke.N._key, smoke.N.pm_market_screener, smoke.N.pm_reputation
        called = []
        try:
            smoke.N._key = lambda: 'test'
            smoke.N.pm_market_screener = lambda per_page=5: [{'question': 'schema drift'}]
            smoke.N.pm_reputation = lambda *a, **k: called.append(1)
            buf, old = io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                rc = smoke.main(['--run'])
            finally:
                sys.stdout = old
            check('PUBLIC: smoke без market_id даёт точный FAIL', rc == 3, buf.getvalue())
            check('PUBLIC: и не тратит holder request на None', not called, called)
        finally:
            smoke.N._key, smoke.N.pm_market_screener, smoke.N.pm_reputation = \
                keep_key, keep_scr, keep_rep
    finally:
        httpx.post, httpx.get = keep, keep_get

    # Footer «this run» считает только строки после старта процесса, не весь сегодняшний лог.
    sys.modules.pop('cli', None)
    import cli
    keep_rows, keep_left, keep_lang = cli.T.read_day, cli.N.credits_left, cli.LANG
    try:
        cli.LANG = 'en'
        cli._RUN_START = 2
        cli.T.read_day = lambda _d: [
            {'cr': 750, 'est': 0}, {'cr': 5, 'est': 0},       # старые команды сегодня
            {'cr': 3, 'est': 0},                              # текущая команда
        ]
        cli.N.credits_left = lambda: 100
        buf, old = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            cli._cost()
        finally:
            sys.stdout = old
        out = buf.getvalue()
        check('PUBLIC: footer считает один вызов этого запуска', '1 call(s)' in out, out)
        check('PUBLIC: и только его 3 кредита, не 758 за день',
              '3 measured credits' in out and '758' not in out, out)
        # matplotlib импортируется лениво внутри maker: ImportError должен стать объяснением,
        # а не traceback после успешного import oc_nansen_viz.
        buf, old = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            rc = cli._png(lambda _v: (_ for _ in ()).throw(ImportError('no matplotlib')), 'chart')
        finally:
            sys.stdout = old
        check('PUBLIC: ленивый ImportError картинки пойман', rc == 2, buf.getvalue())
        check('PUBLIC: и названа установка matplotlib', 'pip install matplotlib' in buf.getvalue(),
              buf.getvalue())
    finally:
        cli.T.read_day, cli.N.credits_left, cli.LANG = keep_rows, keep_left, keep_lang


def main():
    tests = (
        t_eight_refusals_are_eight_texts,
        t_empty_is_not_error_and_error_is_not_empty,
        t_one_call_one_row_and_cache_is_free,
        t_scene_registry_is_closed,
        t_422_is_repaired_by_the_providers_own_words,
        t_money_field_is_found_or_named,
        t_source_is_named,
        t_ledger_counts_people_not_spam,
        t_cli_without_key_says_why,
        t_docs_are_here_and_name_prices,
        t_public_hygiene_and_live_tools_are_safe_by_default,
    )
    for fn in tests:
        print('· ' + fn.__name__)
        try:
            fn()
        except Exception as e:
            import traceback
            FAIL.append('%s УПАЛ: %s: %s\n%s' % (fn.__name__, type(e).__name__, e,
                                                 traceback.format_exc()[-700:]))
    print('')
    for f in FAIL:
        print('FAIL  ' + f)
    print('ИТОГО: %d PASS / %d FAIL' % (len(OK), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
