"""Aplicación web del priorizador (RF-11, TRD 13).

Dos vistas sobre los mismos datos: la lista diaria del asesor y el tablero del gerente.

El aislamiento entre empresas **no** se hace aquí: la app usa la llave anónima y el JWT del usuario,
así que cada consulta pasa por las políticas de Row Level Security (TRD 12). Si esta pantalla
tuviera un error de filtrado, la base seguiría sin devolver filas de otra empresa.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from supabase import Client, create_client

# Streamlit agrega al path la carpeta de este archivo, no la raíz del repositorio.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pipeline.extract.evidencia import campos_sin_respaldo  # noqa: E402  (solo biblioteca estándar)

TITULO = "Priorizador Diario de Leads"

# Color y texto: el color solo acompaña, nunca es la única señal.
ESTILO_TEMPERATURA = {"Caliente": "🔴", "Tibio": "🟠", "Frío": "🔵", "Sin calificar": "⚪"}
ORDEN_TEMPERATURA = ["Caliente", "Tibio", "Frío", "Sin calificar"]

ETIQUETA_FORMA_PAGO = {"contado": "Contado", "credito": "Crédito", "no_informa": "No informa"}
ETIQUETA_MENCION = {"SI": "Sí", "NO": "No", "NO_INFORMA": "No informa"}

# El gerente se queja de los leads que pasan 24 h sin que nadie los toque.
HORAS_PARA_CONTACTAR = 24

# PostgREST corta cada respuesta en `max_rows` (1.000 en supabase/config.toml) sin avisar.
FILAS_POR_PAGINA = 1000


# --------------------------------------------------------------------------------------
# Sesión
# --------------------------------------------------------------------------------------


def conectar() -> Client:
    """Cliente con la llave anónima. Sin sesión iniciada no puede leer nada (RLS)."""
    try:
        url, llave = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"]
    except (KeyError, FileNotFoundError):
        st.error(
            "Faltan las credenciales. Copie `.streamlit/secrets.toml.example` a "
            "`.streamlit/secrets.toml` y complete `SUPABASE_URL` y `SUPABASE_ANON_KEY` "
            "con los valores de `supabase status`."
        )
        st.stop()
    return create_client(url, llave)


def iniciar_sesion(sb: Client) -> None:
    """Formulario de acceso. La sesión vive en `st.session_state`."""
    st.title(TITULO)
    st.caption("Lista priorizada de gestión diaria por asesor.")
    with st.form("acceso"):
        correo = st.text_input("Correo")
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            try:
                sb.auth.sign_in_with_password({"email": correo, "password": clave})
            except Exception:  # el detalle del error del proveedor no se muestra al usuario
                st.error("No se pudo iniciar sesión. Revise el correo y la contraseña.")
                return
            st.session_state.sesion_iniciada = True
            st.rerun()


def perfil_de(sb: Client) -> dict:
    """Empresa, rol y asesor del usuario. La política deja ver solo su propia fila."""
    filas = sb.table("usuario_empresa").select("empresa_id, rol, asesor_id").execute().data
    if not filas:
        st.error("Este usuario no tiene empresa asignada. Avise al equipo de IA.")
        st.stop()
    return filas[0]


# --------------------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------------------


def todas_las_filas(armar: Callable[[], object]) -> list[dict]:
    """Todas las filas de una consulta, página por página.

    Sin esto, una consulta de más de `FILAS_POR_PAGINA` filas llega truncada y nadie se entera.
    `armar` devuelve la consulta **nueva** en cada llamada: `.range()` agrega parámetros a la que
    recibe, así que reutilizarla repetiría el desplazamiento. La consulta debe tener un orden
    total, o dos páginas podrían traer la misma fila.
    """
    filas: list[dict] = []
    while True:
        pagina = armar().range(len(filas), len(filas) + FILAS_POR_PAGINA - 1).execute().data
        filas.extend(pagina)
        if len(pagina) < FILAS_POR_PAGINA:
            return filas


def fechas_disponibles(sb: Client) -> list[date]:
    """Fechas de corte que el usuario puede consultar, de la más reciente a la más antigua."""
    filas = todas_las_filas(
        lambda: sb.table("asignacion").select("fecha_corte").order("fecha_corte").order("lead_id")
    )
    return sorted({date.fromisoformat(f["fecha_corte"]) for f in filas}, reverse=True)


def leads_de(sb: Client, fecha: date, asesor_id: str | None) -> pd.DataFrame:
    """Leads de la fecha de corte. Si se indica un asesor, solo los suyos."""

    def armar():
        consulta = sb.table("v_mis_leads_hoy").select("*").eq("fecha_corte", fecha.isoformat())
        if asesor_id:
            consulta = consulta.eq("asesor_id", asesor_id)
        return consulta.order("orden").order("lead_id")  # `orden` se repite entre asesores

    return pd.DataFrame(todas_las_filas(armar))


def conversacion_de(sb: Client, ids: list[str]) -> pd.DataFrame:
    """Mensajes de las conversaciones del lead, en orden."""
    if not ids:
        return pd.DataFrame()
    filas = (
        sb.table("mensaje")
        .select("conversacion_id, orden, emisor, hora, texto")
        .in_("conversacion_id", ids)
        .order("conversacion_id")
        .order("orden")
        .execute()
    )
    return pd.DataFrame(filas.data)


def evidencia_de(sb: Client, ids: list[str], prompt_version: str | None) -> list[dict]:
    """Fragmentos que el extractor citó para justificar cada campo.

    `extraccion` conserva todas las versiones cacheadas de cada conversación, así que hay que
    filtrar por la que produjo estas señales; si no, se mezclan evidencias que se contradicen.
    """
    if not ids or not prompt_version:
        return []
    filas = (
        sb.table("extraccion")
        .select("conversacion_id, extractor, prompt_version, evidencia")
        .in_("conversacion_id", ids)
        .eq("prompt_version", prompt_version)
        .execute()
    )
    return filas.data


def lineas_de_evidencia(fila: dict, mensajes: pd.DataFrame) -> list[str]:
    """La evidencia de una conversación, lista para mostrar.

    Solo se cita entre comillas lo que el cliente escribió de verdad en esa conversación. Un
    fragmento que no aparece (inventado, dicho por el asesor o de otro chat) se avisa sin citarlo.
    """
    evidencia = fila.get("evidencia") or {}
    textos = []
    if not mensajes.empty:
        del_cliente = mensajes[
            (mensajes["conversacion_id"] == fila["conversacion_id"])
            & (mensajes["emisor"] == "cliente")
        ]
        textos = list(del_cliente["texto"])
    sin_respaldo = set(campos_sin_respaldo(evidencia, textos))
    return [
        f"- `{campo}`: *no aparece en lo que escribió el cliente; no se cita*"
        if campo in sin_respaldo
        else f"- `{campo}`: «{fragmento}»"
        for campo, fragmento in evidencia.items()
        if fragmento
    ]


def otros_leads_de(sb: Client, cliente_id: str, lead_id: str) -> pd.DataFrame:
    """Los demás leads del mismo cliente: la persona pudo escribir por varios canales."""
    filas = (
        sb.table("lead")
        .select("lead_id, canal, estado_gestion, fecha_registro, modelo_texto_original")
        .eq("cliente_id", cliente_id)
        .neq("lead_id", lead_id)
        .execute()
    )
    return pd.DataFrame(filas.data)


# --------------------------------------------------------------------------------------
# Presentación
# --------------------------------------------------------------------------------------


def horas_desde(valor: str | datetime | None, corte: date) -> float | None:
    """Horas entre el registro del lead y el final del día de corte.

    PostgREST entrega la fecha como texto ISO, pero un cliente de Postgres la entrega ya convertida:
    se aceptan las dos para que la función no dependa de por dónde llegaron los datos.
    """
    if not valor:
        return None
    registro = valor if isinstance(valor, datetime) else datetime.fromisoformat(valor)
    fin = datetime.combine(corte, datetime.max.time()).replace(tzinfo=registro.tzinfo)
    return round((fin - registro).total_seconds() / 3600, 1)


def contactados_a_tiempo(df: pd.DataFrame, corte: date) -> tuple[int, int]:
    """(contactados en menos de 24 h, leads medibles): el dolor que describe el gerente.

    Solo cuentan los leads que al corte ya cumplieron 24 h; los más nuevos todavía están a tiempo.
    Un lead con estado avanzado y sin fecha de contacto no se puede medir y queda fuera: se sabe que
    lo llamaron, no cuándo.
    """
    a_tiempo = medibles = 0
    for fila in df.to_dict("records"):
        horas = horas_desde(fila.get("fecha_registro"), corte)
        if horas is None or horas < HORAS_PARA_CONTACTAR:
            continue
        contacto = fila.get("fecha_primer_contacto")
        if not contacto or pd.isna(contacto):
            if fila.get("estado_gestion") != "Sin gestión":
                continue  # contactado, pero sin fecha
            medibles += 1
            continue
        medibles += 1
        espera = horas_desde(fila["fecha_registro"], corte) - horas_desde(contacto, corte)
        a_tiempo += espera <= HORAS_PARA_CONTACTAR
    return a_tiempo, medibles


def lead_de(df: pd.DataFrame, lead_id: str) -> dict:
    """La fila de un lead como diccionario, con los nulos como `None`.

    Al pasar por pandas, un nulo en una columna numérica o mixta sale como `NaN`, y `NaN` es
    verdadero: `lead.get("ia_objecion") and ...` lo dejaba pasar y la app se caía, o escribía
    «tiene — de inicial» y «Pidió cita» a quien no dijo nada de eso. Las listas (`razones`) se
    dejan intactas.
    """
    fila = df[df["lead_id"] == lead_id].iloc[0].to_dict()
    return {
        clave: None if not isinstance(valor, list | dict) and pd.isna(valor) else valor
        for clave, valor in fila.items()
    }


def pesos(valor: object) -> str:
    """Cifra en pesos colombianos, con puntos de miles."""
    if valor is None or pd.isna(valor):
        return "—"
    return f"${int(valor):,.0f}".replace(",", ".")


def frase_de_apertura(lead: dict, corte: date) -> str:
    """Cómo abrir la llamada, en una frase armada con los datos que ya están.

    Es una plantilla, no una llamada al modelo: los mismos datos dan siempre la misma frase, no
    consume cuota y no puede inventar nada. Responde a la queja del enunciado —«el asesor arranca
    de cero en cada llamada»— sin agregar un riesgo de alucinación donde no hacía falta.
    """
    # Se saluda por el primer nombre, pero hay registros con el nombre vacío o en blanco.
    partes_nombre = (lead.get("nombre") or "").split()
    nombre = partes_nombre[0] if partes_nombre else "El cliente"
    if not lead.get("ia_conversaciones"):
        modelo = lead.get("modelo") or lead.get("modelo_texto_original")
        pedido = (
            f"Pidió información de {modelo} por {lead.get('canal', 'el formulario')}."
            if modelo
            else "No dejó modelo de interés."
        )
        # Sin chat el lead está «Sin calificar»: la llamada es para averiguar lo que el puntaje no sabe.
        return f"{nombre} no tiene conversación de WhatsApp. {pedido} Califíquelo: confirme modelo, forma de pago, cuota inicial y si quiere pasar a verla."  # fmt: skip

    partes = []
    modelo = lead.get("ia_modelo") or lead.get("ia_modelo_texto")
    if modelo:
        partes.append(f"preguntó por la {modelo}")
    if lead.get("ia_cuota_inicial_cop"):
        partes.append(f"tiene {pesos(lead['ia_cuota_inicial_cop'])} de inicial")
    if lead.get("ia_forma_pago") == "credito":
        partes.append("va por crédito")
    elif lead.get("ia_forma_pago") == "contado":
        partes.append("paga de contado")

    frase = f"{nombre} " + (", ".join(partes) if partes else "escribió sin dar detalles")

    if lead.get("ia_pidio_cita"):
        frase += ". Pidió cita"
    elif lead.get("ia_pidio_cotizacion"):
        frase += ". Pidió cotización"

    # Lo que conviene tener en la cabeza antes de marcar, no después.
    if lead.get("ia_objecion") and lead["ia_objecion"] != "ninguna":
        frase += f". Ojo: puso una objeción de {lead['ia_objecion'].replace('_', ' ')}"
    if not lead.get("ia_cliente_respondio"):
        frase += ". No respondió al último mensaje"

    horas = horas_desde(lead.get("fecha_registro"), corte)
    if horas is not None and lead.get("estado_gestion") == "Sin gestión":
        frase += f". Lleva {horas:.0f} h sin contacto"
    return frase + "."


def tabla_de(df: pd.DataFrame, corte: date, con_asesor: bool = False) -> pd.DataFrame:
    """Columnas que ve el asesor en la lista (HU-01).

    `orden` es la posición dentro de la lista de **cada asesor**, así que solo significa algo
    cuando se está mirando a un asesor concreto. En la vista de toda la empresa se muestra a quién
    le tocó cada lead: si no, la columna sería una fila de unos sin sentido.
    """
    primera = (
        {"Asesor": df["asesor_id"].fillna("sin cupo")}
        if con_asesor
        # Int64 (entero anulable) y no int: los leads sin cupo no tienen orden.
        else {"#": df["orden"].astype("Int64")}
    )
    return pd.DataFrame({
        **primera,
        "Temp.": [f"{ESTILO_TEMPERATURA.get(t, '')} {t}" for t in df["temperatura"]],
        "Prioridad": df["prioridad"],
        "Cliente": df["nombre"],
        "Teléfono": df["telefono"].fillna("—"),
        "Canal": df["canal"],
        "Modelo de interés": df["ia_modelo"].fillna(df["modelo"]).fillna("—"),
        "Cuota inicial": [pesos(v) for v in df["ia_cuota_inicial_cop"]],
        "Pago": [ETIQUETA_FORMA_PAGO.get(v, "—") for v in df["ia_forma_pago"]],
        "Horas": [horas_desde(v, corte) for v in df["fecha_registro"]],
        "Estado": df["estado_gestion"],
    })  # fmt: skip


def detalle(sb: Client, lead: dict, corte: date) -> None:
    """Todo lo que el asesor necesita para llamar sin leer el chat completo (HU-02)."""
    st.info(f"☎️ **Cómo abrir la llamada** · {frase_de_apertura(lead, corte)}")
    izquierda, derecha = st.columns(2)

    with izquierda:
        st.markdown("**Por qué está aquí**")
        razones = lead.get("razones") or []
        if razones:
            for r in razones:
                valor = r.get("valor")
                detalle_valor = f" ({pesos(valor)})" if r["factor"].startswith("manifestó") else ""
                if r["factor"] == "sin contacto" and valor is not None:
                    detalle_valor = f" (hace {valor} h)"
                st.markdown(f"- {r['factor']}{detalle_valor}: **{r['puntos']:+d}**")
            st.caption(
                f"Calidad {lead['puntos_calidad']} · Conversación {lead['puntos_conversacion']} "
                f"· Urgencia {lead['puntos_urgencia']} = **{lead['prioridad']}**. "
                "El ajuste por conversación es heurístico (TRD 9.2)."
            )
        else:
            st.caption("Sin razones registradas.")

        st.markdown("**Lo que dijo el cliente**")
        if lead.get("ia_conversaciones"):
            st.markdown(
                f"- Modelo: **{lead.get('ia_modelo') or lead.get('ia_modelo_texto') or 'No informa'}**\n"
                f"- Cuota inicial: **{pesos(lead.get('ia_cuota_inicial_cop'))}** "
                f"(menciona: {ETIQUETA_MENCION.get(lead.get('ia_menciona_cuota'), '—')})\n"
                f"- Forma de pago: **{ETIQUETA_FORMA_PAGO.get(lead.get('ia_forma_pago'), '—')}**\n"
                f"- Intención: **{lead.get('ia_intencion') or '—'}** · "
                f"Objeción: **{lead.get('ia_objecion') or '—'}**\n"
                f"- Pidió cita: **{'sí' if lead.get('ia_pidio_cita') else 'no'}** · "
                f"Pidió cotización: **{'sí' if lead.get('ia_pidio_cotizacion') else 'no'}**"
            )
            if not lead.get("ia_cliente_respondio"):
                st.warning("El cliente nunca respondió después de su consulta inicial.")
        else:
            st.info("Sin conversación. Los campos extraídos aparecen como «No informa».")

    with derecha:
        st.markdown("**Ficha del lead**")
        disponible = lead.get("modelo_disponible_pv")
        registro = (lead.get("fecha_registro") or "")[:16].replace("T", " ") or "sin fecha legible"
        st.markdown(
            f"- Lead `{lead['lead_id']}` · registrado {registro}\n"
            f"- Modelo del formulario: {lead.get('modelo') or lead.get('modelo_texto_original') or '—'}\n"
            f"- Disponible en el punto de venta: "
            f"{'sí' if disponible else ('no' if disponible is False else '—')} *(informativo)*\n"
            f"- Punto de venta: {lead['punto_venta_id']}"
        )
        if lead.get("flags_calidad"):
            st.caption("Banderas de calidad: " + ", ".join(lead["flags_calidad"]))

        otros = otros_leads_de(sb, lead["cliente_id"], lead["lead_id"])
        if not otros.empty:
            st.markdown("**Otros leads de esta persona**")
            st.dataframe(otros, hide_index=True, width="stretch")

    ids = lead.get("ia_conversacion_ids") or []
    if ids:
        mensajes = conversacion_de(sb, ids)
        with st.expander(f"Conversación completa ({len(ids)})"):
            for _, m in mensajes.iterrows():
                quien = "🧑 Cliente" if m["emisor"] == "cliente" else "💬 Asesor"
                st.markdown(f"**{quien}** · {m['hora']}  \n{m['texto']}")
        with st.expander("Evidencia citada por el extractor"):
            for fila in evidencia_de(sb, ids, lead.get("ia_prompt_version")):
                st.caption(
                    f"{fila['conversacion_id']} · {fila['extractor']} {fila['prompt_version']}"
                )
                for linea in lineas_de_evidencia(fila, mensajes):
                    st.markdown(linea)


# --------------------------------------------------------------------------------------
# Pantallas
# --------------------------------------------------------------------------------------


def pantalla_leads(sb: Client, perfil: dict, corte: date) -> None:
    """HU-01 y HU-02. El gerente puede mirar la lista de cualquier asesor de su empresa."""
    asesor_id = perfil["asesor_id"]
    if perfil["rol"] == "gerente":
        asesores = sb.table("asesor").select("asesor_id, nombre").eq("activo", True).execute().data
        opciones = {"Todos los de la empresa": None} | {
            f"{a['nombre']} ({a['asesor_id']})": a["asesor_id"]
            for a in sorted(asesores, key=lambda a: a["asesor_id"])
        }
        asesor_id = opciones[st.selectbox("Asesor", list(opciones))]

    df = leads_de(sb, corte, asesor_id)
    if df.empty:
        st.info("No hay leads asignados para esta fecha.")
        return

    asignados = df[df["estado"] == "asignado"]
    # Mirando a toda la empresa, cada asesor trae su propio orden: lo que compara el gerente es
    # la prioridad.
    toda_la_empresa = asesor_id is None
    if toda_la_empresa:
        asignados = asignados.sort_values(["prioridad", "fecha_registro"], ascending=[False, True])

    st.markdown(f"**{len(asignados)} leads** para gestionar hoy.")
    st.dataframe(
        tabla_de(asignados, corte, con_asesor=toda_la_empresa), hide_index=True, width="stretch"
    )

    st.markdown("### Detalle")
    etiquetas = {}
    for _, r in asignados.iterrows():
        posicion = "" if toda_la_empresa or pd.isna(r["orden"]) else f"{int(r['orden'])}. "
        etiquetas[
            f"{posicion}{r['nombre']} · {ESTILO_TEMPERATURA.get(r['temperatura'], '')} "
            f"{r['temperatura']} (prioridad {r['prioridad']})"
        ] = r["lead_id"]
    if etiquetas:
        elegido = etiquetas[st.selectbox("Lead", list(etiquetas), label_visibility="collapsed")]
        detalle(sb, lead_de(df, elegido), corte)


def pantalla_tablero(sb: Client, corte: date) -> None:
    """HU-04. Carga por asesor, temperaturas, leads sin cupo y calidad de los datos."""
    df = leads_de(sb, corte, None)
    if df.empty:
        st.info("No hay asignación para esta fecha.")
        return

    asignados = df[df["estado"] == "asignado"]
    sin_cupo = df[df["estado"] == "sin_cupo"]
    a, b, c, d = st.columns(4)
    a.metric("Leads priorizados", len(df))
    b.metric("Asignados", len(asignados))
    c.metric("Sin cupo", len(sin_cupo))
    a_tiempo, medibles = contactados_a_tiempo(df, corte)
    d.metric(
        "Contactados en menos de 24 h",
        f"{a_tiempo / medibles:.0%}" if medibles else "—",
        help=f"{a_tiempo} de {medibles} leads que ya cumplieron 24 h al corte. Quedan fuera los "
        "que tienen estado avanzado sin fecha de contacto.",
    )

    st.markdown("### Carga por asesor")
    carga = pd.DataFrame(
        sb.table("v_tablero_gerente")
        .select("*")
        .eq("fecha_corte", corte.isoformat())
        .execute()
        .data
    )
    if not carga.empty:
        carga = carga.sort_values("asesor_id")
        carga["uso"] = carga["asignados"] / carga["capacidad_diaria"]
        st.dataframe(
            carga[["asesor_id", "nombre", "asignados", "capacidad_diaria", "prioritarios", "uso"]],
            hide_index=True,
            width="stretch",
            column_config={
                "asesor_id": "Asesor",
                "nombre": "Nombre",
                "asignados": "Asignados",
                "prioritarios": "Prioritarios",
                "capacidad_diaria": "Capacidad",
                "uso": st.column_config.ProgressColumn("Uso", min_value=0, max_value=1),
            },
        )

    st.markdown("### Distribución por temperatura")
    conteo = df["temperatura"].value_counts().reindex(ORDEN_TEMPERATURA).fillna(0).astype(int)
    st.bar_chart(conteo, horizontal=True)

    st.markdown("### Leads sin cupo")
    if sin_cupo.empty:
        st.success("Todos los leads del día cupieron en la capacidad del equipo.")
    else:
        # Los prioritarios van primero: son los que el gerente debería reasignar a mano (TRD 10).
        ordenados = sin_cupo.sort_values(["prioritario", "prioridad"], ascending=False)
        prioritarios = int(ordenados["prioritario"].sum())
        if prioritarios:
            st.warning(
                f"{prioritarios} leads sin cupo son prioritarios: Caliente, o sin contacto con "
                "menos de 24 horas. La asignación automática no los adelanta; usted decide."
            )
        st.dataframe(
            tabla_de(ordenados, corte, con_asesor=True).assign(
                Prioritario=ordenados["prioritario"].values
            ),
            hide_index=True,
            width="stretch",
        )

    st.markdown("### Calidad de los datos de la última carga")
    calidad = pd.DataFrame(sb.table("v_resumen_calidad").select("*").execute().data)
    if calidad.empty:
        st.caption("Sin problemas registrados.")
    else:
        st.dataframe(
            calidad.sort_values("casos", ascending=False), hide_index=True, width="stretch"
        )


def pantalla_metodo() -> None:
    """Cómo se calcula la prioridad, con sus límites declarados."""
    st.markdown("""
