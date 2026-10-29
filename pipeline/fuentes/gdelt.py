"""GDELT: intensidad de cobertura de noticias sobre un tema (API DOC 2.0)."""
from __future__ import annotations

import datetime as dt
import statistics
import time

from .comun import FuenteError, resumen

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_ULTIMA_LLAMADA = [0.0]


def leer(s, regla: dict, hoy: dt.date) -> dict:
    espera = 6 - (time.time() - _ULTIMA_LLAMADA[0])  # GDELT pide una consulta cada 5 segundos
    if espera > 0:
        time.sleep(espera)
    _ULTIMA_LLAMADA[0] = time.time()
    r = s.get(URL, params={"query": regla["consulta"], "mode": "timelinevol",
                           "format": "json", "timespan": "12w"}, timeout=60)
    r.raise_for_status()
    try:
        puntos = r.json()["timeline"][0]["data"]
    except (ValueError, KeyError, IndexError) as e:
        raise FuenteError(f"Respuesta de GDELT sin serie temporal: {e}") from e
    diarios = []
    for p in puntos:
        try:
            diarios.append((dt.datetime.strptime(p["date"][:8], "%Y%m%d").date(), float(p["value"])))
        except (KeyError, ValueError):
            continue
    if len(diarios) < 60:
        raise FuenteError(f"GDELT devolvió solo {len(diarios)} días.")
    diarios.sort()
    ultimo = diarios[-1][0]
    semanas = []
    for k in range(12):
        fin = ultimo - dt.timedelta(days=7 * k)
        vals = [v for d, v in diarios if fin - dt.timedelta(days=7) < d <= fin]
        if vals:
            semanas.append(statistics.fmean(vals))
    if len(semanas) < 10:
        raise FuenteError("Semanas insuficientes en la ventana de GDELT.")
    actual = statistics.fmean(semanas[:4])
    media, desv = resumen(semanas[4:])
    return {
        "lectura": actual,
        "media": media,
        "desviacion": desv,
        "fecha_dato": ultimo.isoformat(),
        "detalle": f"Intensidad {actual:.3f} en las últimas 4 semanas; {media:.3f} en las 8 anteriores",
    }
