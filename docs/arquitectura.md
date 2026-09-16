# Arquitectura — Priorizador Diario de Leads

Diagramas en Mermaid: GitHub los renderiza sin instalar nada. Cada bloque corresponde a un módulo
real del repositorio, y el nombre entre paréntesis es el archivo que lo implementa.

## 1. Flujo de punta a punta

Un solo comando —`uv run python -m pipeline run`— recorre todo el camino de izquierda a derecha.

```mermaid
flowchart LR
  subgraph FUENTES["data/raw (solo lectura)"]
    L[leads.csv]
    C[conversaciones.json]
    K[catalogo_motos.csv]
    A[asesores.csv]
    H[historico_cierres.csv]
  end

  subgraph PIPE["pipeline/ · una corrida idempotente"]
    IN[ingesta<br/>ingest.py]
    NO[normalización<br/>normalize.py]
    CA[catálogo<br/>catalog_match.py]
    DE[deduplicación<br/>dedup.py]
    EX[extracción con IA<br/>extract/]
    SC[puntaje<br/>scoring.py]
    AS[asignación<br/>assign.py]
  end

  subgraph BD["Supabase · PostgreSQL"]
    T1[(cliente · lead<br/>conversacion · mensaje)]
    T2[(extraccion<br/>senales_lead)]
    T3[(score · asignacion)]
    T4[(ejecucion<br/>problema_calidad)]
    V{{vistas security_invoker<br/>v_mis_leads_hoy · v_tablero_gerente}}
  end

  APP[app web<br/>app/streamlit_app.py]

  L & K & A & H --> IN --> NO --> CA --> DE --> T1
  C --> IN
  DE --> EX --> T2
  EX --> SC --> AS --> T3
  PIPE -.registra cada corrida.-> T4
  T1 & T2 & T3 --> V --> APP
```

**Por qué en este orden.** La extracción va después de la carga porque `extraccion` referencia
`conversacion` por llave foránea. El puntaje va después de la extracción porque consume las señales
consolidadas por lead, y la asignación va después del puntaje porque reparte una lista ya ordenada.

## 2. El componente de IA, en detalle

```mermaid
flowchart TD
  CV[677 conversaciones] --> HS["hash del contenido<br/>(hash_mensajes)"]
  HS --> Q{"¿está en la caché<br/>(hash, extractor, prompt_version)?"}
  Q -->|sí| RE[se reusa: 0 peticiones]
  Q -->|no| GE["ExtractorGemini<br/>lotes de 10 · salida estructurada · temperatura 0"]
  GE -->|responde| VA
  GE -->|falla tras reintentos| RG["ExtractorReglas (respaldo)<br/>regex, sin red"]
  RG --> VA
  RE --> VA["validar() contra el catálogo<br/>extract/schema.py"]
  VA --> GU[("extraccion<br/>guarda la salida cruda")]
  VA --> CO["consolidar por lead<br/>extract/consolidar.py"]
  CO --> SE[("senales_lead<br/>+ extractor y prompt_version")]
```

**Dos decisiones que se leen aquí.** La validación corre *siempre*, también sobre lo que viene de la
caché, para que los problemas de calidad no dependan de si la conversación se reevaluó. Y
`senales_lead` guarda su procedencia porque `extraccion` conserva todas las versiones cacheadas:
sin ese dato no se puede recuperar la evidencia que corresponde al puntaje que el asesor tiene
delante.

## 3. Aislamiento por empresa

El requisito «la información de una comercializadora no puede quedar visible para otra» se cumple
en la base, no en la interfaz.

```mermaid
flowchart LR
  U1[gerente EMP-01] --> APP
  U2[asesor AS-001] --> APP
  APP["Streamlit<br/>llave anónima + JWT del usuario"] --> PR[PostgREST]
  PR --> RLS{{"Row Level Security<br/>usuario_empresa → empresa_id"}}
  RLS --> D1[(filas de EMP-01)]
  RLS -. nunca .-x D2[(filas de EMP-02 y EMP-03)]
  PIPE["pipeline (rol de servidor)"] ==> DB[(escritura directa<br/>no pasa por RLS)]
```

| Quién | Con qué llave | Qué puede hacer |
|---|---|---|
| App web | anónima + JWT del usuario | Solo `select`, y solo de su empresa |
| Asesor | la suya | Únicamente las filas de `asignacion` con su `asesor_id` |
| Gerente | la suya | Toda su empresa |
| Pipeline | cadena de Postgres (servidor) | Escribe; RLS no le aplica |
| `crear_usuarios_demo.py` | `service_role` | Único lugar del repositorio que la usa |

Las vistas se crean con `security_invoker = true`: sin esa opción una vista corre con los permisos
de quien la creó y se saltaría las políticas.

## 4. Componentes y responsabilidades

| Componente | Archivo | Responsabilidad |
|---|---|---|
| Ingesta | `pipeline/ingest.py` | Leer los cinco insumos como texto, sin interpretar |
| Normalización | `pipeline/normalize.py` | Teléfono, fecha ambigua, ciudad, estado y canal |
| Catálogo | `pipeline/catalog_match.py` | Resolver el modelo en texto libre contra los 24 SKU |
| Deduplicación | `pipeline/dedup.py` | Una persona por empresa, aunque escriba por dos canales |
| Extracción | `pipeline/extract/` | Dos implementaciones tras una interfaz, con caché y respaldo |
| Puntaje | `pipeline/scoring.py` | Calidad + conversación + urgencia, con sus razones |
| Asignación | `pipeline/assign.py` | Serpentina por punto de venta, respetando la capacidad |
| Persistencia | `pipeline/load.py`, `pipeline/db.py` | Upserts por clave natural, idempotentes |
| Interfaz | `app/streamlit_app.py` | Lista del asesor, tablero del gerente y método |
| Evaluación | `evaluation/` | Extracción contra el conjunto revisado; puntaje contra el histórico |