### Cómo se prioriza

La prioridad es la suma de tres componentes, y cada lead muestra los factores que la componen.

**A. Calidad (0 a 9)** — respaldada por el histórico de 2.021 leads gestionados:

| Factor | Cierra si se cumple | Si no | Puntos |
|---|---|---|---|
| Pidió cita | 11,8 % | 8,9 % | +3 |
| Manifestó cuota inicial | 11,8 % | 8,3 % | +3 |
| Modelo de $10 M o más | 11,5 % | 8,5 % | +2 |
| Pago de contado | 11,8 % | 8,4 % | +1 |

Cita, cuota y contado solo se conocen si el cliente escribió por WhatsApp. Un lead **sin
conversación** no cuenta como un «no»: suma +2, lo que valen en promedio esas tres señales en el
histórico, más el precio del modelo, y su temperatura es **Sin calificar**. Califíquelo en la llamada.

**B. Ajuste por conversación (−3 a +3)** — **heurístico**: el histórico no contiene estas señales,
así que sus pesos no están validados. Intención alta +2, baja −2; objeción de centrales o sin
inicial −1; el cliente no respondió −1; escribió por varios canales +1.

**C. Urgencia (0 a 5)** — sin contacto: 5 si lleva menos de 2 h, 4 hasta 24 h, 2 hasta 72 h y 1
después. Con gestión: cotización enviada 3, en proceso o no contesta 2, contactado 1.

