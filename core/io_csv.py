from datetime import datetime
from typing import List, Tuple, Optional, Dict
import pandas as pd
from .models import Event, PersonInfo
from .parsing import parse_eventi_field, parse_date, parse_personal_data, parse_personal_details

# Nomi colonne attesi (case-insensitive)
EXPECTED = {
    "submission date": "Submission Date",
    "eventi": "Eventi:",
    "eventi personali": "Eventi personali:",
    "eventi familiari a carico": "Eventi familiari a carico:",
    "dati personali": "Dati Personali",
    # retrocompatibilità (se disponibili):
    "nome": "Nome",
    "cognome": "Cognome",
}

def _map_columns(df: pd.DataFrame) -> Tuple[str, List[str], List[str], Optional[str], Optional[str], Optional[str]]:
    """Ritorna le colonne (submission, eventi_personali, eventi_a_carico, nome, cognome, dati_personali). Gestisce BOM e due punti finali."""
    def normalize(col: str) -> str:
        x = (col or "").strip().lstrip("\ufeff").lower()
        x = x.replace("\xa0", " ")
        if x.endswith(":"):
            x = x[:-1]
        return x
    subm_col = None
    eventi_cols: List[str] = []
    eventi_dep_cols: List[str] = []
    nome_col: Optional[str] = None
    cognome_col: Optional[str] = None
    dati_pers_col: Optional[str] = None

    for raw_col in df.columns:
        norm = normalize(raw_col)
        if norm == "submission date":
            subm_col = raw_col
        elif norm in ("eventi", "eventi personali"):
            eventi_cols.append(raw_col)
        elif norm in ("eventi familiari a carico", "eventi familiari"):
            eventi_dep_cols.append(raw_col)
        elif norm == "nome":
            nome_col = raw_col
        elif norm == "cognome":
            cognome_col = raw_col
        elif norm == "dati personali":
            dati_pers_col = raw_col

    if not (subm_col and (eventi_cols or eventi_dep_cols) and (dati_pers_col or nome_col)):
        raise ValueError(
            "Il CSV deve contenere: 'Submission Date', almeno una colonna eventi ('Eventi:' o 'Eventi personali:') "
            "e 'Dati Personali' (oppure 'Nome'[/ 'Cognome'])."
        )
    return subm_col, eventi_cols, eventi_dep_cols, nome_col, cognome_col, dati_pers_col


def load_events_csv(path: str) -> Tuple[List[Event], dict]:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    subm_col, eventi_cols, eventi_dep_cols, nome_col, cognome_col, dati_pers_col = _map_columns(df)

    def _parse_submission(value: object) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            return datetime.min
        parsed = pd.to_datetime(raw, dayfirst=True, utc=False, errors="coerce")
        if pd.isna(parsed):
            parsed = pd.to_datetime(raw, dayfirst=False, utc=False, errors="coerce")
        if pd.isna(parsed):
            return datetime.min
        if isinstance(parsed, pd.Timestamp):
            if parsed.tzinfo is not None:
                parsed = parsed.tz_convert(None)
            return parsed.to_pydatetime()
        if isinstance(parsed, datetime):
            return parsed
        return datetime.min

    def _extract_person(row: pd.Series) -> Tuple[str, Optional[PersonInfo]]:
        full_name = ""
        info: Optional[PersonInfo] = None
        if dati_pers_col:
            details = parse_personal_details(row.get(dati_pers_col, ""))
            nome = (details.get("nome", "") or "").strip()
            cognome = (details.get("cognome", "") or "").strip()
            full_name = f"{nome} {cognome}".strip()
            sesso = (details.get("sesso", "") or "").strip()
            nascita_str = (details.get("nascita_str", "") or "").strip()
            nascita_dt = parse_date(nascita_str) if nascita_str else None
            if full_name:
                info = PersonInfo(
                    nome=nome or full_name,
                    cognome=cognome,
                    sesso=sesso,
                    nascita=nascita_dt,
                )
        if not full_name and nome_col:
            nome = (str(row.get(nome_col, "")) or "").strip()
            cognome = (str(row.get(cognome_col, "")) or "").strip() if cognome_col else ""
            full_name = f"{nome} {cognome}".strip() if cognome_col else nome
            if full_name:
                info = PersonInfo(
                    nome=nome or full_name,
                    cognome=cognome if cognome_col else "",
                    sesso="",
                    nascita=None,
                )
        return full_name, info

    selected_forms: Dict[str, Dict[str, object]] = {}
    for _, row in df.iterrows():
        full_name, info = _extract_person(row)
        if not full_name:
            continue
        submission_dt = _parse_submission(row.get(subm_col))
        existing = selected_forms.get(full_name)
        if existing is None or submission_dt >= existing["submission"]:
            selected_forms[full_name] = {
                "row": row.copy(),
                "submission": submission_dt,
                "info": info,
            }

    events: List[Event] = []
    people: Dict[str, PersonInfo] = {}
    for full_name, payload in selected_forms.items():
        row = payload["row"]
        info = payload.get("info") or PersonInfo(nome=full_name, cognome="", sesso="", nascita=None)
        people[full_name] = info

        event_columns: List[Tuple[bool, str]] = []
        for col in eventi_cols:
            event_columns.append((False, col))
        for col in eventi_dep_cols:
            event_columns.append((True, col))

        for default_dep, col in event_columns:
            text = str(row.get(col, "")).strip()
            if not text:
                continue
            extracted = parse_eventi_field(text, default_is_dependent=default_dep)
            for ev in extracted:
                dt = parse_date(ev["DataEvento"])
                if dt is None:
                    # scarta eventi con data non valida
                    continue
                familiare = ev.get("Familiare", "") or ""
                is_dep = bool(ev.get("Acarico", False)) or default_dep
                events.append(Event(
                    nome=full_name,
                    titolo=ev["Titolo"],
                    categoria=ev["Categoria"],
                    data_str=ev["DataEvento"],
                    dt=dt,
                    familiare=familiare if is_dep else "",
                    is_dependent=is_dep,
                    costo=ev.get("Costo"),
                ))
    events_sorted = sorted(events, key=lambda e: e.dt)
    return events_sorted, people
