import re
from datetime import datetime
from typing import List, Optional, Dict

# Righe stile:
# Titolo: Nascita Luca, Categoria: famiglia, Data: 12/12/2002
# Titolo: Acquisto auto, Categoria: acquisti, Data: 08-14-2005
EVENTI_REGEX = re.compile(
    r"Titolo:\s*([^,\n]+?),\s*Categoria:\s*([^,\n]+?),\s*Data:\s*([0-9]{1,4}[\/-][0-9]{1,2}[\/-][0-9]{2,4})",
    re.IGNORECASE
)

def parse_eventi_field(txt: str) -> List[Dict[str, str]]:
    """
    Estrae [{Titolo, Categoria, DataEvento}, ...] dal campo testuale 'Eventi'.
    Supporta più righe nella stessa cella.
    """
    out: List[Dict[str, str]] = []
    if not txt:
        return out
    for m in EVENTI_REGEX.finditer(str(txt)):
        out.append({
            "Titolo": m.group(1).strip(),
            "Categoria": m.group(2).strip(),
            "DataEvento": m.group(3).strip()
        })
    return out

def parse_date(date_str: str) -> Optional[datetime]:
    """
    Formati:
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
