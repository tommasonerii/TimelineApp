import re
from datetime import datetime
from typing import List, Optional, Dict, Tuple

# ======================
# Parsing campo "Eventi"
# ======================

# v1 (legacy):
#   Titolo: Nascita Luca, Categoria: famiglia, Data: 12/12/2002
EVENTI_REGEX_V1 = re.compile(
    r"Titolo:\s*([^,\n]+?),\s*Categoria:\s*([^,\n]+?),\s*Data:\s*([0-9]{1,4}[\/-][0-9]{1,2}[\/-][0-9]{2,4})",
    re.IGNORECASE,
)

# v2 (nuovo):
#   Titolo Evento: Matrimonio, Categoria: Progetto, Data Evento: 11-09-1999, Nome del Familiare: Carlo
EVENTI_REGEX_V2 = re.compile(
    r"Titolo\s*Evento:\s*([^,\n]+?),\s*Categoria:\s*([^,\n]+?),\s*Data\s*Evento:\s*([0-9]{1,4}[\/-][0-9]{1,2}[\/-][0-9]{2,4})(?:,\s*Nome\s+del\s+Familiare:\s*([^\n,]*))?",
    re.IGNORECASE,
)

# v3 (nuovo con campo A Carico? e Nome del Familiare A Carico):
#   Titolo Evento: ..., Categoria: ..., Data Evento: ..., A Carico?: Si/No, Nome del Familiare A Carico: <nome|vuoto>
EVENTI_REGEX_V3 = re.compile(
    r"Titolo\s*Evento:\s*([^,\n]+?),\s*Categoria:\s*([^,\n]+?),\s*Data\s*Evento:\s*([0-9]{1,4}[\/-][0-9]{1,2}[\/-][0-9]{2,4}),\s*A\s*Carico\?:\s*([^,\n]+?),\s*Nome\s+del\s+Familiare\s+A\s+Carico:\s*([^\n,]*)",
    re.IGNORECASE,
)


def _norm_cat(cat: str) -> str:
    """Normalizza categorie su {bisogno, progetto, desiderio} (fallback: originale)."""
    c = (cat or "").strip().lower()
    mapping = {
        "progetto": "progetto",
        "desiderio": "desiderio",
        "bisogno": "bisogno",
    }
    legacy = {
        # categorie legacy ricondotte a quelle nuove
        "famiglia": "progetto",
        "acquisti": "bisogno",
        "obiettivi": "progetto",
        "lavoro": "progetto",
        "studio": "progetto",
        "salute": "bisogno",
        "finanze": "bisogno",
        "sogni": "desiderio",
        "carriera": "progetto",
        "istruzione": "progetto",
    }
    return mapping.get(c) or legacy.get(c) or c


def parse_eventi_field(txt: str) -> List[Dict[str, str]]:
    """
    Estrae una lista di dict {Titolo, Categoria, DataEvento, Familiare, Acarico} dal
    campo testuale 'Eventi', trattando ogni riga interna come un evento.
    Ordine e spaziatura dei campi sono tolleranti.
    """
    out: List[Dict[str, str]] = []
    if not txt:
        return out

    for raw_line in str(txt).splitlines():
        line = raw_line.strip().strip(',')
        if not line:
            continue

        parsed = _parse_event_line_strict(line)
        if not parsed:
            parsed = _parse_event_line_flexible(line)
        if parsed:
            out.append(parsed)
    return out


def _parse_event_line_strict(line: str) -> Optional[Dict[str, object]]:
    # prova v3
    m = EVENTI_REGEX_V3.search(line)
    if m:
        titolo = (m.group(1) or "").strip()
        categoria = _norm_cat(m.group(2) or "")
        data_ev = (m.group(3) or "").strip()
        acarico_raw = (m.group(4) or "").strip().lower()
        fam = (m.group(5) or "").strip()
        yes_vals = {"si", "sì", "yes", "y", "true", "1"}
        is_dep = acarico_raw in yes_vals
        return {"Titolo": titolo, "Categoria": categoria, "DataEvento": data_ev, "Familiare": fam if is_dep else "", "Acarico": is_dep}
    # prova v2
    m = EVENTI_REGEX_V2.search(line)
    if m:
        titolo = (m.group(1) or "").strip()
        categoria = _norm_cat(m.group(2) or "")
        data_ev = (m.group(3) or "").strip()
        fam = (m.group(4) or "").strip() if getattr(m.re, 'groups', 0) >= 4 else ""
        return {"Titolo": titolo, "Categoria": categoria, "DataEvento": data_ev, "Familiare": fam, "Acarico": bool(fam)}
    # prova v1
    m = EVENTI_REGEX_V1.search(line)
    if m:
        titolo = (m.group(1) or "").strip()
        categoria = _norm_cat(m.group(2) or "")
        data_ev = (m.group(3) or "").strip()
        return {"Titolo": titolo, "Categoria": categoria, "DataEvento": data_ev, "Familiare": "", "Acarico": False}
    return None


