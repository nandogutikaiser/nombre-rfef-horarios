#!/usr/bin/env python3
"""
resultados.py — Complementa a scraper.py: en vez de horarios, busca las
"Crónica de la jornada X" / "resumen de la jornada X" que la RFEF publica
después de cada jornada, con el marcador de cada partido en el texto
(formato "Equipo A 2-1 Equipo B"), y lo guarda en el campo "resultado"
de cada partido en docs/data/horarios.json.

Igual que scraper.py, es "best effort": depende de que la RFEF siga
escribiendo el marcador en ese formato dentro del cuerpo del artículo.
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

CRONICA_TITLE_RE = re.compile(r"cr[oó]nica|resumen", re.IGNORECASE)
JORNADA_RE = re.compile(r"(\d+)\s*[ªa]?\s*jornada", re.IGNORECASE)
# "Equipo A 2-1 Equipo B" (con o sin espacios alrededor del guion)
MARCADOR_RE = re.compile(r"^(.*?)\s+(\d{1,2})\s*-\s*(\d{1,2})\s+(.*)$")


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


def find_cronica_news():
    soup = fetch(LISTADO_URL)
    found, seen = [], set()
    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if not title or not CRONICA_TITLE_RE.search(title):
            continue
        href = a["href"]
        if href.startswith("/"):
            href = BASE_URL + href
        if href not in seen:
            seen.add(href)
            found.append((title, href))
    return found


def equipos_de(data, grupo):
    equipos = set()
    for jornada in data["grupos"].get(str(grupo), {}).get("jornadas", {}).values():
        for p in jornada["partidos"]:
            equipos.add(p["local"])
            equipos.add(p["visitante"])
    return equipos


def procesa_articulo(url, jornada_num, data):
    soup = fetch(url)
    lineas = [l.strip() for l in soup.get_text("\n", strip=True).split("\n")]

    confirmados = []
    for grupo in ("1", "2"):
        equipos = equipos_de(data, grupo)
        jornada_data = data["grupos"].get(grupo, {}).get("jornadas", {}).get(str(jornada_num))
        if not jornada_data:
            continue

        for linea in lineas:
            m = MARCADOR_RE.match(linea)
            if not m:
                continue
            local_txt, gl, gv, visit_txt = m.groups()
            local = next((e for e in equipos if e in local_txt or local_txt.endswith(e)), None)
            visitante = next((e for e in equipos if e in visit_txt or visit_txt.startswith(e)), None)
            if not local or not visitante:
                continue
            for partido in jornada_data["partidos"]:
                if partido["local"] == local and partido["visitante"] == visitante and not partido.get("resultado"):
                    partido["resultado"] = f"{gl}-{gv}"
                    confirmados.append((int(grupo), jornada_num))

    return confirmados


def main():
    data = load_data()
    data.setdefault("cronicas_procesadas", [])
    procesadas = set(data["cronicas_procesadas"])

    news = find_cronica_news()
    nuevos = []

    for title, url in news:
        if url in procesadas:
            continue
        jm = JORNADA_RE.search(title)
        if not jm:
            continue
        jornada_num = int(jm.group(1))

        confirmados = procesa_articulo(url, jornada_num, data)
        procesadas.add(url)
        if confirmados:
            nuevos.extend(confirmados)

    data["cronicas_procesadas"] = sorted(procesadas)
    save_data(data)

    print(json.dumps({"resultados_nuevos": sorted(set(nuevos))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
