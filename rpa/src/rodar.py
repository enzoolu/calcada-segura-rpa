"""Executa um lote de triagem e escreve o registro da execução."""
import argparse
from collections import Counter
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import httpx
from shapely.errors import ShapelyError

from .fontes import Api, Arquivo, FalhaFonte, gravar_json
from .geografia import Subprefeituras
from .triagem import STATUS_REFERENCIA, identificador, prioridade_e_regra, referencia_duplicada, validar

RAIZ = Path(__file__).resolve().parents[1]
CAMADA_PADRAO = RAIZ / "amostras" / "subprefeituras.geojson"


class Auditoria:
    def __init__(self):
        self.id = str(uuid4())
        self.inicio = datetime.now(UTC)
        self.eventos = []
        self.contagens = Counter()

    def registrar(self, evento, **detalhes):
        self.eventos.append({"evento": evento, "data_hora": datetime.now(UTC).isoformat(), **detalhes})

    def finalizar(self, logs, modo):
        contagens = {campo: self.contagens[campo] for campo in (
            "processados", "sucessos", "falhas", "priorizadas", "validadas", "duplicadas", "rejeitadas",
        )}
        resultado = {
            "execucao": self.id, "modo": modo, "inicio": self.inicio.isoformat(),
            "fim": datetime.now(UTC).isoformat(), "contagens": contagens, "eventos": self.eventos,
        }
        gravar_json(logs / f"{self.id}.json", resultado)
        print(json.dumps({"execucao": self.id, **contagens}, ensure_ascii=False))


def solicitar_atualizacao(fonte, registro, dados, auditoria, item):
    try:
        fonte.atualizar(registro, dados)
    except FalhaFonte as erro:
        auditoria.contagens["falhas"] += 1
        auditoria.registrar("falha_atualizacao", item=item, codigo=str(erro))
        return False
    status = dados["status"]
    auditoria.contagens[f"{status}s"] += 1
    if status == "rejeitada":
        auditoria.contagens["falhas"] += 1
    else:
        auditoria.contagens["sucessos"] += 1
    auditoria.registrar("triagem_gravada", item=item, status=status,
                        prioridade=dados["prioridade"], codigo=dados["regra_triagem"])
    return True


def executar(fonte, mapa, auditoria):
    agora = auditoria.inicio
    registros = fonte.listar()
    referencias = []
    fila = []
    estados_conhecidos = STATUS_REFERENCIA | {"nova", "duplicada", "rejeitada"}
    for item, registro in enumerate(registros, start=1):
        status = registro.get("status") if isinstance(registro, dict) else None
        if not isinstance(status, str) or status not in estados_conhecidos:
            auditoria.contagens["processados"] += 1
            auditoria.contagens["falhas"] += 1
            auditoria.registrar("registro_ignorado", item=item, codigo="registro_ou_status_invalido")
        elif status in STATUS_REFERENCIA:
            try:
                referencias.append(validar(registro, agora))
            except ValueError as erro:
                auditoria.registrar("historico_ignorado", item=item, codigo=str(erro))
        elif status == "nova":
            fila.append((registro.get("criado_em"), item, registro))

    # Compara instantes reais, inclusive quando clientes usam fusos diferentes.
    def data_ordem(item_fila):
        try:
            data = datetime.fromisoformat(item_fila[0])
            return data.astimezone(UTC) if data.tzinfo else datetime.max.replace(tzinfo=UTC)
        except (ValueError, TypeError, OverflowError):
            return datetime.max.replace(tzinfo=UTC)

    for _, item, registro in sorted(fila, key=data_ordem):
        auditoria.contagens["processados"] += 1
        try:
            identificador(registro)
        except ValueError:
            auditoria.contagens["falhas"] += 1
            auditoria.registrar("registro_ignorado", item=item, codigo="id_invalido")
            continue
        try:
            ocorrencia = validar(registro, agora)
            regiao = mapa.localizar(ocorrencia.lat, ocorrencia.lon)
        except ValueError as erro:
            if str(erro) == "subprefeitura_ambigua":
                auditoria.contagens["falhas"] += 1
                auditoria.registrar("revisao_manual", item=item, codigo=str(erro))
                continue
            dados = {"status": "rejeitada", "prioridade": None, "subprefeitura": None,
                     "regra_triagem": str(erro)}
            solicitar_atualizacao(fonte, registro, dados, auditoria, item)
            continue
        original = referencia_duplicada(ocorrencia, referencias)
        if original:
            dados = {"status": "duplicada", "prioridade": None, "subprefeitura": regiao,
                     "regra_triagem": "mesmo_tipo_ate_15m_em_30d", "duplicada_de": original}
            solicitar_atualizacao(fonte, registro, dados, auditoria, item)
            continue
        prioridade, regra = prioridade_e_regra(ocorrencia)
        dados = {
            "status": "priorizada" if prioridade == "alta" else "validada",
            "prioridade": prioridade, "subprefeitura": regiao, "regra_triagem": regra,
        }
        if solicitar_atualizacao(fonte, registro, dados, auditoria, item):
            referencias.append(ocorrencia)
    return registros


