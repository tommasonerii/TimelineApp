from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class Event:
    nome: str
    titolo: str
    categoria: str
    data_str: str   # come nel CSV
    dt: datetime    # parsed


@dataclass(frozen=True)
class PersonInfo:
    nome: str
    cognome: str
    sesso: str  # normalizzato: "uomo" | "donna" | "altro" | ""
    nascita: Optional[datetime]
