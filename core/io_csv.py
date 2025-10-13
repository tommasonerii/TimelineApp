from typing import List, Tuple
import pandas as pd
from .models import Event
from .parsing import parse_eventi_field, parse_date

# Nomi colonne attesi (case-insensitive)
EXPECTED = {
    "submission date": "Submission Date",
    "nome": "Nome",
    "eventi": "Eventi",
}

def _map_columns(df: pd.DataFrame) -> Tuple[str, str, str]:
    lower = {c.lower(): c for c in df.columns}
    try:
        subm_col = lower["submission date"]
        nome_col = lower["nome"]
    except KeyError:
        raise ValueError("Il CSV deve contenere le colonne: 'Submission Date', 'Nome', 'Eventi'.")

    eventi_col = lower.get("eventi") or lower.get("eventi:")
    if eventi_col is None:
        raise ValueError("Il CSV deve contenere le colonne: 'Submission Date', 'Nome', 'Eventi'.")

    return subm_col, nome_col, eventi_col

def load_events_csv(path: str) -> List[Event]:
    df = pd.read_csv(path)
    subm_col, nome_col, eventi_col = _map_columns(df)

    events: List[Event] = []
    for _, row in df.iterrows():
        nome = str(row.get(nome_col, "")).strip()
        if not nome:
            continue
        text = str(row.get(eventi_col, "")).strip()
        extracted = parse_eventi_field(text)
        for ev in extracted:
            dt = parse_date(ev["DataEvento"])
            if dt is None:
                # scartiamo eventi con data non valida; potremmo anche accumulare un log
                continue
            events.append(Event(
                nome=nome,
                titolo=ev["Titolo"],
                categoria=ev["Categoria"],
                data_str=ev["DataEvento"],
                dt=dt
            ))
    return sorted(events, key=lambda e: e.dt)
