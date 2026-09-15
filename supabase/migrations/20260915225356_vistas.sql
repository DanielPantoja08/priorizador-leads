-- Vistas para la app (TRD 12 y 13).
-- Todas usan security_invoker = true: se ejecutan con los permisos de quien consulta, así que RLS aplica.
-- Sin esa opción, una vista corre con los permisos de su dueño e ignora RLS.
-- Los campos extraídos por IA se agregan en una migración de la Fase C.

-- Lista diaria: una fila por lead y fecha de corte, con su asignación y su puntaje.
-- Incluye los leads sin cupo (asesor_id nulo), que solo ve el gerente (política de asignacion).
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
  s.razones
from public.asignacion a
join public.lead l on l.lead_id = a.lead_id
join public.cliente c on c.cliente_id = l.cliente_id
left join public.modelo m on m.sku = l.sku_interes
left join lateral (
  -- La versión de puntaje más reciente para esa fecha de corte.
  select sc.*
  from public.score sc
  where sc.lead_id = a.lead_id and sc.fecha_corte = a.fecha_corte
  order by sc.version_score desc
  limit 1
) s on true;

-- Tablero del gerente: carga asignada frente a capacidad por asesor activo y fecha de corte.
create view public.v_tablero_gerente
with (security_invoker = true) as
select
  a.fecha_corte,
  s.empresa_id,
  s.punto_venta_id,
  s.asesor_id,
  s.nombre,
  s.capacidad_diaria,
  count(a.lead_id) as asignados,
  count(a.lead_id) filter (where a.prioritario) as prioritarios
from public.asesor s
join public.asignacion a on a.asesor_id = s.asesor_id and a.estado = 'asignado'
where s.activo
group by a.fecha_corte, s.empresa_id, s.punto_venta_id, s.asesor_id, s.nombre, s.capacidad_diaria;

-- Resumen de problemas de calidad de la última carga, por empresa y tipo.
create view public.v_resumen_calidad
with (security_invoker = true) as
select empresa_id, tipo, count(*) as casos
from public.problema_calidad
group by empresa_id, tipo;

-- Pie de página: fecha y estado de la última ejecución (solo columnas con privilegio de lectura).
create view public.v_ultima_ejecucion
with (security_invoker = true) as
select ejecucion_id, iniciado_en, finalizado_en, estado, fecha_corte
from public.ejecucion
order by ejecucion_id desc
limit 1;

-- Las vistas nuevas no deben quedar abiertas a anon por los privilegios por defecto.
revoke all on public.v_mis_leads_hoy, public.v_tablero_gerente,
              public.v_resumen_calidad, public.v_ultima_ejecucion from anon;
revoke insert, update, delete, truncate on public.v_mis_leads_hoy, public.v_tablero_gerente,
              public.v_resumen_calidad, public.v_ultima_ejecucion from authenticated;
grant select on public.v_mis_leads_hoy, public.v_tablero_gerente,
                public.v_resumen_calidad, public.v_ultima_ejecucion to authenticated;
