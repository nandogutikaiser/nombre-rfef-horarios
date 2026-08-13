#!/usr/bin/env python3
"""
scraper.py — Revisa las noticias de horarios de Primera Federación en
rfef.es y, cuando encuentra una jornada (o un lote de jornadas) con
horarios ya confirmados, rellena la hora y la TV de cada partido sobre
el calendario base (generado antes con build_calendar.py) en
docs/data/horarios.json.

Dispara una notificación (a través de notify.py, desde el workflow de
GitHub Actions) cada vez que detecta jornadas nuevas con horarios.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

LISTADO_URL = "https://rfef.es/es/noticias/competiciones-masculinas/primera-federacion"
BASE_URL = "https://rfef.es"
DATA_FILE = Path(__file__).resolve().parent.parent / "docs" / "data" / "horarios.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; horarios-primerarfef-bot/1.0; "
                  "+https://github.com/) — uso personal, no comercial"
}

TITLE_RE = re.compile(r"horarios?", re.IGNORECASE)

# Cubre "3ª jornada", "de la 5ª a la 19ª jornada", "hasta la 36ª jornada"
JORNADA_UNICA_RE = re.compile(r"(\d+)\s*[ªa]?\s*jornada", re.IGNORECASE)
JORNADA_RANGO_RE = re.compile(
    r"(?:de\s+la\s+)?(\d+)\s*[ªa]?\s*(?:a|hasta)\s+la\s+(\d+)\s*[ªa]?\s*jornada",
    re.IGNORECASE,
)
GRUPO_RE = re.compile(r"grupo\s*([12])", re.IGNORECASE)
HORA_RE = re.compile(r"\b(\d{1,2})[:hH](\d{2})\b")
# Cabeceras de fecha del tipo "Viernes 28.08.2026" o "28/08/2026"
FECHA_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")


def load_data():
    if not DATA_FILE.exists():
        print("No existe docs/data/horarios.json — ejecuta antes build_calendar.py", file=sys.stderr)
        sys.exit(1)
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_data(data):
    data["last_checked"] = datetime.now(timezone.utc).isoformat()
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def find_horario_news():
    soup = fetch(LISTADO_URL)
    found, seen = [], set()
    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if not title or not TITLE_RE.search(title):
            continue
        href = a["href"]
        if href.startswith("/"):
            href = BASE_URL + href
        if href not in seen:
            seen.add(href)
            found.append((title, href))
    return found


def jornadas_mencionadas(title):
    rango = JORNADA_RANGO_RE.search(title)
    if rango:
        a, b = int(rango.group(1)), int(rango.group(2))
        return list(range(min(a, b), max(a, b) + 1))
    return sorted(set(int(n) for n in JORNADA_UNICA_RE.findall(title)))


def normaliza(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def procesa_articulo(url, jornadas, grupos, data):
    """Intenta extraer hora/fecha/TV por partido y rellenarlo sobre el
    calendario base. La RFEF suele listar los partidos bajo cabeceras de
    fecha ("Viernes 28.08.2026", ...), así que se recorre el texto en
    orden y se recuerda la última fecha vista para asignarla a los
    partidos que aparecen debajo. Devuelve la lista de (grupo, jornada)
    para los que se ha podido confirmar al menos un horario."""
    soup = fetch(url)
    texto = soup.get_text("\n", strip=True)

    # (fecha_iso_o_None, linea) en el orden en que aparecen en el artículo
    lineas_con_fecha = []
    fecha_actual = None
    for linea in texto.split("\n"):
        fm = FECHA_RE.search(linea)
        if fm:
            d, mth, y = fm.groups()
            fecha_actual = f"{y}-{mth.zfill(2)}-{d.zfill(2)}"
        if HORA_RE.search(linea):
            lineas_con_fecha.append((fecha_actual, linea))

    confirmadas = []
    for grupo in grupos:
        for j in jornadas:
            jornada_data = data["grupos"].get(str(grupo), {}).get("jornadas", {}).get(str(j))
            if not jornada_data:
                continue
            alguna = False
            for partido in jornada_data["partidos"]:
                if partido["hora"]:
                    continue  # ya confirmado en una pasada anterior
                for fecha_linea, linea in lineas_con_fecha:
                    if partido["local"] in linea and partido["visitante"] in linea:
                        m = HORA_RE.search(linea)
                        if m:
                            partido["hora"] = f"{m.group(1).zfill(2)}:{m.group(2)}"
                            if fecha_linea:
                                partido["fecha"] = fecha_linea
                            partido["fuente"] = url
                            alguna = True
                        break
            if alguna:
                confirmadas.append((grupo, j))

    return confirmadas


def main():
    data = load_data()
    data.setdefault("noticias_procesadas", [])
    procesadas = set(data["noticias_procesadas"])

    news = find_horario_news()
    nuevas_confirmaciones = []

    for title, url in news:
        if url in procesadas:
            continue
        jornadas = jornadas_mencionadas(title)
        if not jornadas:
            continue
        grupos = sorted(set(int(g) for g in GRUPO_RE.findall(title))) or [1, 2]

        confirmadas = procesa_articulo(url, jornadas, grupos, data)
        procesadas.add(url)
        if confirmadas:
            nuevas_confirmaciones.extend(confirmadas)

    data["noticias_procesadas"] = sorted(procesadas)
    save_data(data)

    resultado = {
        "new_entries": [
            {"grupo": g, "jornadas": [j]} for g, j in sorted(set(nuevas_confirmaciones))
        ]
    }
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
