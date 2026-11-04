"""ACNUR (UNHCR): personas desplazadas por la fuerza en el mundo, al cierre de cada año."""
from __future__ import annotations

import datetime as dt

from .comun import FuenteError, es, resumen

URL = "https://api.unhcr.org/population/v1/population/"
CAMPOS = ("refugees", "asylum_seekers", "idps", "oip")  # refugiados, solicitantes de asilo, desplazados internos y otras personas que necesitan protección


def _numero(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip()))
    except ValueError:
        return 0


def leer(s, regla: dict, hoy: dt.date) -> dict:
    r = s.get(URL, params={"limit": 100, "yearFrom": 2000, "yearTo": hoy.year}, timeout=60,
              headers={"Accept": "application/json"})
    r.raise_for_status()
    items = r.json().get("items", [])
    totales: dict[int, float] = {}
    for it in items:
        try:
            anio = int(it.get("year"))
        except (TypeError, ValueError):
            continue
        total = sum(_numero(it.get(c, 0)) for c in CAMPOS)
        if total > 0:
            totales[anio] = totales.get(anio, 0) + total / 1e6
    if len(totales) < 6:
        raise FuenteError("La API de ACNUR no devolvió la serie anual esperada.")
    anios = sorted(totales)
    ultimo = anios[-1]
    media, desv = resumen([totales[a] for a in anios[-6:-1]])
    return {
        "lectura": totales[ultimo], "media": media, "desviacion": desv, "fecha_dato": f"{ultimo}-12-31",
        "detalle": f"{es(totales[ultimo])} millones de personas desplazadas por la fuerza al cierre de {ultimo}; "
                   f"media de los 5 años anteriores {es(media)} millones",
        "extra": {"anuales": {str(a): round(totales[a], 2) for a in anios}},
    }
