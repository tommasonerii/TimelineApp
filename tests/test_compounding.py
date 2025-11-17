from datetime import date

import numpy as np
import pytest

from core.compounding import CompoundParams, simulate_compound


def test_simulate_compound_applies_monthly_contributions_on_first_day():
    start = date(2024, 1, 1)
    params = CompoundParams(
        initial=1000.0,
        monthly=300.0,
        annual_rate=0.0,
        mgmt_fee_annual=0.0,
        inflation_rate=0.0,
        years=1,
    )
    df = simulate_compound(start, params)

    assert df.index[0].date() == start
    assert np.isclose(df.iloc[0]["value"], 1300.0)
    assert np.isclose(df.iloc[0]["contrib"], 1300.0)

    # Fino al 31 gennaio nessun versamento aggiuntivo
    jan_last = df.loc["2024-01-31"]
    assert np.isclose(jan_last["contrib"], 1300.0)
    assert np.isclose(jan_last["value"], 1300.0)

    feb_first = df.loc["2024-02-01"]
    assert np.isclose(feb_first["contrib"], 1600.0)
    assert np.isclose(feb_first["value"], 1600.0)

    # Il valore reale deve coincidere con il nominale nel primo giorno (inflazione nulla)
    assert np.isclose(df.iloc[0]["real_value"], df.iloc[0]["value"])


def test_simulate_compound_requires_positive_years():
    start = date(2024, 1, 1)
    params = CompoundParams(years=0)
    with pytest.raises(ValueError):
        simulate_compound(start, params)
