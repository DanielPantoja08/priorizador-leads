"""Crea los usuarios de demostración (TRD 12). ÚNICO lugar del repositorio que usa la llave service_role.

Crea un gerente por empresa y un asesor de EMP-01, con la contraseña de DEMO_PASSWORD.
Se ejecuta después de `python -m pipeline run`, porque el usuario asesor referencia la tabla asesor.
Es idempotente: si el usuario ya existe, actualiza su contraseña y su empresa.

Uso: uv run python scripts/crear_usuarios_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

DOMINIO = "example.com"  # dominio reservado para ejemplos: no corresponde a correos reales


def requerida(nombre: str) -> str:
    valor = os.getenv(nombre, "").strip()
    if not valor:
        sys.exit(f"Falta la variable {nombre} en .env")
    return valor


def buscar_usuario(cliente: Client, email: str):
    """Devuelve el usuario con ese email, o None."""
    for usuario in cliente.auth.admin.list_users(page=1, per_page=1000):
        if (usuario.email or "").lower() == email:
            return usuario
    return None


def asegurar_usuario(cliente: Client, email: str, password: str) -> str:
    """Crea el usuario (con email confirmado) o actualiza su contraseña. Devuelve su id."""
    existente = buscar_usuario(cliente, email)
    if existente:
        cliente.auth.admin.update_user_by_id(existente.id, {"password": password})
        return existente.id
    respuesta = cliente.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    return respuesta.user.id


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    cliente = create_client(requerida("SUPABASE_URL"), requerida("SUPABASE_SERVICE_ROLE_KEY"))
    password = requerida("DEMO_PASSWORD")

    # Primer asesor activo de EMP-01 (en orden de asesor_id), para el usuario asesor.
    asesores = (
        cliente.table("asesor").select("asesor_id").eq("empresa_id", "EMP-01").eq("activo", True)
        .order("asesor_id").limit(1).execute().data
    )  # fmt: skip
    if not asesores:
        sys.exit("No hay asesores de EMP-01. Ejecute antes: uv run python -m pipeline run")

    usuarios = [
        (f"gerente.emp01@{DOMINIO}", "EMP-01", "gerente", None),
        (f"gerente.emp02@{DOMINIO}", "EMP-02", "gerente", None),
        (f"gerente.emp03@{DOMINIO}", "EMP-03", "gerente", None),
        (f"asesor.emp01@{DOMINIO}", "EMP-01", "asesor", asesores[0]["asesor_id"]),
    ]
    for email, empresa, rol, asesor_id in usuarios:
        user_id = asegurar_usuario(cliente, email, password)
        cliente.table("usuario_empresa").upsert(
            {"user_id": user_id, "empresa_id": empresa, "rol": rol, "asesor_id": asesor_id}
        ).execute()
        print(f"{email:28} {empresa} {rol}{' ' + asesor_id if asesor_id else ''}")
    print("Contraseña: la de DEMO_PASSWORD en .env (no se imprime).")


if __name__ == "__main__":
    main()
