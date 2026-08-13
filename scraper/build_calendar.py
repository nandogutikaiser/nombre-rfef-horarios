#!/usr/bin/env python3
"""
build_calendar.py — Parsea el calendario oficial completo de la temporada
(el PDF "Calendario" que la RFEF publica en junio, con las 38 jornadas y
los emparejamientos de cada grupo, SIN hora) y construye la base de
docs/data/horarios.json.

Se ejecuta UNA VEZ por temporada (cuando la RFEF publica el calendario
nuevo, normalmente a finales de junio). El día a día de "hora + TV" lo
rellena scraper.py sobre esta base.

Uso:
    python scraper/build_calendar.py <grupo1.txt> <grupo2.txt>

Cada .txt es el texto plano del PDF oficial de cada grupo
(rfef.es/sites/default/files/AAAA-MM/Primera_Federacion_Grupo_I.pdf
 y ..._Grupo_II.pdf), tal cual lo extrae cualquier lector de PDF.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "docs" / "data" / "horarios.json"

JORNADA_HEAD_RE = re.compile(r"^Jornada\s+(\d+)\s+\((\d{2}/\d{2}/\d{4})\)$")
SKIP_LINES = {"Primera Federación", "Calendario", "GRUPO 1", "GRUPO 2"}

# El PDF oficial pega "Local Visitante" en una sola línea sin separador,
# así que hace falta la lista cerrada de equipos de cada grupo para poder
# partir cada línea en el punto correcto. Se actualiza una vez por
# temporada (cuando cambian los grupos).
EQUIPOS_GRUPO_1 = [
    "Arenas Club", "Racing Club Ferrol", "Barakaldo CF", "CyD Leonesa",
    "CP Cacereño", "CD Mirandés", "AD Mérida", "RC Deportivo Fabril",
    "UD Ourense", "SD Ponferradina", "Real Avilés Industrial", "Pontevedra CF",
    "Real Unión Club", "CD Coria", "UD Logroñés", "CD Extremadura",
    "Unionistas de Salamanca CF", "CD Lugo", "Zamora CF", 'Athletic Club "B"',
]

EQUIPOS_GRUPO_2 = [
    "Águilas FC", "AD Alcorcón", "Algeciras CF", "FC Cartagena",
    "Atlético Madrileño", "Juventud de Torremolinos CF", "Antequera CF",
    "UD Ibiza", "CE Europa", "Real Jaén CF", "Hércules de Alicante CF",
    "Real Murcia CF", "SD Huesca", "UE Sant Andreu", "CF Rayo Majadahonda",
    'Villarreal CF "B"', "Gimnàstic de Tarragona", "Real Zaragoza",
    "CD Teruel", "Real Madrid Castilla",
]


def split_match_line(line, equipos):
    """'Local Visitante' pegados sin separador -> (local, visitante).
    Prueba cada equipo conocido como posible prefijo (los más largos
    primero) y comprueba que lo que sobra es también un equipo conocido."""
    candidatos = sorted(equipos, key=len, reverse=True)
    for equipo in candidatos:
        if line == equipo:
            continue
        if line.startswith(equipo + " "):
            resto = line[len(equipo):].strip()
            if resto in equipos:
                return equipo, resto
    return None


def is_noise(line):
    if not line.strip():
        return True
    if line.strip() in SKIP_LINES:
        return True
    if re.match(r"^\d{2}/\d{2}/\d{4}$", line.strip()):
        return True
    if re.match(r"^\d{4}/\d{4}$", line.strip()):
        return True
    if line.strip().startswith("Real Federación Española de Fútbol"):
        return True
    return False


def parse_group(text, equipos):
    """Devuelve {jornada_num: {"fecha": iso, "partidos": [...]}}"""
    lines = [l.rstrip() for l in text.splitlines()]
    jornadas = {}
    current_jornada = None

    for raw in lines:
        line = raw.strip()
        if is_noise(line):
            continue

        m = JORNADA_HEAD_RE.match(line)
        if m:
            current_jornada = int(m.group(1))
            d, mth, y = m.group(2).split("/")
            fecha = f"{y}-{mth}-{d}"
            jornadas[current_jornada] = {"fecha": fecha, "partidos": []}
            continue

        if current_jornada is None:
            continue

        split = split_match_line(line, equipos)
        if split is None:
            print(f"  [aviso] no se pudo partir la línea: {line!r}", file=sys.stderr)
            continue
        local, visitante = split
        jornadas[current_jornada]["partidos"].append({
            "local": local,
            "visitante": visitante,
            "hora": None,
            "tv": None,
        })

    return jornadas


def main():
    if len(sys.argv) != 3:
        print("Uso: build_calendar.py <grupo1.txt> <grupo2.txt>")
        return 1

    g1_text = Path(sys.argv[1]).read_text(encoding="utf-8")
    g2_text = Path(sys.argv[2]).read_text(encoding="utf-8")

    g1 = parse_group(g1_text, EQUIPOS_GRUPO_1)
    g2 = parse_group(g2_text, EQUIPOS_GRUPO_2)

    data = {
        "temporada": "2026/27",
        "last_checked": datetime.utcnow().isoformat() + "Z",
        "grupos": {
            "1": {"jornadas": {str(k): v for k, v in sorted(g1.items())}},
            "2": {"jornadas": {str(k): v for k, v in sorted(g2.items())}},
        },
    }

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    total1 = sum(len(v["partidos"]) for v in g1.values())
    total2 = sum(len(v["partidos"]) for v in g2.values())
    print(f"Grupo 1: {len(g1)} jornadas, {total1} partidos")
    print(f"Grupo 2: {len(g2)} jornadas, {total2} partidos")
    print(f"Guardado en {DATA_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
