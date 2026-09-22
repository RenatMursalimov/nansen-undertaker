#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scrub.py — ПРОВЕРКА, ЧТО В ЭТОМ ПУБЛИЧНОМ РЕПОЗИТОРИИ НЕТ ЧУЖИХ ДАННЫХ.

    python3 scrub.py          # 0 = чисто, 1 = нашлось

ЗАЧЕМ ОН ЗДЕСЬ, ЕСЛИ ТАКОЙ ЖЕ СТОИТ В СБОРЩИКЕ. Сборщик в приватном репозитории проверяет
ВЫХОД перед копированием и не даст уехать наружу лишнему. Но репозиторий живёт и после сборки:
в README дописывают строку, в issue вставляют лог, кто-то приносит пример с настоящим адресом.
Проверка, работающая только в момент сборки, охраняет один день из трёхсот.

ПОЧЕМУ ЗДЕСЬ НЕТ СПИСКА КОНКРЕТНЫХ НИКОВ И АДРЕСОВ, а в приватном сборщике он есть.
Чёрный список сам разглашает то, что скрывает: опубликовав «искать ник Х и кошелёк Y», мы
опубликовали бы ник Х и кошелёк Y. Поэтому здесь ищутся не имена, а ПРИЗНАКИ КЛАССА:
любой путь внутри /root, любое имя вида *_bot, любая @-ручка кроме явно разрешённых, любой
0x-адрес кроме списка публичных контрактов, любая 64-символьная шестнадцатеричная строка
(так выглядит приватный ключ) и присвоенное значение ключа API.

Список разрешённых адресов - БЕЛЫЙ, и это осознанно: белый список из семи публичных контрактов
можно прочитать глазами, а чёрный список адресов людей пришлось бы пополнять каждым новым
человеком - то есть он всегда отставал бы ровно на один инцидент.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.basename(os.path.abspath(__file__))

#: РАЗРЕШЁННЫЕ АДРЕСА: только публичные сущности - контракты и адреса из документации.
#: Ни одного адреса человека. Любой другой 0x-адрес в тексте - повод остановиться и спросить,
#: чей он, до того как он уедет в git навсегда.
ALLOWED_ADDR = {
    '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913',   # USDC на Base, контракт
    '0x1f9090aae28b8a3dceadf281b0f12828e676c326',   # публичный билдер блоков Ethereum
    '0x0000000000000000000000000000000000000000',   # нулевой адрес в примерах и тестах
    '0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb',   # pUSD, контракт
    '0x4d97dcd97ec945f40cf65f87097ace5ea0476045',   # ConditionalTokens, контракт
    '0xada100db00ca00073811820692005400218fce1f',   # CtfCollateralAdapter, контракт
    '0xada2005600dec949baf300f4c6120000bdb6eaab',   # NegRiskCtfCollateralAdapter, контракт
    '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',   # условный адрес нативной монеты в trade API
    '0x4200000000000000000000000000000000000006',   # WETH на Base, контракт (проба потоков)
}
#: @-ручки, которым здесь место: площадка, у которой мы берём данные.
#: Питоновские декораторы и ссылки на модули (`@contextlib.contextmanager`) отсекаются не
#: списком, а правилом ниже: за ними идёт точка или скобка, а за ручкой человека - нет.
ALLOWED_HANDLES = {'@nansen_ai', '@property', '@staticmethod', '@classmethod'}

