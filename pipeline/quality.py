"""Colector de problemas de calidad (RF-03).

Cada regla que cambia o descarta un valor registra un problema. Algunos tipos, además, son **banderas**:
se copian a `lead.flags_calidad` para que el asesor y el gerente los vean en el lead.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# Tipos que se muestran en el lead. Los demás (formatos corregidos) solo quedan en problema_calidad.
BANDERAS = {
    "telefono_invalido",
    "fecha_invalida",
    "fecha_ambigua_resuelta_por_defecto",
    "contacto_antes_de_registro",
    "estado_sin_fecha_contacto",
    "sin_gestion_con_contacto",
    "conversacion_antes_de_registro",
    "modelo_ambiguo",
    "modelo_faltante",
    "posible_colision_telefono",
}


@dataclass(frozen=True)
class Problema:
    """Una inconsistencia detectada y la acción tomada."""

    archivo: str
    registro_id: str
    campo: str
    tipo: str
    valor_original: str | None
    accion: str
    empresa_id: str | None = None


class ColectorCalidad:
    """Acumula los problemas de una corrida; al final se cargan en `problema_calidad`."""

    def __init__(self) -> None:
        self.problemas: list[Problema] = []

    def registrar(
        self,
        archivo: str,
        registro_id: str,
        campo: str,
        tipo: str,
        valor_original: object,
        accion: str,
        empresa_id: str | None = None,
    ) -> None:
        """Agrega un problema. El valor original se guarda como texto."""
        valor = None if valor_original is None else str(valor_original)
        self.problemas.append(
            Problema(archivo, registro_id, campo, tipo, valor, accion, empresa_id)
        )

    def banderas_de(self, registro_id: str) -> list[str]:
        """Banderas de un registro, sin repetir y en orden alfabético."""
        return sorted(
            {p.tipo for p in self.problemas if p.registro_id == registro_id and p.tipo in BANDERAS}
        )

    def resumen(self) -> Counter:
        """Cantidad de problemas por tipo."""
        return Counter(p.tipo for p in self.problemas)
