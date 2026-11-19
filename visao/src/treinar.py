"""Treina YOLO11n e avalia os pesos escolhidos no conjunto de teste."""
import argparse
import json
from pathlib import Path

from ultralytics import YOLO

CLASSES = {"buraco", "calcada_quebrada", "obstaculo"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", type=Path, required=True)
    parser.add_argument("--pesos-iniciais", default="yolo11n.pt")
    parser.add_argument("--epocas", type=int, default=60)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--device", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--saida", type=Path, default=Path("runs/treino"))
    args = parser.parse_args()
    dados = args.dados.resolve()
    saida = args.saida.resolve()
    if saida.exists():
        parser.error("--saida já existe. Escolha outro caminho para preservar a execução anterior.")
    if args.epocas < 1 or args.batch < 1 or args.imgsz < 32 or args.workers < 0:
        parser.error("confira épocas, batch, resolução e workers")
    modelo = YOLO(args.pesos_iniciais)
    modelo.train(
        data=str(dados), epochs=args.epocas, imgsz=args.imgsz, batch=args.batch,
        device=args.device, workers=args.workers, seed=args.seed, deterministic=True,
        project=str(saida.parent), name=saida.name, patience=12, plots=True,
    )
    avaliar(saida / "weights" / "best.pt", dados, saida / "teste", args.imgsz, args.device)


def avaliar(pesos, dados, destino, imgsz, device):
    modelo = YOLO(str(pesos))
    classes = modelo.names
    if not classes or any(nome not in CLASSES for nome in classes.values()):
        raise ValueError("classes do modelo fora do contrato Calçada Segura")
    resultado = modelo.val(
        data=str(dados), split="test", imgsz=imgsz, device=device, plots=True,
        project=str(destino.parent), name=destino.name, exist_ok=True,
    )
    caixa = resultado.box
    metricas = {
        "split": "test",
        "map50": float(caixa.map50),
        "map50_95": float(caixa.map),
        "precisao": float(caixa.mp),
        "recall": float(caixa.mr),
        "por_classe": [],
    }
    for posicao, classe in enumerate(caixa.ap_class_index):
        p, r, ap50, ap = caixa.class_result(posicao)
        metricas["por_classe"].append({
            "classe": classes[int(classe)], "precisao": float(p), "recall": float(r),
            "map50": float(ap50), "map50_95": float(ap),
        })
    (destino / "metricas.json").write_text(json.dumps(metricas, indent=2), encoding="utf-8")
    print(json.dumps(metricas, indent=2))


if __name__ == "__main__":
    main()
