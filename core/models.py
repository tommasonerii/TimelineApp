from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Event:
    nome: str
    titolo: str
    categoria: str
    data_str: str   # come nel CSV
    dt: datetime    # parsed
