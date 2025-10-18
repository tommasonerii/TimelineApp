from typing import List, Tuple, Optional
import pandas as pd
from .models import Event
from .parsing import parse_eventi_field, parse_date, parse_personal_data

# Nomi colonne attesi (case-insensitive)
EXPECTED = {
    "submission date": "Submission Date",
    "eventi": "Eventi:",
    "dati personali": "Dati Personali",
    # retrocompatibilità (se disponibili):
    "nome": "Nome",
    "cognome": "Cognome",
}

def _map_columns(df: pd.DataFrame) -> Tuple[str, str, Optional[str], Optional[str], Optional[str]]:
    """Ritorna le colonne (submission, eventi, nome, cognome, dati_personali)."""
    lower = {c.lower(): c for c in df.columns}
    subm_col = lower.get("submission date")
    # eventi: può essere "Eventi" o "Eventi:"
    eventi_col = lower.get("eventi:") or lower.get("eventi")
    nome_col = lower.get("nome")
    cognome_col = lower.get("cognome")
    dati_pers_col = lower.get("dati personali")
    if not (subm_col and eventi_col and (dati_pers_col or nome_col)):
        raise ValueError("Il CSV deve contenere: 'Submission Date', 'Eventi:' e 'Dati Personali' (oppure 'Nome'[/ 'Cognome']).")
    return subm_col, eventi_col, nome_col, cognome_col, dati_pers_col

def load_events_csv(path: str) -> List[Event]:
    df = pd.read_csv(path)
    subm_col, eventi_col, nome_col, cognome_col, dati_pers_col = _map_columns(df)

    events: List[Event] = []
    for _, row in df.iterrows():
        # Deriva il nome completo
        full_name = ""
        if dati_pers_col:
            nome, cognome = parse_personal_data(row.get(dati_pers_col, ""))
            full_name = f"{nome} {cognome}".strip()
        elif nome_col:
            nome = str(row.get(nome_col, "")).strip()
            if cognome_col:
                cognome = str(row.get(cognome_col, "")).strip()
                full_name = f"{nome} {cognome}".strip()
            else:
                full_name = nome

        if not full_name:
            continue

        text = str(row.get(eventi_col, "")).strip()
        extracted = parse_eventi_field(text)
        for ev in extracted:
            dt = parse_date(ev["DataEvento"])
            if dt is None:
                # scarta eventi con data non valida
                continue
            events.append(Event(
                nome=full_name,
                titolo=ev["Titolo"],
                categoria=ev["Categoria"],
                data_str=ev["DataEvento"],
                dt=dt
            ))
    return sorted(events, key=lambda e: e.dt)
