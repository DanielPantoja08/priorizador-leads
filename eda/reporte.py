"""Escribe docs/EDA.md a partir de los resultados de perfil, histórico y conversaciones.

Todas las cifras del documento salen de los diccionarios de resultados: aquí no se escribe ningún número a mano.
"""

from __future__ import annotations

from collections import Counter

from eda.comun import DIR_DOCS, miles, num, pct, tabla_md

SI, NO, INFO = "✅ sí", "❌ no", "ℹ️ informativa"


def _coincide_pct(valor: float, citado: float, decimales: int = 1) -> bool:
    """Coincide si el valor calculado, redondeado como la cifra citada, es igual a la cifra citada."""
    return round(valor * 100, decimales) == citado


def _coincide_num(valor: float, citado: float, decimales: int = 3) -> bool:
    return round(valor, decimales) == citado


def verificacion(p: dict, h: dict, c: dict) -> tuple[str, Counter, list[list]]:
    """Tabla de verificación de cifras (TRD 17, punto 3)."""
    filas: list[list] = []

    def fila(cifra: str, fuente: str, calculado: str, estado: str, nota: str = ""):
        filas.append([cifra, fuente, calculado, estado, nota])

    def si_no(condicion: bool) -> str:
        return SI if condicion else NO

    # Volúmenes
    for cifra, valor, citado in [
        ("`leads.csv`: 1.503 filas", p["filas_leads"], 1503),
        ("`conversaciones.json`: 677 conversaciones", p["conversaciones"], 677),
        ("`catalogo_motos.csv`: 24 referencias", p["catalogo"], 24),
        ("`asesores.csv`: 42 asesores", p["asesores"], 42),
        ("`historico_cierres.csv`: 2.200 filas", p["historico"], 2200),
    ]:
        fila(cifra, "Enunciado §3; PRD 2.1", miles(valor), si_no(valor == citado))
    pv = p["puntos_venta_por_empresa"]
    fila(
        "Cinco puntos de venta por empresa",
        "PRD §8, supuesto 1",
        ", ".join(f"{k}: {v}" for k, v in pv.items()),
        si_no(set(pv.values()) == {5}),
    )
    ultimo = p["momento_corte"]
    fila(
        "Última fecha con registros: 10 de septiembre de 2026",
        "PRD §8, supuesto 3",
        ultimo.strftime("%Y-%m-%d %H:%M"),
        si_no(ultimo.strftime("%Y-%m-%d") == "2026-09-10"),
    )
    fila(
        "Asesores inactivos AS-037 y AS-040",
        "TRD §10",
        ", ".join(p["inactivos"]),
        si_no(p["inactivos"] == ["AS-037", "AS-040"]),
    )
    fila(
        "7 formatos de teléfono",
        "TRD §14",
        f"{p['formatos_telefono'] - 1} formatos válidos + 1 inválido",
        si_no(p["formatos_telefono"] - 1 == 7),
    )
    fila(
        "4 formatos de fecha",
        "TRD §6.1 y §14",
        p["formatos_fecha"],
        si_no(p["formatos_fecha"] == 4),
    )
    fila(
        '"Bajaj Pulsar" corresponde a 3 líneas',
        "TRD §6.2",
        p["lineas_pulsar"],
        si_no(p["lineas_pulsar"] == 3),
    )

    # Histórico: tasas base
    fila(
        "Tasa de cierre base 9,0 % (197 de 2.200)",
        "PRD 2.1",
        f"{pct(h['tasa_base'])} ({h['cierres']} de {miles(h['n_historico'])})",
        si_no(_coincide_pct(h["tasa_base"], 9.0) and h["cierres"] == 197),
    )
    fila(
        '179 registros "Sin gestión"',
        "TRD §9.1",
        h["n_sin_gestion"],
        si_no(h["n_sin_gestion"] == 179),
    )
    fila(
        "Tasa con gestión 9,75 %",
        "TRD §9.2",
        pct(h["tasa_gestion"], 2),
        si_no(_coincide_pct(h["tasa_gestion"], 9.75, 2)),
    )
    fila(
        "Histórico con gestión: 2.021 registros",
        "TRD §9.3",
        miles(h["n_gestion"]),
        si_no(h["n_gestion"] == 2021),
    )
    fila(
        '"De cada diez que gestionamos cerramos menos de uno"',
        "Enunciado §1",
        pct(h["tasa_gestion"], 2),
        si_no(h["tasa_gestion"] < 0.10),
    )

    # Velocidad de contacto
    for horas, citado in [(1, 16.7), (24, 7.4), (120, 4.7)]:
        valor = h[f"horas_{horas}"]
        fila(
            f"Cierre con contacto a {horas} h: {num(citado, 1)} %",
            "PRD 2.1; TRD §9.2 C",
            pct(valor),
            si_no(_coincide_pct(valor, citado)),
        )
    veces = h["horas_1"] / h["horas_120"]
    fila(
        "Contacto en 1 h frente a 120 h: 3,5 veces",
        "PRD 2.1",
        f"{num(veces, 2)} veces",
        si_no(round(veces, 1) == 3.5),
        "Diferencia de redondeo: truncar 3,56 da 3,5; redondear da 3,6",
    )

    # Tabla 9.2
    fila(
        "Pidió cita: 11,8 % frente a 8,9 %",
        "TRD §9.2 A",
        f"{pct(h['cita_si'])} frente a {pct(h['cita_no'])}",
        si_no(_coincide_pct(h["cita_si"], 11.8) and _coincide_pct(h["cita_no"], 8.9)),
    )
    fila(
        "Manifestó cuota: 11,8 % frente a 8,1 %", "TRD §9.2 A",
        f"{pct(h['cuota_si'])} frente a {pct(h['cuota_no'])} (NO + NO_INFORMA) o {pct(h['cuota_no_solo'])} (solo NO)",
        si_no(_coincide_pct(h["cuota_si"], 11.8) and (_coincide_pct(h["cuota_no"], 8.1) or _coincide_pct(h["cuota_no_solo"], 8.1))),
        "Ninguna definición del grupo de comparación reproduce 8,1 %",
    )  # fmt: skip
    fila(
        "Precio ≥ $10 M: 11,5 % frente a 8,5 %",
        "TRD §9.2 A",
        f"{pct(h['precio_si'])} frente a {pct(h['precio_no'])}",
        si_no(_coincide_pct(h["precio_si"], 11.5) and _coincide_pct(h["precio_no"], 8.5)),
    )
    fila(
        "Contado 11,8 % frente a crédito 8,4 %",
        "TRD §9.2 A",
        f"{pct(h['contado'])} frente a {pct(h['credito'])}",
        si_no(_coincide_pct(h["contado"], 11.8) and _coincide_pct(h["credito"], 8.4)),
    )
    fila(
        'Forma de pago "no informa": 12,3 %',
        "TRD §9.2 A",
        pct(h["pago_no_informa"]),
        si_no(_coincide_pct(h["pago_no_informa"], 12.3)),
    )

    # AUC
    fila(
        "AUC de la regresión logística: 0,555", "TRD §9.1",
        f"{num(h['auc_rl_cv'])} (validación cruzada) · {num(h['auc_rl_prueba'])} (temporal) · {num(h['auc_rl_muestra'])} (en muestra)",
        si_no(any(_coincide_num(h[k], 0.555) for k in ("auc_rl_cv", "auc_rl_prueba", "auc_rl_muestra"))),
        "El TRD no especifica variables ni forma de validación; el valor depende de ambas",
    )  # fmt: skip
    fila(
        "AUC del puntaje v1: 0,584",
        "TRD §9.1",
        num(h["auc_v1"]),
        si_no(_coincide_num(h["auc_v1"], 0.584)),
    )
    fila(
        "AUC v1 en entrenamiento 0,577 y en prueba 0,602",
        "TRD §9.3",
        f"{num(h['auc_v1_train'])} y {num(h['auc_v1_test'])}",
        si_no(_coincide_num(h["auc_v1_train"], 0.577) and _coincide_num(h["auc_v1_test"], 0.602)),
    )
    minimo = min(h["auc_rl_cv"], h["auc_rl_prueba"], h["auc_v1"], h["auc_v1_test"])
    maximo = max(h["auc_rl_cv"], h["auc_rl_prueba"], h["auc_v1"], h["auc_v1_test"])
    fila(
        "AUC entre 0,56 y 0,60 con modelos simples",
        "PRD 2.1",
        f"{num(minimo)} a {num(maximo)}",
        si_no(round(minimo, 2) >= 0.56 and round(maximo, 2) <= 0.60),
        "Depende del AUC de la regresión logística (fila anterior)",
    )

    # Tabla 9.3
    citados_93 = {
        "Frío": (7.3, 766, 7.2, 221),
        "Tibio": (9.9, 964, 11.1, 271),
        "Caliente": (15.8, 291, 15.7, 83),
    }
    for t, (tasa_c, n_c, tasa_p, n_p) in citados_93.items():
        todo, prueba = h[f"t93_{t}"], h[f"t93_{t}_prueba"]
        ok = (
            _coincide_pct(todo[2], tasa_c)
            and todo[1] == n_c
            and _coincide_pct(prueba[2], tasa_p)
            and prueba[1] == n_p
        )
        fila(
            f"{t}: {num(tasa_c, 1)} % (n={n_c}) y {num(tasa_p, 1)} % en prueba (n={n_p})", "TRD §9.3; PRD 2.1",
            f"{pct(todo[2])} (n={todo[1]}) y {pct(prueba[2])} (n={prueba[1]})", si_no(ok),
        )  # fmt: skip
    fila(
        "Caliente / Frío en prueba: 2,2 veces (criterio ≥ 1,8)",
        "TRD §9.3; PRD §3",
        f"{num(h['razon_prueba'], 2)} veces",
        si_no(round(h["razon_prueba"], 1) == 2.2 and h["razon_prueba"] >= 1.8),
    )

    # Contacto en 24 h
    fila(
        "55 % de los leads sin contacto en 24 h o nunca", "PRD 2.1",
        f"{pct(p['sin_contacto_24h_medianoche'])} (medianoche) · {pct(p['sin_contacto_24h'])} (conservador) · {pct(p['sin_contacto_24h_pesimista'])} (pesimista)",
        si_no(_coincide_pct(p["sin_contacto_24h_medianoche"], 55.0, 0)),
        "Coincide solo leyendo las fechas con precisión de día como 00:00. Ver §7",
    )  # fmt: skip
    fila(
        '"Cuatro de cada diez leads no se tocan en las primeras 24 horas"',
        "Enunciado §1; PRD §2",
        pct(p["sin_contacto_24h"]),
        INFO,
        "Los datos muestran una lentitud mayor que la percibida, como dice el PRD",
    )

    # Duplicados y conversaciones
    fila(
        "91 teléfonos compartidos entre empresas",
        "TRD §7; TRD §17",
        p["telefonos_compartidos"],
        si_no(p["telefonos_compartidos"] == 91),
    )
    fila(
        "51 grupos duplicados dentro de la misma empresa", "TRD §17", f"{p['grupos_duplicados']} ({p['grupos_con_repetidas']} sin quitar antes los `lead_id` repetidos)",
        si_no(p["grupos_duplicados"] == 51), "La cifra de 51 cuenta las 2 filas con `lead_id` repetido como grupos duplicados",
    )  # fmt: skip
    fila(
        "28 grupos multicanal",
        "TRD §17",
        p["grupos_multicanal"],
        si_no(p["grupos_multicanal"] == 28),
    )
    fila(
        "12 conversaciones huérfanas",
        "TRD §8.4; TRD §17",
        p["huerfanas"],
        si_no(p["huerfanas"] == 12),
    )
    fila(
        "25 leads con dos conversaciones",
        "TRD §17",
        p["leads_dos_conversaciones"],
        si_no(p["leads_dos_conversaciones"] == 25),
    )

    # Informativas
    volumen = p["volumen"]
    dias = (volumen["rango"][1] - volumen["rango"][0]).days + 1
    fila(
        '"Más de 3.000 leads al mes"',
        "Enunciado §1",
        f"{miles(p['leads_unicos'])} leads en {dias} días",
        INFO,
        "Cita del gerente; los datos sintéticos son una muestra menor",
    )
    fila(
        "Volumen diario frente a capacidad de asesores activos", "TRD §17",
        " · ".join(f"{e}: {num(volumen[e]['promedio'], 1)} leads/día, capacidad {volumen[e]['capacidad']}" for e in ("EMP-01", "EMP-02", "EMP-03")),
        INFO, "Sin cifra citada. Ver §7",
    )  # fmt: skip
    fila(
        "Conversaciones con respuesta del cliente",
        "TRD §17",
        f"{c['conversaciones'] - c['sin_respuesta']} de {c['conversaciones']}",
        INFO,
    )

    conteo = Counter(f[3] for f in filas)
    tabla = tabla_md(
        ["Cifra citada", "Documento y sección", "Valor calculado", "¿Coincide?", "Nota"], filas
    )
    return tabla, conteo, [f for f in filas if f[3] == NO]


