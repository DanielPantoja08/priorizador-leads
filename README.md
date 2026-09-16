# Priorizador Diario de Leads — Motos y Servicios

Convierte los leads crudos de tres comercializadoras de motos (WhatsApp, Meta Ads y formulario web)
en una **lista priorizada de gestión diaria por asesor**. Cada lead se enriquece con lo que el
cliente dijo en WhatsApp —extraído con IA— y llega con las razones de su posición, para que el
asesor sepa a quién llamar primero y qué decirle.

Cada empresa ve únicamente sus datos, y ese aislamiento se aplica en la base de datos, no en la
interfaz.

---

## Qué hace, en una corrida

```
leads.csv ─┐
catálogo ──┤
asesores ──┼─▶ ingesta ▶ normalización ▶ catálogo ▶ deduplicación ▶ carga
histórico ─┤                                                          │
chats.json ┘                                                          ▼
                                    extracción con IA ▶ señales por lead
                                                          │
                                            puntaje ▶ asignación ▶ app web
```

Un solo comando ejecuta todo: `uv run python -m pipeline run`.

| Etapa | Resultado medido (corte 2026-09-10) |
|---|---|
| Ingesta y normalización | 1.503 filas crudas → 1.500 leads, 1.451 clientes |
| Conversaciones | 677 chats · 4.310 mensajes |
| Extracción con IA | 677 conversaciones en **68 peticiones**, 8,4 min. La segunda corrida reusa la caché: **0 peticiones y 3 s** |
| Señales consolidadas | 628 leads |
| Puntaje | 981 leads elegibles: 780 Frío, 59 Tibio, 142 Caliente |
| Asignación | 637 asignados y 344 sin cupo, sobre una capacidad de 694 |

La corrida es **idempotente**: repetirla con los mismos insumos deja las tablas byte a byte iguales
(verificado comparando huellas md5 de `senales_lead`, `score` y `asignacion`).

---

## Cómo se prioriza

La prioridad es una suma de tres componentes, y cada lead guarda los factores que la formaron.
Se eligió un puntaje aditivo y no un modelo entrenado porque el histórico tiene poco poder
predictivo (una regresión logística llega a AUC 0,548) y porque los puntos se traducen
directamente en razones que el asesor puede leer.

**A. Calidad (0 a 9)** — derivada de las tasas de cierre de 2.021 leads gestionados:
pidió cita `+3`, manifestó cuota inicial `+3`, modelo de $10 M o más `+2`, pago de contado `+1`.

**B. Ajuste por conversación (−3 a +3)** — **heurístico y así se declara**: el histórico no contiene
estas señales. Intención alta `+2` / baja `−2`, objeción de centrales o sin inicial `−1`, el cliente
no respondió `−1`, escribió por varios canales `+1`.

**C. Urgencia (0 a 5)** — sin gestión: 5 si lleva menos de 2 h, 4 hasta 24 h, 2 hasta 72 h, 1
después. Con gestión: cotización enviada 3, en proceso o no contesta 2, contactado 1.

`temperatura = f(A + B)`: Caliente ≥ 6, Tibio 3–5, Frío ≤ 2. La urgencia ordena pero no calienta.

### Validación contra el histórico (`uv run python -m pipeline validate-scoring`)

Corte temporal: se entrena antes del 15 de junio de 2026 y se mide desde esa fecha, sobre datos que
no participaron en la elección de los pesos.

| Temperatura | Cierre en la ventana de prueba | n |
|---|---|---|
| Caliente | 15,7 % | 83 |
| Tibio | 11,1 % | 271 |
| Frío | 7,2 % | 221 |

Un Caliente cierra **2,16 veces** más que un Frío; el criterio de aceptación era 1,8. El AUC es
0,577 en entrenamiento y 0,602 en prueba: **el puntaje ordena, no predice con certeza.**

---

## El componente de IA

Dos extractores tras la misma interfaz, intercambiables con `--extractor`:

- **`gemini`** (por defecto): `gemini-3.5-flash-lite` con salida estructurada, lotes de 10
  conversaciones, reintentos con espera exponencial y límite propio de peticiones por minuto.
- **`reglas`**: expresiones regulares, sin red. Es la línea base y también el **respaldo**: si el
  LLM falla, el flujo termina igual y la corrida se marca `ok_con_respaldo` (RNF-06).

Cada extracción se guarda con su extractor, modelo y versión de prompt, y se cachea por
`(hash_contenido, extractor, prompt_version)`. Cambiar el prompt sube la versión e invalida la
caché sin borrarla.

### Qué tan bien extrae

Sobre 40 conversaciones cuyas etiquetas **propuso la IA y revisó una persona** —así se declara
siempre, nunca como etiquetado manual—:

