"""Leitura e gravação de ocorrências em arquivo ou HTTP."""
import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

import httpx


class FalhaFonte(Exception):
    pass


def constante_invalida(valor):
    raise ValueError("Constante JSON inválida")


def ler_json(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8-sig"), parse_constant=constante_invalida)


def gravar_json(caminho: Path, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=caminho.parent, delete=False) as temp:
        temporario = Path(temp.name)
        try:
            json.dump(dados, temp, indent=2, ensure_ascii=False, allow_nan=False)
        except BaseException:
            temp.close()
            temporario.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporario, caminho)
    finally:
        temporario.unlink(missing_ok=True)


class Arquivo:
    def __init__(self, entrada: Path, saida: Path):
        self.entrada = entrada
        self.saida = saida
        self.registros = []

    def listar(self):
        try:
            self.registros = ler_json(self.saida if self.saida.exists() else self.entrada)
        except (OSError, ValueError):
            raise FalhaFonte("arquivo_ausente_ou_json_invalido") from None
        if not isinstance(self.registros, list):
            raise FalhaFonte("arquivo_deve_conter_lista")
        return self.registros

    def atualizar(self, registro: dict, dados: dict):
        anterior = registro.copy()
        registro.update(dados)
        try:
            gravar_json(self.saida, self.registros)
        except (OSError, ValueError):
            registro.clear()
            registro.update(anterior)
            raise FalhaFonte("falha_ao_gravar_saida") from None


class Api:
    def __init__(self, cliente: httpx.Client, registrar, espera=time.sleep):
        self.cliente = cliente
        self.registrar = registrar
        self.espera = espera

    def solicitar(self, metodo, rota, **kwargs):
        for tentativa in (1, 2, 3):
            try:
                resposta = self.cliente.request(metodo, rota, **kwargs)
            except httpx.TransportError:
                codigo = "api_indisponivel"
            else:
                if resposta.is_success:
                    return resposta
                codigo = f"http_{resposta.status_code}"
                if resposta.status_code not in {408, 429} and resposta.status_code < 500:
                    raise FalhaFonte(codigo)
            self.registrar("tentativa_falhou", operacao=metodo, tentativa=tentativa, codigo=codigo)
            if tentativa < 3:
                self.espera(2 ** (tentativa - 1))
        raise FalhaFonte(codigo)

    def listar(self):
        resposta = self.solicitar("GET", "ocorrencias")
        try:
            registros = resposta.json()
        except ValueError:
            raise FalhaFonte("resposta_json_invalida") from None
        if not isinstance(registros, list):
            raise FalhaFonte("api_deve_retornar_lista")
        return registros

    def atualizar(self, registro: dict, dados: dict):
        self.solicitar("PATCH", f"ocorrencias/{quote(registro['id'], safe='')}", json=dados)
        registro.update(dados)
