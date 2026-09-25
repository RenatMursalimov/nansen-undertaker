#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/sentinel_funding_unit.py — ЕДИНИЦА ФАНДИНГА ВЫВОДИТСЯ СВЕРКОЙ ПЛОЩАДОК.

═══ ЗАЧЕМ ЭТОТ ИНСТРУМЕНТ СУЩЕСТВУЕТ ═══
Долг верификации №1 дозорного: Variational отдаёт `funding_rate` БЕЗ ЕДИНИЦЫ, и два её же
источника противоречат живому ответу. Справка площадки говорит «RWA/TradFi фиксировано 0.005%
за 8-часовой интервал», а в ответе у MRNA стоит 0.442690, у MSTR 0.455416, у US500 ноль. Ни
«процент за интервал», ни «0.005 фикс» замеру не соответствуют. Поэтому число девять кругов
ехало в карточку под ИМЕНЕМ ПОЛЯ и без приведения к годовым: назвать проценты процентами,
не измерив, — это выдумать человеку цифру, по которой он считает деньги.

═══ ИДЕЯ ЗАМЕРА ═══
Фандинг ОДНОГО актива на разных площадках не может отличаться на два порядка — арбитраж бы это
выел. У Hyperliquid единица известна ДОКУМЕНТАЛЬНО (доля за час). Значит отношение чисел
Variational к приведённым числам Hyperliquid по ДЕСЯТКАМ общих тикеров и есть искомый масштаб.
Медиана, а не одна пара: отдельная пара расходится по настоящей рыночной причине, медиана по
десяткам — это уже единица измерения.

═══ ПОЧЕМУ САМОКАЛИБРОВКА, А НЕ СРАЗУ ВЕРДИКТ ═══
Метод может соврать: площадки правда торгуют по-разному, лента могла протухнуть, тикеры —
оказаться однофамильцами. Поэтому инструмент СНАЧАЛА проверяет метод там, где ответ известен
заранее: в ленте Lighter есть строки `exchange=hyperliquid`, то есть ПЕРЕСКАЗ площадки, чью
единицу мы знаем. Отношение обязано лечь в ×8.000 (Lighter публикует долю за 8 часов) с почти
нулевым разбросом. Не легло — значит сегодня метод не работает, и инструмент ОТКАЗЫВАЕТСЯ
судить о Variational вместо того, чтобы выдать правдоподобное число.
Эталон внутри измерения — то же, что «эталон детектора» в тестах проекта: проверка, которая
не может сама себя проверить, однажды зеленеет на пустоте.

Запуск (сети нужен доступ к трём площадкам, ключей не требует):
    python3 tools/sentinel_funding_unit.py
    python3 tools/sentinel_funding_unit.py --json      # машиночитаемо
