-- Orden numérico de las versiones de puntaje.
--
-- `v_mis_leads_hoy` elegía la versión más reciente con `order by version_score desc`, que compara
-- texto: sirve para v1 y v2, pero con una v10 elegiría v2, porque 'v2' > 'v10'. El nombre `vN` se
-- conserva (es parte de la clave y de lo que se muestra) y la base deriva de él un número:
--   * el `check` garantiza el formato, así que el número siempre se puede calcular;
--   * `version_numero` es una columna generada: nadie la escribe y no puede desalinearse del texto.
-- La columna se calcula antes de evaluar el check: sin el `case`, una versión mal escrita fallaría
-- con un error de conversión a entero en vez de nombrar la regla que incumple.

alter table public.score
  add constraint score_version_score_formato check (version_score ~ '^v[1-9][0-9]*$');

alter table public.score
  add column version_numero int generated always as (
    case when version_score ~ '^v[1-9][0-9]*$' then substring(version_score from 2)::int end
  ) stored;

comment on column public.score.version_numero is
  'Número de la versión de puntaje (v10 → 10). Es lo que se ordena; el texto no ordena bien.';

-- ---------------------------------------------------------------------------
-- v_mis_leads_hoy: misma vista, ordenando la versión por número.
-- ---------------------------------------------------------------------------
create or replace view public.v_mis_leads_hoy
with (security_invoker = true) as
select
  a.fecha_corte,
  a.empresa_id,
  l.punto_venta_id,
  a.asesor_id,
  a.orden,
  a.estado,
  a.prioritario,
  l.lead_id,
  l.cliente_id,
  c.nombre,
  c.telefono,
  l.canal,
  l.modelo_texto_original,
  l.sku_interes,
  m.nombre_completo as modelo,
  l.marca_interes,
  l.modelo_disponible_pv,
  l.estado_gestion,
  l.fecha_registro,
  l.fecha_primer_contacto,
  l.flags_calidad,
  s.version_score,
  s.prioridad,
  s.temperatura,
  s.puntos_calidad,
  s.puntos_conversacion,
  s.puntos_urgencia,
  s.razones,
  -- Señales extraídas por IA, ya consolidadas por lead.
  n.modelo_texto      as ia_modelo_texto,
  mn.nombre_completo  as ia_modelo,
  mn.precio_lista     as ia_precio_lista,
  n.cuota_inicial_cop as ia_cuota_inicial_cop,
  n.menciona_cuota    as ia_menciona_cuota,
  n.forma_pago        as ia_forma_pago,
  n.intencion         as ia_intencion,
  n.objecion          as ia_objecion,
  n.pidio_cita        as ia_pidio_cita,
  n.pidio_cotizacion  as ia_pidio_cotizacion,
  n.cliente_respondio as ia_cliente_respondio,
  n.conversaciones    as ia_conversaciones,
  n.conversacion_ids  as ia_conversacion_ids,
  n.extractor         as ia_extractor,
  n.prompt_version    as ia_prompt_version
from public.asignacion a
join public.lead l on l.lead_id = a.lead_id
join public.cliente c on c.cliente_id = l.cliente_id
left join public.modelo m on m.sku = l.sku_interes
left join public.senales_lead n on n.lead_id = a.lead_id
left join public.modelo mn on mn.sku = n.sku_extraido
left join lateral (
  -- La versión de puntaje más reciente para esa fecha de corte, por número y no por texto.
  select sc.*
  from public.score sc
  where sc.lead_id = a.lead_id and sc.fecha_corte = a.fecha_corte
  order by sc.version_numero desc
  limit 1
) s on true;
