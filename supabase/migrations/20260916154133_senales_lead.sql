-- Señales de IA consolidadas por lead (TRD 8.4) y vista de la lista diaria con esos campos.
--
-- La extracción se guarda por conversación, pero un cliente puede tener varias y el puntaje
-- trabaja sobre el lead principal. `consolidar.py` ya resuelve esa mezcla (cita y cotización con
-- OR, la última cuota declarada, la intención más reciente). Aquí se persiste ese resultado para
-- que la app muestre exactamente las mismas señales que produjeron el puntaje, en vez de volver a
-- consolidar en SQL y arriesgarse a divergir.

create table public.senales_lead (
  lead_id           text primary key references public.lead,
  empresa_id        text not null references public.empresa,
  modelo_texto      text,                      -- el último modelo que nombró el cliente
  sku_extraido      text references public.modelo,  -- ese modelo resuelto contra el catálogo
  cuota_inicial_cop bigint,
  menciona_cuota    text check (menciona_cuota in ('SI', 'NO', 'NO_INFORMA')),
  forma_pago        text check (forma_pago in ('contado', 'credito', 'no_informa')),
  intencion         text check (intencion in ('alta', 'media', 'baja')),
  objecion          text,
  pidio_cita        boolean,
  pidio_cotizacion  boolean,
  cliente_respondio boolean,
  conversaciones    int  not null default 0,   -- cuántas conversaciones se consolidaron
  conversacion_ids  text[] not null default '{}',  -- para mostrar la evidencia y el chat completo
  actualizado_en    timestamptz default now()
);
create index senales_lead_empresa_idx on public.senales_lead (empresa_id);

alter table public.senales_lead enable row level security;

revoke all on public.senales_lead from anon, authenticated;
grant select on public.senales_lead to authenticated;
grant all on public.senales_lead to service_role;

create policy senales_lead_por_empresa on public.senales_lead
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

-- ---------------------------------------------------------------------------
-- v_mis_leads_hoy: se recrea para incluir lo que el cliente dijo en WhatsApp (HU-02).
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
  n.conversacion_ids  as ia_conversacion_ids
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
