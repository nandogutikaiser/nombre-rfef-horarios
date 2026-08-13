#!/usr/bin/env python3
"""Actualiza fechas, horarios y TV desde BeSoccer con cobertura completa."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from besoccer_source import scrape_group

DATA_FILE = Path(__file__).resolve().parent.parent / "docs" / "data" / "horarios.json"


def load_data():
    if not DATA_FILE.exists():
        print("No existe docs/data/horarios.json — ejecuta antes build_calendar.py", file=sys.stderr)
        sys.exit(1)
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_data(data):
    data["last_checked"] = datetime.now(timezone.utc).isoformat()
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    data = load_data()
    nuevas = []
    warnings = []
    coverage = {}

    try:
        for grupo in (1, 2):
            jornadas, avisos, cov = scrape_group(data, grupo, mode="horarios")
            warnings.extend(avisos)
            coverage[str(grupo)] = {str(j): v for j, v in cov.items() if v["detectados"] or v["con_hora"]}
            for j in jornadas:
                nuevas.append({"grupo": grupo, "jornadas": [j]})
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    data["fuente_horarios"] = "BeSoccer"
    save_data(data)

    for aviso in warnings:
        print(f"[aviso] {aviso}", file=sys.stderr)

    print(json.dumps({"new_entries": nuevas, "coverage": coverage}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
