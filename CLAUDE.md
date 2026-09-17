# CLAUDE.md — Priorizador Diario de Leads

Guía del repositorio para el asistente de desarrollo. Máximo 150 líneas.

## Propósito
Convertir los leads crudos de tres comercializadoras de motos (WhatsApp, Meta Ads y formulario web) en una
**lista priorizada de gestión diaria por asesor**. Cada lead se enriquece con lo que el cliente dijo en
WhatsApp (extracción con IA) e incluye las razones de su posición. Cada empresa ve solo sus datos (RLS).

- Qué y por qué: [docs/PRD.md](docs/PRD.md)
- Cómo: [docs/TRD.md](docs/TRD.md)
- Evidencia de los datos: [docs/EDA.md](docs/EDA.md), generado con `uv run python -m eda`
- Prioridad si hay contradicciones: enunciado (`docs/enunciado.pdf`) > PRD > TRD. Ante una ambigüedad que
  cambie el diseño, **preguntar antes de decidir**.

## Comandos frecuentes (TRD 11.2)
```bash
uv sync --all-groups                 # entorno bloqueado por uv.lock
supabase start                       # Postgres, Auth y Studio en Docker
supabase db reset                    # aplica migraciones y seed.sql
uv run python -m eda                 # regenera docs/EDA.md y docs/img/eda/
uv run python -m pipeline run --fecha-corte 2026-09-10
uv run python scripts/crear_usuarios_demo.py   # después del pipeline (el asesor demo debe existir)
uv run python -m pipeline eval          # y eval-robustness, validate-scoring, simulate-policy
uv run streamlit run app/streamlit_app.py
```
Antes de cada commit: `uv run ruff check .`, `uv run ruff format .` y `uv run pytest -q`.

## Estructura (TRD 3)
```
supabase/          config.toml, migrations/ (esquema, rls, vistas), seed.sql
data/raw/          insumos sintéticos entregados (SOLO LECTURA)
eda/               análisis exploratorio reproducible -> docs/EDA.md
pipeline/          config, db, quality, ingest, normalize, catalog_match, dedup,
                   extract/ (schema, base, rules, gemini, consolidar, etapa, prompts/),
                   scoring, assign
scripts/           crear_usuarios_demo.py (único uso de service_role)
evaluation/        muestra_gold.py, gold_40_muestra.json, gold_40_borrador.json, gold_40.json,
                   eval_extraction.py, validate_scoring.py
app/               streamlit_app.py
tests/             pytest, sin red
docs/              enunciado.pdf, PRD.md, TRD.md, EDA.md, img/
```

## Reglas obligatorias

### Versionamiento (TRD 15.1)
- Commits pequeños y frecuentes, uno por unidad lógica. Nunca una fase entera en un commit.
- Conventional Commits: tipo en inglés, descripción en español e imperativo.
  Ejemplo: `feat(normalize): resolver fechas ambiguas dd/mm y mm/dd`.
- **Sin coautoría ni atribución**: nada de `Co-Authored-By`, `Generated with ...` ni `Claude-Session`.
  El único autor es el usuario de git. Capas: `.claude/settings.json`, esta regla y `.githooks/commit-msg`
  (activar con `git config core.hooksPath .githooks`).
- Nunca `--no-verify`. Sin `push`, remotos ni reescritura de historial sin autorización explícita.
- Verificación: `git log --format=%B | grep -iE "co-authored|claude-session|generated with"` debe estar vacío.

### Entorno y código
- Python 3.12 con uv: `uv add` / `uv add --group <dev|eda|app>` y ejecutar siempre con `uv run`.
  Nada de `pip install` ni `requirements.txt`.
- pandas 3.x: leer los insumos con `dtype="str"` (vacíos = NaN) y asumir copy-on-write.
- Base de datos con Supabase CLI: `supabase migration new <nombre>` y `supabase db reset`.
  Si Docker o la CLI no están disponibles, detenerse y avisar.
