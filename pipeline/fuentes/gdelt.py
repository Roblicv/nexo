"""GDELT: intensidad de cobertura de noticias sobre un tema (API DOC 2.0).

GDELT limita las consultas por dirección IP, y las máquinas de GitHub comparten direcciones.
Por eso se espera 10 segundos entre consultas y, si responde 429 (demasiadas peticiones),
se reintenta con esperas cada vez más largas.
"""
from __future__ import annotations

import datetime as dt
import statistics
import time

import requests

from .comun import AGENTE, FuenteError, resumen

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
ESPERA_ENTRE_CONSULTAS = 10
ESPERAS_429 = (30, 60, 120)
_ULTIMA_LLAMADA = [0.0]


def _consultar(consulta: str) -> dict:
    params = {"query": consulta, "mode": "timelinevol", "format": "json", "timespan": "12w"}
    for intento in range(len(ESPERAS_429) + 1):
        espera = ESPERA_ENTRE_CONSULTAS - (time.time() - _ULTIMA_LLAMADA[0])
        if espera > 0:
            time.sleep(espera)
        _ULTIMA_LLAMADA[0] = time.time()
        r = requests.get(URL, params=params, timeout=60, headers={"User-Agent": AGENTE})
        if r.status_code == 429 and intento < len(ESPERAS_429):
            time.sleep(ESPERAS_429[intento])
            continue
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as e:  # GDELT responde en texto cuando la consulta no es válida
            raise FuenteError(f"GDELT no aceptó la consulta: {r.text[:120]}") from e
    raise FuenteError("GDELT limitó las consultas tras varios reintentos.")


def leer(s, regla: dict, hoy: dt.date) -> dict:
    try:
        puntos = _consultar(regla["consulta"])["timeline"][0]["data"]
    except (KeyError, IndexError) as e:
        raise FuenteError("Respuesta de GDELT sin serie temporal.") from e
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