CLASSES = [
    (r'/root/[A-Za-z0-9_.\-]+', 'путь внутри /root: боевая раскладка сервера'),
    (r'\b[a-z][a-z0-9_]{2,}_bot\b', 'похоже на имя телеграм-бота'),
    (r'\b0x[a-fA-F0-9]{64}\b', 'шестьдесят четыре hex: так выглядит приватный ключ'),
    (r'NANSEN_API_KEY\s*=\s*[\'"]?[A-Za-z0-9_\-]{12,}', 'ключу API присвоено значение'),
    (r'\b[0-9]{9,10}\b(?=\s*[,:\]\)]?\s*#\s*(?:uid|admin|id человека))', 'telegram id человека'),
]
SKIP_DIRS = {'.git', '__pycache__', 'nansen_tele', 'venv', '.venv', 'node_modules'}
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.db', '.pyc', '.ttf', '.zip'}
# Эти имена не должны СУЩЕСТВОВАТЬ в дереве, которое собираются коммитить. Просто пропустить
# их содержимое недостаточно: прежний scrubber именно так и делал, а сломанный .gitignore
# одновременно не игнорировал файлы из-за inline-комментариев. Две защиты были зелёными, а
# runtime state мог попасть в git.
RUNTIME_NAMES = {
    'nansen_tele', 'nansen_credits.json', 'nansen_credits.json.pending',
    'nansen_schema.json', 'nansen_asks.json',
    'nansen_cache.json', 'nansen_pm_refs.json', 'nansen_meridian_corpus.jsonl',
    'nansen_endpoint_sweep_state.json', 'nansen_local.db',
}


def _runtime_state():
    found = []
    for base, dirs, names in os.walk(HERE):
        if '.git' in dirs:
            dirs.remove('.git')
        for d in dirs:
            if d in RUNTIME_NAMES:
                found.append(os.path.relpath(os.path.join(base, d), HERE))
        for n in names:
            if n in RUNTIME_NAMES or n.endswith(('.db-shm', '.db-wal', '.db-journal')):
                found.append(os.path.relpath(os.path.join(base, n), HERE))
    return sorted(set(found))


def files():
    for base, dirs, names in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if os.path.splitext(n)[1].lower() in SKIP_EXT:
                continue
            # СВОЙ ФАЙЛ ПРОПУСКАЕМ: в нём лежат сами шаблоны поиска, и детектор, который
            # ловит собственные регулярки, показывает только себя.
            if n == SELF:
                continue
            yield os.path.join(base, n)


def _line(txt, pos):
    return txt[:pos].count('\n') + 1


def main():
    runtime = _runtime_state()
    if runtime:
        print('РАНТАЙМ-СОСТОЯНИЕ В ДЕРЕВЕ (%d): перед коммитом удалить' % len(runtime))
        for p in runtime:
            print('  ' + p)
        return 1
    bad, seen_files = [], 0
    for path in files():
        rel = os.path.relpath(path, HERE)
        try:
            txt = open(path, encoding='utf-8', errors='replace').read()
        except OSError as e:
            print('не прочитался %s: %s' % (rel, e))
            continue
        seen_files += 1
        for rx, why in CLASSES:
            for m in re.finditer(rx, txt):
                bad.append('%s:%d %s -> %r' % (rel, _line(txt, m.start()), why,
                                               m.group(0)[:48]))
        for m in re.finditer(r'0x[a-fA-F0-9]{40}\b', txt):
            if m.group(0).lower() not in ALLOWED_ADDR:
                bad.append('%s:%d адрес не в белом списке -> %s'
                           % (rel, _line(txt, m.start()), m.group(0)))
        for m in re.finditer(r'(?<![\w/])@[A-Za-z][A-Za-z0-9_]{3,}(?![\w.(])', txt):
            if m.group(0).lower() not in ALLOWED_HANDLES:
                bad.append('%s:%d @-ручка не в белом списке -> %s'
                           % (rel, _line(txt, m.start()), m.group(0)))
    # СКАНЕР МОГ ОСЛЕПНУТЬ, И «НАРУШЕНИЙ НЕТ» ВЫГЛЯДЕЛО БЫ ТАК ЖЕ. Поэтому сначала
    # утверждение о том, что файлы вообще читались.
    if seen_files < 10:
        print('ПОДОЗРИТЕЛЬНО: просмотрено всего %d файлов - сканер смотрит не туда' % seen_files)
        return 1
    if bad:
        print('НАШЛОСЬ %d в %d файлах:' % (len(bad), seen_files))
        for b in bad[:60]:
            print('  ' + b)
        return 1
    print('чисто: %d файлов, ни путей сервера, ни чужих адресов, ни ручек, ни ключей'
          % seen_files)
    return 0


if __name__ == '__main__':
    sys.exit(main())