def conclusiones(p: dict, h: dict, c: dict, discrepancias: list[list]) -> str:
    """Conclusiones para el diseño, con cifras tomadas de los resultados."""
    confirma = [
        f"La velocidad de contacto es la señal más fuerte del histórico: {pct(h['horas_1'])} de cierre a 1 h frente a {pct(h['horas_120'])} a 120 h. La urgencia debe pesar en la prioridad.",
        f"El componente A del puntaje v1 separa los extremos de forma estable: Caliente/Frío = {num(h['razon_todo'], 2)} veces en todo el histórico y {num(h['razon_prueba'], 2)} en la ventana de prueba (criterio ≥ 1,8).",
        f"El poder predictivo es bajo (AUC v1 = {num(h['auc_v1'])}): el puntaje ordena, no predice con certeza.",
        f"La deduplicación debe ser por empresa: {p['telefonos_compartidos']} teléfonos aparecen en más de una empresa.",
        f"Las reglas de fecha 6.1 resuelven todas las fechas con barras; solo {p['motivos_fecha'].get('por_defecto', 0)} lecturas terminan en dd/mm por defecto y hay {p['motivos_fecha'].get('invalida', 0)} fecha imposible.",
        f"La regla 6.2 asigna SKU a {p['reglas_modelo'].get('coincidencia_completa', 0) + p['reglas_modelo'].get('coincidencia_linea', 0)} leads, deja {p['reglas_modelo'].get('modelo_ambiguo', 0)} como solo marca y no deja textos sin coincidencia ({len(p['modelo_sin_coincidencia'])}).",
        f"Hay jerga de montos en las conversaciones (palos, millonzitos, Nmil) y {c['cero_millones']} dicen tener 0 de inicial: el extractor por reglas y el prompt deben cubrirlo.",
        f"{c['cambios_modelo']} conversaciones mencionan más de un modelo: la regla de usar el último modelo es necesaria.",
    ]
    contradice = [f"{f[0]} ({f[1]}): calculado {f[2]}. {f[4]}" for f in discrepancias]
    recomienda = [
        "Corregir en el PRD y el TRD las cifras marcadas con ❌ según la tabla de verificación (requiere aprobación).",
        "Documentar el método del porcentaje de leads sin contacto en 24 h, porque el resultado depende de cómo se tratan las fechas con precisión de día.",
        "Especificar en el TRD las variables y la validación de la regresión logística, o citar el AUC calculado aquí.",
        "Contar los grupos duplicados después de eliminar las filas con `lead_id` repetido, como indica la sección 6 del TRD.",
        "Agregar al diccionario de ciudades `bogota` y `bogota d.c.` → Bogotá D.C.",
        "Renombrar `capacidad_diaria_leads` a `capacidad_diaria` en la ingesta y anotarlo en el TRD.",
    ]
    partes = ["### Qué confirma", *[f"- {x}" for x in confirma], "", "### Qué contradice"]
    partes += [f"- {x}" for x in contradice] or ["- Nada."]
    partes += ["", "### Qué ajustes recomienda", *[f"- {x}" for x in recomienda]]
    return "\n".join(partes)


