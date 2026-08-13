#!/usr/bin/env python3
"""
reminders.py — Cuando scraper.py confirma la hora de un partido, este
script programa (vía el `send_after` de OneSignal) un recordatorio para
la gente que:
  a) sigue a uno de los dos equipos de ese partido como favorito
     (tag `equipo_<slug>` = "1"), y
  b) tiene activada esa antelación concreta (tag `recordatorio_1h`,
     `recordatorio_2h` o `recordatorio_24h` = "1").

No hace falta cron aparte: se programa en el momento en que se conoce
la hora, y OneSignal se encarga de entregarlo cuando toca.

Uso:
    python reminders.py '{"new_entries": [...]}'   # salida de scraper.py
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

import requests

ONESIGNAL_URL = "https://onesignal.com/api/v1/notifications"
OFFSETS_HORAS = [1, 2, 24]

import pathlib
DATA_FILE = pathlib.Path(__file__).resolve().parent.parent / "docs" / "data" / "horarios.json"


def slug(equipo):
    s = equipo.lower()
    s = re.sub(r'["\']', "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def cargar_partidos_confirmados(new_entries):
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    partidos = []
    for entry in new_entries:
        grupo = str(entry["grupo"])
        for j in entry["jornadas"]:
            jornada = data["grupos"].get(grupo, {}).get("jornadas", {}).get(str(j))
            if not jornada or not jornada.get("fecha"):
                continue
            for p in jornada["partidos"]:
                if p.get("hora"):
                    partidos.append((jornada["fecha"], p))
    return partidos


def programa_recordatorio(fecha, partido, horas_antes):
    kickoff = datetime.strptime(f"{fecha} {partido['hora']}", "%Y-%m-%d %H:%M")
    send_after = kickoff - timedelta(hours=horas_antes)
    if send_after < datetime.now():
        return None  # ya no tiene sentido programarlo

    app_id = os.environ["ONESIGNAL_APP_ID"]
    api_key = os.environ["ONESIGNAL_API_KEY"]

    tag_local = f"equipo_{slug(partido['local'])}"
    tag_visitante = f"equipo_{slug(partido['visitante'])}"
    tag_recordatorio = f"recordatorio_{horas_antes}h"

    # OneSignal aplica los filtros en orden con AND por defecto; para
    # expresar "recordatorio=1 AND (local=1 OR visitante=1)" hacen falta
    # dos llamadas (una por equipo), ya que la API v1 no soporta
    # paréntesis explícitos entre condiciones OR.
    filtro_local = [
        {"field": "tag", "key": tag_recordatorio, "relation": "=", "value": "1"},
        {"field": "tag", "key": tag_local, "relation": "=", "value": "1"},
    ]
    filtro_visitante = [
        {"field": "tag", "key": tag_recordatorio, "relation": "=", "value": "1"},
        {"field": "tag", "key": tag_visitante, "relation": "=", "value": "1"},
    ]

    payload_base = {
        "app_id": app_id,
        "headings": {"es": "Primera RFEF"},
        "contents": {"es": f"En {horas_antes}h: {partido['local']} - {partido['visitante']}"},
        "send_after": send_after.strftime("%Y-%m-%d %H:%M:%S GMT+0000"),
    }

    resultados = []
    for filtro_equipo in (filtro_local, filtro_visitante):
        payload = {**payload_base, "filters": filtro_equipo}
        resp = requests.post(
            ONESIGNAL_URL,
            headers={"Authorization": f"Basic {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=20,
        )
        resultados.append((resp.status_code, resp.text))
    return resultados


def main():
    if len(sys.argv) < 2:
        print("Sin datos de entrada, nada que programar.")
        return 0

    payload = json.loads(sys.argv[1])
    new_entries = payload.get("new_entries", [])
    if not new_entries:
        return 0

    partidos = cargar_partidos_confirmados(new_entries)
    programados = 0
    for fecha, partido in partidos:
        for horas in OFFSETS_HORAS:
            res = programa_recordatorio(fecha, partido, horas)
            if res:
                programados += 1

    print(f"Recordatorios programados (intentos): {programados}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
