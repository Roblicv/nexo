"""ACLED: eventos de protesta. Opcional: necesita una cuenta gratuita de ACLED.

Usa las variables de entorno ACLED_USUARIO y ACLED_CLAVE (en GitHub: Settings > Secrets).
ACLED cambió su sistema de acceso en 2025; si la primera ejecución falla aquí, revisa
https://acleddata.com/api-documentation y ajusta URL_TOKEN o URL_DATOS. El resto de Nexo sigue funcionando.
"""
from __future__ import annotations

import datetime as dt
import os

from .comun import FuenteError, resumen

URL_TOKEN = "https://acleddata.com/oauth/token"
URL_DATOS = "https://acleddata.com/api/acled/read"


def _token(s) -> str:
    usuario, clave = os.environ.get("ACLED_USUARIO"), os.environ.get("ACLED_CLAVE")
    if not usuario or not clave:
        raise FuenteError("Sin credenciales de ACLED: fuente opcional desactivada.")
    r = s.post(URL_TOKEN, data={"username": usuario, "password": clave,
                                "grant_type": "password", "client_id": "acled"}, timeout=40)
    r.raise_for_status()
    return r.json()["access_token"]


def _contar(s, token: str, pais: str, inicio: dt.date, fin: dt.date) -> int:
    r = s.get(URL_DATOS, headers={"Authorization": f"Bearer {token}"}, timeout=60, params={
        "_format": "json", "country": pais, "event_type": "Protests",
        "event_date": f"{inicio.isoformat()}|{fin.isoformat()}", "event_date_where": "BETWEEN",
        "fields": "event_id_cnty", "limit": 0})
    r.raise_for_status()
    datos = r.json()
    return int(datos.get("count", len(datos.get("data", []))))


def leer(s, regla: dict, hoy: dt.date) -> dict:
    token = _token(s)
    fin = hoy - dt.timedelta(days=7)  # ACLED publica con una semana de retraso
    inicio = fin - dt.timedelta(weeks=4)
    actual = sum(_contar(s, token, p, inicio, fin) for p in regla["paises"])
    base = []
    for anio in range(2018, 2026):
        i, f = inicio.replace(year=anio - (inicio.year != fin.year)), fin.replace(year=anio)
        base.append(sum(_contar(s, token, p, i, f) for p in regla["paises"]))
    media, desv = resumen(base)
    return {
        "lectura": actual,
        "media": media,
        "desviacion": desv,
        "fecha_dato": fin.isoformat(),
        "detalle": f"{actual} protestas en 4 semanas en {len(regla['paises'])} países; media 2018-2025: {media:.0f}",
    }
