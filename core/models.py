from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class Event:
    nome: str               # Capofamiglia (Nome Cognome)
    titolo: str
    categoria: str
    data_str: str           # come nel CSV
    dt: datetime            # parsed
    familiare: str          # "" per capofamiglia, altrimenti nome familiare a carico
    is_dependent: bool      # True se l'evento è di un familiare a carico


@dataclass(frozen=True)
class PersonInfo:
    nome: str
    cognome: str
    sesso: str  # normalizzato: "uomo" | "donna" | "altro" | ""
    nascita: Optional[datetime]
