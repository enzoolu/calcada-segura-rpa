"""Gera um lote sintético para validar o contrato e demonstrar o RPA."""
import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from rpa.src.fontes import gravar_json


def gerar():
    agora = datetime.now(UTC) - timedelta(minutes=5)
    variantes = [
        {"tipo": "buraco", "confianca": 0.89},
        {"tipo": "buraco", "lat": -23.56143, "confianca": 0.83},
        {"tipo": "rampa_irregular", "origem": "robo", "inclinacao_pct": 10.4, "confianca": None},
        {"tipo": "trepidacao", "origem": "robo", "lat": -23.5585, "vibracao_rms": 0.42, "confianca": None},
        {"tipo": "obstaculo", "lat": -23.5723, "lon": -46.598, "confianca": 0.66},
        {"tipo": "calcada_quebrada", "lat": -29.5614, "confianca": 0.88},
    ]
    return [
        {
            "id": str(UUID(int=i + 1)), "origem": "visao", "lat": -23.5614, "lon": -46.6559,
            "foto_url": None, "criado_em": (agora + timedelta(seconds=i)).isoformat(), "status": "nova",
            "prioridade": None, "subprefeitura": None, **especifico,
        }
        for i, especifico in enumerate(variantes)
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destino", type=Path)
    args = parser.parse_args()
    gravar_json(args.destino, gerar())
