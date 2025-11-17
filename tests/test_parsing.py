from datetime import datetime

from core.parsing import (
    parse_date,
    parse_eventi_field,
    parse_personal_details,
)


def test_parse_eventi_field_handles_multiple_formats():
    text = """
    Titolo Evento: Laurea Classica, Categoria: Progetto, Data Evento: 11-09-1999, Costo: 1500 €, A Carico?: Si, Nome del Familiare A Carico: Carlo
    Titolo Evento: Matrimonio, Categoria: famiglia, Data Evento: 12/03/2001, Nome del Familiare:  , Costo:
    Titolo: Casa nuova, Categoria: desiderio, Data: 05/07/2005
    """
    events = parse_eventi_field(text)
    assert len(events) == 3

    first, second, third = events

    assert first["Titolo"] == "Laurea Classica"
    assert first["Categoria"] == "progetto"
    assert first["Acarico"] is True
    assert first["Familiare"] == "Carlo"
    assert first["Costo"] == "1500 €"  # costo preservato e ripulito

    assert second["Titolo"] == "Matrimonio"
    assert second["Categoria"] == "progetto"  # legacy 'famiglia' → 'progetto'
    assert second["Acarico"] is False
    assert second["Familiare"] == ""

    assert third["Titolo"] == "Casa nuova"
    assert third["Categoria"] == "desiderio"
    assert third["Acarico"] is False


def test_parse_eventi_field_forces_default_dependent_flag():
    text = "Titolo Evento: Viaggio, Categoria: sogni, Data Evento: 01-01-2020"
    events = parse_eventi_field(text, default_is_dependent=True)
    assert len(events) == 1
    ev = events[0]
    assert ev["Acarico"] is True
    # Se non è indicato nessun familiare l'informazione rimane vuota ma il flag è True
    assert ev["Familiare"] == ""


def test_parse_date_supports_multiple_unambiguous_formats():
    assert parse_date("2024-01-05") == datetime(2024, 1, 5)
    assert parse_date("05/06/2024") == datetime(2024, 6, 5)
    assert parse_date("06-20-2028") == datetime(2028, 6, 20)
    assert parse_date("2001/7/03") == datetime(2001, 7, 3)
    assert parse_date("32/13/2020") is None  # giorno/mese non validi


def test_parse_personal_details_extracts_full_payload():
    txt = "Nome: Mario, Cognome: Rossi, Sesso: Maschio, Data Di Nascita: 18-11-1970"
    result = parse_personal_details(txt)
    assert result["nome"] == "Mario"
    assert result["cognome"] == "Rossi"
    assert result["sesso"] == "Maschio"
    assert result["nascita_str"] == "18-11-1970"
