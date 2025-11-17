from core.mortality_tables import MortalityTableLoader


def test_load_table_handles_bom_header_and_commas(tmp_path):
    content = """\ufeffEtà;Anni residui\n65;20\n70;15,5\ninvalid;row\n"""
    path = tmp_path / "mortality.csv"
    path.write_text(content, encoding="utf-8")

    loader = MortalityTableLoader()
    table = loader.load_table(str(path))

    assert table[65] == 20
    assert table[70] == 15
    assert 0 not in table  # la riga testuale viene ignorata


def test_load_table_returns_empty_dict_for_missing_file(tmp_path):
    path = tmp_path / "missing.csv"
    loader = MortalityTableLoader()
    assert loader.load_table(str(path)) == {}
