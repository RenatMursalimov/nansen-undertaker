# -*- coding: utf-8 -*-
"""nansen_limits.py — ОДНА дверь на все лимиты Nansen: сколько вопросов человеку в сутки и
сколько кредитов можно сжечь на всех.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ЧИСЛО ПО МЕСТАМ. До этого «3 вопроса в сутки» лежало ХАРДКОДОМ
в трёх местах - Хаб (`bot.py`), паблик (`pub_tools.py`), личка (`dm_module.py`), - причём в
двух РАЗНЫХ файлах счётчика (`nansen_usage.json` и `nansen_dm_usage.json`), так что человек
суммарно имел не 3 вопроса, а 6. Поменять число во время конкурса значило бы править код на
живом сервере в трёх файлах и всё равно получить два независимых бюджета.

ДВЕ РУЧКИ, И ОНИ НЕ ДУБЛИРУЮТ ДРУГ ДРУГА
- `asks_daily()` - сколько вопросов АГЕНТУ в сутки на человека. Защищает от одного
  увлёкшегося.
- `day_cap()` - сколько кредитов в сутки можно сжечь НА ВСЕХ. Защищает от пятидесяти сразу:
  50 человек по 6 вопросов это 60 000 кредитов при остатке 70 450, то есть весь бюджет
  конкурса за сутки. Первая ручка этот случай не ловит вовсе.

ЛИМИТ ТОЛЬКО НА АГЕНТА, И ЭТО СОЗНАТЕЛЬНО. Вопрос агенту стоит 200 кредитов (expert - 750),
а структурный сценарий - 1-5. Гасить «смарт потоки» тем же лимитом, что и свободный вопрос,
значило бы закрыть людям дешёвые сценарии ради экономии, которой они не создают.

ЧЕГО ЗДЕСЬ НЕТ: денег юзера. На время конкурса Nansen для человека БЕСПЛАТЕН - ни звёзд, ни
списаний. Лимит здесь про бюджет владельца, а не про счёт человека.
"""

import json
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))

#: дефолты, если ручка админа не задана. Совпадают с прежним хардкодом: правка ручкой должна
#: менять поведение осознанно, а не «начать работать иначе после деплоя».
ASKS_DAILY_DEFAULT = 3
DAY_CAP_DEFAULT = 0            # 0 = общий кап выключен, действует только лимит на человека

#: ОДИН файл счётчика вопросов на ВСЕ контуры. Раньше их было два, и человек с двумя дверями
#: получал двойной бюджет - «лимит 3» на бумаге и 6 в жизни.
USAGE_PATH = os.path.join(BASE, 'nansen_asks.json')


def asks_daily():
    """Сколько вопросов агенту в сутки на человека. -> int (0 = запрещено)."""
    try:
        import admin_config as _ac
        return _ac.int_value(_ac.K_NANSEN_DAILY, ASKS_DAILY_DEFAULT)
    except Exception as e:
        print('[nansen] лимит вопросов не прочитан (%s) - беру код' % str(e)[:90])
        return ASKS_DAILY_DEFAULT


def day_cap():
    """Общий суточный кап кредитов на всех. -> int (0 = выключен)."""
    try:
        import admin_config as _ac
        return _ac.int_value(_ac.K_NANSEN_DAY_CAP, DAY_CAP_DEFAULT)
    except Exception as e:
        print('[nansen] общий кап не прочитан (%s) - беру код' % str(e)[:90])
        return DAY_CAP_DEFAULT


def _today():
    return time.strftime('%Y-%m-%d', time.gmtime())


