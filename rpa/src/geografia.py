"""Associa coordenadas WGS84 a polígonos de subprefeituras."""
from pathlib import Path

from shapely import make_valid
from shapely.geometry import Point, shape

from .fontes import ler_json


class Subprefeituras:
    def __init__(self, caminho: Path, campo_nome: str):
        geojson = ler_json(caminho)
        if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
            raise ValueError("GeoJSON precisa ser uma FeatureCollection")
        self.poligonos = []
        for feicao in geojson["features"]:
            nome = feicao["properties"].get(campo_nome)
            geometria = shape(feicao["geometry"])
            if not isinstance(nome, str) or not nome.strip():
                raise ValueError(f"campo de nome ausente ou vazio: {campo_nome}")
            if geometria.geom_type not in {"Polygon", "MultiPolygon"} or geometria.is_empty:
                raise ValueError("camada deve conter polígonos")
            oeste, sul, leste, norte = geometria.bounds
            if not (-180 <= oeste < leste <= 180 and -90 <= sul < norte <= 90):
                raise ValueError("exporte a camada em WGS84 (EPSG:4326), longitude antes de latitude")
            self.poligonos.append((nome.strip(), make_valid(geometria)))
        if not self.poligonos:
            raise ValueError("camada sem feições")

    def localizar(self, lat: float, lon: float) -> str:
        ponto = Point(lon, lat)
        candidatos = {nome for nome, poligono in self.poligonos if poligono.covers(ponto)}
        if len(candidatos) == 1:
            return candidatos.pop()
        if candidatos:
            raise ValueError("subprefeitura_ambigua")
        raise ValueError("fora_da_area_mapeada")
