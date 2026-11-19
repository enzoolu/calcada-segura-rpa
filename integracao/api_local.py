"""API local para verificar o contrato de Visão e RPA."""
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import UUID
import os
import secrets

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from rpa.src.fontes import gravar_json, ler_json
from rpa.src.triagem import STATUS_REFERENCIA, validar

app = FastAPI(title="Calçada Segura | API local de integração")
DADOS = Path(os.getenv("CALCADA_DEMO_DIR", ".demo"))
TRAVA = Lock()
PAINEL = Path(__file__).with_name("painel")
CAMADA = Path(__file__).resolve().parents[1] / "rpa" / "amostras" / "subprefeituras.geojson"


@app.get("/", include_in_schema=False)
def abrir_painel():
    return FileResponse(PAINEL / "index.html")


@app.get("/painel/subprefeituras.geojson", include_in_schema=False)
def camada_painel():
    return FileResponse(CAMADA, media_type="application/geo+json")


app.mount("/painel", StaticFiles(directory=PAINEL), name="painel")


def exigir_chave(x_api_key: Annotated[str | None, Header()] = None):
    chave = os.getenv("CALCADA_API_KEY")
    if chave and not secrets.compare_digest((x_api_key or "").encode(), chave.encode()):
        raise HTTPException(401, "Chave inválida")


def carregar():
    arquivo = DADOS / "ocorrencias.json"
    return ler_json(arquivo) if arquivo.exists() else []


@app.get("/health")
def health():
    return {"status": "ok", "ambiente": "integracao-local"}


@app.get("/ocorrencias")
def listar(status: str | None = None):
    with TRAVA:
        registros = carregar()
    return [item for item in registros if status is None or item["status"] == status]


@app.post("/ocorrencias", status_code=201, dependencies=[Depends(exigir_chave)])
def registrar(
    id: Annotated[UUID, Form()], origem: Annotated[str, Form()], tipo: Annotated[str, Form()],
    lat: Annotated[float, Form()], lon: Annotated[float, Form()], criado_em: Annotated[str, Form()],
    confianca: Annotated[float | None, Form()] = None,
    inclinacao_pct: Annotated[float | None, Form()] = None,
    vibracao_rms: Annotated[float | None, Form()] = None,
    foto: Annotated[UploadFile | None, File()] = None,
):
    item = {
        "id": str(id), "origem": origem, "tipo": tipo, "lat": lat, "lon": lon,
        "criado_em": criado_em, "confianca": confianca, "inclinacao_pct": inclinacao_pct,
        "vibracao_rms": vibracao_rms, "status": "nova", "prioridade": None, "subprefeitura": None,
        "foto_url": None,
    }
    try:
        validar(item, datetime.now(UTC))
    except ValueError as erro:
        raise HTTPException(422, str(erro)) from None
    with TRAVA:
        registros = carregar()
        existente = next((x for x in registros if x["id"] == item["id"]), None)
        if existente:
            campos = ("origem", "tipo", "lat", "lon", "criado_em", "confianca", "inclinacao_pct", "vibracao_rms")
            if any(existente[campo] != item[campo] for campo in campos):
                raise HTTPException(409, "ID com conteúdo diferente")
            return existente
        if foto:
            dados = foto.file.read(2_000_001)
            if foto.content_type != "image/jpeg" or len(dados) > 2_000_000 or not dados.startswith(b"\xff\xd8"):
                raise HTTPException(422, "Foto deve ser JPEG de até 2 MB")
            pasta = DADOS / "fotos"
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / f"{id}.jpg").write_bytes(dados)
            item["foto_url"] = f"/fotos/{id}"
        gravar_json(DADOS / "ocorrencias.json", [*registros, item])
    return item


class Triagem(BaseModel):
    status: str
    prioridade: str | None
    subprefeitura: str | None
    regra_triagem: str | None = None
    duplicada_de: UUID | None = None


@app.patch("/ocorrencias/{id}", dependencies=[Depends(exigir_chave)])
def atualizar(id: UUID, triagem: Triagem):
    dados = triagem.model_dump(mode="json", exclude_unset=True)
    permitidas = {"priorizada": {"alta"}, "validada": {"media", "baixa"},
                  "duplicada": {None}, "rejeitada": {None}}
    if triagem.status not in permitidas or triagem.prioridade not in permitidas[triagem.status]:
        raise HTTPException(422, "Triagem inválida")
    if triagem.duplicada_de and (triagem.status != "duplicada" or triagem.duplicada_de == id):
        raise HTTPException(422, "Referência de duplicidade inválida")
    with TRAVA:
        registros = carregar()
        for item in registros:
            if item["id"] != str(id):
                continue
            if item["status"] != "nova":
                if all(item.get(campo) == valor for campo, valor in dados.items()):
                    return item
                raise HTTPException(409, "Ocorrência já triada")
            if triagem.duplicada_de and not any(
                referencia["id"] == str(triagem.duplicada_de) and referencia["tipo"] == item["tipo"]
                and referencia["status"] in STATUS_REFERENCIA
                for referencia in registros
            ):
                raise HTTPException(422, "A ocorrência original deve estar triada e ter o mesmo tipo")
            item.update(dados)
            gravar_json(DADOS / "ocorrencias.json", registros)
            return item
    raise HTTPException(404, "Ocorrência ausente")


@app.get("/fotos/{id}")
def obter_foto(id: UUID):
    caminho = DADOS / "fotos" / f"{id}.jpg"
    if not caminho.is_file():
        raise HTTPException(404, "Foto ausente")
    return FileResponse(caminho, media_type="image/jpeg")


@app.get("/relatorios/{subprefeitura}")
def relatorio(subprefeitura: str):
    caminho = Path(os.getenv("CALCADA_RELATORIOS", str(DADOS / "relatorios.json")))
    if caminho.is_file():
        resultado = ler_json(caminho).get(subprefeitura)
        if resultado:
            return resultado
    raise HTTPException(404, "Relatório ausente")