def _load():
    try:
        with open(USAGE_PATH, encoding='utf-8') as f:
            d = json.loads(f.read().strip() or '{}')
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    try:
        with open(USAGE_PATH, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        print('[nansen] счётчик вопросов не записался: %s' % str(e)[:120])


def spent_today():
    """Сколько кредитов сожжено за сегодня ПО ФАКТУ телеметрии. -> int.

    Считаем по СВОЕМУ логу, а не по заголовку остатка: заголовок отражает и чужие ключи, и
    ручные запросы из кабинета, а кап должен ограничивать РОВНО наш бот. Кэш-хиты в сумму не
    входят - они не стоят ничего (это уже посчитано в `nansen_log.summary`)."""
    try:
        import nansen_log as _tl
        s = _tl.summary(_tl._day())
        return int((s or {}).get('credits') or 0)
    except Exception as e:
        print('[nansen] расход за сутки не прочитан: %s' % str(e)[:120])
        return 0


def cap_left():
    """Сколько кредитов осталось до общего капа. -> int | None (кап выключен)."""
    cap = day_cap()
    if cap <= 0:
        return None
    return max(0, cap - spent_today())


def check(uid, unlimited=(), cost=200):
    """Можно ли человеку задать вопрос агенту. -> (можно, осталось_после, причина).

    ПРОВЕРЯЕТ, НО НЕ СПИСЫВАЕТ. Списание отдельным вызовом `spend()` и ТОЛЬКО после
    фактического успешного ответа: раньше счётчик увеличивался до вызова, и человек терял
    попытку на нашем же таймауте - платил за наш отказ.

    `cost` - цена предстоящего вопроса (200 fast / 750 expert). Нужна общему капу: пускать
    вопрос за 750, когда до капа осталось 300, значит перейти его молча.
    reason: None | 'user' (личный лимит) | 'shared' (общий кап)."""
    lim = asks_daily()
    if uid in (unlimited or ()):            # владелец и админы вне лимита, как было
        return True, -1, None
    if lim <= 0:
        return False, 0, 'user'
    d = _load()
    k = '%s:%s' % (_today(), uid)
    used = int(d.get(k) or 0)
    if used >= lim:
        return False, 0, 'user'
    left = cap_left()
    if left is not None and left < cost:
        # ОБЩИЙ КАП ПРОВЕРЯЕТСЯ ПОСЛЕ ЛИЧНОГО НАРОЧНО: человеку важнее узнать, что лимит
        # именно общий, только когда у него самого попытки ещё есть.
        return False, max(0, lim - used), 'shared'
    return True, lim - used - 1, None


def spend(uid, unlimited=()):
    """Списать одну попытку ПОСЛЕ успешного ответа. -> сколько осталось."""
    lim = asks_daily()
    if uid in (unlimited or ()):
        return -1
    d = _load()
    k = '%s:%s' % (_today(), uid)
    d[k] = int(d.get(k) or 0) + 1
    today = _today()
    d = {kk: vv for kk, vv in d.items() if str(kk).startswith(today)}   # чистка старых суток
    _save(d)
    return max(0, lim - d[k])


def refusal_text(reason, lang='ru', left_cap=None):
    """Текст отказа по лимиту. -> str. Оба языка (закон №20).

    ОТКАЗ НАЗЫВАЕТ, ЧЕЙ ЛИМИТ КОНЧИЛСЯ. «Лимит исчерпан» на общий кап заставило бы человека
    ждать завтрашнего дня, хотя дело не в нём и попытки у него есть; а на личный - винить
    бота. Это разные действия, значит разные слова."""
    if reason == 'shared':
        if lang == 'en':
            return ('⛔ The shared daily Nansen budget is used up (a cap the owner set, not '
                    'your limit). Structured scenarios still work - smart flows, holdings, '
                    'wallet profile, who bought and sold: they cost units of credits, not '
                    'hundreds.')
        return ('⛔ Общий суточный бюджет Nansen на сегодня выбран (это кап владельца, а не '
                'твой лимит). Структурные сценарии работают как обычно - смарт потоки, '
                'холдинги, профиль кошелька, кто входил: они стоят единицы кредитов, а не '
                'сотни.')
    if lang == 'en':
        return ('🖤 Your on-chain agent questions for today are used up (%d/day). Structured '
                'scenarios are not limited - try «смарт потоки» or «кто входил 0x…».'
                % asks_daily())
    return ('🖤 Вопросы к ончейн-агенту на сегодня исчерпаны (%d/день). Структурные сценарии '
            'без лимита - попробуй «смарт потоки» или «кто входил 0x…».' % asks_daily())