La **temperatura** usa solo A + B: Caliente ≥ 6, Tibio 3 a 5, Frío ≤ 2; sin conversación, Sin
calificar.

### Qué tan bien funciona

Validación con corte temporal (entrenamiento antes del 15 de junio de 2026, prueba desde esa fecha):

| Temperatura | Cierre en la ventana de prueba | IC 95 % | Cierres / n |
|---|---|---|---|
| Caliente | 15,7 % | 9,4 – 25,0 % | 13 / 83 |
| Tibio | 11,1 % | 7,9 – 15,4 % | 30 / 271 |
| Frío | 7,2 % | 4,5 – 11,4 % | 16 / 221 |

Un Caliente cierra **2,16 veces** más que un Frío, con un intervalo de 1,01 a 4,36. El criterio
de aceptación (1,8) cae dentro: es un **indicio de separación**, no una prueba. Y la validación es
parcial, porque los pesos se eligieron mirando todo el histórico. El AUC es 0,602: el puntaje
**ordena**, no predice con certeza. Reproducible con `uv run python -m pipeline validate-scoring`.

### Qué significa en ventas

El histórico muestra que esperar cuesta: un lead que espera un día conserva el 64 % de su
probabilidad de cierre, y uno que espera cinco, el 41 %. Con ese decaimiento y la capacidad de hoy
(70 % de la demanda), atender por calidad más urgencia captura **10,3 cierres más (7,1 %)** que
atender primero lo más reciente. Frente al orden de llegada la diferencia es mucho mayor, pero se
debe sobre todo a atender fresco. Reproducible con `uv run python -m pipeline simulate-policy`.

