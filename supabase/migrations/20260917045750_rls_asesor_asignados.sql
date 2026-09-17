-- Mínimo privilegio del asesor (TRD 12).
-- Hasta aquí solo `asignacion` distinguía el rol: un asesor podía consultar por PostgREST todos los
-- clientes, conversaciones, extracciones y puntajes de su empresa. Ahora:
--   * el gerente sigue viendo toda su empresa;
--   * el asesor ve solo lo de los clientes que tiene asignados, incluidos los otros leads de ese
--     mismo cliente (la app los muestra en el detalle);
--   * el histórico y los problemas de calidad son del gerente.
-- La separación entre empresas no cambia: todas las condiciones siguen exigiendo la empresa propia.

-- ---------------------------------------------------------------------------
-- Clientes asignados al asesor que consulta
-- ---------------------------------------------------------------------------
-- `security definer` para leer `asignacion` y `lead` sin pasar por sus políticas: la política de
-- `lead` no puede consultar `lead` sin entrar en recursión. Vive en un esquema que PostgREST no
-- expone y no recibe parámetros: solo responde por el usuario de la sesión.
create schema if not exists privado;
revoke all on schema privado from public;
grant usage on schema privado to authenticated;

create function privado.clientes_asignados()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
  select distinct l.cliente_id
  from public.asignacion a
  join public.lead l on l.lead_id = a.lead_id
  join public.usuario_empresa u
    on u.asesor_id = a.asesor_id and u.empresa_id = a.empresa_id
  where u.user_id = (select auth.uid())
$$;

revoke all on function privado.clientes_asignados() from public, anon;
grant execute on function privado.clientes_asignados() to authenticated;

-- ---------------------------------------------------------------------------
-- cliente y lead: el gerente, toda la empresa; el asesor, sus clientes asignados
-- ---------------------------------------------------------------------------
drop policy cliente_por_empresa on public.cliente;
create policy cliente_por_empresa_y_rol on public.cliente
  for select to authenticated
  using (exists (
    select 1 from public.usuario_empresa u
    where u.user_id = (select auth.uid())
      and u.empresa_id = cliente.empresa_id
      and (u.rol = 'gerente' or cliente.cliente_id in (select privado.clientes_asignados()))
  ));

drop policy lead_por_empresa on public.lead;
create policy lead_por_empresa_y_rol on public.lead
  for select to authenticated
  using (exists (
    select 1 from public.usuario_empresa u
    where u.user_id = (select auth.uid())
      and u.empresa_id = lead.empresa_id
      and (u.rol = 'gerente' or lead.cliente_id in (select privado.clientes_asignados()))
  ));

-- ---------------------------------------------------------------------------
-- Lo que cuelga de un lead: visible si el lead lo es
-- ---------------------------------------------------------------------------
-- Las subconsultas sobre `lead` y `conversacion` pasan por sus propias políticas, así que heredan
-- la empresa y el rol sin repetir la regla.
drop policy conversacion_por_empresa on public.conversacion;
create policy conversacion_por_lead_visible on public.conversacion
  for select to authenticated
  using (exists (
    select 1 from public.lead l
    where l.lead_id = conversacion.lead_id and l.empresa_id = conversacion.empresa_id
  ));

drop policy mensaje_por_empresa on public.mensaje;
create policy mensaje_por_conversacion_visible on public.mensaje
  for select to authenticated
  using (exists (
    select 1 from public.conversacion c where c.conversacion_id = mensaje.conversacion_id
  ));

drop policy extraccion_por_empresa on public.extraccion;
create policy extraccion_por_conversacion_visible on public.extraccion
  for select to authenticated
  using (exists (
    select 1 from public.conversacion c
    where c.conversacion_id = extraccion.conversacion_id and c.empresa_id = extraccion.empresa_id
  ));

drop policy score_por_empresa on public.score;
create policy score_por_lead_visible on public.score
  for select to authenticated
  using (exists (
    select 1 from public.lead l
    where l.lead_id = score.lead_id and l.empresa_id = score.empresa_id
  ));

drop policy senales_lead_por_empresa on public.senales_lead;
create policy senales_lead_por_lead_visible on public.senales_lead
  for select to authenticated
  using (exists (
    select 1 from public.lead l
    where l.lead_id = senales_lead.lead_id and l.empresa_id = senales_lead.empresa_id
  ));

-- ---------------------------------------------------------------------------
-- Histórico y calidad de datos: solo el gerente
-- ---------------------------------------------------------------------------
drop policy historico_por_empresa on public.historico_cierre;
create policy historico_del_gerente on public.historico_cierre
  for select to authenticated
  using (exists (
    select 1 from public.usuario_empresa u
    where u.user_id = (select auth.uid())
      and u.empresa_id = historico_cierre.empresa_id
      and u.rol = 'gerente'
  ));

drop policy problema_calidad_por_empresa on public.problema_calidad;
create policy problema_calidad_del_gerente on public.problema_calidad
  for select to authenticated
  using (exists (
    select 1 from public.usuario_empresa u
    where u.user_id = (select auth.uid())
      and u.empresa_id = problema_calidad.empresa_id
      and u.rol = 'gerente'
  ));