- Nombres de dominio, docstrings y comentarios en español. Type hints en funciones públicas.
- Código claro, corto y comentado: el responsable debe poder defender cada línea.

### Seguridad
- Nunca versionar `.env`, `.streamlit/secrets.toml`, llaves (incluidas las locales de Supabase),
  `supabase/.temp` ni `supabase/.branches`.
- `service_role` solo en `scripts/crear_usuarios_demo.py`; la app usa la llave anon + JWT del usuario.
- Todas las vistas se crean con `with (security_invoker = true)`.
- Las pruebas no llaman servicios externos: el cliente de Gemini se simula.
- **No inventar cifras**: todo número de la documentación sale de un script versionado.

## Decisiones de dominio que no deben romperse
- **Deduplicación solo dentro de la misma empresa**: clave `(empresa_id, telefono_normalizado)`, secundaria
  `(empresa_id, email)`. Teléfonos compartidos entre empresas generan clientes independientes.
- **Fechas ambiguas `NN/NN/YYYY HH:MM`** (TRD 6.1): 1) componente > 12 decide; 2) descartar lecturas fuera
  del 1-ago al 30-sep-2026; 3) coherencia registro <= primer contacto; 4) empate -> dd/mm y se registra
  `fecha_ambigua_resuelta_por_defecto`.
- **Histórico**: se analiza sin los registros "Sin gestión"; `numero_contactos` no se usa como predictor
  (fuga de información).
- **Pesos y prompt versionados**: cualquier cambio sube `version_score` o `prompt_version` y se anota en el README.
- **Conjunto de referencia**: la IA propone `gold_40_borrador.json` (`"revisado": false`); una persona lo revisa.
  La evaluación solo usa registros revisados y nunca se presenta como etiquetado manual.
- `data/raw/` no se modifica nunca.

## Estado actual
- **Fase A cerrada**: repositorio con uv, Supabase CLI y hook de atribución; EDA determinista en
  `docs/EDA.md`; PRD 1.2 y TRD 1.2 corregidos según el EDA.
- Decisiones de la Fase A: tasa sin cuota contra el resto (8,3 %); sin contacto en 24 h con el
  método medianoche; grupos duplicados contados tras quitar los `lead_id` repetidos;
  `modelo_disponible_pv` informativo; `bogota` y `bogota d.c.` → Bogotá D.C.;
  `capacidad_diaria_leads` → `capacidad_diaria`; pandas 3.x; llaves heredadas de Supabase;
  `docs/PROMPT.md` fuera del repositorio; ruff no formatea los documentos.
- **Fase B cerrada**: migraciones (esquema, RLS con privilegios explícitos, vistas
  `security_invoker`), `seed.sql` con las empresas, pipeline `run` idempotente
  (ingest → normalize → catalog_match → dedup → load) y `crear_usuarios_demo.py`.
- Decisiones de la Fase B: `cliente.clave_dedup`; `problema_calidad` guarda solo la última corrida;
  `lead.flags_calidad` solo banderas (`quality.BANDERAS`); `prioritario` en `asignacion`;
  esta versión de Supabase no concede privilegios por defecto (se conceden en la migración de RLS);
  el EDA reutiliza `pipeline/normalize.py`; herramientas: Supabase CLI 2.117, uv 0.9.24,
  Docker 28.4, Python 3.12.
- **Fase C cerrada**: extracción con dos implementaciones tras una misma interfaz: `rules` (regex,
  sin red) y `gemini` (lotes, salida estructurada, reintentos y respaldo por reglas). Corrida real:
  677 conversaciones en 68 peticiones y 8,4 min, sin errores ni respaldo; la segunda reusa la caché
  (0 peticiones, 3 s).
