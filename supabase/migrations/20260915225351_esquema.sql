-- Esquema del Priorizador Diario de Leads (TRD 5).
-- Marcas de tiempo en timestamptz; los datos de origen se interpretan en America/Bogota.

-- ---------------------------------------------------------------------------
-- 5.1 Tablas de referencia
-- ---------------------------------------------------------------------------
create table public.empresa (
  empresa_id text primary key,                 -- EMP-01
  nombre     text not null,
  region     text                              -- Antioquia | Costa Atlántica | Bogotá
);

create table public.punto_venta (
  punto_venta_id text primary key,             -- PV-001
  empresa_id     text not null references public.empresa,
  ciudad         text                          -- inferida: ciudad más frecuente de sus leads
);
create index punto_venta_empresa_idx on public.punto_venta (empresa_id);

create table public.asesor (
  asesor_id        text primary key,
  empresa_id       text not null references public.empresa,
  punto_venta_id   text not null references public.punto_venta,
  nombre           text not null,
  capacidad_diaria int  not null check (capacidad_diaria > 0),  -- capacidad_diaria_leads en asesores.csv
  activo           boolean not null,
  fecha_ingreso    date
);
create index asesor_empresa_idx on public.asesor (empresa_id);
create index asesor_punto_venta_idx on public.asesor (punto_venta_id);

create table public.modelo (
  sku                  text primary key,
  marca                text   not null,
  linea                text   not null,
  nombre_completo      text generated always as (marca || ' ' || linea) stored,
  cilindraje           int,
  segmento             text,
  precio_lista         bigint not null,
  unidades_disponibles int
);

create table public.modelo_punto_venta (
  sku            text references public.modelo,
  punto_venta_id text references public.punto_venta,
  primary key (sku, punto_venta_id)
);
create index modelo_punto_venta_pv_idx on public.modelo_punto_venta (punto_venta_id);

-- ---------------------------------------------------------------------------
-- 5.2 Tablas de negocio
-- ---------------------------------------------------------------------------
create table public.cliente (
  cliente_id  uuid primary key default gen_random_uuid(),
  empresa_id  text not null references public.empresa,
  clave_dedup text not null,                   -- 'tel:3001234567' o 'email:x@y.co' (TRD 7)
  telefono    text,                            -- 10 dígitos; null si es inválido
  email       text,
  nombre      text not null,                   -- el nombre más completo del grupo
  ciudad      text,
  unique (empresa_id, clave_dedup)             -- deduplicación solo dentro de la empresa
);

create table public.lead (
  lead_id                  text primary key,
  empresa_id               text not null references public.empresa,
  punto_venta_id           text not null references public.punto_venta,
  cliente_id               uuid not null references public.cliente,
  canal                    text not null check (canal in ('WhatsApp', 'Meta Ads', 'Formulario Web')),
  campania                 text,
  fecha_registro           timestamptz,
  fecha_registro_precision text check (fecha_registro_precision in ('minuto', 'dia')),
  fecha_primer_contacto    timestamptz,
  fecha_contacto_precision text check (fecha_contacto_precision in ('minuto', 'dia')),
  estado_gestion           text not null check (estado_gestion in (
                             'Sin gestión', 'No contesta', 'Contactado',
                             'En proceso', 'Cotización enviada', 'Descartado')),
  modelo_texto_original    text,
  sku_interes              text references public.modelo,
  marca_interes            text,
  match_modelo_score       numeric,
  modelo_disponible_pv     boolean,            -- el SKU está en el punto de venta del lead; informativo
  es_principal             boolean not null default true,
  flags_calidad            text[]  not null default '{}',
  actualizado_en           timestamptz default now()
);
create index lead_empresa_idx on public.lead (empresa_id);
create index lead_punto_venta_idx on public.lead (punto_venta_id);
create index lead_cliente_idx on public.lead (cliente_id);
create index lead_sku_idx on public.lead (sku_interes);

create table public.conversacion (
  conversacion_id text primary key,
  lead_id_origen  text not null,               -- tal como viene en el JSON
  lead_id         text references public.lead, -- null si es huérfana
  empresa_id      text references public.empresa, -- null si es huérfana: nadie la ve desde la app
  fecha_inicio    timestamptz,
  hash_contenido  text not null,               -- sha256 de los mensajes
  es_huerfana     boolean not null
);
create index conversacion_lead_idx on public.conversacion (lead_id);
create index conversacion_empresa_idx on public.conversacion (empresa_id);

create table public.mensaje (
  conversacion_id text references public.conversacion on delete cascade,
  orden           int,
  emisor          text check (emisor in ('cliente', 'asesor')),
  hora            time,
  texto           text,
  primary key (conversacion_id, orden)
);

