"""Crea los usuarios de demostración (TRD 12). ÚNICO lugar del repositorio que usa la llave service_role.

Crea un gerente por empresa y **un usuario por cada asesor activo**, con la contraseña de
DEMO_PASSWORD. Así la lista «Mis leads de hoy» se puede mostrar con cualquier asesor, y no solo con
uno: cada quien entra con su propia cuenta y RLS le deja ver únicamente sus leads.

Se ejecuta después de `python -m pipeline run`, porque los usuarios de asesor referencian la tabla
asesor. Es idempotente: si el usuario ya existe, actualiza su contraseña y su empresa.

Uso: uv run python scripts/crear_usuarios_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

DOMINIO = "example.com"  # dominio reservado para ejemplos: no corresponde a correos reales
# Antes existía una sola cuenta de asesor; ahora hay una por asesor y esta queda sin sentido.
CORREO_ASESOR_HEREDADO = f"asesor.emp01@{DOMINIO}"


def requerida(nombre: str) -> str:
    valor = os.getenv(nombre, "").strip()
    if not valor:
        sys.exit(f"Falta la variable {nombre} en .env")
    return valor


def correo_de_asesor(asesor_id: str) -> str:
    """AS-001 -> asesor.as001@example.com. El correo se deriva del id, así que es estable."""
    return f"asesor.{asesor_id.lower().replace('-', '')}@{DOMINIO}"


def correo_de_gerente(empresa_id: str) -> str:
    """EMP-01 -> gerente.emp01@example.com."""
    return f"gerente.{empresa_id.lower().replace('-', '')}@{DOMINIO}"


def indice_de_usuarios(cliente: Client) -> dict[str, object]:
    """Correo -> usuario existente. Se lista una sola vez: son decenas de cuentas."""
    usuarios = cliente.auth.admin.list_users(page=1, per_page=1000)
    return {(usuario.email or "").lower(): usuario for usuario in usuarios}


def asegurar_usuario(cliente: Client, indice: dict, email: str, password: str) -> str:
    """Crea el usuario (con email confirmado) o actualiza su contraseña. Devuelve su id."""
    existente = indice.get(email)
    if existente:
        cliente.auth.admin.update_user_by_id(existente.id, {"password": password})
        return existente.id
    respuesta = cliente.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    return respuesta.user.id


def borrar_asesor_heredado(cliente: Client, indice: dict) -> None:
    """Elimina la cuenta única de asesor, si quedó de una versión anterior del script.

    Su fila de usuario_empresa cae por cascada. Solo se toca ese correo exacto.
    """
    usuario = indice.get(CORREO_ASESOR_HEREDADO)
    if usuario:
        cliente.auth.admin.delete_user(usuario.id)
        print(f"{CORREO_ASESOR_HEREDADO} eliminado: ahora hay una cuenta por asesor.")


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    cliente = create_client(requerida("SUPABASE_URL"), requerida("SUPABASE_SERVICE_ROLE_KEY"))
    password = requerida("DEMO_PASSWORD")

    asesores = (
        cliente.table("asesor").select("asesor_id, empresa_id, nombre").eq("activo", True)
        .order("asesor_id").execute().data
    )  # fmt: skip
    if not asesores:
        sys.exit("No hay asesores activos. Ejecute antes: uv run python -m pipeline run")

    # Las empresas salen de los propios datos: si mañana hay una cuarta, tendrá su gerente.
    empresas = sorted({a["empresa_id"] for a in asesores})
    usuarios = [(correo_de_gerente(e), e, "gerente", None) for e in empresas]
    usuarios += [(correo_de_asesor(a["asesor_id"]), a["empresa_id"], "asesor", a["asesor_id"]) for a in asesores]  # fmt: skip

    indice = indice_de_usuarios(cliente)
    borrar_asesor_heredado(cliente, indice)
    for email, empresa, rol, asesor_id in usuarios:
        user_id = asegurar_usuario(cliente, indice, email, password)
        cliente.table("usuario_empresa").upsert(
            {"user_id": user_id, "empresa_id": empresa, "rol": rol, "asesor_id": asesor_id}
        ).execute()

    print(f"{len(empresas)} gerentes y {len(asesores)} asesores activos:\n")
    for empresa in empresas:
        de_la_empresa = [a["asesor_id"] for a in asesores if a["empresa_id"] == empresa]
        print(f"  {empresa}  {correo_de_gerente(empresa)}")
        print(
            f"          {len(de_la_empresa)} asesores: "
            f"{correo_de_asesor(de_la_empresa[0])} … {correo_de_asesor(de_la_empresa[-1])}"
        )
    print("\nEl correo de un asesor se deriva de su id: AS-001 -> asesor.as001@example.com")
    print("Contraseña: la de DEMO_PASSWORD en .env (no se imprime).")


if __name__ == "__main__":
    main()