- Decisiones de la Fase C:
  - La plata declarada de contado se registra en `cuota_inicial_cop`; "la inicial está muy alta" es
    objeción de `precio`. Cuota sobre el precio de lista: hasta 5 % se recorta, por encima se descarta.
  - `extraccion` guarda la salida cruda y la validación corre siempre, para que los problemas de
    calidad no dependan de la caché, que va por `(hash_contenido, extractor, prompt_version)`.
  - Modelo **`gemini-3.5-flash-lite`** (`GEMINI_MODEL`): nivel gratuito y pensado para volumen.
    `gemini-3.8-flash` responde 429 y `gemini-2.5-flash` responde 404: no sirven por defecto.
  - Prompt `v4`: hablar de cuota inicial es crédito y `precio` pesa más que `comparando`.
  - **`temperature = 0` no hace determinista al modelo**: dos corridas de las 40 dieron 98,6 % y
    99,2 %, así que comparar prompts con una sola corrida no concluye nada (TRD 8.5).
  - El conjunto de referencia lo propuso la IA y lo revisó una persona; se declara así siempre. La
    columna de `reglas` parte con ventaja, así que la cifra que vale es la de `gemini`.
  - Si una petición falla entera no se reintenta una por una: solo se piden por separado las
    conversaciones que el modelo omitió en una respuesta que sí llegó.
- **Fase D terminada, en punto de control D**:
  - `scoring.py` (puntaje v1, temperatura y razones) y `assign.py` (serpentina con capacidad).
  - Corrida 2026-09-10: 981 elegibles, 637 asignados y 344 sin cupo (capacidad activa 694);
    780 Frío, 142 Caliente y 59 Tibio. Huellas iguales entre corridas: es idempotente.
  - `pipeline validate-scoring` reproduce el TRD 9.3: Caliente/Frío 2,16 veces (criterio 1,8).
- Decisiones de la Fase D:
  - Un lead con estado avanzado y sin fecha de contacto puntúa por su estado, no por la espera: el
    contacto ocurrió y lo que falta es el dato (ya lleva `estado_sin_fecha_contacto`).
  - `momento_corte` es el último registro del día de corte, no el reloj: conserva la idempotencia.
  - La serpentina ordena los asesores por `asesor_id` para que el reparto sea reproducible.
  - Los pesos viven solo en `pipeline/scoring.py`; el EDA y la validación los importan, así que
    regenerar el EDA tras el refactor dio un archivo idéntico.
  - 565 de los 981 elegibles no tienen conversación: su techo son 2 puntos y quedan en Frío. Es la
    limitación declarada en TRD 9.2, no un defecto.
- **Fase E terminada, en punto de control E**:
  - `senales_lead` guarda las señales y su procedencia (`extractor`, `prompt_version`); la vista
    diaria las expone. Migraciones con `supabase migration up --local` para no perder la caché.
  - `app/streamlit_app.py`: lista del asesor, tablero y «Cómo prioriza». Probada con Playwright:
    4 defectos corregidos (evidencia mezclada, `orden` flotante, `#` a unos, cabeceras crudas).
- Decisiones de la Fase E:
  - El aislamiento se prueba en la base, no en la interfaz: la app usa la llave anónima y el JWT.
  - La consolidación no se reescribe en SQL: una sola implementación, la de `consolidar.py`.
  - `orden` es por asesor: en la vista de empresa se muestra el asesor y se ordena por prioridad.
  - La contraseña de demostración no se teclea en el navegador.
- **Revisión contra el enunciado**: `docs/arquitectura.md`, README con supuestos y API, 40 asesores
  y 3 gerentes, frase de apertura sin LLM, `simulate-policy` (70 %: +9 cierres, +6,2 %). 298 pruebas.
- `eval-robustness`: 97 frases fijas; reformuladas, reglas 99,4 → 87,2 %, Gemini 97,5–98,6 %. Falta revisión humana.
- **Fase F**: repo público, Supabase remoto (sa-east-1, session pooler 5432), workflow verde a mano y
  https://priorizador-leads.streamlit.app con aislamiento verificado. Credenciales en `.env.remoto`
  (ignorado). `setup-uv` sin etiqueta mayor: versión exacta. Falta: cron verde y presentación.
