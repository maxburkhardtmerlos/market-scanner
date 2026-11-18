"""Universo de acciones y descarga de datos (Yahoo Finance vía yfinance, gratis y sin clave)."""
from __future__ import annotations

import csv
import io
import json
import math
import time
import zlib
from datetime import date, datetime, timezone
from pathlib import Path

from . import config as C

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "universe"
CACHE = ROOT / "cache"
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"


# ---------------------------------------------------------------- utilidades
def num(x):
    """Convierte a float limpio o None (sin NaN/inf)."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def log(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- universo
def _read_semicolon(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            t = (r.get("ticker") or "").strip()
            if t and not t.startswith("#"):
                rows.append(r)
    return rows


def load_universe(refresh_sp500=True):
    """Devuelve [{ticker, name, region, index}] sin duplicados."""
    sp_path = UNIVERSE / "sp500.csv"
    if refresh_sp500:
        try:
            import requests

            r = requests.get(SP500_URL, timeout=20)
            if r.ok and r.text.count("\n") > 400:
                sp_path.write_text(r.text, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log(f"No se pudo actualizar la lista del S&P 500 ({e!r}); uso la copia local")

    out, seen = [], set()

    def add(ticker, name, region, index):
        if ticker not in seen:
            seen.add(ticker)
            out.append({"ticker": ticker, "name": name, "region": region, "index": index})

    with sp_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(io.StringIO(f.read())):
            add(r["Symbol"].strip().replace(".", "-"), r["Security"].strip(), "US", "S&P 500")
    for r in _read_semicolon(UNIVERSE / "dax.csv"):
        add(r["ticker"].strip(), r["name"].strip(), "DE", "DAX")
    for r in _read_semicolon(UNIVERSE / "mdax.csv"):
        add(r["ticker"].strip(), r["name"].strip(), "DE", "MDAX")
    for r in _read_semicolon(UNIVERSE / "extra.csv"):
        add(r["ticker"].strip(), r["name"].strip(), (r.get("region") or "US").strip(), "Extra")
    return out


# ---------------------------------------------------------------- precios
def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _download(tickers, **kw):
    import yfinance as yf

    for attempt in range(3):
        try:
            df = yf.download(tickers, group_by="ticker", auto_adjust=False, threads=True, progress=False, **kw)
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            log(f"Fallo de descarga (intento {attempt + 1}): {e!r}")
        time.sleep(20 * (attempt + 1))
    return None


def _sub(df, ticker):
    import pandas as pd

    if df is None:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        if ticker not in df.columns.get_level_values(0):
            return None
        sub = df[ticker]
    else:
        sub = df
    sub = sub.dropna(subset=["Close"])
    return sub if not sub.empty else None


def fetch_prices(tickers):
    """Un año de precios diarios -> métricas por ticker."""
    out = {}
    for chunk in _chunks(tickers, 80):
        df = _download(chunk, period="1y", interval="1d", actions=True)
        for t in chunk:
            sub = _sub(df, t)
            if sub is None or len(sub) < 30:
                continue
            close = sub["Close"]
            split_date = None
            if "Stock Splits" in sub.columns:
                sp = sub["Stock Splits"].fillna(0)
                sp = sp[sp > 0]
                if len(sp):
                    split_date = str(sp.index[-1].date())
            last = num(close.iloc[-1])
            if not last:
                continue

            def chg(n):
                if len(close) > n:
                    base = num(close.iloc[-1 - n])
                    return round(last / base - 1, 4) if base else None
                return None

            ma200 = num(close.iloc[-200:].mean()) if len(close) >= 200 else None
            weekly = close.iloc[::-1].iloc[::5].iloc[::-1]
            out[t] = {
                "price": round(last, 2),
                "price_date": str(sub.index[-1].date()),
                "high_52w": num(sub["High"].max()),
                "chg_1d": chg(1),
                "chg_5d": chg(5),
                "chg_1m": chg(21),
                "above_ma200": (last > ma200) if ma200 else None,
                "spark": [round(float(x), 2) for x in weekly.tolist() if math.isfinite(float(x))],
                "split_date": split_date,  # último split del año (para invalidar cachés)
            }
        time.sleep(1)
    return out


def _split_after(splits, t, cached_iso):
    """True si el ticker ha tenido un split desde que se guardó en caché (los precios viejos ya no son comparables)."""
    s = (splits or {}).get(t)
    return bool(s and cached_iso <= s)


def update_ath(tickers, today: date, splits=None):
    """Máximo histórico: se recalcula completo cada ATH_REFRESH_DAYS (o tras un split); si no, se mantiene en caché."""
    path = CACHE / "ath.json"
    cache = load_json(path, {})
    stale = [
        t for t in tickers
        if t not in cache
        or (today - date.fromisoformat(cache[t]["d"])).days >= C.ATH_REFRESH_DAYS + zlib.crc32(t.encode()) % 7
        or _split_after(splits, t, cache[t]["d"])
    ]
    if stale:
        log(f"Máximos históricos: actualizando {len(stale)} tickers")
    for chunk in _chunks(stale, 60):
        df = _download(chunk, period="max", interval="1mo")
        for t in chunk:
            sub = _sub(df, t)
            if sub is None:
                continue
            h = num(sub["High"].max())
            if h:
                cache[t] = {"ath": h, "d": today.isoformat()}
        time.sleep(1)
    save_json(path, cache)
    return {t: v["ath"] for t, v in cache.items()}


# ---------------------------------------------------------------- fundamentales
def _is_rate_limit(e: Exception):
    s = f"{type(e).__name__} {e}".lower()
    return "ratelimit" in s or "too many requests" in s or "429" in s


def _row(stmt, names):
    for n in names:
        if n in stmt.index:
            vals = [num(v) for v in stmt.loc[n].tolist()]
            return vals  # más reciente primero
    return []


def _cagr(vals):
    """vals: más reciente primero. CAGR entre el primero y el más antiguo disponible (máx. 3 años)."""
    vals = [v for v in vals[:4]]
    while vals and vals[-1] is None:
        vals.pop()
    if len(vals) < 2 or vals[0] is None:
        return None
    new, old, n = vals[0], vals[-1], len(vals) - 1
    if old is None or old <= 0:
        return None
    if new <= 0:
        return -1.0
    return round((new / old) ** (1 / n) - 1, 4)


def fetch_fundamentals(ticker: str):
    """Datos fundamentales de un ticker (2 llamadas a Yahoo). Lanza excepción si falla."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    info = t.info or {}
    if not info.get("marketCap") and not info.get("sector"):
        raise ValueError("sin datos en Yahoo")
    g = lambda k: num(info.get(k))  # noqa: E731

    d = {
        "yname": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "market_cap": g("marketCap"),
        "fwd_eps": g("forwardEps"),
        "trail_pe": g("trailingPE"),
        "peg": g("trailingPegRatio") or g("pegRatio"),
        "op_margin": g("operatingMargins"),
        "net_margin": g("profitMargins"),
        "roe": g("returnOnEquity"),
        "div_yield": g("dividendYield"),
        "target_price": g("targetMeanPrice"),
        "shares": g("sharesOutstanding"),
    }
    if not d["market_cap"] or not d["shares"]:
        # Algunas acciones alemanas (p. ej. CON.DE) vienen sin marketCap/sharesOutstanding en .info
        try:
            fi = t.fast_info
            d["shares"] = d["shares"] or num(fi["shares"])
            d["market_cap"] = d["market_cap"] or num(fi["marketCap"])
        except Exception as e:  # noqa: BLE001
            if _is_rate_limit(e):
                raise
    same_ccy = (info.get("financialCurrency") or info.get("currency")) == info.get("currency")
    fcf, rev, debt, cash, ebitda = g("freeCashflow"), g("totalRevenue"), g("totalDebt"), g("totalCash"), g("ebitda")
    d["fcf"] = fcf if same_ccy else None  # con ADRs la divisa de las cuentas no coincide con la del precio
    d["fcf_margin"] = round(fcf / rev, 4) if fcf is not None and rev else None
    d["net_debt_ebitda"] = round(((debt or 0) - (cash or 0)) / ebitda, 2) if ebitda and ebitda > 0 and debt is not None else None

    ts = g("earningsTimestampStart") or g("earningsTimestamp")
    d["earnings_date"] = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else None

    # Cuenta de resultados anual: crecimiento a 3 años y tendencia de margen
    d["rev_cagr"] = d["ni_cagr"] = d["op_margin_change"] = d["roic"] = None
    try:
        stmt = t.income_stmt
        if stmt is not None and not stmt.empty:
            revs = _row(stmt, ["Total Revenue", "Operating Revenue"])
            nis = _row(stmt, ["Net Income", "Net Income Common Stockholders"])
            ops = _row(stmt, ["Operating Income", "EBIT"])
            d["rev_cagr"] = _cagr(revs)
            d["ni_cagr"] = _cagr(nis)
            pairs = [(o, r) for o, r in zip(ops[:4], revs[:4]) if o is not None and r]
            if len(pairs) >= 2:
                d["op_margin_change"] = round(pairs[0][0] / pairs[0][1] - pairs[-1][0] / pairs[-1][1], 4)
            bv = g("bookValue")
            if pairs and bv is not None and d["shares"] and same_ccy:
                invested = (debt or 0) + bv * d["shares"]
                if invested > 0:
                    d["roic"] = round(pairs[0][0] * 0.79 / invested, 4)
    except Exception as e:  # noqa: BLE001
        if _is_rate_limit(e):
            raise
    return d


