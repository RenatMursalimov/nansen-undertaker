# -*- coding: utf-8 -*-
"""db.py — МОСТ К SQLITE ДЛЯ ПУБЛИЧНОЙ ВЫЖИМКИ. Единственный файл здесь, которого нет в боте.

ЗАЧЕМ ОН ВООБЩЕ НУЖЕН. `nansen_log.py` ведёт зачёт вклада (кто из людей сколько спросил и на
сколько кредитов) в таблице `nansen_contrib`. В боте за базу отвечает общий слой `db`: он
переводит sqlite-диалект в PostgreSQL, держит пул, знает про BIGINT для телеграмных id и про
десяток чужих таблиц. Тащить его сюда значило бы тащить половину бота.

ПОЧЕМУ ЭТО МОСТ, А НЕ ВТОРАЯ РЕАЛИЗАЦИЯ. Ни одного запроса здесь нет: SQL целиком живёт в
`nansen_log.py` и приезжает сюда БАЙТ-В-БАЙТ из приватного репозитория. Здесь только открытие
файла и `CREATE TABLE IF NOT EXISTS` через переданную функцию. Значит разойтись нечему: если в
боте поменяется схема или запрос, поменяется и здесь - сам собой, потому что это один файл.

`?` вместо `%s` работает без перевода: sqlite3 из стандартной библиотеки понимает именно `?`, а
переводом в диалект PostgreSQL занят приватный слой, которому здесь делать нечего.
"""

import os
import sqlite3
import threading

#: одна база на всю выжимку. Путь переопределяется переменной окружения - это нужно тестам,
#: чтобы прогон не писал в рабочий файл (иначе второй прогон читал бы память первого).
DB_PATH = os.getenv('NANSEN_DB_PATH') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'nansen_local.db')

_LOCAL = threading.local()
_ENSURED = set()


def get_conn(key='main', timeout=None, busy_timeout=None):
    """Соединение с базой. По одному на поток: sqlite3 не любит делиться между потоками,
    а клиент Nansen синхронный и зовётся из `asyncio.to_thread`.

    `timeout`/`busy_timeout` - ТА ЖЕ ПОДПИСЬ, ЧТО У ПРИВАТНОГО `db.get_conn`: их передаёт
    `alert_log` (журнал отправок дозорного). Он берёт СВОЁ соединение и закрывает его сам,
    поэтому с этими аргументами отдаётся НОВОЕ соединение, а не общее потоковое: закрыв общее,
    журнал уронил бы всем остальным «Cannot operate on a closed database».
    """
    if timeout is not None or busy_timeout is not None:
        own = sqlite3.connect(DB_PATH, timeout=float(timeout or 10))
        if busy_timeout:
            own.execute('PRAGMA busy_timeout=%d' % int(busy_timeout))
        return own
    conn = getattr(_LOCAL, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        _LOCAL.conn = conn
    return conn


def ready(name, ensure_fn, key='main'):
    """Соединение с ГАРАНТИРОВАННО созданными таблицами модуля. -> conn.

    Тот же контракт, что у приватного `db.ready`: модуль готовит себя сам при первом
    обращении к базе, а не ждёт, что кто-то снаружи вызовет configure(). Помним пару
    «модуль + путь к базе», а не одно имя: тесты переставляют путь на ходу, и запомнив
    просто имя, мы посчитали бы готовым модуль, чьи таблицы созданы В ДРУГОМ ФАЙЛЕ.
    """
    conn = get_conn(key)
    mark = (name, DB_PATH, id(conn))
    if mark not in _ENSURED:
        ensure_fn(conn)
        conn.commit()
        _ENSURED.add(mark)
    return conn


def set_path(key, path):
    """Переставить путь к базе (тесты). Соединение потока сбрасывается, иначе следующий
    запрос ушёл бы в прежний файл - и тест мерил бы остатки предыдущего."""
    global DB_PATH
    DB_PATH = path
    conn = getattr(_LOCAL, 'conn', None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _LOCAL.conn = None
    _ENSURED.clear()
