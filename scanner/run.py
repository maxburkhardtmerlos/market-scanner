"""Escaneo completo: descarga, puntúa y escribe docs/data/latest.json.

Uso:
    python -m scanner.run             # escaneo real
    python -m scanner.run --limit 30  # prueba rápida con 30 tickers
    python -m scanner.run --demo      # datos inventados, para probar el dashboard sin red
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import time
from datetime import date, datetime, timedelta, timezone

from . import config as C
from .data import (CACHE, ROOT, fetch_estimates, fetch_prices, load_json, load_universe, log, save_json,
                   update_ath, update_fundamentals)
from .scoring import score_all

OUT = ROOT / "docs" / "data"
FUND_KEYS = ["sector", "industry", "currency", "market_cap", "trail_pe", "peg", "op_margin", "net_margin", "roe", "roic",
             "div_yield", "target_price", "fcf_margin", "net_debt_ebitda", "rev_cagr", "ni_cagr", "op_margin_change",
             "earnings_date"]


# ---------------------------------------------------------------- modo demo
def demo_data(universe, today):
    rnd = random.Random(7)
    sectors = ["Technology", "Healthcare", "Financial Services", "Consumer Cyclical", "Industrials",
               "Consumer Defensive", "Energy", "Utilities", "Basic Materials", "Real Estate", "Communication Services"]
    prices, fund, ath = {}, {}, {}
    for u in universe:
        t = u["ticker"]
        price = round(rnd.uniform(15, 600), 2)
        dd = min(0.0, rnd.gauss(-0.13, 0.13))
        high = price / (1 + max(dd, -0.7))
        spark, p = [], high * rnd.uniform(0.6, 0.95)
        for i in range(52):
            p = p * (1 + rnd.gauss(0, 0.03))
            spark.append(p)
        k = price / spark[-1]
        prices[t] = {"price": price, "price_date": today.isoformat(), "high_52w": high,
                     "chg_1d": round(rnd.gauss(0, 0.015), 4), "chg_5d": round(rnd.gauss(0, 0.03), 4),
                     "chg_1m": round(rnd.gauss(0, 0.06), 4), "above_ma200": rnd.random() > 0.45,
                     "spark": [round(x * k, 2) for x in spark]}
        ath[t] = high * rnd.uniform(1.0, 1.4)
        sector = rnd.choice(sectors)
        fund[t] = {"_d": today.isoformat(), "sector": sector, "industry": "—", "currency": "EUR" if u["region"] == "DE" else "USD",
                   "market_cap": rnd.uniform(3e9, 8e11), "fwd_eps": price / rnd.uniform(8, 40), "trail_pe": rnd.uniform(8, 45),
                   "peg": rnd.uniform(0.6, 3.5), "op_margin": rnd.uniform(0.02, 0.4), "net_margin": rnd.uniform(-0.02, 0.3),
                   "roe": rnd.uniform(0.02, 0.4), "roic": rnd.uniform(0.02, 0.3), "div_yield": rnd.uniform(0, 4),
                   "target_price": price * rnd.uniform(0.9, 1.5), "fcf": None, "fcf_margin": rnd.uniform(-0.02, 0.3),
                   "net_debt_ebitda": rnd.uniform(-1, 5), "rev_cagr": rnd.gauss(0.07, 0.07), "ni_cagr": rnd.gauss(0.08, 0.12),
                   "op_margin_change": rnd.gauss(0, 0.03),
                   "earnings_date": (today + timedelta(days=rnd.randint(1, 90))).isoformat(), "_fcf_yield": rnd.uniform(0, 0.08)}
    est = lambda t: {"eps_rev_90d": round(random.Random(t).gauss(0.0, 0.06), 4),  # noqa: E731
                     "eps_rev_30d": round(random.Random(t + "x").gauss(0.0, 0.03), 4), "earnings_date": None}
    idx = {k: {"name": n, "price": round(rnd.uniform(15, 25000), 2), "chg_1d": round(rnd.gauss(0, 0.01), 4),
               "dd_52w": round(-abs(rnd.gauss(0.04, 0.03)), 4)} for k, n in C.INDICES.items()}
    return prices, fund, ath, est, idx


def _clean(o):
    """Redondea y elimina NaN/inf para que el JSON sea válido y ligero."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        if not math.isfinite(o):
            return None
        return round(o) if abs(o) >= 1e6 else round(o, 4)
    return o


