"""Utilidades compartidas por las fuentes."""
from __future__ import annotations

import datetime as dt
import statistics

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

AGENTE = "Nexo/1.0 (observatorio abierto; https://github.com)"


class FuenteError(Exception):
    """La fuente no respondió o los datos no sirven para aplicar la regla."""


def sesion() -> requests.Session:
    s = requests.Session()
    reintentos = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=reintentos))
    s.headers["User-Agent"] = AGENTE
    return s


def resumen(valores: list[float], minimo: int = 3) -> tuple[float, float]:
    """Media y desviación de la línea base. La desviación nunca baja de un 5 % de la media
    (ni de 0,5) para que una base muy estable no convierta ruido en alarma."""
    if len(valores) < minimo:
        raise FuenteError(f"Línea base con {len(valores)} valores; la regla pide al menos {minimo}.")
    media = statistics.fmean(valores)
    desv = statistics.pstdev(valores)
    return media, max(desv, abs(media) * 0.05, 0.5 if abs(media) >= 10 else 0.05)


def semana_iso(fecha: dt.date) -> tuple[int, int]:
    a, s, _ = fecha.isocalendar()
    return a, s


def distancia_semanas(s1: int, s2: int) -> int:
    d = abs(s1 - s2)
    return min(d, 52 - d)
