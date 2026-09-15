-- Datos de referencia que NO vienen de los CSV (TRD 5.1).
-- Los CSV solo traen empresa_id; el nombre y la región salen del supuesto 1 del PRD.
-- Se ejecuta en cada `supabase db reset`. Es idempotente.

insert into public.empresa (empresa_id, nombre, region) values
  ('EMP-01', 'Comercializadora Antioquia', 'Antioquia'),
  ('EMP-02', 'Comercializadora Costa Atlántica', 'Costa Atlántica'),
  ('EMP-03', 'Comercializadora Bogotá y Soacha', 'Bogotá')
on conflict (empresa_id) do update
  set nombre = excluded.nombre,
      region = excluded.region;
