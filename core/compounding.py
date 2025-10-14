# core/compounding.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CompoundParams:
    initial: float = 10_000.0           # capitale iniziale (€)
    monthly: float = 300.0              # versamento mensile (€)
    annual_rate: float = 0.05           # rendimento annuo lordo (0..1)
    mgmt_fee_annual: float = 0.005      # commissione annua gestione (0..1)
    years: int = 20                     # orizzonte (anni)

def _date_range_daily(start: date, years: int) -> List[date]:
    """Serie giornaliera da start a start+years (inclusa), robusta per fine mese."""
    end = date(start.year + years, start.month, min(start.day, 28))
    n = (end - start).days
    return [start + timedelta(days=i) for i in range(n + 1)]

def simulate_compound(start: date, p: CompoundParams) -> pd.DataFrame:
    """
    Simula interesse composto con contribuzioni mensili.
    Ritorna DataFrame indicizzato per data (DatetimeIndex) con colonne:
      - value   : valore portafoglio (€)
      - contrib : contributi cumulati (€)
      - net_rate: tasso netto giornaliero applicato (decimale)
    Modello:
      v[t+1] = v[t]*(1+r_net) + contrib_mese_if_day
      r_net = (1+annual_rate)^(1/365)-1 - mgmt_fee_annual/365
    Le contribuzioni mensili sono applicate il primo giorno di ogni mese.
    """
    if p.years <= 0:
        raise ValueError("years must be > 0")

    # tasso netto giornaliero
    daily_gross = (1.0 + float(p.annual_rate)) ** (1.0 / 365.0) - 1.0
    daily_mgmt  = float(p.mgmt_fee_annual) / 365.0
    daily_net   = daily_gross - daily_mgmt

    dates = _date_range_daily(start, p.years)
    index = pd.to_datetime(dates)

    n_days = len(index)
    values = np.empty(n_days, dtype=float)
    contribs = np.empty(n_days, dtype=float)
    rates = np.full(n_days, daily_net, dtype=float)

    if p.monthly > 0.0:
        contrib_increment = np.where(index.day == 1, float(p.monthly), 0.0)
    else:
        contrib_increment = np.zeros(n_days, dtype=float)

    initial = float(p.initial)
    values[0] = initial + contrib_increment[0]
    contribs[0] = initial + contrib_increment[0]

    growth = 1.0 + daily_net
    for i in range(1, n_days):
        values[i] = values[i - 1] * growth + contrib_increment[i]
        contribs[i] = contribs[i - 1] + contrib_increment[i]

    df = pd.DataFrame({
        "value": values,
        "contrib": contribs,
        "net_rate": rates,
    }, index=index)
    return df