def _parse_event_line_flexible(line: str) -> Optional[Dict[str, object]]:
    def norm_key(k: str) -> str:
        return (k or '').strip().lower().replace('  ', ' ')

    yes_vals = {"si", "sì", "yes", "y", "true", "1"}
    # estrae key:value separati da virgola nella stessa riga
    pairs = re.findall(r"([^:]+):\s*([^,]*)", line)
    if not pairs:
        return None
    d: Dict[str, str] = {}
    for k, v in pairs:
        d[norm_key(k)] = v.strip()

    titolo = d.get("titolo evento") or d.get("titolo") or ""
    cat = d.get("categoria") or ""
    data_ev = d.get("data evento") or d.get("data") or ""
    acar = d.get("a carico?") or ""
    fam = d.get("nome del familiare a carico") or d.get("nome del familiare") or ""
    if not (titolo and cat and data_ev):
        return None
    return {
        "Titolo": titolo.strip(),
        "Categoria": _norm_cat(cat),
        "DataEvento": data_ev.strip(),
        "Familiare": fam.strip() if (acar or '').strip().lower() in yes_vals else "",
        "Acarico": (acar or '').strip().lower() in yes_vals,
    }


# ============================
# Parsing campo "Dati Personali"
# ============================

# Esempio:
#   "Nome: Mario, Cognome: Rossi, Sesso: Maschio, Data Di Nascita: 18-11-1970"
PERSONA_REGEX = re.compile(
    r"Nome:\s*([^,\n]+)\s*,\s*Cognome:\s*([^,\n]+)",
    re.IGNORECASE,
)


def parse_personal_data(txt: str) -> Tuple[str, str]:
    """Estrae (nome, cognome) dal campo 'Dati Personali'."""
    if not txt:
        return "", ""
    m = PERSONA_REGEX.search(str(txt))
    if not m:
        return "", ""
    nome = (m.group(1) or "").strip()
    cognome = (m.group(2) or "").strip()
    return nome, cognome


# Estrai anche Sesso e Data di Nascita
SESSO_REGEX = re.compile(r"Sesso:\s*([^,\n]+)", re.IGNORECASE)
NASCITA_REGEX = re.compile(r"Data\s+Di\s+Nascita:\s*([0-9]{1,4}[\/-][0-9]{1,2}[\/-][0-9]{2,4})", re.IGNORECASE)


def parse_personal_details(txt: str) -> Dict[str, Optional[str]]:
    """Ritorna dict: {nome, cognome, sesso, nascita_str} dal campo 'Dati Personali'."""
    s = str(txt or "")
    nome, cognome = parse_personal_data(s)
    sesso_m = SESSO_REGEX.search(s)
    nasc_m = NASCITA_REGEX.search(s)
    sesso = (sesso_m.group(1).strip() if sesso_m else "")
    nascita_str = (nasc_m.group(1).strip() if nasc_m else "")
    return {"nome": nome, "cognome": cognome, "sesso": sesso, "nascita_str": nascita_str}


# =====================
# Parsing della data
# =====================

def parse_date(date_str: str) -> Optional[datetime]:
    """
    Formati accettati:
    - YYYY-MM-DD
    - DD/MM/YYYY (se il primo numero > 12)
    - MM/DD/YYYY (se il primo numero <= 12)
    - DD-MM-YYYY
    - MM-DD-YYYY
    """
    if not date_str:
        return None
    s = str(date_str).strip()
    parts = re.split(r"[\/-]", s)
    if len(parts) != 3 or any(not p.isdigit() for p in parts):
        return None
    a, b, c = map(int, parts)
    try:
        # Preferisci D-M-Y quando l'ultimo è l'anno
        if c > 999:
            d, m, y = a, b, c
        elif a > 999:  # YYYY-M-D
            y, m, d = a, b, c
        else:
            # fallback euristico: se b è un mese valido → D/M/Y
            if 1 <= b <= 12:
                d, m, y = a, b, c
            else:
                return None
        return datetime(y, m, d)
    except Exception:
        return None
