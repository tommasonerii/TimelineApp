from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from core.io_csv import load_events_csv


COLS = [
    "Submission Date",
    "Eventi:",
    "Eventi familiari a carico:",
    "Dati Personali",
]


def _write_csv(tmp_path, rows):
    df = pd.DataFrame(rows, columns=COLS)
    path = tmp_path / "events.csv"
    df.to_csv(path, index=False)
    return path


def test_load_events_csv_keeps_latest_submission_and_dependents(tmp_path):
    mario_details = "Nome: Mario, Cognome: Rossi, Sesso: Maschio, Data Di Nascita: 18/11/1970"
    rows = [
        {
            COLS[0]: "2023-01-01",
            COLS[1]: "Titolo Evento: Laurea Classica, Categoria: Progetto, Data Evento: 11-09-1999",
            COLS[2]: "",
            COLS[3]: mario_details,
        },
        {
            COLS[0]: "2024-05-01",
            COLS[1]: "Titolo Evento: Promozione, Categoria: lavoro, Data Evento: 01/06/2024, Costo: 2000",
            COLS[2]: (
                "Titolo Evento: Operazione, Categoria: salute, Data Evento: 01-04-2010, "
                "A Carico?: Sì, Nome del Familiare A Carico: Anna"
            ),
            COLS[3]: mario_details,
        },
        {
            COLS[0]: "2022-10-10",
            COLS[1]: (
                "Titolo Evento: Casa nuova, Categoria: desiderio, Data Evento: 15-08-2025\n"
                "Titolo Evento: Errato, Categoria: progetto, Data Evento: 32-13-2024"
            ),
            COLS[2]: "",
            COLS[3]: "Nome: Lucia, Cognome: Bianchi, Sesso: Donna, Data Di Nascita: 05-07-1985",
        },
    ]
    csv_path = _write_csv(tmp_path, rows)

    events, people = load_events_csv(str(csv_path))

    assert len(events) == 3  # un evento dipendente, uno personale e uno per Lucia
    titles = {e.titolo for e in events}
    assert "Promozione" in titles
    assert "Operazione" in titles
    assert "Casa nuova" in titles
    assert "Laurea Classica" not in titles  # riga vecchia sovrascritta

    dep_event = next(e for e in events if e.titolo == "Operazione")
    assert dep_event.is_dependent is True
    assert dep_event.familiare == "Anna"

    mario = people["Mario Rossi"]
    assert mario.nome == "Mario"
    assert mario.cognome == "Rossi"
    assert mario.sesso == "Maschio"
    assert mario.nascita == datetime(1970, 11, 18)

    lucia = people["Lucia Bianchi"]
    assert lucia.nascita == datetime(1985, 7, 5)


def test_load_events_csv_requires_minimum_columns(tmp_path):
    rows = [
        {
            "Submission Date": "2024-01-01",
            "Eventi:": "Titolo Evento: Test, Categoria: progetto, Data Evento: 01-01-2024",
        }
    ]
    df = pd.DataFrame(rows)
    path = tmp_path / "missing.csv"
    df.to_csv(path, index=False)

    with pytest.raises(ValueError):
        load_events_csv(str(path))
