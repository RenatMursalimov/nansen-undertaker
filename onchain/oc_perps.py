# -*- coding: utf-8 -*-
"""Киты перпов: позиции по адресу на Hyperliquid и Lighter (публичные API)."""
import re

import httpx

HL_API = "https://api.hyperliquid.xyz/info"
LIGHTER_API = "https://mainnet.zklighter.elliot.ai/api/v1"

_EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def fnum(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


async def hl_coin_stats(coin, dex=''):
    """Перп-данные ПО КОИНУ на Hyperliquid (metaAndAssetCtxs): OI/funding/объём/mark.
    Публичного «китов по коину» у HL нет — это перп-сентимент по монете. -> dict | None.

    `dex` — HIP-3 венью сторонего деплойера (пусто = основной перп-рынок HL). Нужен для
    pre-IPO контрактов: они живут не в основном универсуме, а в отдельном dex («vntl»,
    «para»), и БЕЗ этого параметра ответ их просто не содержит. Параметр добавлен к
    существующей двери, а не скопирован в новую функцию: две копии одного запроса разошлись
    бы на первой правке формата ответа.
    """
    try:
        _body = {"type": "metaAndAssetCtxs"}
        if dex:
            _body["dex"] = str(dex)
        async with httpx.AsyncClient() as client:
            r = await client.post(HL_API, json=_body, timeout=15)
            if r.status_code != 200:
                return None
            d = r.json()
    except Exception as e:
        print("[hl coin] %s%s: %s" % (coin, ('@' + dex) if dex else '', e))
        return None
    if not isinstance(d, list) or len(d) < 2:
        return None
    uni = (d[0] or {}).get("universe") or []
    ctxs = d[1] or []
    c = (coin or "").upper()
    idx = next((i for i, u in enumerate(uni) if (u.get("name") or "").upper() == c), None)
    if idx is None or idx >= len(ctxs):
        return None
    x = ctxs[idx]
    mark = fnum(x.get("markPx"))
    prev = fnum(x.get("prevDayPx"))
    return {
        "mark": mark,
        "oi_usd": fnum(x.get("openInterest")) * mark,   # OI в монете * цена = USD
        "vol24": fnum(x.get("dayNtlVlm")),
        "funding": fnum(x.get("funding")) * 100,        # часовой фандинг, %
        "chg24": (mark / prev - 1) * 100 if prev else 0.0,
    }


async def hl_universe(dex=''):
    """ВСЕ перп-коины Hyperliquid ОДНИМ запросом. -> {ТИКЕР: {mark, oi_usd, vol24, chg24}}.

    ЗАЧЕМ ОТДЕЛЬНО ОТ `hl_coin_stats`. Тот запрашивает ТОТ ЖЕ `metaAndAssetCtxs` и выбрасывает
    всё, кроме одного коина. Пока спрашивали один - это было незаметно; борду риска нужны цены
    сразу по нескольким, и цикл из четырёх вызовов тянул бы один и тот же ответ четыре раза.
    Плюс этот словарь отвечает на вопрос «а какие тикеры вообще есть» - список перп-токенов
    больше не приходится держать в коде руками.

    ПОРЯДОК НЕ НАВЯЗЫВАЕМ: возвращаем словарь, а «топ-N» считает вызывающий (`hl_top_tokens`) -
    по объёму, по OI или по своему признаку. Сортировка внутри источника означала бы, что
    экран не может выбрать критерий, не правя клиент.
    """
    try:
        _body = {"type": "metaAndAssetCtxs"}
        if dex:
            _body["dex"] = str(dex)
        async with httpx.AsyncClient() as client:
            r = await client.post(HL_API, json=_body, timeout=15)
            if r.status_code != 200:
                return {}
            d = r.json()
    except Exception as e:                        # noqa: BLE001
        print("[hl universe] %s" % str(e)[:120])
        return {}
    if not isinstance(d, list) or len(d) < 2:
        return {}
    uni = (d[0] or {}).get("universe") or []
    ctxs = d[1] or []
    out = {}
    for i, u in enumerate(uni):
        if i >= len(ctxs):
            break
        nm = (u.get("name") or "").upper()
        if not nm:
            continue
        x = ctxs[i] or {}
        mark = fnum(x.get("markPx"))
        prev = fnum(x.get("prevDayPx"))
        # ДОБАВЛЕНЫ ТРИ ПОЛЯ, СТАРЫЕ НЕ ТРОНУТЫ. Их просит живой дозорный (`sentinel/venues.py`):
        # без фандинга и спреда он мог бы ловить на Hyperliquid только движение и объём, а свой
        # второй фетчер к тому же `metaAndAssetCtxs` был бы дублем транспорта (закон №40).
        # `impactPxs` - цены исполнения на заметный размер, то есть настоящая цена входа, а не
        # середина: спред считаем из них, и это ЗАМЕР, а не оценка.
        _imp = x.get("impactPxs") or []
        _spread_bps = None
        if isinstance(_imp, list) and len(_imp) >= 2:
            _lo, _hi = fnum(_imp[0]), fnum(_imp[1])
            _mid = (_lo + _hi) / 2 if (_lo and _hi) else 0
            if _mid:
                _spread_bps = abs(_hi - _lo) / _mid * 10000.0
        out[nm] = {"mark": mark,
                   "oi_usd": fnum(x.get("openInterest")) * mark,
                   "vol24": fnum(x.get("dayNtlVlm")),
                   "chg24": (mark / prev - 1) * 100 if prev else 0.0,
                   "oi_base": fnum(x.get("openInterest")),
                   "funding": fnum(x.get("funding")),
                   "spread_bps": _spread_bps}
    return out


def hl_top_tokens(uni, n=10, by='vol24'):
    """Топ перп-тикеров ПО ИЗМЕРЕННОЙ ВЕЛИЧИНЕ. -> [str].

    Список ИЗМЕРЯЕТСЯ, а не пишется руками, и это не косметика: руками написанный список
    «топ-10» устаревает молча - монета уходит из топа, а кнопка остаётся, и человек смотрит
    карту того, чем уже никто не торгует. Здесь порядок = объём за сутки на самой площадке, где
    висит это плечо.
    """
    if not isinstance(uni, dict) or not uni:
        return []
    _key = by if by in ('vol24', 'oi_usd') else 'vol24'
    rows = sorted(uni.items(), key=lambda kv: -(kv[1].get(_key) or 0))
    return [k for k, _v in rows[:max(1, int(n))]]


async def hl_portfolio_curve(addr, window="day"):
    """История net worth HL-счёта (accountValueHistory) за окно day/week/month/allTime.
    Публичный info endpoint type=portfolio. -> list[(ts_sec, usd)] | []."""
    if not _EVM_RE.match(addr or ""):
        return []
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(HL_API, json={"type": "portfolio", "user": addr}, timeout=15)
            if r.status_code != 200:
                return []
            d = r.json()
    except Exception as e:
        print("[hl curve] %s: %s" % ((addr or "")[:8], e))
        return []
    if not isinstance(d, list):
        return []
    wins = dict(d)                      # [["day",{...}],...] -> {"day":{...}}
    w = wins.get(window) or wins.get("day") or {}
    out = []
    for pt in (w.get("accountValueHistory") or []):
        try:
            out.append((int(pt[0]) // 1000, float(pt[1])))   # ts мс -> сек
        except (TypeError, ValueError, IndexError):
            continue
    out.sort()
    return out


def parse_hl_state(j):
    """Разбор ответа clearinghouseState -> {venue, account_value, withdrawable, positions}.

    Вынесен из hl_positions ОТДЕЛЬНОЙ дверью (закон №40): perp_watch гоняет через него и
    QA-заглушку (TEST_MODE), и юнит-тест с мок-ответом - разбор ОДИН, транспорт подменяем
    на границе. Вторая копия разбора разошлась бы с этой на первой правке формата."""
    if not j or not isinstance(j, dict):
        return {"error": "Пустой ответ HL (адрес мастер-аккаунта, не agent wallet?)."}
    acc_val = fnum((j.get("marginSummary") or {}).get("accountValue"))
    poss = []
    for ap in j.get("assetPositions") or []:
        p = ap.get("position") or {}
        szi = fnum(p.get("szi"))
        if not szi:
            continue
        poss.append({
            "coin": p.get("coin"),
            "side": "LONG" if szi > 0 else "SHORT",
            "size": abs(szi),
            "entry": fnum(p.get("entryPx")),
            "value": fnum(p.get("positionValue")),
            "upnl": fnum(p.get("unrealizedPnl")),
            "lev": fnum((p.get("leverage") or {}).get("value")),
            "liq": fnum(p.get("liquidationPx")),
        })
    poss.sort(key=lambda x: -x["value"])
    return {"venue": "Hyperliquid", "account_value": acc_val,
            "withdrawable": fnum(j.get("withdrawable")), "positions": poss}


async def hl_positions(addr):
    """Открытые позиции на Hyperliquid: clearinghouseState (вес 2)."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(HL_API, json={"type": "clearinghouseState",
                                                "user": addr}, timeout=15)
            j = r.json()
        except Exception as e:
            return {"error": f"HL не ответил: {e}"}
    return parse_hl_state(j)


async def lighter_positions(addr):
    """Позиции на Lighter по L1-адресу (вес 300 -> не спамить)."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{LIGHTER_API}/account",
                                 params={"by": "l1_address", "value": addr},
                                 timeout=15)
            j = r.json()
        except Exception as e:
            return {"error": f"Lighter не ответил: {e}"}
    accs = j.get("accounts") or ([j["account"]] if j.get("account") else [])
    if not accs:
        return {"error": "Аккаунт не найден на Lighter."}
    poss = []
    total_collateral = 0.0
    for acc in accs:
        total_collateral += fnum(acc.get("collateral"))
        for p in acc.get("positions") or []:
            size = fnum(p.get("position"))
            if not size:
                continue
            sign = int(p.get("sign") or 1)
            poss.append({
                "coin": p.get("symbol") or f"mkt{p.get('market_id')}",
                "side": "LONG" if sign > 0 else "SHORT",
                "size": abs(size),
                "entry": fnum(p.get("avg_entry_price")),
                "value": abs(size) * fnum(p.get("avg_entry_price")),
                "upnl": fnum(p.get("unrealized_pnl")),
                "liq": fnum(p.get("liquidation_price")),
                "lev": 0.0,
            })
    poss.sort(key=lambda x: -x["value"])
    return {"venue": "Lighter", "account_value": total_collateral,
            "withdrawable": 0.0, "positions": poss}


def format_perps(res, addr):
    if res.get("error"):
        return f"🐋 {res['error']}"
    L = [f"🐋 <b>{res['venue']}</b> <code>{addr[:6]}…{addr[-4:]}</code>",
         f"Счёт: ${res['account_value']:,.0f}"]
    if not res["positions"]:
        return "\n".join(L + ["\nОткрытых позиций нет — кит спит."])
    L.append("")
    for p in res["positions"][:10]:
        e = "🟢" if p["side"] == "LONG" else "🔴"
        pnl = f"{p['upnl']:+,.0f}$"
        lev = f" x{p['lev']:g}" if p.get("lev") else ""
        liq = f" | ликв ${p['liq']:,.4g}" if p.get("liq") else ""
        L.append(f"{e} <b>{p['coin']}</b> {p['side']}{lev} "
                 f"${p['value']:,.0f} @ {p['entry']:,.6g}\n"
                 f"   PnL {pnl}{liq}")
    return "\n".join(L)


async def perps_all(addr):
    """Обе площадки разом."""
    if not _EVM_RE.match(addr):
        return None, None
    hl = await hl_positions(addr)
    lt = await lighter_positions(addr)
    return hl, lt
