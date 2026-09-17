"""Cómo se registra qué lanzó cada corrida del pipeline."""

import pytest

from pipeline.__main__ import origen_de_la_corrida


@pytest.mark.parametrize(
    ("evento", "disparador", "esperado"),
    [
        ("schedule", None, "schedule"),
        ("workflow_dispatch", "supabase_cron", "supabase_cron"),
        ("workflow_dispatch", "manual", "manual"),
        ("workflow_dispatch", "", "manual"),
        ("push", "supabase_cron", "manual"),  # la entrada solo cuenta en un disparo por API
        (None, None, "manual"),  # corrida local
    ],
)
def test_origen_de_la_corrida(evento, disparador, esperado) -> None:
    assert origen_de_la_corrida(evento, disparador) == esperado
