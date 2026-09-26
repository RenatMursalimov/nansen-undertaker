# -*- coding: utf-8 -*-
"""ОБЩИЙ МЕХАНИЗМ ТЕКСТОВЫХ СТОРОЖЕЙ: «строка есть в файле» - это ещё не «правило действует».

ЗАЧЕМ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ (четыре живых случая за месяц, разбор Ren 01.09).
Сторож ищет строку по ВСЕМУ файлу и находит её:
  · в собственном комментарии - `client_max_body_size` в закомментированной директиве,
    `_sys_pair` в комментарии про имя, которого в коде уже нет; сторож ЗЕЛЁН, а механизма нет;
  · в отрицании - `заверен` внутри законного «файл НЕ заверен»; сторож зелен ровно на том
    тексте, который он должен был забраковать;
  · и наоборот - ЗАПРЕТ (`not in`) краснеет из-за чужого комментария: страница НЕ ходит в
    Polymarket, а фраза стоит в комментарии, цитирующем отказ, и тест обвиняет исправный код.
Общая причина одна: у файла ДВЕ ПОЛОВИНЫ - код и проза, - а сторож смотрел на их СУММУ и
поэтому не мог сказать, что именно он проверил.

ПОЭТОМУ ЗДЕСЬ ДВЕ ДВЕРИ, А НЕ ОДНА. «Срезать комментарии везде» было бы неверно: половина
сторожей проверяет прозу НАРОЧНО (закон записан в модуле, причина запрета названа для
человека, ссылка на открытый баг не потеряна) - им нужна ровно проза, и общий стрип сделал бы
их красными на верном коде. Сторож НАЗЫВАЕТ, какую половину он имеет в виду:

    import guard_text as gt
    assert gt.in_code('publish_static.py', 'env_load.load()')      # механизм работает
    assert gt.in_prose('product_search.py', 'НИКОГДА НЕ СОКРАЩ')   # закон записан людям
    assert gt.not_in_code('miniapp_room/index.html', 'gamma-api')  # запрет по коду

ПЕРЕНОС СТРОКИ. `in_code` ищет и по СКЛЕЕННЫМ строковым литералам: питон сливает соседние
литералы ещё при разборе, поэтому фраза, разрезанная переносом (`'а '\n 'б'`), в сыром тексте
не находится ВООБЩЕ - сторож либо краснеет на верном коде, либо автор пишет короткий обрывок,
который потом находится где угодно.

ОТРИЦАНИЕ РЕШАЕТ ЧЕЛОВЕК, А НЕ МЕХАНИЗМ. У прозы отрицание переворачивает смысл («не
заверен» содержит «заверен»), поэтому `in_prose` вхождения ПОД ОТРИЦАНИЕМ по умолчанию не
засчитывает. У кода - наоборот: `if not tw._has_key():` это и есть проверка ключа, и запрет
отрицания там забраковал бы верный код. Значит у `in_code` такого умолчания нет, а есть
явный `not_negated=True` на случай, когда иголка - утверждение, а не вызов.

САМОПРОВЕРКА. `audit()` проходит по тестам репо и находит сторожей, зелёных ИЗ-ЗА
комментария и красных ИЗ-ЗА комментария. Её же гоняет инвариант `gt01`, поэтому новый сторож,
написанный по-старому, краснеет на месте, а не через месяц.

Разбор рукой: `python3 tests/guard_text.py` (таблица) и `--all` (все проверки).
"""
import ast
import collections
import io
import os
import re
import textwrap
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

C_LIKE = ('.js', '.mjs', '.cjs', '.html', '.htm', '.css', '.json5')
HASH_LIKE = ('.conf', '.tmpl', '.sh', '.yaml', '.yml', '.toml', '.ini', '.env', '.example')

_CACHE = {}
_SPLIT = {}
_JOINED = {}

# РАЗБОР, КОТОРЫЙ НЕ СОСТОЯЛСЯ, НАЗЫВАЕТ СЕБЯ. Без этого дверь тихо отдавала бы сырой текст:
# `in_code` снова ловился бы на комментарий, а `in_prose` всегда отвечал бы «нет», - то есть
# механизм против тихой зелени сам работал бы тихо. Список проверяет инвариант gt01.
PARSE_FAILED = []


# ═══════════════════════ разделение файла на код и прозу ═══════════════════════

