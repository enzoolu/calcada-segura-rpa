"""Abre um MVP local isolado para demonstrar o RPA com dados sintéticos."""
import argparse
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import mkdtemp
import time
import webbrowser

import httpx

from rpa.src.fontes import ler_json
from .simular_ocorrencias import gerar

RAIZ = Path(__file__).resolve().parents[1]
ESPERADO = {"priorizada": 2, "validada": 2, "duplicada": 1}


def porta_local():
    with socket.socket() as conexao:
        conexao.bind(("127.0.0.1", 0))
        return conexao.getsockname()[1]


@contextmanager
def servidor(porta, pasta):
    ambiente = {**os.environ, "CALCADA_DEMO_DIR": str(pasta)}
    # A demo usa dados descartáveis e uma API restrita ao loopback.
    ambiente.pop("CALCADA_API_KEY", None)
    ambiente.pop("CALCADA_RELATORIOS", None)
    with (pasta / "api.log").open("w", encoding="utf-8") as log:
        processo = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "integracao.api_local:app",
            "--host", "127.0.0.1", "--port", str(porta), "--no-access-log",
        ], env=ambiente, cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT)
        api = f"http://127.0.0.1:{porta}/"
        try:
            with httpx.Client(base_url=api, trust_env=False, timeout=2) as cliente:
                limite = time.monotonic() + 15
                while time.monotonic() < limite and processo.poll() is None:
                    try:
                        if cliente.get("health").is_success:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.15)
                else:
                    raise RuntimeError(f"API local não iniciou. Consulte {pasta / 'api.log'}.")
                yield cliente, api
        finally:
            processo.terminate()
            try:
                processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait()


def alimentar(cliente):
    for item in gerar()[:-1]:
        campos = {
            k: (None, str(v)) for k, v in item.items()
            if v is not None and k != "status"
        }
        cliente.post("ocorrencias", files=campos).raise_for_status()


def processar(api, pasta, nome_logs):
    return subprocess.run([
        sys.executable, "-m", "rpa.src.rodar", "--api", api,
        "--saida", str(pasta), "--logs", str(pasta / nome_logs),
    ], cwd=RAIZ, check=False, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def resultado(cliente):
    lote = cliente.get("ocorrencias").raise_for_status().json()
    se = cliente.get("relatorios/SE").raise_for_status().json()
    contagens = dict(Counter(x["status"] for x in lote))
    if contagens != ESPERADO or se["total"] != 3:
        raise RuntimeError("A API e o relatório divergiram do cenário esperado.")
    duplicada = next(item for item in lote if item["status"] == "duplicada")
    original = next((item for item in lote if item["id"] == duplicada.get("duplicada_de")), None)
    if not original or duplicada.get("regra_triagem") != "mesmo_tipo_ate_15m_em_30d":
        raise RuntimeError("A duplicata não expôs a regra e o registro original.")
    return {"status": contagens, "relatorio_se": se["total"], "original_vinculado": True,
            "regra_duplicada": duplicada["regra_triagem"]}


def conferir_falha(retorno, pasta):
    logs = list((pasta / "logs-falha").glob("*.json"))
    if len(logs) != 1:
        raise RuntimeError("Arquivo de auditoria da falha ausente.")
    auditado = ler_json(logs[0])
    tentativas = [x["tentativa"] for x in auditado["eventos"] if x["evento"] == "tentativa_falhou"]
    if retorno.returncode != 2 or tentativas != [1, 2, 3]:
        raise RuntimeError("A falha não correspondeu às três tentativas previstas.")
    return {"tentativas": tentativas, "codigo": retorno.returncode, "log": logs[0].name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--automatico", action="store_true", help="valida o fluxo sem abrir navegador")
    args = parser.parse_args()
    destino = RAIZ / ".demo"
    destino.mkdir(exist_ok=True)
    pasta = Path(mkdtemp(prefix="rpa-", dir=destino))
    porta = porta_local()
    with servidor(porta, pasta) as (cliente, api):
        alimentar(cliente)
        antes = len(cliente.get("ocorrencias", params={"status": "nova"}).raise_for_status().json())
        if antes != 5:
            raise RuntimeError("O painel deve iniciar com cinco ocorrências novas.")
        print(f"Painel: {api}")
        print(f"Evidências: {pasta}")
        if not args.automatico:
            webbrowser.open(api)
            input("Confira as 5 ocorrências novas. Pressione Enter para executar o RPA. ")
        retorno = processar(api, pasta, "logs")
        print(retorno.stdout.strip())
        retorno.check_returncode()
        comprovado = resultado(cliente)
        if not args.automatico:
            input("Confira a triagem e o relatório no painel. Pressione Enter para desligar a API de teste. ")
    falha = processar(api, pasta, "logs-falha")
    print(json.dumps({"antes": antes, "depois": comprovado, "falha": conferir_falha(falha, pasta)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
