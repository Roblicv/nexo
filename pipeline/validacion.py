"""El norte de Nexo: ¿mejora una variable los aciertos frente a la tasa base?

Se predice cada año usando solo los años anteriores (fuera de muestra) y se compara la
puntuación de Brier: el promedio de (probabilidad - resultado)². Menor es mejor.
"""
from __future__ import annotations

import math

import numpy as np


def _logit(x: list[float], y: list[int], ridge: float = 0.5, iteraciones: int = 50) -> tuple[float, float]:
    X = np.column_stack([np.ones(len(x)), np.asarray(x, float)])
    Y = np.asarray(y, float)
    b = np.zeros(2)
    for _ in range(iteraciones):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        grad = X.T @ (Y - p) - ridge * np.r_[0, b[1]]
        hess = X.T @ (X * W[:, None]) + ridge * np.diag([1e-6, 1])
        paso = np.linalg.solve(hess, grad)
        b += paso
        if np.max(np.abs(paso)) < 1e-8:
            break
    return float(b[0]), float(b[1])


def brier(p: list[float], y: list[int]) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def validar(predictor: dict[int, float], resultado: dict[int, int],
            minimo_anios: int = 10, calentamiento: int = 5) -> dict:
    """predictor[año - 1] intenta anticipar resultado[año]."""
    anios = sorted(a for a in resultado if (a - 1) in predictor)
    if len(anios) < minimo_anios:
        return {"estado": "historial_insuficiente", "n": len(anios),
                "mensaje": f"Hay {len(anios)} años con datos; la regla pide {minimo_anios}."}
    pb, pm, ys = [], [], []
    for i, anio in enumerate(anios):
        previos = anios[:i]
        if len(previos) < calentamiento:
            continue
        yp = [resultado[a] for a in previos]
        xp = [predictor[a - 1] for a in previos]
        pb.append((sum(yp) + 0.5) / (len(yp) + 1))
        b0, b1 = _logit(xp, yp)
        pm.append(1 / (1 + math.exp(-(b0 + b1 * predictor[anio - 1]))))
        ys.append(resultado[anio])
    b_base, b_mod = brier(pb, ys), brier(pm, ys)
    _, b1 = _logit([predictor[a - 1] for a in anios], [resultado[a] for a in anios])
    sd = float(np.std([predictor[a - 1] for a in anios])) or 1.0
    mejora = b_mod < b_base
    return {
        "estado": "validada" if mejora else "no_mejora",
        "n": len(ys),
        "brier_base": round(b_base, 4),
        "brier_con_variable": round(b_mod, 4),
        "elasticidad": round(max(-1.0, min(1.0, 2 * b1 * sd)), 3) if mejora else 0.0,
        "mensaje": ("La variable mejora los aciertos y entra al pronóstico." if mejora
                    else "La variable no mejora los aciertos: su peso queda en 0."),
    }
