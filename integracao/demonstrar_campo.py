"""Prova com vídeo gravado, foto, API local e retomada da fila."""
import argparse
from base64 import b64decode
import json
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

from rpa.src.fontes import ler_json, gravar_json
from visao.src.inferir import ResultadoEnvio, publicar, reenviar

from .demonstrar_rpa import RAIZ, porta_local, processar, servidor


def demonstrar(fonte, saida, abrir_painel=False):
    if not fonte.is_file():
        raise ValueError("Informe o caminho de um vídeo gravado.")
    saida.mkdir(parents=True, exist_ok=False)
    fila = saida / "fila"
    porta = porta_local()
    offline = f"http://127.0.0.1:{porta}/"
    modelo = RAIZ / "visao/evidencias/treino-publico"
    execucao = subprocess.run([
        sys.executable, "-m", "visao.src.inferir", "--fonte", str(fonte),
        "--pesos", str(modelo / "best.pt"), "--perfil", str(modelo / "perfil.json"),
        "--device", "cpu", "--imgsz", "384", "--anexar-foto", "--sem-janela",
        "--lat", "-23.5614", "--lon", "-46.6559", "--fila", str(fila),
        "--api", offline, "--saida", str(saida / "video-anotado.mp4"),
    ], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", timeout=90,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    (saida / "visao.log").write_text(execucao.stdout + execucao.stderr, encoding="utf-8")
    execucao.check_returncode()
    pendentes = sorted(fila.glob("*.json"))
    if len(pendentes) != 1 or "API indisponível" not in execucao.stderr:
        raise RuntimeError("A prova exige uma ocorrência confirmada e enfileirada com a API desligada.")
    evento = ler_json(pendentes[0])
    foto = b64decode(evento["foto_jpeg"], validate=True)
    id_teste = "00000000-0000-0000-0000-000000000000"
    campos_teste = {k: v for k, v in evento.items() if k != "foto_jpeg"}
    gravar_json(fila / f"{id_teste}.json", {**campos_teste, "id": id_teste, "tipo": "invalido_para_teste"})
    with servidor(porta, saida) as (cliente, api):
        reenviar(cliente, fila)
        if list(fila.glob("*.json")):
            raise RuntimeError("O reenvio deixou registros na fila.")
        revisao = list((fila / "revisao").glob("*.json"))
        if len(revisao) != 1 or ler_json(revisao[0])["id"] != id_teste:
            raise RuntimeError("O registro inválido não foi separado para revisão.")
        if publicar(cliente, evento) is not ResultadoEnvio.ACEITO:
            raise RuntimeError("Falhou a repetição controlada do mesmo envio.")
        antes = cliente.get("ocorrencias?status=nova").raise_for_status().json()
        if [x["id"] for x in antes] != [evento["id"]]:
            raise RuntimeError("A repetição alterou o número de ocorrências ou o ID.")
        url_foto = antes[0]["foto_url"]
        if not url_foto or cliente.get(url_foto).raise_for_status().content != foto:
            raise RuntimeError("A foto recebida diverge da foto enfileirada.")
        if abrir_painel:
            print(f"Painel da demonstração em {api}", flush=True)
            webbrowser.open(api)
            input("Confira a ocorrência na fila. Pressione Enter para executar a triagem. ")
        retorno = processar(api, saida, "logs-triagem")
        retorno.check_returncode()
        depois = cliente.get("ocorrencias").raise_for_status().json()
        if len(depois) != 1 or depois[0]["status"] not in {"validada", "priorizada"}:
            raise RuntimeError("A ocorrência não foi triada de forma única.")
        regiao = depois[0]["subprefeitura"]
        relatorio = cliente.get(f"relatorios/{regiao}").raise_for_status().json()
        if relatorio["total"] != 1:
            raise RuntimeError("O relatório deve conter uma ocorrência aceita.")
        repeticao = processar(api, saida, "logs-reexecucao")
        repeticao.check_returncode()
        if json.loads(repeticao.stdout)["processados"] != 0:
            raise RuntimeError("O RPA processou de novo um registro já triado.")
        pagina = cliente.get("/").raise_for_status().text
        cliente.get("/painel/painel.js").raise_for_status()
        if 'id="registros"' not in pagina:
            raise RuntimeError("O painel não expôs a tabela de ocorrências.")
        resumo = {
            "tipo": evento["tipo"], "confianca": evento["confianca"],
            "origem": "vídeo de campo processado offline",
            "localizacao": "coordenadas de teste para a Sé",
            "enfileiradas_com_api_desligada": len(pendentes),
            "pendentes_apos_reenvio": 0, "separadas_para_revisao": len(revisao),
            "registros_apos_envio_repetido": len(depois),
            "status_apos_triagem": depois[0]["status"], "prioridade": depois[0]["prioridade"],
            "subprefeitura": regiao, "processados_ao_repetir_triagem": 0,
            "foto_verificada": True, "ocorrencias_no_relatorio": relatorio["total"],
        }
        gravar_json(saida / "resultado.json", resumo)
        print(json.dumps(resumo, ensure_ascii=False, indent=2), flush=True)
        if abrir_painel:
            input("Confira o status Validada e a foto no painel. Pressione Enter para encerrar. ")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonte", type=Path, required=True, help="clipe que contenha uma ocorrência detectável")
    parser.add_argument("--saida", type=Path, required=True, help="nova pasta de evidências")
    parser.add_argument("--painel", action="store_true", help="abre o painel e mantém a API ativa durante a conferência")
    args = parser.parse_args()
    demonstrar(args.fonte.resolve(), args.saida.resolve(), abrir_painel=args.painel)
