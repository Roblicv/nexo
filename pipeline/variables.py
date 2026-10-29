"""Convierte una lectura en un valor de -1 a +1 con la regla registrada."""
from __future__ import annotations

import math


def transformar(lectura: float, media: float, desviacion: float) -> tuple[float, float]:
    z = (lectura - media) / desviacion
    return z, math.tanh(z / 2)
