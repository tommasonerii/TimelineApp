# core/forecast.py
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


# ------------------ utilità base ------------------
def _fetch_adj_close(ticker: str, start: date | datetime, end: date | datetime) -> pd.Series:
    """
    Scarica 'Adj Close' da Yahoo Finance (indice per data, ordinata).
    """
    df = yf.download(
        tickers=ticker,
        start=pd.Timestamp(start).date().isoformat(),
        end=(pd.Timestamp(end).date() + pd.Timedelta(days=1)).isoformat(),  # end esclusiva
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if isinstance(df.columns, pd.MultiIndex):
        s = df.xs("Adj Close", axis=1, level=1)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
    else:
        s = df["Adj Close"]
    return s.dropna().sort_index()


def _estimate_cagr(series: pd.Series, years_window: float) -> float:
    """
    CAGR sugli ultimi 'years_window' anni (fallback: tutta la serie).
    """
    if series is None or series.empty:
        return 0.0
    end = series.index[-1]
    start_cut = end - pd.DateOffset(years=years_window)
    w = series[series.index >= start_cut]
    if len(w) < 30:
        w = series
        years = max((w.index[-1] - w.index[0]).days / 365.25, 0.25)
    else:
        years = years_window
    if years <= 0 or len(w) < 2:
        return 0.0
    return (float(w.iloc[-1]) / float(w.iloc[0])) ** (1.0 / years) - 1.0


def forecast_from_history(hist: pd.Series, future_index: pd.DatetimeIndex, *, lookback_years: int = 5) -> pd.Series:
    """
    CAGR deterministico (baseline).
    """
    if hist is None or hist.empty or future_index.empty:
        return pd.Series(dtype=float)
    hist = hist.dropna().sort_index()
    g = _estimate_cagr(hist, years_window=lookback_years)
    last_price = float(hist.iloc[-1])
    last_date = pd.Timestamp(hist.index[-1])
    daily = (1.0 + g) ** (1.0 / 365.25) - 1.0
    vals = []
    for d in future_index:
        days = max(0, int((pd.Timestamp(d) - last_date).days))
        vals.append(last_price * ((1.0 + daily) ** days))
    return pd.Series(vals, index=future_index)


# ------------------ CAGR-X con proxy macro Yahoo ------------------
def _tnx_to_decimal(y: float) -> float:
    """
    ^TNX su Yahoo tipicamente è in 'punti' (43.21 ≈ 4.321%).
    Se y>1 → /1000, altrimenti già decimale.
    """
    if y is None:
        return None
    return y / 1000.0 if y > 1.0 else y


def _zscore_last(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 30:
        return 0.0
    m = float(s.mean())
    sd = float(s.std()) + 1e-9
    return float((float(s.iloc[-1]) - m) / sd)


def forecast_cagrx_from_yfinance(
    hist: pd.Series,
    future_index: pd.DatetimeIndex,
    *,
    lookback_years: int = 5,
    macro_years: int = 5,
    max_upshift: float = 0.03,   # +300 bps massimo
    max_downshift: float = 0.03  # -300 bps massimo
) -> pd.Series:
    """
    CAGR-X: CAGR storico aggiustato in base a proxy macro da Yahoo:
      - ^TNX (tasso 10Y)   → zscore negativo (tassi alti = crescita più prudente)
      - ^VIX (volatilità)  → zscore negativo
      - DX-Y.NYB (Dollar)  → zscore leggermente negativo (penalizza globale)
    L'aggiustamento è "clamped" per stabilità di lungo periodo.
    """
    if hist is None or hist.empty or future_index.empty:
        return pd.Series(dtype=float)

    hist = hist.dropna().sort_index()
    base_cagr = _estimate_cagr(hist, years_window=lookback_years)

    # Finestra macro
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=max(macro_years, 3))

    # Proxy macro
    tnx = _fetch_adj_close("^TNX", start, end).apply(_tnx_to_decimal)
    vix = _fetch_adj_close("^VIX", start, end)
    dxy = _fetch_adj_close("DX-Y.NYB", start, end)

    z_tnx = _zscore_last(tnx)
    z_vix = _zscore_last(vix)
    z_dxy = _zscore_last(dxy)

    # Pesi piccoli (in bps per 1σ) per non snaturare il CAGR
    w_tnx = -0.004   # −40 bps per 1σ
    w_vix = -0.003   # −30 bps per 1σ
    w_dxy = -0.0015  # −15 bps per 1σ

    adj = float(np.clip(w_tnx * z_tnx + w_vix * z_vix + w_dxy * z_dxy,
                        -max_downshift, max_upshift))

    g = base_cagr + adj
    # Guardrail finali: tra −5% e +15% annui
    g = float(np.clip(g, -0.05, 0.15))

    last_price = float(hist.iloc[-1])
    last_date = pd.Timestamp(hist.index[-1])
    daily = (1.0 + g) ** (1.0 / 365.25) - 1.0

    vals = []
    for d in future_index:
        days = max(0, int((pd.Timestamp(d) - last_date).days))
        vals.append(last_price * ((1.0 + daily) ** days))
    return pd.Series(vals, index=future_index)