def relatar(registros, pasta):
    relatorios = {}
    for registro in registros:
        if not isinstance(registro, dict) or registro.get("status") not in ("validada", "priorizada", "encaminhada", "resolvida"):
            continue
        nome = registro.get("subprefeitura")
        if not isinstance(nome, str) or not nome.strip():
            continue
        linha = {campo: registro.get(campo) for campo in ("id", "tipo", "status", "prioridade", "criado_em")}
        relatorios.setdefault(nome, []).append(linha)
    gravar_json(pasta / "relatorios.json", {
        nome: {"subprefeitura": nome, "total": len(itens), "ocorrencias": itens}
        for nome, itens in sorted(relatorios.items())
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    fontes = parser.add_mutually_exclusive_group(required=True)
    fontes.add_argument("--entrada", type=Path, help="lista JSON de ocorrências")
    fontes.add_argument("--api", help="URL base da API do MVP")
    parser.add_argument("--saida", type=Path, default=Path("saida"))
    parser.add_argument("--logs", type=Path, default=Path("logs"))
    parser.add_argument("--geojson", type=Path, default=CAMADA_PADRAO)
    parser.add_argument("--campo-subprefeitura", default="subprefeitura")
    args = parser.parse_args()

    auditoria = Auditoria()
    modo = "api" if args.api else "arquivo"
    falha_lote = False
    try:
        mapa = Subprefeituras(args.geojson, args.campo_subprefeitura)
        destino = args.saida / "ocorrencias.json"
        if args.entrada:
            if destino.resolve() == args.entrada.resolve():
                raise FalhaFonte("entrada_e_saida_precisam_ser_distintas")
            registros = executar(Arquivo(args.entrada, destino), mapa, auditoria)
        else:
            chave = os.getenv("CALCADA_API_KEY")
            headers = {"X-API-Key": chave} if chave else {}
            with httpx.Client(base_url=args.api.rstrip("/") + "/", headers=headers, timeout=5, trust_env=False) as cliente:
                registros = executar(Api(cliente, auditoria.registrar), mapa, auditoria)
        relatar(registros, args.saida)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ShapelyError, httpx.InvalidURL) as erro:
        falha_lote = True
        auditoria.contagens["falhas"] += 1
        auditoria.registrar("lote_interrompido", codigo="configuracao_ou_saida_invalida", classe=type(erro).__name__)
        print("Confira a camada GeoJSON, a URL ou a pasta de saída.", file=sys.stderr)
    except FalhaFonte as erro:
        falha_lote = True
        auditoria.contagens["falhas"] += 1
        auditoria.registrar("lote_interrompido", codigo=str(erro))
        print(f"Lote interrompido ({erro}). Consulte o log.", file=sys.stderr)
    try:
        auditoria.finalizar(args.logs, modo)
    except OSError:
        print("Falha ao gravar o log de auditoria.", file=sys.stderr)
        return 2
    return 2 if falha_lote else int(auditoria.contagens["falhas"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
