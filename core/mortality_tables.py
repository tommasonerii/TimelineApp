from __future__ import annotations
from typing import Dict, Tuple
import os


class MortalityTableLoader:
    """
    Carica tabelle di mortalità dal file CSV con separatore ';'.
    Ogni riga (dopo l'header) deve contenere: "eta;anni_rimanenti".
    Restituisce una mappa: {eta(int): anni_rimanenti(int)}.
    """

    def __init__(self, sep: str = ";") -> None:
        self.sep = sep

    def load_table(self, path: str) -> Dict[int, int]:
        table: Dict[int, int] = {}
        if not path or not os.path.exists(path):
            return table

        # Tollerante all'header ed a encoding con BOM
        encodings = ("utf-8-sig", "utf-8", "latin-1")
        last_err: Exception | None = None
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc, errors="strict") as f:
                    lines = f.read().splitlines()
                break
            except Exception as e:
                last_err = e
                lines = None  # type: ignore
        if lines is None:  # type: ignore
            # Nessun encoding è andato a buon fine
            raise last_err if last_err else RuntimeError(f"Impossibile leggere il file: {path}")

        # Salta header, poi parse semplice delle due colonne separate da ';'
        for i, raw in enumerate(lines):
            line = (raw or "").strip()
            if not line:
                continue
            # Salta riga header (prima riga o righe con testo non numerico in prima colonna)
            parts = [p.strip() for p in line.split(self.sep)]
            if len(parts) < 2:
                continue
            if i == 0 and not parts[0].isdigit():
                continue
            # In caso di header con testo anche oltre la prima riga, filtra righe non numeriche
            if not parts[0].replace(" ", "").isdigit():
                continue
            try:
                age = int(parts[0].split()[0])  # "Età x" -> 0
                years_left = int(float(parts[1].replace(",", ".")))
            except Exception:
                continue
            if age >= 0 and years_left >= 0:
                table[age] = years_left
        return table

    def load_both(self, male_path: str, female_path: str) -> Tuple[Dict[int, int], Dict[int, int]]:
        return self.load_table(male_path), self.load_table(female_path)