# ---------------------------------------------------------------- principal
def build(args):
    today = date.today()
    universe = load_universe(refresh_sp500=not args.demo)
    if args.limit:
        us = [u for u in universe if u["region"] == "US"][: args.limit]
        de = [u for u in universe if u["region"] == "DE"][: max(5, args.limit // 3)]
        universe = us + de
    tickers = [u["ticker"] for u in universe]
    log(f"Universo: {len(tickers)} acciones")

    failed_fund = []
    if args.demo:
        prices, fund, ath, est_fn, indices = demo_data(universe, today)
    else:
        prices = fetch_prices(tickers)
        log(f"Precios: {len(prices)}/{len(tickers)}")
        if len(prices) < 0.5 * len(tickers):
            raise SystemExit("Yahoo no ha devuelto precios para más de la mitad del universo; no publico datos incompletos.")
        ip = fetch_prices(list(C.INDICES))
        indices = {k: {"name": n, "price": ip[k]["price"], "chg_1d": ip[k]["chg_1d"],
                       "dd_52w": round(ip[k]["price"] / ip[k]["high_52w"] - 1, 4)} for k, n in C.INDICES.items() if k in ip}
        splits = {t: p["split_date"] for t, p in prices.items() if p.get("split_date")}
        ath = update_ath(list(prices), today, splits)
        fund, failed_fund = update_fundamentals(list(prices), today, splits=splits)
        est_fn = fetch_estimates

    stocks = []
    for u in universe:
        t = u["ticker"]
        p, f = prices.get(t), fund.get(t)
        if not p:
            continue
        s = {**u, **{k: p[k] for k in ("price", "price_date", "chg_1d", "chg_5d", "chg_1m", "above_ma200", "spark")}}
        hi = max(p["high_52w"] or 0, p["price"])
        s["dd_52w"] = round(p["price"] / hi - 1, 4)
        a = max(ath.get(t) or 0, hi)
        s["dd_ath"] = round(p["price"] / a - 1, 4)
        if f:
            s.update({k: f.get(k) for k in FUND_KEYS})
            fe = f.get("fwd_eps")
            s["fwd_pe"] = round(p["price"] / fe, 1) if fe and fe > 0 else None
            if f.get("_fcf_yield") is not None:
                s["fcf_yield"] = round(f["_fcf_yield"], 4)
            else:
                s["fcf_yield"] = round(f["fcf"] / f["market_cap"], 4) if f.get("fcf") is not None and f.get("market_cap") else None
            s["upside_target"] = round(f["target_price"] / p["price"] - 1, 3) if f.get("target_price") else None
        s["has_fundamentals"] = bool(f)
        stocks.append(s)

    # 1ª pasada: calidad y caída -> candidatas a las que se piden estimaciones
    score_all(stocks, today)
    cands = [s for s in stocks if s["category"] in ("alerta", "vigilar", "deterioro")]
    log(f"Candidatas (calidad + caída): {len(cands)}; consultando estimaciones")
    for s in cands:
        e = est_fn(s["ticker"])
        s["eps_rev_90d"], s["eps_rev_30d"] = e["eps_rev_90d"], e["eps_rev_30d"]
        if e["earnings_date"]:
            s["earnings_date"] = e["earnings_date"]
        if not args.demo:
            time.sleep(C.SLEEP_BETWEEN_CALLS_S)
    score_all(stocks, today)

    # Historial de alertas: ¿nueva hoy? ¿desde cuándo?
    hist_path = OUT / "history.json"
    hist = {} if args.demo else load_json(hist_path, {})
    prev_days = sorted(d for d in hist if d < today.isoformat())
    alerts_now = sorted(s["ticker"] for s in stocks if s["category"] == "alerta")
    for s in stocks:
        if s["category"] == "alerta":
            since = today.isoformat()
            for d in reversed(prev_days):
                if s["ticker"] in hist[d]:
                    since = d
                else:
                    break
            s["alert_since"] = since
            s["alert_new"] = bool(prev_days) and since == today.isoformat()
    hist[today.isoformat()] = alerts_now
    hist = {d: hist[d] for d in sorted(hist)[-180:]}

    for s in stocks:  # el gráfico de 1 año solo viaja con las candidatas
        if s["category"] not in ("alerta", "vigilar", "deterioro"):
            s.pop("spark", None)
        s.pop("quality_parts", None) if s["category"] == "resto" else None

    # Resumen de mercado y sectores
    def share(pred, items):
        vals = [pred(x) for x in items if pred(x) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    breadth = {}
    for reg in ("US", "DE"):
        grp = [s for s in stocks if s["region"] == reg]
        breadth[reg] = {"n": len(grp), "above_ma200": share(lambda s: s["above_ma200"], grp),
                        "down_25": share(lambda s: s["dd_52w"] <= -C.DRAWDOWN_ALERT, grp)}
    sectors = {}
    for s in stocks:
        if s.get("sector"):
            sectors.setdefault(s["sector"], []).append(s)
    sector_rows = [{"sector": k, "n": len(v), "median_dd_52w": round(statistics.median(x["dd_52w"] for x in v), 4),
                    "median_fwd_pe": v[0].get("sector_pe"),
                    "alerts": sum(1 for x in v if x["category"] == "alerta")} for k, v in sectors.items() if len(v) >= 3]
    sector_rows.sort(key=lambda r: r["median_dd_52w"])

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": bool(args.demo),
        "config": {k: getattr(C, k) for k in ("DRAWDOWN_ALERT", "DRAWDOWN_WATCH", "QUALITY_MIN", "VALUATION_MIN", "EPS_REV_MIN",
                                              "EARNINGS_WARN_DAYS", "EARNINGS_WINDOW_DAYS", "PE_ABS_CHEAP")},
        "indices": indices,
        "breadth": breadth,
        "sectors": sector_rows,
        "coverage": {"universe": len(tickers), "with_prices": len(stocks),
                     "with_fundamentals": sum(1 for s in stocks if s["has_fundamentals"]),
                     "no_price": sorted(set(tickers) - {s["ticker"] for s in stocks}), "fund_failed": failed_fund[:50]},
        "stocks": stocks,
    }
    save_json(OUT / "latest.json", _clean(out))
    if not args.demo:
        save_json(hist_path, hist)
    cats = {}
    for s in stocks:
        cats[s["category"]] = cats.get(s["category"], 0) + 1
    log(f"Hecho. {cats}. Alertas: {', '.join(alerts_now) or 'ninguna'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    build(ap.parse_args())