def update_fundamentals(tickers, today: date, demo_fetch=None, splits=None):
    """Refresca la caché de fundamentales de forma escalonada y con límite de tiempo.
    Tras un split se refresca enseguida: el EPS y el precio objetivo en caché estarían en la escala antigua."""
    path = CACHE / "fundamentals.json"
    cache = load_json(path, {})
    fetch = demo_fetch or fetch_fundamentals

    def age(t):
        return (today - date.fromisoformat(cache[t]["_d"])).days if t in cache else 10**6

    todo = [t for t in tickers
            if age(t) >= C.FUND_REFRESH_DAYS + zlib.crc32(t.encode()) % 5
            or (t in cache and _split_after(splits, t, cache[t]["_d"]))]
    todo.sort(key=age, reverse=True)  # primero los que no tienen datos
    log(f"Fundamentales: {len(todo)} tickers por actualizar de {len(tickers)}")
    start, fails_in_a_row, failed = time.time(), 0, []
    for i, t in enumerate(todo):
        if time.time() - start > C.FUND_TIME_BUDGET_S:
            log(f"Límite de tiempo alcanzado; quedan {len(todo) - i} para la próxima ejecución")
            break
        if fails_in_a_row >= 8:
            log("Demasiados fallos seguidos (¿límite de Yahoo?); sigo con la caché")
            break
        for attempt in range(3):
            try:
                d = fetch(t)
                d["_d"] = today.isoformat()
                cache[t] = d
                fails_in_a_row = 0
                break
            except Exception as e:  # noqa: BLE001
                if _is_rate_limit(e) and attempt < 2:
                    log(f"Yahoo limita peticiones; espero {60 * (attempt + 1)} s")
                    time.sleep(60 * (attempt + 1))
                    continue
                failed.append(t)
                fails_in_a_row += 1
                log(f"  {t}: sin fundamentales ({type(e).__name__}: {str(e)[:80]})")
                break
        if not demo_fetch:
            time.sleep(C.SLEEP_BETWEEN_CALLS_S)
        if i and i % 50 == 0:
            save_json(path, cache)
            log(f"  {i}/{len(todo)}")
    save_json(path, cache)
    return cache, failed


def fetch_estimates(ticker: str):
    """Revisión del EPS estimado (90 y 30 días) y próxima fecha de resultados. Solo para candidatas."""
    import yfinance as yf

    out = {"eps_rev_90d": None, "eps_rev_30d": None, "earnings_date": None}
    t = yf.Ticker(ticker)
    try:
        df = t.eps_trend
        if df is not None and not df.empty:
            row = df.loc["+1y"] if "+1y" in df.index else df.loc["0y"]
            cur = num(row.get("current"))
            for key, col in (("eps_rev_90d", "90daysAgo"), ("eps_rev_30d", "30daysAgo")):
                old = num(row.get(col))
                if cur is not None and old:
                    out[key] = round((cur - old) / abs(old), 4)
    except Exception as e:  # noqa: BLE001
        log(f"  {ticker}: sin tendencia de EPS ({type(e).__name__})")
    try:
        cal = t.calendar or {}
        dates = cal.get("Earnings Date") or []
        if dates:
            out["earnings_date"] = str(dates[0])[:10]
    except Exception:  # noqa: BLE001
        pass
    return out
