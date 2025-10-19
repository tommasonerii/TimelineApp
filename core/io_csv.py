from typing import List, Tuple, Optional, Dict
import pandas as pd
from .models import Event, PersonInfo
from .parsing import parse_eventi_field, parse_date, parse_personal_data, parse_personal_details

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
    """Ritorna le colonne (submission, eventi, nome, cognome, dati_personali). Gestisce BOM e due punti finali."""
    def normalize(col: str) -> str:
        x = (col or "").strip().lstrip("\ufeff").lower()
        x = x.replace("\xa0", " ")
        if x.endswith(":"):
            x = x[:-1]
        return x
    norm_map: Dict[str, str] = {normalize(c): c for c in df.columns}
    subm_col = norm_map.get("submission date")
    eventi_col = norm_map.get("eventi")
    nome_col = norm_map.get("nome")
    cognome_col = norm_map.get("cognome")
    dati_pers_col = norm_map.get("dati personali")
    if not (subm_col and eventi_col and (dati_pers_col or nome_col)):
        raise ValueError("Il CSV deve contenere: 'Submission Date', 'Eventi:' e 'Dati Personali' (oppure 'Nome'[/ 'Cognome']).")
    return subm_col, eventi_col, nome_col, cognome_col, dati_pers_col

def load_events_csv(path: str) -> Tuple[List[Event], dict]:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    subm_col, eventi_col, nome_col, cognome_col, dati_pers_col = _map_columns(df)

    events: List[Event] = []
    people: dict = {}
    for _, row in df.iterrows():
        # Deriva il nome completo
        full_name = ""
        if dati_pers_col:
            details = parse_personal_details(row.get(dati_pers_col, ""))
            nome = details.get("nome", "")
            cognome = details.get("cognome", "")
            full_name = f"{nome} {cognome}".strip()
            sesso = (details.get("sesso", "") or "").strip()
            nascita_str = (details.get("nascita_str", "") or "").strip()
            nascita_dt = parse_date(nascita_str) if nascita_str else None
            if full_name and full_name not in people:
                people[full_name] = PersonInfo(nome=nome, cognome=cognome, sesso=sesso, nascita=nascita_dt)
        elif nome_col:
            nome = str(row.get(nome_col, "")).strip()
            if cognome_col:
                cognome = str(row.get(cognome_col, "")).strip()
                full_name = f"{nome} {cognome}".strip()
            else:
                full_name = nome
            if full_name and full_name not in people:
                people[full_name] = PersonInfo(nome=nome or full_name, cognome=cognome if cognome_col else "", sesso="", nascita=None)

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
                dt=dt,
                familiare=ev.get("Familiare", ""),
                is_dependent=bool(ev.get("Acarico", False)),
            ))
    events_sorted = sorted(events, key=lambda e: e.dt)
    return events_sorted, people
