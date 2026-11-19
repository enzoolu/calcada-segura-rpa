"""Detecta defeitos em vídeo e registra ocorrências confirmadas."""
from base64 import b64decode, b64encode
from collections import deque
from datetime import UTC, datetime
from enum import Enum
import argparse
import json
from math import isfinite
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import cv2
import httpx
from ultralytics import YOLO

from .calibrar import intersecao_sobre_uniao
from .treinar import CLASSES

REJEICOES_DE_DADOS = {400, 409, 413, 415, 422}


class ResultadoEnvio(Enum):
    ACEITO = "aceito"
    REJEITADO = "rejeitado"
    PENDENTE = "pendente"


def converter_fonte(valor: str):
    return int(valor) if valor.isdecimal() else valor


def codificar_foto(quadro):
    altura, largura = quadro.shape[:2]
    fator = min(1, 1280 / max(altura, largura))
    if fator < 1:
        quadro = cv2.resize(quadro, (max(1, round(largura*fator)), max(1, round(altura*fator))),
                            interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok or jpeg.nbytes > 2_000_000:
        raise ValueError("Não foi possível codificar a foto da ocorrência em JPEG de até 2 MB.")
    return b64encode(jpeg).decode("ascii")


def publicar(cliente, evento):
    if not isinstance(evento, dict):
        print("Evento da fila precisa ser um objeto JSON.", file=sys.stderr)
        return ResultadoEnvio.REJEITADO
    arquivos = {campo: (None, str(valor)) for campo, valor in evento.items() if campo != "foto_jpeg"}
    if "foto_jpeg" in evento:
        try:
            jpeg = b64decode(evento["foto_jpeg"], validate=True)
        except (ValueError, TypeError):
            print("Foto inválida no evento da fila.", file=sys.stderr)
            return ResultadoEnvio.REJEITADO
        arquivos["foto"] = ("evidencia.jpg", jpeg, "image/jpeg")
    try:
        resposta = cliente.post("ocorrencias", files=arquivos)
    except httpx.TransportError:
        print("POST /ocorrencias: API indisponível. Evento ficou na fila local.", file=sys.stderr)
        return ResultadoEnvio.PENDENTE
    if resposta.is_success:
        return ResultadoEnvio.ACEITO
    if resposta.status_code in REJEICOES_DE_DADOS:
        print(f"POST /ocorrencias: registro recusado por HTTP {resposta.status_code}.", file=sys.stderr)
        return ResultadoEnvio.REJEITADO
    print(f"POST /ocorrencias: HTTP {resposta.status_code}. Evento ficou na fila local.", file=sys.stderr)
    return ResultadoEnvio.PENDENTE


def reenviar(cliente, fila):
    for pendente in sorted(fila.glob("*.json")):
        try:
            evento = json.loads(pendente.read_text(encoding="utf-8"))
        except ValueError:
            print(f"Evento ilegível na fila: {pendente.name}.", file=sys.stderr)
            resultado = ResultadoEnvio.REJEITADO
        else:
            resultado = publicar(cliente, evento)
        if resultado is ResultadoEnvio.PENDENTE:
            return
        if resultado is ResultadoEnvio.ACEITO:
            pendente.unlink()
            continue
        revisao = fila / "revisao"
        revisao.mkdir(exist_ok=True)
        destino = revisao / pendente.name
        if destino.exists():
            destino = revisao / f"{pendente.stem}-{uuid4()}.json"
        pendente.replace(destino)
        print(f"Evento disponível para revisão em {destino}.", file=sys.stderr)


def ler_limiares(caminho, nomes, padrao):
    if caminho is None:
        return {nome: padrao for nome in nomes.values()}
    try:
        perfil = json.loads(caminho.read_text(encoding="utf-8"))
        limiares = {nome: float(perfil["classes"][nome]["confianca"]) for nome in nomes.values()}
        if set(perfil["classes"]) != set(nomes.values()) or any(not 0 < valor <= 1 for valor in limiares.values()):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("O perfil de confiança deve conter todas as classes dos pesos informados.") from None
    return limiares


def obstaculo_na_faixa(nome, centro_y, obstaculo_ate_y):
    return nome != "obstaculo" or centro_y <= obstaculo_ate_y


def filtrar_deteccoes(resultado, limiares, obstaculo_ate_y=1.0):
    manter = []
    for i, (classe, confianca, centro_y) in enumerate(zip(
        resultado.boxes.cls.tolist(), resultado.boxes.conf.tolist(),
        resultado.boxes.xywhn[:, 1].tolist(), strict=True,
    )):
        nome = resultado.names[int(classe)]
        limiar = limiares.get(nome)
        if limiar is not None and confianca >= limiar and obstaculo_na_faixa(nome, centro_y, obstaculo_ate_y):
            manter.append(i)
    return resultado[manter]


def detecoes_confirmadas(janela):
    """Confirma caixas da mesma classe que se sobrepõem em quadros consecutivos."""
    for nome, deteccoes in janela[-1].items():
        for confianca, caixa in deteccoes:
            caminho = caixa
            for anterior in reversed(list(janela)[:-1]):
                opcoes = anterior.get(nome, ())
                iou, proxima = max(
                    ((intersecao_sobre_uniao(caminho, candidata), candidata) for _, candidata in opcoes),
                    default=(0, None),
                )
                if iou < 0.30:
                    break
                caminho = proxima
            else:
                yield nome, confianca
                break


def rodar(args, cliente):
    cv2.setNumThreads(2)
    modelo = YOLO(args.pesos)
    nomes = modelo.names
    if not nomes or any(nome not in CLASSES for nome in nomes.values()):
        raise ValueError("Informe pesos customizados com as classes do Calçada Segura.")
    limiares = ler_limiares(args.perfil, nomes, args.confianca)
    confianca_minima = min(limiares.values())
    modelo_buraco = YOLO(args.pesos_buraco) if args.pesos_buraco else None
    if modelo_buraco:
        if "buraco" not in modelo_buraco.names.values():
            raise ValueError("Os pesos de buraco precisam detectar a classe buraco.")
        limiares.pop("buraco", None)
    origem = converter_fonte(args.fonte)
    arquivo_local = isinstance(origem, str) and Path(origem).is_file()
    fonte = cv2.VideoCapture(origem)
    if not fonte.isOpened():
        raise ValueError("Não foi possível abrir a câmera ou vídeo informado.")
    fps_origem = fonte.get(cv2.CAP_PROP_FPS)
    fps_saida = fps_origem if isfinite(fps_origem) and fps_origem >= 1 else 25
    janela = deque(maxlen=args.frames)
    ultimo_evento = {}
    ultimo_envio = 0.0
    gravador = None
    total = 0
    eventos = 0
    inicio = time.monotonic()
    fila = args.fila
    fila.mkdir(parents=True, exist_ok=True)
    try:
        while not args.max_frames or total < args.max_frames:
            ok, quadro = fonte.read()
            if not ok:
                break
            resultado = modelo.predict(
                quadro, conf=confianca_minima, imgsz=args.imgsz, device=args.device, verbose=False,
            )[0]
            resultados = [filtrar_deteccoes(resultado, limiares, args.obstaculo_ate_y)]
            if modelo_buraco:
                buracos = modelo_buraco.predict(
                    quadro, conf=min(0.05, args.confianca_buraco), imgsz=args.imgsz_buraco,
                    device=args.device, verbose=False,
                )[0]
                resultados.append(filtrar_deteccoes(buracos, {"buraco": args.confianca_buraco}))
            anotado = quadro
            por_classe = {}
            for resultado in resultados:
                anotado = resultado.plot(img=anotado)
                for classe, confianca, caixa in zip(
                    resultado.boxes.cls.tolist(), resultado.boxes.conf.tolist(), resultado.boxes.xyxyn.tolist(),
                ):
                    nome = resultado.names[int(classe)]
                    por_classe.setdefault(nome, []).append((confianca, caixa))
            if args.obstaculo_ate_y < 1:
                y = min(anotado.shape[0] - 1, round(anotado.shape[0] * args.obstaculo_ate_y))
                cv2.line(anotado, (0, y), (anotado.shape[1] - 1, y), (90, 205, 255), 2)
                cv2.putText(anotado, "Limite da faixa de obstaculos", (8, max(16, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, .48, (90, 205, 255), 1, cv2.LINE_AA)
            janela.append(por_classe)
            agora = time.monotonic()
            tempo_evento = total / fps_saida if arquivo_local else agora
            if args.lat is not None and len(janela) == args.frames:
                for nome, confianca in detecoes_confirmadas(janela):
                    if tempo_evento - ultimo_evento.get(nome, -float("inf")) < args.cooldown:
                        continue
                    evento = {
                        "id": str(uuid4()), "origem": "visao", "tipo": nome,
                        "confianca": round(confianca, 4), "lat": args.lat, "lon": args.lon,
                        "criado_em": datetime.now(UTC).isoformat(),
                    }
                    if args.anexar_foto:
                        evento["foto_jpeg"] = codificar_foto(quadro)
                    destino = fila / f"{evento['id']}.json"
                    temporario = destino.with_suffix(".tmp")
                    temporario.write_text(json.dumps(evento, indent=2), encoding="utf-8")
                    temporario.replace(destino)
                    ultimo_evento[nome] = tempo_evento
                    eventos += 1
                    print(f"Ocorrência confirmada: {nome} ({evento['confianca']:.2f})")
            if cliente and agora - ultimo_envio >= 5:
                reenviar(cliente, fila)
                ultimo_envio = time.monotonic()
            total += 1
            if args.saida:
                if gravador is None:
                    args.saida.parent.mkdir(parents=True, exist_ok=True)
                    altura, largura = anotado.shape[:2]
                    gravador = cv2.VideoWriter(str(args.saida), cv2.VideoWriter_fourcc(*"mp4v"), fps_saida,
                                               (largura, altura))
                    if not gravador.isOpened():
                        raise ValueError("Não foi possível gravar o vídeo de saída.")
                gravador.write(anotado)
            if not args.sem_janela:
                cv2.imshow("Calcada Segura | Visao", anotado)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        if not total:
            raise ValueError("A fonte abriu, mas não entregou quadros.")
        if cliente:
            reenviar(cliente, fila)
        print(f"Quadros: {total} | FPS do processamento: {total/max(time.monotonic()-inicio,.001):.1f} | Eventos: {eventos}")
    finally:
        fonte.release()
        if gravador:
            gravador.release()
        if not args.sem_janela:
            cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pesos", required=True)
    parser.add_argument("--fonte", default="0", help="0, URL de stream ou caminho de vídeo")
    parser.add_argument("--saida", type=Path, help="grava um MP4 anotado")
    parser.add_argument("--sem-janela", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--confianca", type=float, default=0.50)
    parser.add_argument("--perfil", type=Path, help="JSON com limiares por classe, gerado na validação")
    parser.add_argument("--pesos-buraco", help="Pesos alternativos usados somente para detectar buracos")
    parser.add_argument("--confianca-buraco", type=float, default=0.12)
    parser.add_argument("--imgsz-buraco", type=int, default=480)
    parser.add_argument("--obstaculo-ate-y", type=float, default=1.0,
                        help="posição vertical máxima do centro da caixa de obstáculo, como fração da altura")
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--cooldown", type=float, default=20)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default=None)
    parser.add_argument("--api", help="URL base da API de ocorrências")
    parser.add_argument("--lat", type=float, help="latitude fixa da rota de teste")
    parser.add_argument("--lon", type=float, help="longitude fixa da rota de teste")
    parser.add_argument("--anexar-foto", action="store_true", help="guarda e envia um JPEG por ocorrência confirmada")
    parser.add_argument("--fila", type=Path, default=Path("saida/fila"))
    args = parser.parse_args()
    if (args.lat is None) != (args.lon is None):
        parser.error("latitude e longitude devem ser informadas juntas")
    if args.api and args.lat is None:
        parser.error("informe a coordenada da rota de teste para publicar")
    if args.lat is not None and not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        parser.error("coordenadas fora do intervalo WGS84")
    if not (0 < args.confianca <= 1 and args.frames >= 1 and args.cooldown > 0 and args.max_frames >= 0):
        parser.error("valores inválidos para confiança, frames, cooldown ou max-frames")
    if args.pesos_buraco and not (0 < args.confianca_buraco <= 1 and args.imgsz_buraco >= 32):
        parser.error("confira a confiança e a resolução usadas para buracos")
    if not 0 < args.obstaculo_ate_y <= 1:
        parser.error("a faixa de obstáculos deve terminar entre 0 e 1, acima de zero")
    try:
        if args.api:
            chave = os.getenv("CALCADA_API_KEY")
            headers = {"X-API-Key": chave} if chave else {}
            with httpx.Client(base_url=args.api.rstrip("/") + "/", headers=headers, timeout=3, trust_env=False) as cliente:
                rodar(args, cliente)
        else:
            rodar(args, None)
    except (ValueError, OSError, cv2.error, httpx.InvalidURL) as erro:
        print(str(erro), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
