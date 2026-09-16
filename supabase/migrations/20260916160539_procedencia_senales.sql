-- Procedencia de las señales: qué extractor y qué versión de prompt las produjeron.
--
-- La tabla `extraccion` conserva por diseño todas las versiones cacheadas de cada conversación
-- (v2, v4, reglas_v1, reglas_v3...). La app pedía la evidencia filtrando solo por conversación,
-- así que mostraba las cuatro a la vez, con fragmentos que se contradicen entre sí. Y no se puede
-- resolver tomando la más reciente: en este repositorio la última escrita es `reglas_v3`, que no
-- es la vigente.
--
-- Guardando aquí la versión con la que se consolidaron las señales, la app filtra por ella y el
-- asesor ve exactamente la evidencia del puntaje que tiene delante (RNF-08, trazabilidad).

alter table public.senales_lead
  add column extractor      text,
  add column prompt_version text;

comment on column public.senales_lead.prompt_version is
  'Versión con la que se extrajeron estas señales; la app filtra la evidencia por ella.';

-- ---------------------------------------------------------------------------
-- v_mis_leads_hoy: se recrea para exponer la procedencia.
-- ---------------------------------------------------------------------------
drop view if exists public.v_mis_leads_hoy;

create view public.v_mis_leads_hoy
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
  -- La versión de puntaje más reciente para esa fecha de corte.
  select sc.*
  from public.score sc
  where sc.lead_id = a.lead_id and sc.fecha_corte = a.fecha_corte
  order by sc.version_score desc
  limit 1
) s on true;

revoke all on public.v_mis_leads_hoy from anon;
revoke insert, update, delete, truncate on public.v_mis_leads_hoy from authenticated;
grant select on public.v_mis_leads_hoy to authenticated;
