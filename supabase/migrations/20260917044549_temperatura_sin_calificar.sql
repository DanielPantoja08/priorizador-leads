-- Puntaje v2: un lead sin conversación de WhatsApp ya no se marca Frío, porque que falte el chat
-- es falta de dato, no baja calidad. Su temperatura es 'Sin calificar' y el asesor la resuelve
-- en la primera llamada. Las filas de v1 conservan su temperatura.
alter table public.score drop constraint score_temperatura_check;
alter table public.score add constraint score_temperatura_check
  check (temperatura in ('Caliente', 'Tibio', 'Frío', 'Sin calificar'));
