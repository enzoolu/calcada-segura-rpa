import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

import httpx

from src.fontes import Api, Arquivo, FalhaFonte, gravar_json
from src.geografia import Subprefeituras
from src.rodar import Auditoria, CAMADA_PADRAO, executar, relatar


def registro(indice, **campos):
    return {
        "id": str(UUID(int=indice)), "origem": "visao", "tipo": "buraco", "status": "nova",
        "lat": -23.5614, "lon": -46.6559, "confianca": 0.87, "criado_em": "2026-11-13T14:32:00-03:00",
        **campos,
    }


class TesteTriagem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapa = Subprefeituras(CAMADA_PADRAO, "subprefeitura")

    def rodar_lote(self, registros):
        with TemporaryDirectory() as pasta:
            entrada = Path(pasta) / "entrada.json"
            saida = Path(pasta) / "saida.json"
            gravar_json(entrada, registros)
            arquivo = Arquivo(entrada, saida)
            auditoria = Auditoria()
            resultado = executar(arquivo, self.mapa, auditoria)
            relatar(resultado, Path(pasta))
            relatorios = json.loads((Path(pasta) / "relatorios.json").read_text(encoding="utf-8"))
            auditoria_repeticao = Auditoria()
            executar(arquivo, self.mapa, auditoria_repeticao)
            self.assertEqual(0, auditoria_repeticao.contagens["processados"])
            return resultado, relatorios, auditoria

    def test_sucesso_localiza_regiao_gera_relatorio_e_reexecuta(self):
        lote, relatorios, auditoria = self.rodar_lote([registro(1)])
        self.assertEqual("SE", lote[0]["subprefeitura"])
        self.assertEqual(1, relatorios["SE"]["total"])
        self.assertNotIn("lat", relatorios["SE"]["ocorrencias"][0])
        self.assertEqual(1, auditoria.contagens["sucessos"])

    def test_decisao_alta_e_duplicidade_interfontes(self):
        lote, _, _ = self.rodar_lote([
            registro(1, origem="robo", tipo="rampa_irregular", inclinacao_pct=10.4),
            registro(2, origem="robo", criado_em="2026-11-13T18:00:00+00:00"),
            registro(3, criado_em="2026-11-13T14:32:00-03:00", lat=-23.56143),
        ])
        self.assertEqual(["priorizada", "duplicada", "priorizada"], [item["status"] for item in lote])
        self.assertEqual("alta", lote[0]["prioridade"])
        self.assertEqual("alta", lote[2]["prioridade"])
        self.assertEqual("rampa_acima_do_limiar", lote[0]["regra_triagem"])
        self.assertEqual("mesmo_tipo_ate_15m_em_30d", lote[1]["regra_triagem"])
        self.assertEqual(lote[2]["id"], lote[1]["duplicada_de"])

    def test_duplicata_aponta_para_a_referencia_mais_proxima(self):
        lote, _, _ = self.rodar_lote([
            registro(1, status="validada", lat=-23.56148),
            registro(2, status="validada", lat=-23.56141),
            registro(3),
        ])
        self.assertEqual(lote[1]["id"], lote[2]["duplicada_de"])

    def test_dado_invalido_e_coordenada_fora_da_cidade(self):
        lote, _, auditoria = self.rodar_lote([registro(1, lat=-30), registro(2, confianca=2)])
        self.assertEqual(["rejeitada", "rejeitada"], [item["status"] for item in lote])
        self.assertEqual(2, auditoria.contagens["falhas"])

    def test_historico_fora_da_janela_nao_bloqueia_nova_ocorrencia(self):
        lote, _, _ = self.rodar_lote([
            registro(1, status="priorizada", criado_em="2026-10-01T14:00:00-03:00"),
            registro(2),
        ])
        self.assertEqual("priorizada", lote[1]["status"])

    def test_falha_api_log_e_tres_tentativas(self):
        registros, pausas = [], []

        def indisponivel(request):
            raise httpx.ConnectError("falha simulada", request=request)

        with httpx.Client(base_url="http://mvp.test/", transport=httpx.MockTransport(indisponivel)) as cliente:
            api = Api(cliente, lambda evento, **dados: registros.append(dados), espera=pausas.append)
            with self.assertRaisesRegex(FalhaFonte, "api_indisponivel"):
                api.listar()
        self.assertEqual([1, 2, 3], [etapa["tentativa"] for etapa in registros])
        self.assertEqual([1, 2], pausas)

    def test_api_atualiza_pelo_contrato(self):
        lote = [registro(1, foto_url="/fotos/amostra")]
        requisicoes = []

        def responder(request):
            requisicoes.append((request.method, request.url.path))
            if request.method == "GET":
                return httpx.Response(200, json=lote)
            dados = json.loads(request.content)
            self.assertEqual({"status": "priorizada", "prioridade": "alta", "subprefeitura": "SE",
                              "regra_triagem": "buraco_degrau_confianca_alta"}, dados)
            return httpx.Response(200, json=dados)

        with httpx.Client(base_url="http://mvp.test/", transport=httpx.MockTransport(responder)) as cliente:
            auditoria = Auditoria()
            resultado = executar(Api(cliente, auditoria.registrar), self.mapa, auditoria)
        self.assertEqual("priorizada", resultado[0]["status"])
        self.assertEqual([("GET", "/ocorrencias"), ("PATCH", "/ocorrencias/" + lote[0]["id"])], requisicoes)


if __name__ == "__main__":
    unittest.main()
