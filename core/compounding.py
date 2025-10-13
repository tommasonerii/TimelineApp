# core/compounding.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List

import pandas as pd


@dataclass(frozen=True)
class CompoundParams:
    initial: float = 10_000.0           # capitale iniziale (€)
    monthly: float = 300.0              # versamento mensile (€)
    annual_rate: float = 0.05           # rendimento annuo lordo (0..1)
    mgmt_fee_annual: float = 0.005      # commissione annua gestione (0..1)
    overnight_daily: float = 0.0        # commissione overnight giornaliera (0..1)
    years: int = 20                     # orizzonte (anni)
    contribution_day: int = 1           # giorno del mese (1..28)

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
      r_net = (1+annual_rate)^(1/365)-1 - mgmt_fee_annual/365 - overnight_daily
    """
    if p.years <= 0:
        raise ValueError("years must be > 0")
    if not (1 <= p.contribution_day <= 28):
        raise ValueError("contribution_day must be in [1, 28]")

    # tasso netto giornaliero
    daily_gross = (1.0 + float(p.annual_rate)) ** (1.0 / 365.0) - 1.0
    daily_mgmt  = float(p.mgmt_fee_annual) / 365.0
    daily_net   = daily_gross - daily_mgmt - float(p.overnight_daily)

    dates = _date_range_daily(start, p.years)

    v = float(p.initial)
    contrib_cum = float(p.initial)
    values = []
    contribs = []
    rates = []

    def is_contribution_day(d: date) -> bool:
        # versa il giorno p.contribution_day di ogni mese (se coincide con start e giorno=contribution_day, versa subito)
        return d.day == p.contribution_day

    for i, d in enumerate(dates):
        if i > 0:
            v *= (1.0 + daily_net)
        if is_contribution_day(d) and p.monthly > 0.0:
            v += float(p.monthly)
            contrib_cum += float(p.monthly)
        values.append(v)
        contribs.append(contrib_cum)
        rates.append(daily_net)

    df = pd.DataFrame({
        "value": values,
        "contrib": contribs,
        "net_rate": rates,
    }, index=pd.to_datetime(dates))
    return df
