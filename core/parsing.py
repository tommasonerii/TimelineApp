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
    Estrae una lista di dict {Titolo, Categoria, DataEvento} dal campo testuale 'Eventi'.
    Supporta sia il formato legacy (Titolo/Categoria/Data) sia il nuovo
    (Titolo Evento/Categoria/Data Evento[, Nome del Familiare]).
    """
    out: List[Dict[str, str]] = []
    if not txt:
        return out

    s = str(txt)
    matches_v2 = list(EVENTI_REGEX_V2.finditer(s))
    matches_v1 = [] if matches_v2 else list(EVENTI_REGEX_V1.finditer(s))
    matches = matches_v2 or matches_v1

    for m in matches:
        titolo = (m.group(1) or "").strip()
        categoria = _norm_cat(m.group(2) or "")
        data_ev = (m.group(3) or "").strip()
        out.append({
            "Titolo": titolo,
            "Categoria": categoria,
            "DataEvento": data_ev,
        })
    return out


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
        if a > 999:          # YYYY-M-D
            y, m, d = a, b, c
        elif c > 999:        # D/M/YYYY oppure M/D/YYYY
            if a > 12:       # D/M/YYYY
                d, m, y = a, b, c
            else:            # M/D/YYYY
                m, d, y = a, b, c
        else:
            return None
        return datetime(y, m, d)
    except Exception:
        return None

