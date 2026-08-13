#!/usr/bin/env python3
"""
notify.py — Envía una notificación push normal (vía OneSignal) cuando el
scraper detecta jornadas nuevas.

Uso:
    python notify.py '{"new_entries": [...]}'

Variables de entorno requeridas (se configuran como Secrets en GitHub Actions):
    ONESIGNAL_APP_ID
    ONESIGNAL_API_KEY
"""

import json
import os
import sys

import requests

ONESIGNAL_URL = "https://onesignal.com/api/v1/notifications"


def build_message(new_entries):
    jornadas = sorted({j for e in new_entries for j in e["jornadas"]})
    grupos = sorted({e["grupo"] for e in new_entries})
    grupo_txt = f" (Grupo {', '.join(str(g) for g in grupos)})" if len(grupos) == 1 else ""

    if len(jornadas) == 1:
        titulo = f"Horarios de la jornada {jornadas[0]} actualizados{grupo_txt}"
    else:
        lista = ", ".join(str(j) for j in jornadas)
        titulo = f"Horarios de las jornadas {lista} actualizados{grupo_txt}"
    return titulo


def send_notification(titulo, url=None):
    app_id = os.environ["ONESIGNAL_APP_ID"]
    api_key = os.environ["ONESIGNAL_API_KEY"]

    payload = {
        "app_id": app_id,
        "included_segments": ["Subscribed Users"],
        "headings": {"es": "Primera RFEF"},
        "contents": {"es": titulo},
    }
    if url:
        payload["url"] = url

    resp = requests.post(
        ONESIGNAL_URL,
        headers={
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    if len(sys.argv) < 2:
        print("Sin datos de entrada, nada que notificar.")
        return 0

    payload = json.loads(sys.argv[1])
    new_entries = payload.get("new_entries", [])
    if not new_entries:
        print("No hay jornadas nuevas, no se envía notificación.")
        return 0

    if not os.environ.get("ONESIGNAL_APP_ID") or not os.environ.get("ONESIGNAL_API_KEY"):
        print("OneSignal no está configurado; se omite la notificación sin bloquear la actualización.")
        return 0

    titulo = build_message(new_entries)
    result = send_notification(titulo)
    print(f"Notificación enviada: {titulo}")
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
