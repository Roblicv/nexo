"""Modelo de Nexo: la misma matemática que la página (docs/index.html)."""
from __future__ import annotations

import math

import numpy as np

ANIO_INICIO, ANIO_FIN = 2027, 2075
ANIOS = np.arange(ANIO_INICIO, ANIO_FIN + 1)
H, TAU, D_LENTA, THETA = 3.0, 1.5, 9.0, 6.0
JUEGO_BASE = {"c": 3, "pi": 0.5, "b": 5, "a": 2, "g": 5, "s": 0.5}


def juego(p: dict) -> dict:
    """Dilema de reportar: anunciar pronto o retrasar."""
    q = 0.2 + 0.7 * p["s"]
    eu_r = -p["c"] - p["pi"] * p["b"] + (1 - p["pi"]) * p["a"]
    eu_c = -q * (p["g"] + p["b"]) - H
    prob = 1 / (1 + math.exp(-(eu_r - eu_c) / TAU))
    demora = prob * (3.5 - 2 * p["s"]) + (1 - prob) * D_LENTA
    return {"p_anuncio": prob, "demora_semanas": demora, "escape": 1 - math.exp(-demora / THETA)}


def pronostico(eventos: int, anios: int, tendencia: float, multiplicador: float,
               simulaciones: int = 1500, semilla: int = 20261029) -> dict:
    rng = np.random.default_rng(semilla)
    lam0 = rng.gamma(eventos + 0.5, 1 / anios, simulaciones)
    g = np.maximum(0, tendencia + 0.0075 * rng.standard_normal(simulaciones))
    m = multiplicador * np.exp(0.25 * rng.standard_normal(simulaciones))
    exponentes = ANIOS - 2026
    tasas = lam0[:, None] * m[:, None] * (1 + g[:, None]) ** exponentes[None, :]
    acumulada = 1 - np.exp(-np.cumsum(tasas, axis=1))
    media = acumulada.mean(axis=0)
    p10, p90 = np.percentile(acumulada, [10, 90], axis=0)

    def cruce(serie):
        idx = np.nonzero(serie >= 0.5)[0]
        return int(ANIOS[idx[0]]) if idx.size else None

    i2036 = int(np.nonzero(ANIOS == 2036)[0][0])
    return {
        "anio_50": cruce(media),
        "rango_80": [cruce(p90), cruce(p10)],
        "p_2027_2036": round(float(media[i2036]), 4),
        "p_2027": round(float(media[0]), 4),
        "curva": {"anios": ANIOS.tolist(), "media": np.round(media, 4).tolist(),
                  "p10": np.round(p10, 4).tolist(), "p90": np.round(p90, 4).tolist()},
    }
