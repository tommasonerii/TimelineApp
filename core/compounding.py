# core/compounding.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import List

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CompoundParams:
    initial: float = 10_000.0           # capitale iniziale (€)
    monthly: float = 300.0              # versamento mensile (€)
    annual_rate: float = 0.05           # rendimento annuo lordo (0..1)
    mgmt_fee_annual: float = 0.005      # commissione annua gestione (0..1)
    inflation_rate: float = 0.02        # inflazione annua attesa (0..1)
    years: int = 20                     # orizzonte (anni)


def _date_range_daily(start: date, years: int) -> List[date]:
    """Serie giornaliera da start a start+years (inclusa), robusta per fine mese."""
    end = date(start.year + years, start.month, min(start.day, 28))
    n = (end - start).days
    return [start + timedelta(days=i) for i in range(n + 1)]


@lru_cache(maxsize=64)
def simulate_compound(start: date, p: CompoundParams) -> pd.DataFrame:
    """
    Simula interesse composto con contribuzioni mensili (il giorno 1 di ogni mese).
    Ritorna DataFrame indicizzato per data (DatetimeIndex) con colonne:
      - value            : valore portafoglio nominale (€)
      - contrib          : contributi cumulati (€)
      - net_rate         : tasso netto giornaliero applicato (decimale)
      - inflation_value  : valore che crescerebbe SOLO all'inflazione attesa (€)
      - real_value       : valore REALE (deflazionato: potere d'acquisto del portafoglio)

    Modello:
      v[t+1] = v[t]*(1+r_net) + contrib_mese_if_day
      r_net  = (1+annual_rate)^(1/365)-1 - mgmt_fee_annual/365
      infl   = (1+inflation_rate)^(1/365)-1
    """
    if p.years <= 0:
        raise ValueError("years must be > 0")

    # tassi giornalieri
    daily_gross = (1.0 + float(p.annual_rate)) ** (1.0 / 365.0) - 1.0
    daily_mgmt  = float(p.mgmt_fee_annual) / 365.0
    daily_net   = daily_gross - daily_mgmt
    daily_infl  = (1.0 + float(p.inflation_rate)) ** (1.0 / 365.0) - 1.0

    dates = _date_range_daily(start, p.years)
    index = pd.to_datetime(dates)

    n_days = len(index)
    values = np.empty(n_days, dtype=float)
    contribs = np.empty(n_days, dtype=float)
    infl_values = np.empty(n_days, dtype=float)
    rates = np.full(n_days, daily_net, dtype=float)

    if p.monthly > 0.0:
        contrib_increment = np.where(index.day == 1, float(p.monthly), 0.0)
    else:
        contrib_increment = np.zeros(n_days, dtype=float)

    initial = float(p.initial)
    values[0] = initial + contrib_increment[0]
    contribs[0] = initial + contrib_increment[0]
    infl_values[0] = initial + contrib_increment[0]

    growth = 1.0 + daily_net
    infl_growth = 1.0 + daily_infl
    for i in range(1, n_days):
        values[i] = values[i - 1] * growth + contrib_increment[i]
        contribs[i] = contribs[i - 1] + contrib_increment[i]
        infl_values[i] = infl_values[i - 1] * infl_growth + contrib_increment[i]

    # fattore di inflazione cumulato e valore reale (deflazionato)
    infl_factor = infl_values / infl_values[0]
    # Evita divisioni per zero o numeri patologici
    infl_factor = np.where(infl_factor <= 0, 1.0, infl_factor)
    real_values = values / infl_factor

    df = pd.DataFrame({
        "value": values,
        "contrib": contribs,
        "net_rate": rates,
        "inflation_value": infl_values,
        "real_value": real_values,
    }, index=index)
    return df
