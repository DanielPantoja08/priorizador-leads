-- Disparo diario del pipeline desde la base.
--
-- El cron de GitHub Actions no garantiza la hora y en este repositorio no disparó (2026-09-17: ni a
-- las 6:00, ni a las 10:37, ni a las 12:07 de Bogotá). pg_cron corre dentro de Postgres y, a la
-- hora, pg_net llama a la API de GitHub para lanzar el workflow pipeline.yml. El pipeline sigue
-- corriendo en GitHub; el cron de GitHub queda de respaldo y la corrida es idempotente.
--
-- El token de GitHub (fine-grained, solo este repositorio, Actions: lectura y escritura) vive en
-- Supabase Vault con el nombre github_token_pipeline. Nunca está en el repositorio.

create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

-- La base registra de dónde vino cada corrida.
alter table public.ejecucion drop constraint ejecucion_disparador_check;
alter table public.ejecucion add constraint ejecucion_disparador_check
  check (disparador in ('schedule', 'manual', 'supabase_cron'));

-- Pide a GitHub la corrida y devuelve el id de la petición de pg_net (la respuesta queda en
-- net._http_response; GitHub responde 204 si la aceptó). Sin el secreto, avisa y no llama a nada:
-- así la base local funciona sin token.
create or replace function privado.disparar_pipeline()
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  token text;
begin
  select s.decrypted_secret into token
  from vault.decrypted_secrets s
  where s.name = 'github_token_pipeline';

  if token is null then
    raise warning 'Falta el secreto github_token_pipeline en Vault: no se dispara el pipeline';
    return null;
  end if;

  return net.http_post(
    url := 'https://api.github.com/repos/DanielPantoja08/priorizador-leads/actions/workflows/pipeline.yml/dispatches',
    body := jsonb_build_object(
      'ref', 'main',
      'inputs', jsonb_build_object('disparador', 'supabase_cron')
    ),
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || token,
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'priorizador-leads-pg-cron',
      'Content-Type', 'application/json'
    ),
    timeout_milliseconds := 10000
  );
end;
$$;

-- Solo la usa pg_cron (rol postgres): ni la app ni la API pueden lanzar corridas.
revoke all on function privado.disparar_pipeline() from public, anon, authenticated;

-- 06:17 America/Bogota (pg_cron usa UTC). Fuera de la hora en punto; si el nombre ya existe, se
-- actualiza.
select cron.schedule('pipeline-diario', '17 11 * * *', 'select privado.disparar_pipeline()');