def escribir(perfil: dict, historico: dict, conversaciones: dict) -> tuple[Counter, list[list]]:
    """Genera docs/EDA.md y devuelve el conteo de la verificación y las discrepancias."""
    p, h, c = perfil["cifras"], historico["cifras"], conversaciones["cifras"]
    tabla_verif, conteo, discrepancias = verificacion(p, h, c)
    motivos = tabla_md(
        ["Motivo de resolución (registro y contacto)", "Fechas"],
        [[f"`{k}`", v] for k, v in sorted(p["motivos_fecha"].items(), key=lambda par: -par[1])],
    )
    modelo = tabla_md(
        ["Resultado de la regla 6.2", "Leads"],
        [[f"`{k}`", v] for k, v in sorted(p["reglas_modelo"].items(), key=lambda par: -par[1])],
    )
    bajo_c, alto_c, bajo_f, alto_f = historico["ic_prueba"]

    documento = f"""# EDA — Priorizador Diario de Leads

> Documento generado con `uv run python -m eda` a partir de `data/raw/`. **No se edita a mano.**
> Las cifras de este documento salen del código de `eda/`; dos ejecuciones producen el mismo resultado.

## Resumen

- Verificación de cifras: **{conteo[SI]} coinciden**, **{conteo[NO]} no coinciden** y {conteo[INFO]} son informativas (sección 3).
- Leads únicos analizados: {miles(p["leads_unicos"])} (sin filas con `lead_id` repetido ni registros de prueba). Histórico: {miles(h["n_historico"])} registros entre {h["rango"][0]} y {h["rango"][1]}.
- Las discrepancias no se ajustaron: se reportan con su causa probable y una corrección propuesta (sección 8).

## 1. Perfil de los archivos

{perfil["perfil"]}

## 2. Calidad de datos

Las inconsistencias marcadas como **(nueva)** no están descritas en las secciones 6 y 7 del TRD.

{perfil["calidad"]}

### 2.1 Fechas

![Formatos de fecha]({perfil["figura_fechas"]})

Resolución con la regla 6.1 del TRD (cada lead aporta dos fechas: registro y primer contacto):

{motivos}

### 2.2 Modelo de interés

{modelo}

### 2.3 Punto de venta, empresa y ciudad

Cada punto de venta pertenece a una sola empresa. La ciudad declarada por el cliente no siempre coincide con la más frecuente del punto de venta (supuesto 7 del PRD).

{perfil["punto_venta"]}

### 2.4 Duplicados

{perfil["duplicados"]}

### 2.5 Leads y conversaciones

{perfil["conversaciones"]}

## 3. Verificación de cifras

Una cifra coincide si el valor calculado, redondeado con los mismos decimales de la cifra citada, es igual a ella.

{tabla_verif}

## 4. Histórico de cierres

### 4.1 Por qué se excluye "Sin gestión"

Los registros "Sin gestión" nunca fueron contactados: no tienen horas al primer contacto y no cierran. Su desenlace refleja la falta de gestión, no la calidad del lead.

{historico["exclusion"]}

### 4.2 Por qué no se usa `numero_contactos`

El número de contactos solo se conoce al final de la gestión (un lead que cierra acumula más contactos), así que usarlo para priorizar sería fuga de información.

{historico["contactos"]}

### 4.3 Tasas por variable (histórico con gestión, IC 95 % de Wilson)

La columna p compara cada nivel con el resto (prueba z de dos proporciones). Hay **{historico["no_significativas"]} niveles sin diferencia estadísticamente significativa** (p ≥ 0,05); esas diferencias no deben interpretarse como señales.

{historico["variables"]}

![Cierre por horas]({historico["figura_horas"]})

### 4.4 Factores del componente A (tabla 9.2 del TRD)

{historico["tabla_92"]}

### 4.5 Poder predictivo (AUC)

Variables de la regresión logística: {", ".join(f"`{v}`" for v in historico["variables_rl"])}. Se excluyen `numero_contactos` (fuga) y las horas al primer contacto (dependen de la gestión, no del lead).

{historico["tabla_auc"]}

### 4.6 Validación del puntaje por temperatura (tabla 9.3 del TRD)

{historico["tabla_93"]}

En la ventana de prueba, el IC 95 % de Caliente es {pct(bajo_c)} – {pct(alto_c)} y el de Frío es {pct(bajo_f)} – {pct(alto_f)}. Con n pequeño, la razón Caliente/Frío tiene incertidumbre alta.

![Cierre por temperatura]({historico["figura_temperatura"]})

## 5. Conversaciones

Las objeciones y señales se miden con palabras clave: son una **aproximación** para dimensionar, no etiquetas. La extracción real la hace el componente de IA (Fase C).

{conversaciones["longitud"]}

### 5.1 Jerga de montos

{conversaciones["montos"]}

### 5.2 Objeciones

{conversaciones["objeciones"]}

![Objeciones]({conversaciones["figura_objeciones"]})

### 5.3 Señales de intención

{conversaciones["senales"]}

## 6. Volumen frente a capacidad

{perfil["volumen"]}

![Volumen diario]({perfil["figura_volumen"]})

## 7. Leads sin contacto en 24 horas

Método: base de leads únicos. Un lead cuenta como "sin contacto en 24 h" si no tiene fecha de primer contacto o si el contacto llegó más de 24 h después del registro. Cuando alguna fecha tiene precisión de día no se conocen las horas, y por eso se reportan tres variantes.

{perfil["contacto_24h"]}

## 8. Conclusiones para el diseño

{conclusiones(p, h, c, discrepancias)}
"""
    (DIR_DOCS / "EDA.md").write_text(documento, encoding="utf-8", newline="\n")
    return conteo, discrepancias
