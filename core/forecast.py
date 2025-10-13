# core/forecast.py
from __future__ import annotations

from datetime import date, datetime
from typing import Dict

import pandas as pd
import yfinance as yf


def _fetch_adj_close(ticker: str, start: date | datetime, end: date | datetime) -> pd.Series:
    """
    Scarica la serie 'Adj Close' da Yahoo Finance (indice per data, ordinata).
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
    Stima il CAGR (tasso medio annuo composto) sugli ultimi 'years_window' anni.
    Se la finestra è troppo corta, usa l'intera serie disponibile.
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


def forecast_from_history(
    hist: pd.Series,
    future_index: pd.DatetimeIndex,
    *,
    lookback_years: int = 10,
) -> pd.Series:
    """
    Prevede i prezzi futuri assumendo crescita annua costante pari al CAGR
    stimato sugli ultimi 'lookback_years'. Nessuna aleatorietà.
    """
    if hist is None or hist.empty or future_index.empty:
        return pd.Series(dtype=float)

    hist = hist.dropna().sort_index()
    g = _estimate_cagr(hist, years_window=lookback_years)
    last_price = float(hist.iloc[-1])
    last_date = pd.Timestamp(hist.index[-1])

    # Converti CAGR in tasso giornaliero composto
    daily = (1.0 + g) ** (1.0 / 365.25) - 1.0

    vals = []
    for d in future_index:
        days = max(0, int((pd.Timestamp(d) - last_date).days))
        vals.append(last_price * ((1.0 + daily) ** days))
    return pd.Series(vals, index=future_index)
    
