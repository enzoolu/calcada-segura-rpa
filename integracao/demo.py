"""Prova o caminho POST → triagem → GET → relatório na API local."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx

from .simular_ocorrencias import gerar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000/")
    parser.add_argument("--saida", type=Path, default=Path(".demo"))
    args = parser.parse_args()
    chave = os.getenv("CALCADA_API_KEY")
    headers = {"X-API-Key": chave} if chave else {}
    lote = gerar()[:-1]
    with httpx.Client(base_url=args.api.rstrip("/") + "/", headers=headers, timeout=10, trust_env=False) as cliente:
        for item in lote:
            campos = {
                k: (None, str(v)) for k, v in item.items()
                if v is not None and k not in {"status"}
            }
            resposta = cliente.post("ocorrencias", files=campos)
            resposta.raise_for_status()
        antes = cliente.get("ocorrencias", params={"status": "nova"}).raise_for_status().json()
        terminou = subprocess.run([
            sys.executable, "-m", "rpa.src.rodar", "--api", args.api,
            "--saida", str(args.saida), "--logs", str(args.saida / "logs"),
        ], check=False)
        depois = cliente.get("ocorrencias").raise_for_status().json()
        relatorio = cliente.get("relatorios/SE").raise_for_status().json()
    resultado = {
        "ambiente": "API local com lote sintetico", "novas_antes": len(antes),
        "status_depois": [item["status"] for item in depois],
        "prioridade_primeiro_buraco": depois[0]["prioridade"],
        "relatorio_se_total": relatorio["total"],
    }
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    esperado = ["priorizada", "duplicada", "priorizada", "validada", "validada"]
    return int(terminou.returncode != 0 or len(antes) != 5 or resultado["status_depois"] != esperado
               or resultado["prioridade_primeiro_buraco"] != "alta" or relatorio["total"] != 3)


if __name__ == "__main__":
    raise SystemExit(main())
