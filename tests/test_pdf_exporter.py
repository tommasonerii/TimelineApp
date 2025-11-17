from datetime import date

from core.pdf_exporter import default_pdf_filename


def test_default_pdf_filename_normalizes_person_name():
    today = date(2024, 9, 1)
    name = "Àlè Dé-Rossi Jr."
    assert default_pdf_filename(name, today=today) == "de_rossi_jr_ale_timeline_01-09-2024.pdf"


def test_default_pdf_filename_handles_missing_person():
    today = date(2024, 9, 1)
    assert default_pdf_filename("", today=today) == "timeline_01-09-2024.pdf"
    assert default_pdf_filename("Rossi", today=today) == "rossi_timeline_01-09-2024.pdf"
