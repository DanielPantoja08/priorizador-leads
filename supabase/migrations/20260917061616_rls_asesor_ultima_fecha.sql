-- El asesor ve solo la asignación vigente: la de la última fecha de corte de su empresa.
--
-- `privado.clientes_asignados()` juntaba las asignaciones de todas las fechas: desde la segunda
-- corrida, un asesor seguiría viendo los clientes de días anteriores aunque hoy los tenga otro.
-- Ahora cuenta solo la última fecha de corte, y lo mismo vale para sus filas de `asignacion`: una
-- fecha anterior la ve vacía. El gerente sigue viendo todas las fechas de su empresa.

-- ---------------------------------------------------------------------------
-- Última fecha de corte de una empresa
-- ---------------------------------------------------------------------------
-- `security definer` porque la política de `asignacion` la usa: consultar `asignacion` desde su
-- propia política entraría en recursión.
create function privado.ultima_fecha_corte(empresa text)
returns date
language sql
stable
security definer
set search_path = ''
as $$
  select max(fecha_corte) from public.asignacion where empresa_id = empresa
$$;

revoke all on function privado.ultima_fecha_corte(text) from public, anon;
grant execute on function privado.ultima_fecha_corte(text) to authenticated;

-- ---------------------------------------------------------------------------
-- Clientes asignados: solo en la última fecha de corte
-- ---------------------------------------------------------------------------
create or replace function privado.clientes_asignados()
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
    and a.fecha_corte = privado.ultima_fecha_corte(a.empresa_id)
$$;

-- ---------------------------------------------------------------------------
-- asignacion: el gerente, todas las fechas; el asesor, sus filas de la última
-- ---------------------------------------------------------------------------
drop policy asignacion_por_empresa_y_rol on public.asignacion;
create policy asignacion_por_empresa_y_rol on public.asignacion
  for select to authenticated
  using (exists (
    select 1 from public.usuario_empresa u
    where u.user_id = (select auth.uid())
      and u.empresa_id = asignacion.empresa_id
      and (
        u.rol = 'gerente'
        or (
          u.asesor_id = asignacion.asesor_id
          and asignacion.fecha_corte = privado.ultima_fecha_corte(asignacion.empresa_id)
        )
      )
  ));
