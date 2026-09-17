# Priorizador Diario de Leads — Motos y Servicios

Convierte los leads crudos de tres comercializadoras de motos (WhatsApp, Meta Ads y formulario web)
en una **lista priorizada de gestión diaria por asesor**. Cada lead se enriquece con lo que el
cliente dijo en WhatsApp —extraído con IA— y llega con las razones de su posición, para que el
asesor sepa a quién llamar primero y qué decirle.

Cada empresa ve únicamente sus datos, y ese aislamiento se aplica en la base de datos, no en la
interfaz.

**App en línea:** https://priorizador-leads.streamlit.app · **Pipeline diario:**
[GitHub Actions](https://github.com/DanielPantoja08/priorizador-leads/actions/workflows/pipeline.yml) ·
**CI:** [pruebas](https://github.com/DanielPantoja08/priorizador-leads/actions/workflows/ci.yml)

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
| Puntaje (v3) | 981 leads elegibles: 142 Caliente, 60 Tibio, 220 Frío y 559 Sin calificar |
| Asignación | 637 asignados y 344 sin cupo, sobre una capacidad de 694 |
| Evidencia de la IA | 4 campos con una cita que no aparece en la conversación: se toman como desconocidos, se registran y no se citan |

La corrida es **idempotente**: repetirla con los mismos insumos deja las tablas byte a byte iguales
(verificado comparando huellas md5 de `senales_lead`, `score` y `asignacion`).

---

## Cómo se prioriza

La prioridad es una suma de tres componentes, y cada lead guarda los factores que la formaron.
Se eligió un puntaje aditivo y no un modelo entrenado porque el histórico tiene poco poder
predictivo (una regresión logística llega a AUC 0,548) y porque los puntos se traducen
directamente en razones que el asesor puede leer.

**A. Calidad (0 a 9)** — derivada de las tasas de cierre de 2.021 leads gestionados: pidió cita
`+3`, manifestó cuota inicial `+3`, modelo de $10 M o más `+2`, forma de pago `+1`.

**Cada estado de una señal vale lo que dice el histórico de ese estado** (puntaje v3), no «sí»
contra «todo lo demás». Con la cuota, «no informa» cierra 7,8 %, por debajo de «no» (8,7 %): suma
0. Con la forma de pago, «no informa» cierra 12,3 %, igual que contado (11,8 %) y por encima de
crédito (8,4 %): suma `+1`, como contado. `validate-scoring` comprueba que ningún estado sin puntos
cierre más que uno con puntos.

La misma regla cubre lo que no se sabe:

- **Sin conversación** no hay estado que mirar: el lead suma el valor esperado de las tres señales
  del chat, 2,47 puntos redondeado a `+2` (cita en el 29,4 % del histórico, cuota en el 40,7 % y
  forma de pago que puntúa en el 36,9 %), más el precio del modelo, y queda **«Sin calificar»**.
- **Con conversación, un campo cuya cita no aparece en el chat** se toma como desconocido: vuelve a
  su valor neutro (cuota «no informa», intención media, sin objeción...) y puntúa como tal. La razón
  queda en la lista del lead con 0 puntos.

**B. Ajuste por conversación (−3 a +3)** — **heurístico y así se declara**: el histórico no contiene
estas señales. Intención alta `+2` / baja `−2`, objeción de centrales o sin inicial `−1`, el cliente
no respondió `−1`, escribió por varios canales `+1`.

**C. Urgencia (0 a 5)** — sin gestión: 5 si lleva menos de 2 h, 4 hasta 24 h, 2 hasta 72 h, 1
después. Con gestión: cotización enviada 3, en proceso o no contesta 2, contactado 1.

`temperatura = f(A + B)`: Caliente ≥ 6, Tibio 3–5, Frío ≤ 2. La urgencia ordena pero no calienta.
Un lead sin conversación es **«Sin calificar»**, no Frío: la frase de apertura le pide al asesor
averiguar en la llamada lo que el puntaje no sabe.

### Validación contra el histórico (`uv run python -m pipeline validate-scoring`)

Corte temporal: antes del 15 de junio de 2026 es entrenamiento y desde esa fecha, prueba. **La
validación es parcial:** los pesos y los estados que puntúan se eligieron con las tasas de todo el
histórico, ventana de prueba incluida, así que esa ventana no es una muestra que el puntaje no haya
visto. En el entrenamiento solo, la forma de pago «no informa» cierra 11,1 %, entre crédito (8,3 %)
y contado (12,3 %): la asignación se sostiene con menos margen. Unos pesos derivados solo del
entrenamiento (regresión logística con las mismas señales) ordenan casi igual (AUC 0,616).

| Temperatura | Cierre en la ventana de prueba | IC 95 % (Wilson) | Cierres / n |
|---|---|---|---|
| Caliente | 18,1 % | 11,9 – 26,5 % | 19 / 105 |
| Tibio | 9,9 % | 6,8 – 14,1 % | 26 / 263 |
| Frío | 6,8 % | 4,1 – 11,0 % | 14 / 207 |

Un Caliente cierra **2,68 veces** más que un Frío, con un intervalo al 95 % (bootstrap) de **1,43 a
5,48**. El criterio de aceptación era 1,8 y queda dentro del intervalo: es un **indicio de
separación, no un criterio demostrado**, con 33 cierres entre los dos grupos. El AUC es 0,579 en
entrenamiento y 0,618 en prueba: **el puntaje ordena, no predice con certeza.**

Con v1 eran 2,16 veces y AUC 0,602 (`docs/EDA.md` conserva v1 porque es lo que citan el PRD y el
TRD). **Esa subida no es una mejora demostrada**: v2 y v3 se diseñaron mirando el histórico
completo, ventana de prueba incluida, así que la prueba ya no es independiente de la elección. Y el
intervalo de v3 (1,43 a 5,48) contiene a 2,16. Lo que se puede afirmar es que, en la misma ventana, v3
no ordena peor que v1 y aplica una regla más coherente; confirmar una mejora exige datos
posteriores al diseño.

### Cuántos cierres más son (`uv run python -m pipeline simulate-policy`)

El AUC dice que el puntaje ordena; esto dice qué significa eso en ventas. Sobre el mismo histórico
se simulan las políticas bajo la misma capacidad diaria y se cuentan los cierres que alcanzan a
entrar en el cupo. Se corre en dos escenarios, porque el supuesto pesa más que la política.

**Sin espera:** el desenlace es propiedad del lead; si no entra en el cupo del día, se pierde.

| Capacidad diaria | Orden de llegada | Al azar | **Priorizado** | Ganancia |
|---|---|---|---|---|
| 50 % de la demanda | 102 | 102,6 | **120** | +18 (17,6 %) |
| 70 % de la demanda | 145 | 145,3 | **156** | +11 (7,6 %) |
| 90 % de la demanda | 185 | 183,5 | **188** | +3 (1,6 %) |
| 100 % de la demanda | 197 | 197,0 | **197** | +0 (0,0 %) |

La columna «al azar» es el control: el promedio de 200 barajadas con semilla fija. Queda pegada a
la del orden de llegada, que es lo que debe pasar si el orden actual no aporta información. **La
ganancia depende de cuán escaso sea el cupo**: con capacidad para todos ninguna política gana.

**Con espera:** lo que no cabe hoy pasa a mañana, y a los 5 días se pierde. Este escenario tiene dos
cuidados que el anterior no necesita:

1. **Es simétrico.** No usa el desenlace de cada lead, que ya trae incorporada la espera que tuvo.
   Cada lead tiene una probabilidad base según su temperatura, calibrada para que con las esperas
   reales reproduzca los cierres observados, y la espera la reduce. Atender rápido a un lead que en
   la realidad no cerró también suma.
2. **El efecto de la espera es observacional.** Quien recibe respuesta en menos de 24 h cierra más
   (un día de espera: 64 % de la tasa; cinco: 41 %), pero quizá porque se contesta antes a los
   mejores leads. Se reporta con tres supuestos: nada de esa diferencia es causada por la espera
   (0 %), la mitad (50 %) o toda (100 %).

Con la capacidad de hoy (70 % de la demanda), en cierres esperados:

| Efecto causal de la espera | Orden de llegada | Más reciente primero | Solo calidad (A) | **Calidad + urgencia** | Ganancia sobre el más reciente |
|---|---|---|---|---|---|
| 0 % | 144,3 | 144,2 | 160,0 | **159,4** | +15,2 (10,6 %) |
| 50 % | 112,6 | 156,5 | 169,9 | **172,5** | +16,1 (10,3 %) |
| 100 % | 75,0 | 171,1 | 181,7 | **188,1** | +17,0 (9,9 %) |

Cómo se lee: la distancia contra el orden de llegada depende casi entera del supuesto causal, así
que no se defiende. Lo que **no depende del supuesto** es la última columna: frente a atender lo más
reciente, la política completa suma **entre 15 y 17 cierres (10–11 %)** en los cinco meses del
histórico. Con efecto causal total, la calidad sola queda por debajo de lo más reciente al 90 % de
capacidad; por eso la urgencia forma parte de la prioridad. La tabla completa, con las cuatro
capacidades, la imprime el comando. La probabilidad base es por temperatura, así que subestima lo
que aporta ordenar dentro de una misma temperatura.

El histórico no trae hora dentro del día: la llegada se aproxima con el `lead_id`, que es
correlativo, y un lead del día se toma a las 12 h de espera. El tablero muestra el indicador que
este análisis vuelve central: **leads contactados en menos de 24 h** (hoy, 47 % en EMP-01).

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

### Entonces, ¿para qué la IA? (`uv run python -m pipeline eval-robustness --con-gemini`)

Las reglas aciertan tanto porque los datos repiten el mismo vocabulario: los 2.610 mensajes de
cliente de las 677 conversaciones salen de **97 frases fijas**, en las que solo cambian el modelo y
las cifras. Las reglas se escribieron mirando esas frases. Un cliente real no escribe así.

Para medirlo, cada frase del cliente en las 40 conversaciones de referencia se reescribió con el
mismo significado y otras palabras («¿Mañana los visito?» → «¿les caigo mañana?»; «Estoy en
centrales» → «estoy reportado en datacrédito»), sin tocar el modelo ni las cifras. Luego se
midieron los dos extractores contra **las mismas etiquetas**:

| Extractor | Frases originales | Frases reformuladas | Caída |
|---|---|---|---|
| Reglas | 99,4 % | **87,2 %** | −12,2 puntos |
| Gemini (dos corridas) | 98,3 % y 98,3 % | **97,5 % y 98,6 %** | menos de 1 punto |

Con las reglas se derrumban justo los campos que dependen de cómo se dice: intención (97,5 % → 70,0 %),
objeción (97,5 % → 72,5 %) y si pidió cita (100 % → 72,5 %). El modelo y la cuota casi no se mueven.
Gemini no usó el respaldo por reglas en ninguna de las corridas.

**La conclusión que se defiende:** con estos datos, las reglas bastan; con conversaciones reales,
que no repiten 97 frases, no. Por eso la extracción la hace el modelo, y las reglas quedan como
respaldo y como línea base.

Límites de esta prueba: **las reformulaciones las propuso la IA y las revisó una persona**
(`evaluation/reformulaciones.json`), así se declara siempre; y es una sola redacción por frase, así
que mide fragilidad, no la exactitud esperada en producción.

---

## Seguridad y aislamiento

- La app usa la **llave anónima** y el JWT del usuario; cada consulta pasa por Row Level Security.
  Un error de filtrado en la interfaz no expondría datos de otra empresa.
- `authenticated` **solo lee**: no hay políticas de `insert`, `update` ni `delete`.
- Las vistas se crean con `security_invoker = true`; sin esa opción una vista ignora RLS.
- Un asesor ve **solo los datos de sus clientes asignados en la última fecha de corte**, también
  consultando la API directamente: leads (incluidos otros canales del mismo cliente), clientes,
  conversaciones, mensajes, extracciones, puntajes y señales. Si mañana un cliente pasa a otro
  asesor, el anterior deja de verlo. El histórico y los problemas de calidad son del gerente, que
  ve toda su empresa y todas las fechas.
- Las conversaciones huérfanas (sin empresa) no son visibles para nadie.
- La llave `service_role` se usa **únicamente** en `scripts/crear_usuarios_demo.py`, nunca en la app.
- `.env` y `.streamlit/secrets.toml` están fuera del repositorio; solo se versionan los `.example`.

`tests/test_aislamiento.py` comprueba todo esto de extremo a extremo contra el Supabase local, con
sesiones reales: 19 pruebas que verifican que un usuario de EMP-01 no ve una sola fila de otra
empresa, en seis tablas y en la vista diaria, y que el asesor AS-001 ve 13 leads (sus 12 asignados
y otro canal de uno de esos clientes) frente a los 494 del gerente, y 0 filas del histórico.

### La misma lista, como API

No hubo que construirla: Supabase publica cada vista por PostgREST, así que `v_mis_leads_hoy` **ya
es una API REST** y responde con las mismas políticas que la app. El JWT decide qué filas salen.

```bash
# 1. Iniciar sesión y quedarse con el token del usuario
TOKEN=$(curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" -H "Content-Type: application/json" \
  -d "{\"email\":\"asesor.as001@example.com\",\"password\":\"$DEMO_PASSWORD\"}" | jq -r .access_token)

# 2. Pedir la lista priorizada del día
curl -s "$SUPABASE_URL/rest/v1/v_mis_leads_hoy?fecha_corte=eq.2026-09-10&order=orden" \
  -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $TOKEN"
```

Con el token de un asesor devuelve sus 12 leads; con el de un gerente, los de toda su empresa. No
hay endpoints de escritura: `authenticated` solo tiene `select`.

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
uv run python -m pipeline eval-robustness --con-gemini   # la misma, con frases reformuladas
uv run python -m pipeline validate-scoring     # valida el puntaje contra el histórico
uv run python -m pipeline simulate-policy      # mide los cierres que captura priorizar
uv run streamlit run app/streamlit_app.py
```

`DATABASE_URL`, `SUPABASE_URL` y `SUPABASE_ANON_KEY` salen de `supabase status`.
Para correr sin llave de Gemini: `EXTRACTOR=reglas` en `.env`, o `--extractor reglas`.

Usuarios de demostración: un gerente por empresa (`gerente.emp01@example.com`,
`gerente.emp02@example.com`, `gerente.emp03@example.com`) y **uno por cada asesor activo**, con el
correo derivado de su id: `AS-001` → `asesor.as001@example.com`. Así la lista diaria se puede
mostrar con cualquier asesor y no solo con uno. La contraseña es la de `DEMO_PASSWORD` y se
comparte fuera del repositorio.

Antes de cada commit: `uv run ruff check .`, `uv run ruff format .` y `uv run pytest -q`
(**360 pruebas**; ninguna llama a servicios externos). Las 31 de `test_aislamiento.py`,
`test_interfaz.py`, `test_version_score.py` y `test_rls_fechas.py` usan el Supabase local y se
omiten solas si no está en ejecución. Las dos últimas trabajan en una transacción que se deshace:
una comprueba que la vista elige `v10` antes que `v2` (la versión se ordena por
`score.version_numero`, no como texto); la otra traspasa un cliente a otro asesor en una fecha de
corte nueva y comprueba, con la sesión de cada uno simulada en la base, quién lo ve. La de interfaz pide los
leads con las mismas funciones de la app y la ejecuta con `AppTest`: inicia sesión como asesor y abre el detalle de
todos sus leads.

### Despliegue

El código es el mismo que en local; solo cambian las variables (TRD 11.3).

| Pieza | Dónde | Cómo |
|---|---|---|
| Base | Supabase remoto, São Paulo | `supabase link` y `supabase db push --include-seed`. Las migraciones se aplican a mano (`--dry-run` antes) |
| Pipeline | [GitHub Actions](.github/workflows/pipeline.yml) | Todos los días a las 06:00 de Bogotá, cuando cambian los insumos de `data/raw/` y a mano (`workflow_dispatch`, con fecha y extractor). Antes de correr, `check-migrations`: si la base no tiene las migraciones del repositorio, se detiene y abre un issue |
| CI | [GitHub Actions](.github/workflows/ci.yml) | En cada push y pull request: `ruff`, `pytest` y `validate-scoring`. En los push, además, `check-migrations` contra la base remota: un cambio de esquema sin `db push` deja el CI en rojo |
| App | Streamlit Community Cloud | `app/streamlit_app.py`, Python 3.12, dependencias de `app/requirements.txt` |

Son dos workflows a propósito: una prueba rota avisa en CI y no impide publicar la lista del día.
CI instala con `uv sync --frozen`, pasa `ruff` y `pytest` y termina con `validate-scoring`, que falla
si un cambio en el histórico o en los pesos rompe el criterio. El pipeline solo corre
`pipeline run` y, si falla, abre un issue con el enlace a la corrida. Con los insumos estáticos de
este ejercicio el cron produce cada día la misma lista: es la idempotencia esperada, no un defecto.
Secretos: `DATABASE_URL`
(por el *session pooler*, puerto 5432: el *transaction pooler* no admite las sentencias preparadas
de psycopg) y `GEMINI_API_KEY`. La app solo recibe `SUPABASE_URL` y `SUPABASE_ANON_KEY`.

`app/requirements.txt` no se edita a mano: se regenera con
`uv export --only-group app --no-hashes --frozen --no-emit-project -o app/requirements.txt`.
Streamlit Cloud busca primero junto al punto de entrada, así que instala solo lo que la app usa.

Primera corrida remota (disparo manual, extractor `gemini`): 677 conversaciones en 68 peticiones,
sin errores ni respaldo, en 13,6 min; 981 leads puntuados, 637 asignados y 344 sin cupo, igual que en
local. La temperatura quedó en 142 Caliente, 60 Tibio y 779 Frío: un lead pasó de Frío a Tibio
respecto de la corrida local, porque `temperature = 0` no hace determinista al modelo (TRD 8.5).
En la URL pública, un asesor de EMP-01 ve sus 12 leads y un gerente de EMP-02 ve los 201 asignados
de su empresa; por la API, ese gerente recibe 0 leads al pedir los de EMP-01, y sin sesión la base
respuesta `permission denied`.

Con el puntaje v3 y el RLS por última fecha de corte (2026-09-17: `supabase db push` y disparo
manual en verde, con la caché de extracción, 0 peticiones): 142 Caliente, 61 Tibio, 219 Frío y 559
Sin calificar; 637 asignados y 344 sin cupo; 4 campos sin respaldo. En remoto el asesor AS-001 ve
los mismos 13 leads y 0 filas del histórico. (Entre local y remoto un lead cambia de temperatura:
`temperature = 0` no hace determinista al modelo.)

---

## Documentación

| Documento | Contenido |
|---|---|
| [docs/arquitectura.md](docs/arquitectura.md) | Diagramas: flujo, componente de IA y aislamiento |
| [docs/PRD.md](docs/PRD.md) | Qué se construye y por qué |
| [docs/TRD.md](docs/TRD.md) | Cómo: modelo de datos, reglas, prompts, puntaje y despliegue |
| [docs/EDA.md](docs/EDA.md) | Evidencia de los datos, generada por script |
| [CLAUDE.md](CLAUDE.md) | Guía del repositorio y decisiones vigentes |

Ninguna cifra de esta documentación se escribió a mano: todas salen de un script versionado, y
`docs/EDA.md` incluye una tabla que compara cada cifra citada con su valor calculado.

---

## Decisiones tomadas

Cada fila dice qué se eligió, qué se descartó y por qué. El detalle está en [docs/TRD.md](docs/TRD.md).

### Datos y base

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| **Supabase (PostgreSQL)**, igual en local (CLI + Docker) y en la nube | SQLite, o Postgres con autenticación y API propias | Trae RLS, autenticación y API REST (PostgREST) sin escribir un backend, y es el mismo motor en los dos entornos |
| **Separación por empresa con RLS**; la app usa la llave anónima y el JWT del usuario | Filtrar por empresa en la interfaz | Un error en la app no puede mostrar datos de otra empresa: la base no los entrega. Por eso el aislamiento se prueba contra la base |
| **Duplicados solo dentro de la empresa**, por teléfono y luego por correo | Deduplicar en todo el grupo | Cada comercializadora solo puede ver a sus clientes; un teléfono compartido entre empresas son dos clientes |
| **Fechas ambiguas `NN/NN` por reglas en orden** (componente > 12, ventana de datos, coherencia con el contacto, y dd/mm por defecto con bandera) | Asumir siempre dd/mm | Resuelve con los datos cuando se puede y deja marcado el caso que no se pudo resolver |
| **Esquema en migraciones versionadas** | Crear las tablas desde el código | `supabase db push` reproduce la misma base en la nube |

### Priorización

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| **Puntaje aditivo con razones** | Modelo entrenado | El histórico predice poco (una regresión logística llega a AUC 0,548) y cada punto se traduce en una razón que el asesor puede leer |
| **Validación con corte temporal** (antes y desde el 15 de junio), **declarada parcial** y con intervalos | Presentar la razón Caliente/Frío como criterio cumplido | Los pesos y estados vieron todo el histórico y la prueba tiene 33 cierres entre Caliente y Frío |
| **Cada estado vale lo que dice el histórico** (v3); sin chat, valor esperado y «Sin calificar» | «Sí» contra todo lo demás (v1), o valor esperado solo sin chat (v2) | Una sola regla para lo sabido y lo desconocido; «no informa» no es lo mismo en cuota (cierra menos) que en forma de pago (cierra como contado) |
| **Urgencia dentro de la prioridad** | Ordenar solo por calidad | Con efecto causal de la espera, la calidad sola pierde contra atender fresco; la suma gana en todos los supuestos |
| **Simulación simétrica y con tres supuestos causales** | Desenlace observado × caída por espera | El desenlace ya trae la espera real, y la caída por espera es observacional: se reporta el rango |
| **Sin los registros «Sin gestión» ni `numero_contactos`** | Usar todo el histórico | Un lead que nadie llamó no dice nada de su calidad, y el número de contactos solo se conoce al final (fuga de información) |
| **El corte es el último registro del día**, no el reloj | Medir la urgencia contra la hora de ejecución | Dos corridas sobre los mismos datos dan la misma lista |
| **Reparto en serpentina**, con tope de capacidad y sin cruzar punto de venta | Repartir siempre en el mismo sentido | Así el primer asesor no se queda con todos los mejores leads del día |

### Componente de IA

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| **Gemini `gemini-3.5-flash-lite`** con salida estructurada y esquema Pydantic | Texto libre, o un modelo de pago | Nivel gratuito pensado para volumen; el esquema obliga a respuestas que se pueden validar |
| **Reglas como respaldo**, detrás de la misma interfaz | Que la corrida falle si el modelo falla | El pipeline programado termina aunque la API no responda, y la corrida declara qué conversaciones resolvió el respaldo |
| **Caché por contenido, extractor y versión del prompt** | Volver a extraer en cada corrida | La segunda corrida no hace peticiones; cambiar el prompt sube la versión e invalida la caché sin borrarla |
| **Etiquetas de referencia propuestas por la IA y revisadas por una persona** | Etiquetar a mano las 40 conversaciones | Cabía en el tiempo del ejercicio; se declara siempre así, nunca como etiquetado manual |
| **Frase de apertura con plantilla** | Generarla con el modelo | No gasta cuota, siempre sale igual y no puede inventar datos |
| **Comprobar la evidencia del modelo** contra la conversación, y tomar como desconocido lo que no tiene cita | Mostrarla tal como llega, o solo ocultarla | Un campo sin respaldo no cuenta como dicho: puntúa como su estado desconocido (una forma de pago «crédito» sin cita vuelve a «no informa» y suma +1, como en el histórico). Se toleran el encabezado «asesor [hora]:» y las erratas de copia (parecido ≥ 0,9), no las paráfrasis: la app la muestra como cita textual, y juzgar si otras palabras dicen lo mismo es el juicio del modelo que se quiere comprobar. «No respondió» puede citar al asesor |

### Automatización y publicación

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| **Un solo comando** (`pipeline run`) y **GitHub Actions** con cron, disparo por insumos nuevos y manual | Un orquestador aparte (Airflow, un servidor) | Es gratis, vive junto al código y corre el mismo comando que en local |
| **CI separado del pipeline productivo** | Pruebas dentro del mismo job | Una prueba rota no deja a los asesores sin lista |
| **Streamlit Community Cloud** | Un frontend aparte (React en Vercel) | Todo en Python y publicación directa desde el repositorio |
| **uv con `uv.lock`**; `app/requirements.txt` exportado desde el lock | `pip` con `requirements.txt` editado a mano | El entorno es el mismo en local, en CI y en la nube |

---

## Límites conocidos

- **559 de los 981 leads priorizados no tienen conversación de WhatsApp** y salen «Sin calificar».
  Suman el valor esperado del histórico, que los ordena bien frente a los demás, pero entre ellos
  solo los distinguen el precio del modelo y la urgencia.
- **La validación del puntaje es parcial y la muestra es chica**: el intervalo de la razón
  Caliente/Frío (1,01 a 4,36) incluye el criterio de 1,8.
- **La simulación de impacto depende de supuestos**: qué pasa con lo que no se atiende y cuánto
  de la caída por espera es causal. Por eso se reporta con y sin espera y con tres supuestos
  causales; la cifra que se defiende es la que no depende de ellos (+15 a +17 cierres frente a
  atender lo más reciente).
- **La exactitud de la extracción se mide sobre 40 conversaciones**: un error mueve un campo 2,5
  puntos, y cada campo se reporta con su intervalo de Wilson (por ejemplo, 97,5 % → 87 a 100 %).
  Ampliarla a unas 100, estratificadas y etiquetadas a ciegas, exige tiempo de una persona.
- El **ajuste por conversación no tiene validación histórica**. Por eso pesa poco y la app lo marca
  como heurístico.
- La extracción con IA **no es reproducible al 100 %** entre corridas, aunque la caché hace que una
  misma conversación no se reevalúe.
- `numero_contactos` no se usa como predictor: solo se conoce al final y sería fuga de información.
- La deduplicación es **solo dentro de cada empresa**: un teléfono compartido entre dos empresas
  genera dos clientes independientes, por diseño.
- El histórico se analiza sin los 179 registros "Sin gestión": nunca fueron contactados, así que su
  desenlace no habla de la calidad del lead.

---

## Supuestos asumidos

Ninguno de estos supuestos venía dado: se tomaron para poder avanzar y cada uno cambiaría el
resultado si fuera falso.

1. **Los archivos de `data/raw/` son la única fuente y no se corrigen.** Las inconsistencias se
   resuelven en la normalización y quedan registradas en `problema_calidad`; el archivo original
   nunca se toca.
2. **La fecha de corte es un parámetro, no el reloj.** La demostración corre con `2026-09-10`, el
   último día con registros. Medir la urgencia contra la hora real haría que la misma corrida diera
   resultados distintos y rompería la idempotencia.
3. **Un lead deja de ser gestionable si está `Descartado` o si superó la ventana de 30 días.** Por
   eso la lista diaria tiene 981 leads y no 1.500.
4. **La capacidad diaria del asesor es un tope duro.** Lo que no cabe queda `sin_cupo` y el gerente
   decide; el sistema no sobrecarga a nadie por su cuenta.
5. **Dos empresas con el mismo teléfono son dos clientes distintos.** Comparten el CRM pero no los
   clientes, así que deduplicar entre empresas filtraría datos de una a otra.
6. **Una conversación sin lead asociado no tiene dueño** y no se muestra a nadie.
7. **El histórico es comparable con los leads de hoy**: mismos canales, mismo negocio y misma
   estacionalidad. Si el negocio cambia, los pesos del componente A hay que recalcularlos.
8. **Las etiquetas del conjunto de referencia las propuso la IA y las revisó una persona.** Nunca se
   presentan como etiquetado manual, y por eso la cifra de `reglas` parte con ventaja.
9. **`estado_gestion` es confiable aunque falte la fecha de contacto.** Los 76 leads con estado
   avanzado y sin fecha puntúan por su estado: el contacto ocurrió y lo que falta es el dato.

---

## Qué haría con más tiempo

En orden de lo que más movería la aguja:

1. **Cerrar el ciclo con el asesor.** Hoy el sistema ordena pero no aprende: no hay forma de saber
   si el lead que puso primero sirvió. Un botón de «contactado / no sirvió / cerrado» convertiría
   cada día de uso en datos de entrenamiento, y en unos meses el puntaje aditivo podría
   reemplazarse por un modelo con un AUC que valga la pena.
2. **Validar el componente B.** El ajuste por conversación pesa poco justamente porque nadie lo ha
   medido. Con desenlaces propios se sabría si la intención declarada predice algo.
3. **Reasignar desde el tablero.** El gerente ve los prioritarios sin cupo pero tiene que resolverlo
   por fuera; darle el botón cierra el flujo sin salir de la herramienta.
4. **Ampliar el conjunto de referencia** a unas 100 conversaciones etiquetadas a ciegas.
5. **Podar la caché de extracción.** Se conservan las cuatro versiones de prompt de cada
   conversación; conviene archivar las que ya no son vigentes.
6. **Reconstruir la ciudad y el punto de venta faltantes** con el histórico del cliente, en vez de
   dejarlos nulos.