def _offsets(code):
    off, cur = [0], 0
    for ln in code.split('\n'):
        cur += len(ln) + 1
        off.append(cur)
    return off


def _bytecol(line, col):
    """col_offset У AST - ЭТО БАЙТЫ, А НЕ СИМВОЛЫ, и на кириллице он уезжает вправо.

    Токенайзер при этом считает СИМВОЛАМИ. Смешав две системы координат, срез докстринга
    съедал первые строки кода под ним - и сторож, ищущий этот код, объявлялся обманутым
    комментарием. То есть механизм против ложной зелени сам порождал ложную красноту.
    """
    return len(line.encode('utf-8')[:col].decode('utf-8', 'ignore'))


def _split_py(code):
    """(код, проза) для питона. Комментарии - ТОКЕНАЙЗЕРОМ, докстринги - AST-ом.

    Regex тут не годится: `#` внутри строкового литерала это не комментарий, и `re.sub`
    этого не различает - вырезав его, мы получили бы «код», в котором нет живой строки.

    Вырезаем ПО КООРДИНАТАМ, а не заменой текста: `str.replace` на файле в полтора
    мегабайта проходит его целиком на КАЖДЫЙ докстринг, и разбор dm_module.py занимал
    шесть секунд - инвариант, который столько думает, начинают выключать.
    """
    # ОТСТУП: `inspect.getsource` вложенной функции отдаёт код С ОТСТУПОМ, и он не
    # разбирается ни ast, ни токенайзером. Прежняя редакция молча возвращала его как есть -
    # докстринг оставался в «коде», и запрет по коду краснел на своём же объяснении. Поймано
    # подсадкой-эталоном, а не чтением.
    if code[:1] in (' ', '\t'):
        ded = textwrap.dedent(code)
        try:
            ast.parse(ded)
            code = ded
        except SyntaxError:
            pass
    lines = code.split('\n')
    off = _offsets(code)

    def _pos(line, col):
        return off[line - 1] + col

    cuts = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type == tokenize.COMMENT:
                cuts.append((_pos(*tok.start), _pos(*tok.end)))
    except Exception as _e:
        # разобрать не смогли - НЕ выдумываем: отдаём как есть. Съесть половину файла молча
        # здесь опаснее, чем не срезать комментарии: сторож краснел бы на живом коде.
        # Но и МОЛЧАТЬ нельзя: строка в PARSE_FAILED роняет gt01 и называет причину.
        PARSE_FAILED.append('python: %s' % _e)
        return code, ''
    try:
        tree = ast.parse(code)
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                  ast.Module)):
                continue
            b = getattr(n, 'body', None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                d = b[0].value
                cuts.append((_pos(d.lineno, _bytecol(lines[d.lineno - 1], d.col_offset)),
                             _pos(d.end_lineno,
                                  _bytecol(lines[d.end_lineno - 1], d.end_col_offset))))
    except SyntaxError:
        pass
    cuts.sort()
    out, prose, prev = [], [], 0
    for a, b in cuts:
        if a < prev:
            continue
        out.append(code[prev:a])
        prose.append(code[a:b])
        prev = b
    out.append(code[prev:])
    return ''.join(out), '\n'.join(prose)


def _split_c(code, hash_comments=False, html=False):
    """(код, проза) для C-подобных: // , /* */ , <!-- --> и (для conf/sh) # .

    Одним проходом с учётом строк и шаблонов: маркер комментария внутри 'http://x' или
    внутри `${...}` комментарием НЕ является, а построчный regex этого не видит.
    РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ НЕ РАЗБИРАЕМ: отличить `/x/` от деления без парсера нельзя, и
    ошибка тут стоит вырезанного кода. Поэтому при сомнении ОСТАВЛЯЕМ текст: лишний
    комментарий в «коде» ловится аудитом, а съеденный код - никем.
    """
    out, prose = [], []
    i, n = 0, len(code)
    q = None                       # ' " ` либо None
    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ''
        if q:
            out.append(ch)
            if ch == '\\':
                if i + 1 < n:
                    out.append(nxt)
                    i += 2
                    continue
            elif ch == q:
                q = None
            i += 1
            continue
        if ch in '\'"`':
            q = ch
            out.append(ch)
            i += 1
            continue
        if ch == '/' and nxt == '*':
            j = code.find('*/', i + 2)
            j = n if j < 0 else j + 2
            prose.append(code[i:j])
            out.append(' ')
            i = j
            continue
        if ch == '/' and nxt == '/':
            j = code.find('\n', i)
            j = n if j < 0 else j
            prose.append(code[i:j])
            i = j
            continue
        if html and code.startswith('<!--', i):
            j = code.find('-->', i + 4)
            j = n if j < 0 else j + 3
            prose.append(code[i:j])
            out.append(' ')
            i = j
            continue
        if hash_comments and ch == '#':
            j = code.find('\n', i)
            j = n if j < 0 else j
            prose.append(code[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return ''.join(out), '\n'.join(prose)


def split(path, text=None):
    """Файл -> (код, проза). Вид разбора выбирает расширение.

    Кэш обязателен, а не «для скорости»: аудит спрашивает один и тот же файл сотни раз,
    а разбор index.html посимвольный - без кэша прогон инварианта уходил за минуты.
    """
    if text is None:
        f = _abs(path)
        if f in _SPLIT:
            return _SPLIT[f]
    src = text if text is not None else read(path)
    p = str(path).lower()
    if p.endswith('.py'):
        got = _split_py(src)
    elif p.endswith(C_LIKE):
        got = _split_c(src, hash_comments=False, html=p.endswith(('.html', '.htm')))
    elif p.endswith(HASH_LIKE) or '/conf.d/' in p:
        got = _split_c(src, hash_comments=True)
    else:
        got = (src, '')
    if text is None:
        _SPLIT[_abs(path)] = got
    return got


def _joined_literals(path, src):
    """Код + все строковые литералы отдельными строками (питон).

    Питон СЛИВАЕТ соседние литералы при разборе, поэтому фраза, разрезанная переносом,
    существует только в дереве. Без этого сторож с длинной иголкой ломается от рефлоу.
    """
    if not str(path).endswith('.py'):
        return src
    f = _abs(path)
    if f in _JOINED:
        return _JOINED[f]
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        _JOINED[f] = src
        return src
    # ДОКСТРИНГИ ИЗ СКЛЕЙКИ ИСКЛЮЧЕНЫ, и это не мелочь: они тоже строковые литералы, и без
    # этого «код» снова начинал содержать прозу - иголка из докстринга находилась в коде, а
    # сторож объявлялся исправным. Механизм чинил бы ровно тот класс, ради которого написан.
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            b = getattr(n, 'body', None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                docs.add(id(b[0].value))
    add = [n.value for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and id(n) not in docs]
    _JOINED[f] = src + '\n' + '\n'.join(add)
    return _JOINED[f]


# ═══════════════════════ двери ═══════════════════════

def _abs(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def read(path):
    """Сырой текст файла. Кэш на процесс: аудит читает один файл десятки раз."""
    f = _abs(path)
    if f not in _CACHE:
        try:
            _CACHE[f] = io.open(f, encoding='utf-8').read()
        except Exception:
            _CACHE[f] = ''
    return _CACHE[f]


def code(path):
    """Файл БЕЗ комментариев и докстрингов - то, что исполняется."""
    return split(path)[0]


def prose(path):
    """ТОЛЬКО комментарии и докстринги - то, что написано человеку."""
    return split(path)[1]


NEG = re.compile(r'(?:\bне\s+|\bnot\s+|\bбез\s+|\bno\s+|!)\s*$', re.I | re.U)


def _all_negated(text, needle):
    hits = [m.start() for m in re.finditer(re.escape(needle), text)]
    if not hits:
        return False
    return all(NEG.search(text[max(0, i - 16):i]) for i in hits)


def in_code(path, needle, not_negated=False):
    """Иголка ЕСТЬ В ИСПОЛНЯЕМОМ коде (комментарий не считается). Перенос строки учтён."""
    c = code(path)
    ok = needle in c or needle in _joined_literals(path, c)
    if ok and not_negated and _all_negated(c, needle):
        return False
    return ok


def not_in_code(path, needle):
    """Иголки НЕТ в исполняемом коде. Комментарий с этим словом запрет не роняет."""
    return not in_code(path, needle)


def in_prose(path, needle, allow_negated=False):
    """Иголка ЕСТЬ В КОММЕНТАРИЯХ/докстрингах.

    Вхождение ПОД ОТРИЦАНИЕМ по умолчанию не засчитывается: «файл не заверен» содержит
    «заверен», и сторож, ищущий слово целиком, зеленел бы ровно на том тексте, который
    обязан был забраковать.
    """
    p = prose(path)
    if needle not in p:
        return False
    return True if allow_negated else not _all_negated(p, needle)


def code_of(src, kind='.py'):
    """Тот же разбор для УЖЕ ПРОЧИТАННОГО текста: `inspect.getsource(fn)` файла не даёт."""
    return split('x' + kind, src)[0]


def prose_of(src, kind='.py'):
    """Комментарии и докстринги куска исходника (спутник code_of)."""
    return split('x' + kind, src)[1]


def in_code_of(src, needle, kind='.py'):
    return needle in code_of(src, kind)


def in_prose_of(src, needle, kind='.py', allow_negated=False):
    pr = prose_of(src, kind)
    if needle not in pr:
        return False
    return True if allow_negated else not _all_negated(pr, needle)


def in_text(path, needle):
    """Сырой текст целиком. Оставлено НАРОЧНО для случаев, где половина не важна
    (наличие ключа в .env.example, строка в README) - но такой сторож обязан объяснить,
    почему ему всё равно, код это или проза."""
    return needle in read(path)


# ═══════════════════════ САМОПРОВЕРКА: кого можно обмануть ═══════════════════════

SCAN_DIRS = ('tests', 'tests/e2e', 'tools', 'autotester')
READERS = ('read', 'read_text', '_read', 'getsource', 'open')
EXT = ('.py', '.js', '.mjs', '.html', '.sh', '.conf', '.yaml', '.yml', '.tmpl', '.md',
       '.txt', '.json')


def _index():
    idx = {}
    for dp, dn, fns in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in ('.git', 'venv', 'node_modules', '__pycache__',
                                            '_attic', 'oss')]
        for fn in fns:
            idx.setdefault(fn, []).append(os.path.join(dp, fn))
    return idx


def _join_args(call):
    parts = [a.value for a in call.args
             if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return '/'.join(p.strip('/') for p in parts if p) if parts else None


def _walk_call(node):
    yield node
    for a in getattr(node, 'args', []):
        if isinstance(a, ast.Call):
            for x in _walk_call(a):
                yield x
    f = getattr(node, 'func', None)
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Call):
        for x in _walk_call(f.value):
            yield x


def _const_path(node):
    parts = []
    for a in getattr(node, 'args', []):
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            parts.append(a.value)
        elif isinstance(a, ast.Call):
            nm = getattr(a.func, 'attr', None) or getattr(a.func, 'id', None) or ''
            if nm == 'join':
                j = _join_args(a)
                if j:
                    parts.append(j)
            else:
                for b in a.args:
                    if isinstance(b, ast.Constant) and isinstance(b.value, str):
                        parts.append(b.value)
    cand = [p for p in parts if ('/' in p or p.endswith(EXT))]
    return cand[-1] if cand else None


def _local_readers(tree):
    """Имена ЧИТАЛОК, объявленных в самом файле теста. -> {'_src', ...}

    ДЕТЕКТОР, НЕ ВИДЯЩИЙ ЦЕЛОГО СЕМЕЙСТВА, ОТЧИТЫВАЕТСЯ «ОБМАНУТЫХ: 0» И ВРЁТ (закон №16).
    Половина сторожей репо читает исходник не `open(...).read()` по месту, а своим хелпером
    (`def _src(rel): return open(os.path.join(ROOT, rel)).read()`), и таких файлов аудит не
    видел ВООБЩЕ - ни одной строки из `test_group_card`, `test_acc_news`, `test_entity_link`
    в таблице не было, при том что там `assert 'cache_drop' in _src(...)` по СЫРОМУ тексту.

    Гоняться за произвольным хелпером бессмысленно - это спор без конца. Признак
    МЕХАНИЧЕСКИЙ и узкий: функция уровня модуля, у которой в `return` стоит настоящее чтение
    (`open`/`read`/`read_text`), а путь собран ИЗ ЕЁ ЖЕ ПАРАМЕТРА. Тогда `_src('x.py')`
    разбирается как чтение `x.py`, а `_src(BASE)` без строкового аргумента - как и раньше,
    никак: пути там нет, и выдумывать его нечем.
    """
    out = set()
    for n in tree.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = [a.arg for a in n.args.args]
        if len(args) != 1:
            continue
        for r in ast.walk(n):
            if not (isinstance(r, ast.Return) and isinstance(r.value, ast.Call)):
                continue
            reads = any((getattr(c.func, 'attr', None) or getattr(c.func, 'id', None) or '')
                        in READERS for c in _walk_call(r.value))
            uses = any(isinstance(x, ast.Name) and x.id == args[0]
                       for x in ast.walk(r.value))
            if reads and uses:
                out.add(n.name)
                break
    return out


# ДВЕРЬ, КОТОРАЯ САМА НАЗЫВАЕТ ПОЛОВИНУ, ВЫВОДИТ СТОРОЖА ИЗ ОБЛАСТИ АУДИТА - и `code_of`
# такой дверью и является: комментарии из текста уже вырезаны, обмануть сторожа
# комментарием НЕЧЕМ по построению. Аудит про неё не знал: `_read_info` смотрел сквозь
# обёртку на внутреннее чтение и судил `code_of(open(...).read())` как сторожа НАД СЫРЫМ
# ФАЙЛОМ. Латентно это жило у двух десятков вызовов и выстрелило на первом же, чья иголка
# оказалась только в прозе цели: аудит выдал «КРАСЕН ИЗ-ЗА КОММЕНТАРИЯ» ИСПРАВНОМУ
# сторожу, то есть ровно ту ложную красноту, против которой этот файл и написан.
# `prose_of` СЮДА НЕ ВХОДИТ НАМЕРЕННО: у прозы отрицание переворачивает смысл («не
# заверен» содержит «заверен»), и вывести её из аудита значило бы снять эту проверку. Её
# присваиваний в репо сегодня НОЛЬ - заводить под них машинерию нечего.
HALF_DOORS = {'code_of': 'код', 'in_code_of': 'код'}


def _read_info(call, local=()):
    got_path, got_src, half = None, None, None
    for c in _walk_call(call):
        nm = getattr(c.func, 'attr', None) or getattr(c.func, 'id', None) or ''
        if nm in HALF_DOORS:
            half = HALF_DOORS[nm]
        elif nm == 'getsource':
            a = c.args[0] if c.args else None
            got_src = ast.unparse(a) if a is not None else '?'
        elif nm in READERS or nm in local:
            got_path = _const_path(c) or got_path
    if half:
        return ('половина:' + half, got_path or got_src or '?')
    if got_path:
        return ('file', got_path)
    if got_src is not None:
        return ('getsource', got_src)
    return None


def _aliases(tree):
    a = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for x in n.names:
                a[x.asname or x.name.split('.')[0]] = x.name.split('.')[-1]
        elif isinstance(n, ast.ImportFrom) and n.module:
            for x in n.names:
                a[x.asname or x.name] = x.name
    return a


def _scopes(tree):
    """Модуль и КАЖДАЯ функция - своя область.

    Сбор по файлу целиком врал: `text = <чтение исходника>` в одной функции склеивался
    с `text = <ответ бота>` в соседней, и в таблицу лезли проверки чужого класса.
    """
    fns = [n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    inner = set()
    for f in fns:
        for n in ast.walk(f):
            inner.add(id(n))
    mod = [n for n in ast.walk(tree) if id(n) not in inner]
    return [('<модуль>', mod)] + [(f.name, list(ast.walk(f))) for f in fns]


def _collect(path):
    src = read(path)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    ali = _aliases(tree)
    local = _local_readers(tree)
    lines = src.split('\n')
    out = []
    for sname, nodes in _scopes(tree):
        reads, kills = {}, collections.defaultdict(list)
        assigns = [n for n in nodes
                   if isinstance(n, ast.Assign) and len(n.targets) == 1
                   and isinstance(n.targets[0], ast.Name)]
        # ВЫРЕЗАННОЕ ТЕЛО - ТОТ ЖЕ ИСХОДНИК, И СТОРОЖ НАД НИМ ТОТ ЖЕ. Половина проверок репо
        # устроена «прочитал файл -> вырезал тело функции -> ищу в нём» (`b = s[i:j]`), и это
        # НЕ обход правила, а рекомендованный приём: искать по файлу целиком значит находить у
        # соседа. Прежний сбор шёл ровно по прямому чтению, поэтому такие сторожа выпадали из
        # аудита ЦЕЛИКОМ - вместе с файлами, где других сторожей нет вовсе.
        # Признак узкий: значение упоминает РОВНО ОДНО уже известное чтение и не зовёт ничего
        # чужого. Проход повторяется до неподвижной точки: `ast.walk` идёт не по исходнику, и
        # за один круг производная от производной осталась бы невидимой.
        for _ in range(4):
            grew = False
            for n in assigns:
                nm = n.targets[0].id
                info = _read_info(n.value, local) if isinstance(n.value, ast.Call) else None
                if not info:
                    kin = {x.id for x in ast.walk(n.value)
                           if isinstance(x, ast.Name) and x.id in reads}
                    if len(kin) == 1:
                        base = kin.pop()
                        earlier = [(ln, i) for ln, i in reads[base] if ln <= n.lineno]
                        if earlier and base != nm:
                            info = (earlier[-1][1][0], earlier[-1][1][1], 'cut')
                if info and (n.lineno, info) not in reads.get(nm, []):
                    reads.setdefault(nm, []).append((n.lineno, info))
                    grew = True
            if not grew:
                break
        for n in assigns:
            nm = n.targets[0].id
            if not any(ln == n.lineno for ln, _ in reads.get(nm, [])):
                kills[nm].append(n.lineno)
        if not reads:
            continue
        for n in nodes:
            if not (isinstance(n, ast.Compare) and len(n.ops) == 1
                    and isinstance(n.ops[0], (ast.In, ast.NotIn))):
                continue
            left, right = n.left, n.comparators[0]
            if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
                continue
            rn, chain = right, []
            while isinstance(rn, ast.Call) and isinstance(rn.func, ast.Attribute):
                chain.append(rn.func.attr)
                rn = rn.func.value
            if not (isinstance(rn, ast.Name) and rn.id in reads):
                continue
            before = [(ln, i) for ln, i in reads[rn.id] if ln <= n.lineno]
            if not before:
                continue
            ln, info = before[-1]
            if any(ln < k <= n.lineno for k in kills[rn.id]):
                continue
            alt = []
            for b in nodes:
                if isinstance(b, ast.BoolOp) and isinstance(b.op, ast.Or) \
                        and any(x is n for x in b.values):
                    for x in b.values:
                        if x is not n and isinstance(x, ast.Compare) \
                                and isinstance(x.left, ast.Constant) \
                                and isinstance(x.left.value, str):
                            alt.append(x.left.value)
            out.append({'guard': os.path.relpath(path, ROOT), 'scope': sname, 'line': n.lineno,
                        'neg': isinstance(n.ops[0], ast.NotIn), 'needle': left.value,
                        'kind': info[0], 'target': info[1], 'chain': chain, 'alt': alt,
                        'cut': len(info) > 2,
                        'ali': ali, 'code': lines[n.lineno - 1].strip()[:120]})
    return out


_CALLISH = re.compile(r"[A-Za-z_][\w.]*\s*\(|[A-Za-z_]\w*\s*=[^=]|\bdef\b|\bclass\b|"
                      r"^[A-Za-z_][\w.]*$|\[|\]|\{|\}|;")


def _asserts(needle):
    """Иголка - УТВЕРЖДЕНИЕ (слова), а не обращение к коду? -> bool

    От этого зависит, переворачивает ли её смысл соседнее «не». «файл заверен» под `not`
    означает обратное; `job_guard.should_run(...)` под `not` означает ровно себя - это тот
    же вызов, и запрет отрицания забраковал бы верный гейт.
    """
    n = (needle or '').strip()
    if not n or _CALLISH.search(n):
        return False
    return bool(re.search(r'[А-Яа-яЁё]', n)) and ' ' in n


# ── СТОРОЖА, КОТОРЫЕ ПРОВЕРЯЮТ ПРОЗУ НАРОЧНО ────────────────────────────────────────────
# Аудит не читает намерения: «иголка живёт только в комментарии» это ОБМАН у сторожа,
# который целил в механизм, и РОВНО ТО, ЧТО НУЖНО, у сторожа, который целит в комментарий.
# У целого файла намерение называется дверью (`in_prose`); у ВЫРЕЗКИ двери нет - окно
# задаётся смещением в сыром тексте, а половины файла смещений не сохраняют.
# Поэтому здесь ИМЕНОВАННОЕ гашение с причиной, как у любого реестра в этом репо. Мёртвая
# строка роняет аудит: прощение, пережившее свою причину, прикроет следующего.
PROSE_ON_PURPOSE = {
    ('tests/e2e/60_public.py', 'gm01', 'ОТКЛЮЧЁН'):
        'сторож проверяет, что GM-джоба выключена ИМЕННО комментарием с датой и причиной, '
        'а не вырезана молча - комментарий здесь и есть проверяемый механизм',
    ('tests/e2e/60_public.py', 'gm01', 'Вернуть'):
        'та же проверка: в пометке обязан быть способ вернуть джобу одной строкой',
}


def audit(dirs=SCAN_DIRS):
    """Все текстовые сторожа репо с вердиктом. -> [строка, ...]

    Вердикты, ради которых всё писалось:
      ЗЕЛЁН ИЗ-ЗА КОММЕНТАРИЯ - иголка есть только в прозе цели, механизма нет;
      ЗЕЛЁН ИЗ-ЗА ОТРИЦАНИЯ  - все вхождения под «не»;
      КРАСЕН ИЗ-ЗА КОММЕНТАРИЯ - запрет сработал на комментарии, обвинён исправный код.
    """
    idx = _index()
    modmap = {}
    for fn, hits in idx.items():
        if fn.endswith('.py') and len(hits) == 1:
            modmap.setdefault(fn[:-3], hits[0])

    def resolve(p):
        if not p:
            return None
        p = p.lstrip('./')
        for base in (ROOT, os.path.join(ROOT, 'tests'), os.path.join(ROOT, 'tools')):
            f = os.path.join(base, p)
            if os.path.isfile(f):
                return f
        hits = idx.get(os.path.basename(p), [])
        if '/' in p:
            narrow = [h for h in hits if h.endswith('/' + p)]
            if len(narrow) == 1:
                return narrow[0]
        return hits[0] if len(hits) == 1 else None

    rows, seen_prose = [], set()
    for d in dirs:
        full = os.path.join(ROOT, d)
        if not os.path.isdir(full):
            continue
        for fn in sorted(os.listdir(full)):
            if fn.endswith('.py'):
                rows += _collect(os.path.join(full, fn))
    for r in rows:
        if r['kind'].startswith('половина'):
            # НАЗВАЛ ПОЛОВИНУ - ВЫШЕЛ ИЗ ОБЛАСТИ АУДИТА ПО ПОСТРОЕНИЮ, и это ровно то, что
            # обещает договор gt01. Вопрос аудита один: «можно ли обмануть этого сторожа
            # комментарием». У сторожа над `code_of` ответ НЕТ до всякой проверки, поэтому
            # решение принимается ДО резолва цели: у `code_of(inspect.getsource(X))` файла
            # нет вовсе, и «цель не установлена» тут описывало бы не сторожа, а нашу
            # неспособность его адресовать - то есть раздувало бы счётчик деградации
            # резолва тем, что к резолву отношения не имеет.
            r.pop('ali', None)
            r['target_abs'] = None
            r['verdict'] = 'назвал половину'
            continue
        if r['kind'] == 'file':
            tgt = resolve(r['target'])
        else:
            m = re.match(r'([A-Za-z_]\w*)', r['target'] or '')
            nm = m.group(1) if m else ''
            tgt = modmap.get(r['ali'].get(nm, nm)) or modmap.get(nm)
        r.pop('ali', None)
        r['target_abs'] = os.path.relpath(tgt, ROOT) if tgt else None
        if not tgt:
            r['verdict'] = 'цель не установлена'
            continue
        raw = read(tgt)
        c, pr = split(tgt)
        nd = r['needle']
        in_raw, in_c = nd in raw, (nd in c or nd in _joined_literals(tgt, c))
        if r['neg']:
            # ЗАПРЕТ НАД ВЫРЕЗАННЫМ ТЕЛОМ СУДИТЬ ПО ВСЕМУ ФАЙЛУ НЕЛЬЗЯ - ЭТО ПРИЗНАК
            # РЯДОМ С ОТВЕТОМ (закон №35). «Иголка есть только в прозе файла» доказывает
            # ложную красноту лишь тогда, когда сторож смотрит файл ЦЕЛИКОМ; у вырезки
            # комментарий может лежать за её границами, и обвинение было бы выдумано, а
            # красный на верном коде учит не смотреть на красное. Положительный вердикт
            # («иголки в коде нет вовсе») к вырезке применим и остаётся: чего нет в файле,
            # того нет и в куске.
            r['verdict'] = ('КРАСЕН ИЗ-ЗА КОММЕНТАРИЯ'
                            if (in_raw and not in_c and not r.get('cut')) else 'запрет')
        elif in_raw and not in_c and any(a in c for a in r.get('alt') or []):
            # ВЕТКА `or`, У КОТОРОЙ ЖИВ СОСЕД, СТОРОЖА НЕ ОБМАНЫВАЕТ. Проверка проходит на
            # соседнем условии, которое ЕСТЬ в коде; мёртвая ветка тут - мусор, а не ложная
            # зелень. Прежнее правило смотрело соседей только когда иголки нет в файле
            # ВООБЩЕ, и ветку, дожившую до комментария, объявляло обманом.
            r['verdict'] = 'ok (ветка or)'
        elif in_raw and not in_c:
            key = (r['guard'], r['scope'], nd)
            if key in PROSE_ON_PURPOSE:
                seen_prose.add(key)
                r['verdict'] = 'проза нарочно'
            else:
                r['verdict'] = 'ЗЕЛЁН ИЗ-ЗА КОММЕНТАРИЯ'
        elif in_c and _all_negated(c, nd) and _asserts(nd):
            # ОТРИЦАНИЕ ПЕРЕВОРАЧИВАЕТ СМЫСЛ У ПРОЗЫ, А НЕ У ВЫЗОВА - так написано в договоре
            # этого файла, и `in_code` отрицание НЕ запрещает. Аудит же запрещал его всему
            # подряд и обвинял `if not job_guard.should_run(...)`, то есть САМ ГЕЙТ, ради
            # которого сторож и написан. Флажок остаётся там, где иголка - утверждение
            # (слова), и снят там, где она - обращение к коду.
            r['verdict'] = 'ЗЕЛЁН ИЗ-ЗА ОТРИЦАНИЯ'
        elif not in_raw and any(a in raw for a in r.get('alt') or []):
            r['verdict'] = 'ok (ветка or)'
        elif not in_raw:
            r['verdict'] = 'не находится вовсе'
        else:
            r['verdict'] = 'ok'
    dead = sorted(set(PROSE_ON_PURPOSE) - seen_prose)
    for k in dead:
        rows.append({'guard': k[0], 'scope': k[1], 'line': 0, 'needle': k[2],
                     'target_abs': None, 'code': PROSE_ON_PURPOSE[k][:110],
                     'verdict': 'МЁРТВОЕ ГАШЕНИЕ'})
    return rows


BAD = ('ЗЕЛЁН ИЗ-ЗА КОММЕНТАРИЯ', 'ЗЕЛЁН ИЗ-ЗА ОТРИЦАНИЯ', 'КРАСЕН ИЗ-ЗА КОММЕНТАРИЯ',
       'МЁРТВОЕ ГАШЕНИЕ')


def main():
    import sys
    rows = audit()
    st = collections.Counter(r['verdict'] for r in rows)
    print('ТЕКСТОВЫХ СТОРОЖЕЙ: %d проверок в %d файлах\n'
          % (len(rows), len(set(r['guard'] for r in rows))))
    for k, c in st.most_common():
        print('%5d  %s' % (c, k))
    bad = [r for r in rows if r['verdict'] in BAD]
    print('\nОБМАНУТЫХ: %d' % len(bad))
    for r in bad:
        print('\n%s\n  %s:%d (%s)\n  цель: %s\n  ищет: %r\n  %s'
              % (r['verdict'], r['guard'], r['line'], r['scope'], r['target_abs'],
                 r['needle'][:80], r['code']))
    if '--all' in sys.argv:
        print('\n── ВСЕ ПРОВЕРКИ ──')
        for r in rows:
            print('%-24s %s:%d  %r -> %s'
                  % (r['verdict'], r['guard'], r['line'], r['needle'][:50], r['target_abs']))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