### Límites que conviene conocer

- 559 de los 981 leads priorizados no tienen conversación de WhatsApp: salen Sin calificar y entre
  ellos solo los distinguen el precio del modelo y la urgencia.
- La extracción con IA acierta entre 97,8 % y 99,2 % según la corrida sobre 40 conversaciones
  revisadas por una persona. El modelo no es determinista ni con temperatura 0. Una cita que no
  aparece en lo que escribió el cliente no se muestra.
- El ajuste por conversación no tiene validación histórica y por eso pesa poco.
""")


# --------------------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title=TITULO, page_icon="🏍️", layout="wide")
    # El cliente se crea una sola vez: `setdefault` lo construiría en cada recarga aunque ya exista.
    if "sb" not in st.session_state:
        st.session_state.sb = conectar()
    sb = st.session_state.sb

    if not st.session_state.get("sesion_iniciada"):
        iniciar_sesion(sb)
        return

    perfil = perfil_de(sb)
    with st.sidebar:
        st.markdown(f"**{perfil['empresa_id']}** · {perfil['rol']}")
        if perfil["asesor_id"]:
            st.caption(f"Asesor {perfil['asesor_id']}")
        fechas = fechas_disponibles(sb)
        if not fechas:
            st.warning("No hay corridas cargadas todavía.")
            st.stop()
        corte = st.selectbox("Fecha de corte", fechas, format_func=lambda f: f.strftime("%Y-%m-%d"))
        if st.button("Cerrar sesión"):
            sb.auth.sign_out()
            st.session_state.clear()
            st.rerun()

    st.title(TITULO)
    nombres = ["Mis leads de hoy", "Cómo prioriza"]
    if perfil["rol"] == "gerente":
        nombres.insert(1, "Tablero")
    pestanas = dict(zip(nombres, st.tabs(nombres), strict=True))

    with pestanas["Mis leads de hoy"]:
        pantalla_leads(sb, perfil, corte)
    if "Tablero" in pestanas:
        with pestanas["Tablero"]:
            pantalla_tablero(sb, corte)
    with pestanas["Cómo prioriza"]:
        pantalla_metodo()

    ultima = sb.table("v_ultima_ejecucion").select("*").execute().data
    if ultima:
        e = ultima[0]
        st.caption(
            f"Última ejecución #{e['ejecucion_id']} · estado {e['estado']} · "
            f"fecha de corte {e['fecha_corte']} · {(e['finalizado_en'] or '')[:19].replace('T', ' ')}"
        )


if __name__ == "__main__":
    main()