-- ---------------------------------------------------------------------------
-- 5.3 Tablas de resultados
-- ---------------------------------------------------------------------------
create table public.extraccion (
  extraccion_id     bigserial primary key,
  conversacion_id   text not null references public.conversacion,
  empresa_id        text references public.empresa,
  hash_contenido    text not null,
  extractor         text not null check (extractor in ('gemini', 'reglas')),
  modelo_llm        text,
  prompt_version    text not null,
  modelo_texto      text,
  sku_interes       text references public.modelo,
  cuota_inicial_cop bigint,
  menciona_cuota    text check (menciona_cuota in ('SI', 'NO', 'NO_INFORMA')),
  forma_pago        text check (forma_pago in ('contado', 'credito', 'no_informa')),
  intencion         text check (intencion in ('alta', 'media', 'baja')),
  objecion          text,                      -- enumeración de TRD 8.1
  pidio_cita        boolean,
  pidio_cotizacion  boolean,
  cliente_respondio boolean,
  evidencia         jsonb,                     -- fragmentos que justifican cada campo
  creado_en         timestamptz default now(),
  unique (hash_contenido, extractor, prompt_version)   -- clave de caché
);
create index extraccion_conversacion_idx on public.extraccion (conversacion_id);
create index extraccion_empresa_idx on public.extraccion (empresa_id);
create index extraccion_sku_idx on public.extraccion (sku_interes);

create table public.score (
  lead_id             text references public.lead,
  fecha_corte         date,
  version_score       text,
  empresa_id          text not null references public.empresa,
  puntos_calidad      int,
  puntos_conversacion int,
  puntos_urgencia     int,
  prioridad           int,
  temperatura         text check (temperatura in ('Caliente', 'Tibio', 'Frío')),
  razones             jsonb,                   -- [{"factor": "pidió cita", "puntos": 3}, ...]
  primary key (lead_id, fecha_corte, version_score)
);
create index score_empresa_idx on public.score (empresa_id);

create table public.asignacion (
  fecha_corte date,
  lead_id     text references public.lead,
  empresa_id  text not null references public.empresa,
  asesor_id   text references public.asesor,   -- null si quedó sin cupo
  orden       int,
  estado      text check (estado in ('asignado', 'sin_cupo')),
  prioritario boolean not null default false,  -- Caliente o sin contacto con < 24 h (TRD 10)
  primary key (fecha_corte, lead_id)
);
create index asignacion_empresa_idx on public.asignacion (empresa_id);
create index asignacion_asesor_idx on public.asignacion (asesor_id);
create index asignacion_lead_idx on public.asignacion (lead_id);

create table public.historico_cierre (
  lead_id                  text primary key,
  fecha_registro           date not null,
  canal                    text not null,
  empresa_id               text not null references public.empresa,
  punto_venta_id           text not null references public.punto_venta,
  modelo_cotizado          text,
  precio_lista             bigint,
  horas_al_primer_contacto numeric,            -- null en "Sin gestión"
  numero_contactos         int,                -- no se usa como predictor (fuga)
  manifesto_cuota_inicial  text check (manifesto_cuota_inicial in ('SI', 'NO', 'NO_INFORMA')),
  forma_pago_declarada     text check (forma_pago_declarada in ('contado', 'credito', 'no_informa')),
  pidio_cita               boolean,
  desenlace                text not null check (desenlace in ('Cerrado', 'Perdido', 'Sin gestión'))
);
create index historico_empresa_idx on public.historico_cierre (empresa_id);
create index historico_punto_venta_idx on public.historico_cierre (punto_venta_id);

-- ---------------------------------------------------------------------------
-- 5.4 Operación y seguridad
-- ---------------------------------------------------------------------------
create table public.ejecucion (
  ejecucion_id  bigserial primary key,
  iniciado_en   timestamptz not null default now(),
  finalizado_en timestamptz,
  estado        text not null check (estado in ('en_curso', 'ok', 'error', 'ok_con_respaldo')),
  fecha_corte   date,
  disparador    text check (disparador in ('schedule', 'manual')),
  conteos       jsonb,                         -- filas por etapa
  llamadas_llm  int,
  errores_llm   int,
  detalle_error text
);

create table public.problema_calidad (
  id             bigserial primary key,
  ejecucion_id   bigint references public.ejecucion on delete cascade,
  empresa_id     text references public.empresa, -- null si no se puede atribuir (p. ej. huérfanas)
  archivo        text,
  registro_id    text,
  campo          text,
  tipo           text not null,                -- formato_fecha_ambiguo, telefono_invalido, ...
  valor_original text,
  accion         text
);
create index problema_calidad_ejecucion_idx on public.problema_calidad (ejecucion_id);
create index problema_calidad_empresa_idx on public.problema_calidad (empresa_id);

create table public.usuario_empresa (
  user_id    uuid primary key references auth.users on delete cascade,
  empresa_id text not null references public.empresa,
  rol        text not null check (rol in ('gerente', 'asesor')),
  asesor_id  text references public.asesor,
  check (rol <> 'asesor' or asesor_id is not null)   -- el asesor_id es obligatorio para el rol asesor
);
create index usuario_empresa_empresa_idx on public.usuario_empresa (empresa_id);
create index usuario_empresa_asesor_idx on public.usuario_empresa (asesor_id);
