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
uv run python -m pipeline eval
uv run streamlit run app/streamlit_app.py
```
Antes de cada commit: `uv run ruff check .`, `uv run ruff format .` y `uv run pytest -q`.

## Estructura (TRD 3)
```
supabase/          config.toml, migrations/ (esquema, rls, vistas), seed.sql
data/raw/          insumos sintéticos entregados (SOLO LECTURA)
eda/               análisis exploratorio reproducible -> docs/EDA.md
pipeline/          config, db, quality, ingest, normalize, catalog_match, dedup,
                   extract/ (schema, base, rules, gemini, prompts/), scoring, assign
scripts/           crear_usuarios_demo.py (único uso de service_role)
evaluation/        gold_40_borrador.json, gold_40.json, eval_extraction.py, validate_scoring.py
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
- **Fase A cerrada**:
  - Repositorio inicializado con uv, Supabase CLI y el hook de atribución.
  - EDA generado en `docs/EDA.md`; es determinista.
  - PRD 1.2 y TRD 1.2 corregidos según el EDA y aprobados por el responsable.
- **Decisiones aprobadas en el punto de control A**:
  - Tasa sin cuota calculada contra el resto (8,3 %).
  - Sin contacto en 24 h con el método medianoche.
  - Grupos duplicados contados después de quitar las filas con `lead_id` repetido.
  - `modelo_disponible_pv` informativo en la app.
  - `bogota` y `bogota d.c.` → Bogotá D.C.
  - `capacidad_diaria_leads` → `capacidad_diaria`.
- Decisiones tomadas en la Fase A:
  - pandas 3.x.
  - Llaves heredadas de Supabase (anon y service_role).
  - `docs/PROMPT.md` fuera del repositorio.
  - ruff no formatea los documentos.
- Fase B: no iniciada.