"""

import json
import statistics
import sys
import urllib.error
import urllib.request

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/131.0.0.0 Safari/537.36')
VAR = 'https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats'
HL = 'https://api.hyperliquid.xyz/info'
LG = 'https://mainnet.zklighter.elliot.ai/api/v1/funding-rates'

#: ЧТО ЗНАЕМ ДОКУМЕНТАЛЬНО. Hyperliquid начисляет фандинг ЕЖЕЧАСНО, и поле `funding` — доля за
#: час (не процент). Это единственная точка опоры всего замера, поэтому она названа отдельно.
HL_INTERVAL_S = 3600
#: ЧЕГО ЖДЁМ ОТ КАЛИБРОВКИ: Lighter публикует долю за 8 часов (выведено этим же методом 26.09,
#: 95 из 95 пар). Здесь это ЭТАЛОН — если сверка не воспроизводит его, метод сломан.
CAL_EXPECT = 8.0
CAL_TOL = 0.25          # ±25%: рыночного расхождения в пересказе быть не должно вовсе


def _get(url, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        'User-Agent': UA, 'Accept': 'application/json',
        'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def read_variational():
    """-> {TICKER: (funding_raw, interval_s)}."""
    out = {}
    for x in (_get(VAR).get('listings') or []):
        fr, iv = _num(x.get('funding_rate')), int(x.get('funding_interval_s') or 0)
        if fr is None or not iv:
            continue
        out[str(x.get('ticker') or '').upper()] = (fr, iv)
    return out


def read_hyperliquid():
    """-> {TICKER: доля за ЧАС}. Единица ДОКУМЕНТИРОВАНА, это наша опора."""
    d = _get(HL, {'type': 'metaAndAssetCtxs'})
    out = {}
    for u, c in zip(d[0]['universe'], d[1]):
        f = _num(c.get('funding'))
        if f is not None:
            out[str(u['name']).upper()] = f
    return out


def read_lighter():
    """-> {exchange: {TICKER: rate}}. В ответе лежат ставки НЕСКОЛЬКИХ бирж (поле `exchange`)."""
    out = {}
    for r in (_get(LG).get('funding_rates') or []):
        v = _num(r.get('rate'))
        if v is None:
            continue
        out.setdefault(str(r.get('exchange') or '?').lower(), {})[
            str(r.get('symbol') or '').upper()] = v
    return out


def ratios(a, b, interval_s):
    """Отношения a/b по общим тикерам, где b приведён к интервалу `interval_s`. -> (список, n).

    НУЛИ ОТСЕКАЕМ С ДВУХ СТОРОН: ноль в знаменателе даёт бесконечность, ноль в числителе —
    ложный «масштаб 0». У фандинга ноль это штатное значение (US500 в живом ответе), а не сбой.
    """
    ks = []
    for t, av in a.items():
        bv = b.get(t)
        if bv is None or abs(bv) < 1e-12 or abs(av) < 1e-12:
            continue
        ks.append(abs(av / (bv * (interval_s / float(HL_INTERVAL_S)))))
    return ks, len(ks)


def verdict(ks, tight_mult=2.0):
    """Медиана и плотность облака. -> dict.

    ПЛОТНОСТЬ ВАЖНЕЕ МЕДИАНЫ. Медиана есть всегда, даже у случайного шума; а вот «сколько пар
    легло рядом с медианой» отвечает на вопрос, измерили мы единицу или получили среднее от
    разных рынков. Без этого числа вердикт был бы догадкой с двумя знаками после запятой.
    """
    if not ks:
        return {'n': 0}
    med = statistics.median(ks)
    tight = sum(1 for k in ks if med / tight_mult <= k <= med * tight_mult)
    q = statistics.quantiles(ks, n=4) if len(ks) >= 4 else [med, med, med]
    return {'n': len(ks), 'median': med, 'q1': q[0], 'q3': q[2],
            'tight': tight, 'tight_share': tight / float(len(ks))}


YEAR_S = 365 * 24 * 3600


def hypotheses(interval_s):
    """Гипотезы о единице ДЛЯ ЭТОГО интервала. -> ((множитель, название), …).

    ЗАВИСИМОСТЬ ОТ ИНТЕРВАЛА - СУТЬ ЗАМЕРА, А НЕ ДЕТАЛЬ. Гипотеза «годовая ставка» предсказывает
    РАЗНОЕ число для 4-часовых и 8-часовых инструментов (2190 и 1095 интервалов в году), а все
    остальные гипотезы - одно и то же. Поэтому проверка на двух интервалах сразу отличает
    настоящую единицу от подогнанной константы: одна константа не может объяснить обе группы.
    Названия - словами, потому что вердикт читает человек: «×2190» не отвечает на вопрос «что
    писать в карточке», а «годовая доля» отвечает.
    """
    per_year = YEAR_S / float(interval_s or HL_INTERVAL_S)
    return ((1.0, 'доля за интервал (0.0004 = 0.04% за интервал)'),
            (100.0, 'ПРОЦЕНТ за интервал (0.04 = 0.04% за интервал)'),
            (10000.0, 'базисные пункты за интервал'),
            (per_year, 'ГОДОВАЯ ДОЛЯ: 0.1095 = 10.95%% годовых (в году %.0f интервалов)'
             % per_year),
            (per_year * 100.0, 'годовой ПРОЦЕНТ'))


def name_unit(med, interval_s):
    """Ближайшая гипотеза к измеренной медиане. -> (множитель, название, во сколько раз мимо)."""
    hs = hypotheses(interval_s)
    best = min(hs, key=lambda h: abs(_log(med) - _log(h[0])))
    off = max(med / best[0], best[0] / med) if med and best[0] else float('inf')
    return best[0], best[1], off


def _log(x):
    import math
    return math.log(max(1e-12, abs(float(x or 0))))


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    as_json = '--json' in argv
    rep = {}
    try:
        V, H, L = read_variational(), read_hyperliquid(), read_lighter()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
        # ОТКАЗ НАЗЫВАЕТ СЕБЯ И НЕ ПРИТВОРЯЕТСЯ ВЕРДИКТОМ.
        print('ЗАМЕР НЕ СДЕЛАН: площадка не ответила (%s: %s)' % (type(e).__name__, str(e)[:120]))
        return 2
    rep['sizes'] = {'variational': len(V), 'hyperliquid': len(H),
                    'lighter_exchanges': {k: len(v) for k, v in L.items()}}

    # ── ШАГ 1. КАЛИБРОВКА МЕТОДА НА ИЗВЕСТНОМ ОТВЕТЕ ──────────────────────────────────────
    cal_src = L.get('hyperliquid') or {}
    cal_ks, cal_n = ratios(cal_src, H, HL_INTERVAL_S)
    cal = verdict(cal_ks)
    rep['calibration'] = dict(cal, expect=CAL_EXPECT, source='lighter:exchange=hyperliquid')
    ok_cal = bool(cal.get('n', 0) >= 20
                  and abs(cal.get('median', 0) - CAL_EXPECT) <= CAL_EXPECT * CAL_TOL
                  and cal.get('tight_share', 0) >= 0.9)
    rep['calibration']['passed'] = ok_cal

    # ── ШАГ 2. СУД О VARIATIONAL (только если метод подтверждён) ───────────────────────────
    ivs = {}
    for _t, (_fr, _iv) in V.items():
        ivs[_iv] = ivs.get(_iv, 0) + 1
    rep['variational_intervals'] = ivs
    # ИНТЕРВАЛ БЕРЁМ САМЫЙ ЧАСТЫЙ, А НЕ «8 часов по памяти»: площадка отдаёт его полем, и у
    # части инструментов он другой. Смешав интервалы, мы измеряли бы кашу.
    iv_main = max(ivs.items(), key=lambda kv: kv[1])[0] if ivs else HL_INTERVAL_S
    Vm = {t: fr for t, (fr, iv) in V.items() if iv == iv_main}
    ks, n = ratios(Vm, H, iv_main)
    var = verdict(ks)
    rep['variational'] = dict(var, interval_s=iv_main)
    if var.get('n'):
        mult, unit, off = name_unit(var['median'], iv_main)
        rep['variational'].update({'nearest_mult': mult, 'unit': unit, 'off_by': off})

    # ── ШАГ 3. ВТОРАЯ ГРУППА ИНТЕРВАЛОВ: ПРОВЕРКА, КОТОРУЮ ПОДГОНКА НЕ ПРОЙДЁТ ────────────
    # Гипотеза «годовая ставка» предсказывает для каждой группы СВОЁ число интервалов в году.
    # Если единица угадана, совпасть должны ОБЕ группы; если мы подогнали константу под первую,
    # вторая её опровергнет. Это тот же приём, что калибровка на шаге 1, только внутри данных.
    rep['groups'] = {}
    for _iv in sorted(ivs, key=lambda k: -ivs[k]):
        _sub = {t: fr for t, (fr, tiv) in V.items() if tiv == _iv}
        _ks, _ = ratios(_sub, H, _iv)
        if len(_ks) < 10:
            continue
        _v = verdict(_ks)
        _pred = YEAR_S / float(_iv)
        rep['groups'][_iv] = dict(_v, predicted_if_apr=_pred,
                                  off_by=max(_v['median'] / _pred, _pred / _v['median']))

    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if ok_cal else 1

    print('РАЗМЕРЫ ЛЕНТ: Variational %d с фандингом · Hyperliquid %d · Lighter по биржам %s'
          % (len(V), len(H), rep['sizes']['lighter_exchanges']))
    print('\n── ШАГ 1. КАЛИБРОВКА МЕТОДА (ответ известен заранее) ──')
    print('   сверяем: строки exchange=hyperliquid в ленте Lighter ПРОТИВ нашего чтения HL')
    print('   ждём ×%.1f (Lighter публикует долю за 8ч), пар %d' % (CAL_EXPECT, cal_n))
    if cal.get('n'):
        print('   получили: медиана ×%.4f · квартили %.3f..%.3f · рядом с медианой %d из %d '
              '(%.0f%%)' % (cal['median'], cal['q1'], cal['q3'], cal['tight'], cal['n'],
                            100 * cal['tight_share']))
    print('   ВЕРДИКТ КАЛИБРОВКИ: %s' % ('метод воспроизводит известный ответ - можно судить'
                                         if ok_cal else
                                         'МЕТОД НЕ ПОДТВЕРЖДЁН - о Variational не сужу'))
    print('\n── ШАГ 2. VARIATIONAL ──')
    print('   интервалы фандинга в ответе: %s (беру самый частый: %dс)' % (ivs, iv_main))
    if not ok_cal:
        print('   ПРОПУЩЕНО: пока калибровка не прошла, любое число здесь было бы догадкой '
              'с двумя знаками после запятой.')
        return 1
    if not var.get('n'):
        print('   ОБЩИХ ТИКЕРОВ С НЕНУЛЕВЫМ ФАНДИНГОМ НЕТ - замер невозможен, и это не вердикт.')
        return 1
    print('   общих пар с ненулевым фандингом: %d' % var['n'])
    print('   медиана |Variational / HL за тот же интервал| = %.4f' % var['median'])
    print('   квартили %.4f .. %.4f · рядом с медианой %d из %d (%.0f%%)'
          % (var['q1'], var['q3'], var['tight'], var['n'], 100 * var['tight_share']))
    mult, unit, off = rep['variational']['nearest_mult'], rep['variational']['unit'], \
        rep['variational']['off_by']
    print('\n   БЛИЖАЙШАЯ ГИПОТЕЗА: ×%g — %s' % (mult, unit))
    print('   мимо неё в %.2f раза' % off)
    # ── ПРОВЕРКА, КОТОРУЮ ПОДГОНКА НЕ ПРОЙДЁТ ─────────────────────────────────────────────
    if len(rep.get('groups') or {}) >= 2:
        print('\n── ШАГ 3. ДВЕ ГРУППЫ ИНТЕРВАЛОВ ПРОТИВ ГИПОТЕЗЫ «ГОДОВАЯ СТАВКА» ──')
        print('   у каждой группы СВОЁ предсказание (число интервалов в году), и совпасть')
        print('   должны ОБЕ - одна подогнанная константа обе группы объяснить не может:')
        _worst = 0.0
        for _iv, _g in sorted(rep['groups'].items()):
            print('   %5dс (%2.0fч): пар %3d · медиана %9.2f · предсказано %9.2f · мимо в %.4f'
                  % (_iv, _iv / 3600.0, _g['n'], _g['median'], _g['predicted_if_apr'],
                     _g['off_by']))
            _worst = max(_worst, _g['off_by'])
        if _worst <= 1.15:
            print('   ОБЕ ГРУППЫ СОШЛИСЬ (худшее отклонение %.1f%%). Единица измерена, а не '
                  'угадана.' % ((_worst - 1) * 100))
        else:
            print('   ГРУППЫ РАСХОДЯТСЯ (худшее отклонение %.1f%%) - гипотеза «годовая ставка» '
                  'НЕ подтверждена.' % ((_worst - 1) * 100))
    if var['tight_share'] < 0.6:
        print('\n   ОБЛАКО РАСПОЛЗЛОСЬ (рядом с медианой меньше 60%% пар). Это значит, что '
              'сверкой единицу здесь НЕ ВЫВЕСТИ: числа площадок расходятся по рыночным '
              'причинам сильнее, чем на масштаб. Единицу оставляем незаявленной.')
        return 1
    if off > 3:
        print('\n   НИ ОДНА ГИПОТЕЗА НЕ ПОДОШЛА (мимо больше чем в 3 раза). Честный ответ - '
              'оставить поле под именем провайдера, а не подгонять.')
        return 1
    print('\n   ИТОГ: единицу можно заявить как «%s».' % unit)
    print('   Проверить это в коде: sentinel/venues.funding_scale(\'variational\').')
    return 0


if __name__ == '__main__':
    sys.exit(main())