| | Exactitud media por campo |
|---|---|
| Gemini (prompt v4) | **97,8 % – 99,2 %** según la corrida |
| Reglas | 99,4 % |

Dos advertencias que conviene leer antes que las cifras:

1. **`temperature = 0` no hace determinista al modelo.** Dos corridas idénticas de las mismas 40
   conversaciones dieron 98,6 % y 99,2 % (4 campos distintos de 360). Comparar dos versiones de
   prompt con una sola corrida no concluye nada.
2. **La columna de reglas parte con ventaja.** Las etiquetas se propusieron con los mismos criterios
   que implementan las reglas, así que la cifra que vale para juzgar la extracción con IA es la de
   Gemini.

---

## Seguridad y aislamiento

- La app usa la **llave anónima** y el JWT del usuario; cada consulta pasa por Row Level Security.
  Un error de filtrado en la interfaz no expondría datos de otra empresa.
- `authenticated` **solo lee**: no hay políticas de `insert`, `update` ni `delete`.
- Las vistas se crean con `security_invoker = true`; sin esa opción una vista ignora RLS.
- Un asesor ve solo sus leads; un gerente, toda su empresa.
- Las conversaciones huérfanas (sin empresa) no son visibles para nadie.
- La llave `service_role` se usa **únicamente** en `scripts/crear_usuarios_demo.py`, nunca en la app.
- `.env` y `.streamlit/secrets.toml` están fuera del repositorio; solo se versionan los `.example`.

`tests/test_aislamiento.py` comprueba todo esto de extremo a extremo contra el Supabase local, con
sesiones reales: 11 pruebas que verifican que un usuario de EMP-01 no ve una sola fila de otra
empresa, en seis tablas y en la vista diaria.

---

## Cómo ejecutarlo

Requisitos: [uv](https://docs.astral.sh/uv/), Docker y la CLI de Supabase.

```bash
uv sync --all-groups                 # entorno bloqueado por uv.lock
cp .env.example .env                 # complete los valores
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

supabase start                       # Postgres, Auth y Studio en Docker
supabase db reset                    # aplica migraciones y seed.sql

uv run python -m eda                 # regenera docs/EDA.md (no usa la base)
uv run python -m pipeline run --fecha-corte 2026-09-10
uv run python scripts/crear_usuarios_demo.py   # después del pipeline

uv run python -m pipeline eval --con-gemini    # evalúa la extracción
uv run python -m pipeline validate-scoring     # valida el puntaje
uv run streamlit run app/streamlit_app.py
```

`DATABASE_URL`, `SUPABASE_URL` y `SUPABASE_ANON_KEY` salen de `supabase status`.
Para correr sin llave de Gemini: `EXTRACTOR=reglas` en `.env`, o `--extractor reglas`.

Usuarios de demostración: `gerente.emp01@example.com`, `gerente.emp02@example.com`,
`gerente.emp03@example.com` y `asesor.emp01@example.com`. La contraseña es la de `DEMO_PASSWORD`
y se comparte fuera del repositorio.

Antes de cada commit: `uv run ruff check .`, `uv run ruff format .` y `uv run pytest -q`
(**191 pruebas**; ninguna llama a servicios externos, salvo la de aislamiento, que usa el Supabase
local y se omite sola si no está en ejecución).

---

## Documentación

| Documento | Contenido |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Qué se construye y por qué |
| [docs/TRD.md](docs/TRD.md) | Cómo: modelo de datos, reglas, prompts, puntaje y despliegue |
| [docs/EDA.md](docs/EDA.md) | Evidencia de los datos, generada por script |
| [CLAUDE.md](CLAUDE.md) | Guía del repositorio y decisiones vigentes |

Ninguna cifra de esta documentación se escribió a mano: todas salen de un script versionado, y
`docs/EDA.md` incluye una tabla que compara cada cifra citada con su valor calculado.

---

## Límites conocidos

- **565 de los 981 leads priorizados no tienen conversación de WhatsApp.** Su techo son 2 puntos de
  calidad, así que quedan en Frío y solo la urgencia los ordena. Es coherente —no hay información
  para calificarlos más alto— pero explica por qué el 79 % de la lista sale Frío.
- El **ajuste por conversación no tiene validación histórica**. Por eso pesa poco y la app lo marca
  como heurístico.
- La extracción con IA **no es reproducible al 100 %** entre corridas, aunque la caché hace que una
  misma conversación no se reevalúe.
- `numero_contactos` no se usa como predictor: solo se conoce al final y sería fuga de información.
- La deduplicación es **solo dentro de cada empresa**: un teléfono compartido entre dos empresas
  genera dos clientes independientes, por diseño.
- El histórico se analiza sin los 179 registros "Sin gestión": nunca fueron contactados, así que su
  desenlace no habla de la calidad del lead.
