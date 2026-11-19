"""Escolhe limiares na validação e mede o ponto de operação no teste."""
import argparse
import json
from pathlib import Path

from ultralytics import YOLO
import yaml

LIMIARES = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60)
IOU = 0.50


def caixa_xyxy(a):
    cx, cy, w, h = a
    return (cx-w/2, cy-h/2, cx+w/2, cy+h/2)


def intersecao_sobre_uniao(a, b):
    largura = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    altura = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersecao = altura * largura
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersecao / (area_a + area_b - intersecao) if intersecao else 0.0


def contagens(resultados, classe, limiar):
    vp = fp = fn = 0
    for anotacoes, deteccoes in resultados:
        livres = [caixa for categoria, caixa in anotacoes if categoria == classe]
        for categoria, score, caixa in sorted(deteccoes, key=lambda x: -x[1]):
            if categoria != classe or score < limiar:
                continue
            score_iou, indice = max(
                ((intersecao_sobre_uniao(caixa, anotacao), i) for i, anotacao in enumerate(livres)),
                default=(0, -1),
            )
            if score_iou >= IOU:
                vp += 1
                del livres[indice]
            else:
                fp += 1
        fn += len(livres)
    precisao = vp / (vp + fp) if vp + fp else 0
    recall = vp / (vp + fn) if vp + fn else 0
    return {
        "vp": vp, "fp": fp, "fn": fn, "precisao": precisao, "recall": recall,
        "f1": 2 * vp / (2 * vp + fp + fn) if vp + fp + fn else 0,
    }


def inferir(modelo, pasta, split, imgsz, device):
    imagens = sorted(arq for arq in (pasta / "images" / split).iterdir()
                     if arq.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not imagens:
        raise ValueError(f"Nenhuma imagem na divisão {split}.")
    previsoes = modelo.predict(
        [str(p) for p in imagens], conf=min(LIMIARES), imgsz=imgsz, device=device,
        stream=True, batch=8, verbose=False,
    )
    for img, resultado in zip(imagens, previsoes, strict=True):
        txt = pasta / "labels" / split / img.with_suffix(".txt").name
        anotacoes = []
        for linha in txt.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                classe, *caixa = linha.split()
                anotacoes.append((int(classe), caixa_xyxy(tuple(map(float, caixa)))))
        deteccoes = [(int(c), score, caixa) for c, score, caixa in zip(
            resultado.boxes.cls.tolist(), resultado.boxes.conf.tolist(),
            resultado.boxes.xyxyn.tolist(), strict=True,
        )]
        yield anotacoes, deteccoes


def calibrar(pesos, pasta, imgsz, device):
    modelo = YOLO(str(pesos))
    dados = yaml.safe_load((pasta / "data.yaml").read_text(encoding="utf-8"))
    nomes = dados["names"]
    if isinstance(nomes, list):
        nomes = dict(enumerate(nomes))
    if nomes != modelo.names:
        raise ValueError("Os IDs e nomes das classes do modelo e do conjunto devem coincidir.")
    validacao = list(inferir(modelo, pasta, "val", imgsz, device))
    teste = list(inferir(modelo, pasta, "test", imgsz, device))
    perfil = {"imgsz": imgsz, "iou": IOU, "classes": {}}
    for classe, nome in nomes.items():
        if not any(c == classe for anotacoes, _ in validacao for c, _ in anotacoes):
            raise ValueError(f"A validação não contém exemplos de {nome}.")
        limiar, desempenho = max(
            ((limiar, contagens(validacao, classe, limiar)) for limiar in LIMIARES),
            key=lambda item: (item[1]["f1"], item[0]),
        )
        perfil["classes"][nome] = {
            "confianca": limiar, "validacao": desempenho, "teste": contagens(teste, classe, limiar),
        }
    return perfil


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pesos", type=Path, required=True)
    parser.add_argument("--dados", type=Path, required=True, help="Pasta no formato images/train, labels/train etc.")
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=384)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    perfil = calibrar(args.pesos, args.dados, args.imgsz, args.device)
    args.saida.write_text(json.dumps(perfil, indent=2, ensure_ascii=False), encoding="utf-8")
