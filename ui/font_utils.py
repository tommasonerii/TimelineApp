# ui/font_utils.py
from __future__ import annotations
import sys
from pathlib import Path
from typing import Tuple, Set
from PyQt6.QtGui import QFontDatabase

def load_lato_family(fallback_family: str = "Arial") -> Tuple[str, Set[str]]:
    """
    Carica Lato (Light/Regular/Bold/Black) cercando in più cartelle con PERCORSI ASSOLUTI.
    Ritorna (family_name, available_weights_set).
    Non stampa warning se un file non esiste.
    """
    module_dir = Path(__file__).resolve().parent        # .../ui
    project_root = module_dir.parent                    # root progetto
    cwd = Path.cwd()

    # cartelle candidate (ordine di priorità)
    candidates = [
        module_dir / "fonts",
        project_root / "ui" / "fonts",
        project_root / "assets" / "fonts",
        module_dir,
        cwd / "ui" / "fonts",
        cwd,
    ]
    # supporto PyInstaller
    if hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        candidates += [meipass / "ui" / "fonts", meipass / "assets" / "fonts", meipass]

    files = [
        ("Light",  "Lato-Light.ttf"),
        ("Normal", "Lato-Regular.ttf"),
        ("Bold",   "Lato-Bold.ttf"),
        ("Black",  "Lato-Black.ttf"),
    ]

    loaded_families = []
    available = set()

    for weight, filename in files:
        found: Path | None = None
        for d in candidates:
            p = d / filename
            if p.exists():
                found = p
                break
        if not found:
            continue  # non esiste: non chiamiamo addApplicationFont -> niente warning

        font_id = QFontDatabase.addApplicationFont(str(found))
        if font_id != -1:
            fams = QFontDatabase.applicationFontFamilies(font_id)
            if fams:
                loaded_families.extend(fams)
                available.add(weight)

    family = loaded_families[0] if loaded_families else fallback_family
    if not available:
        available = {"Normal"}
    return family, available
