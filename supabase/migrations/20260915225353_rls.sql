-- Aislamiento por empresa con Row Level Security (TRD 12).
-- Reglas:
--   * RLS activo en todas las tablas; sin política, nadie ve filas.
--   * anon no tiene privilegios: no ve nada.
--   * authenticated solo lee (sin insert, update ni delete).
--   * El pipeline escribe con credenciales de servidor (postgres), que no pasan por RLS.
--   * `(select auth.uid())` se evalúa una vez por consulta y no una vez por fila.

-- ---------------------------------------------------------------------------
-- Activar RLS
-- ---------------------------------------------------------------------------
alter table public.empresa            enable row level security;
alter table public.punto_venta        enable row level security;
alter table public.asesor             enable row level security;
alter table public.modelo             enable row level security;
alter table public.modelo_punto_venta enable row level security;
alter table public.cliente            enable row level security;
alter table public.lead               enable row level security;
alter table public.conversacion       enable row level security;
alter table public.mensaje            enable row level security;
alter table public.extraccion         enable row level security;
alter table public.score              enable row level security;
alter table public.asignacion         enable row level security;
alter table public.historico_cierre   enable row level security;
alter table public.ejecucion          enable row level security;
alter table public.problema_calidad   enable row level security;
alter table public.usuario_empresa    enable row level security;

-- ---------------------------------------------------------------------------
-- Privilegios: anon sin acceso y authenticated solo lectura
-- ---------------------------------------------------------------------------
-- Privilegios explícitos: esta versión de Supabase no los concede por defecto en tablas nuevas.
-- Primero se decide quién puede tocar cada tabla y después RLS decide qué filas ve.
revoke all on all tables in schema public from anon, authenticated;
grant select on all tables in schema public to authenticated;
-- service_role solo lo usa scripts/crear_usuarios_demo.py (lee asesor y escribe usuario_empresa).
grant all on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
alter default privileges in schema public revoke all on tables from anon;
alter default privileges in schema public revoke insert, update, delete, truncate on tables from authenticated;

-- ejecucion: la app solo puede leer los campos del pie de página (TRD 13).
revoke select on public.ejecucion from authenticated;
grant select (ejecucion_id, iniciado_en, finalizado_en, estado, fecha_corte)
  on public.ejecucion to authenticated;

-- ---------------------------------------------------------------------------
-- Políticas
-- ---------------------------------------------------------------------------
-- Cada usuario ve solo su propia fila de usuario_empresa; las demás políticas consultan esta tabla.
create policy usuario_empresa_propio on public.usuario_empresa
  for select to authenticated
  using (user_id = (select auth.uid()));

-- Patrón por empresa: la fila es visible si su empresa_id es la del usuario.
create policy empresa_por_empresa on public.empresa
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

create policy punto_venta_por_empresa on public.punto_venta
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

create policy asesor_por_empresa on public.asesor
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

create policy cliente_por_empresa on public.cliente
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

create policy lead_por_empresa on public.lead
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

-- Las conversaciones huérfanas tienen empresa_id nulo: `null in (...)` no es verdadero, así que nadie las ve.
create policy conversacion_por_empresa on public.conversacion
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

-- mensaje hereda el aislamiento a través de conversacion.
create policy mensaje_por_empresa on public.mensaje
  for select to authenticated
  using (exists (
    select 1 from public.conversacion c
    where c.conversacion_id = mensaje.conversacion_id
      and c.empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid()))
  ));

create policy extraccion_por_empresa on public.extraccion
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

create policy score_por_empresa on public.score
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

-- asignacion: el gerente ve toda su empresa; el asesor, solo sus filas.
-- Es una sola política porque varias políticas permisivas se combinan con OR y no restringirían al asesor.
create policy asignacion_por_empresa_y_rol on public.asignacion
  for select to authenticated
  using (exists (
    select 1 from public.usuario_empresa u
    where u.user_id = (select auth.uid())
      and u.empresa_id = asignacion.empresa_id
      and (u.rol = 'gerente' or u.asesor_id = asignacion.asesor_id)
  ));

create policy historico_por_empresa on public.historico_cierre
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

create policy problema_calidad_por_empresa on public.problema_calidad
  for select to authenticated
  using (empresa_id in (select empresa_id from public.usuario_empresa where user_id = (select auth.uid())));

-- El catálogo es común a las tres empresas: cualquier usuario autenticado lo lee.
create policy modelo_lectura on public.modelo
  for select to authenticated
  using (true);

create policy modelo_punto_venta_lectura on public.modelo_punto_venta
  for select to authenticated
  using (true);

-- ejecucion no tiene datos de empresas; el privilegio de columnas limita qué campos se leen.
create policy ejecucion_lectura on public.ejecucion
  for select to authenticated
  using (true);
