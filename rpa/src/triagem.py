"""Regras de triagem de ocorrências do Calçada Segura."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import asin, cos, isfinite, radians, sin, sqrt
from urllib.parse import urlsplit
from uuid import UUID

TIPOS = {"buraco", "calcada_quebrada", "obstaculo", "rampa_irregular", "trepidacao", "degrau"}
ORIGENS = {"robo", "visao", "cidadao"}
STATUS_REFERENCIA = {"validada", "priorizada", "encaminhada", "resolvida"}
RAIO_METROS = 15
JANELA = timedelta(days=30)
LIMIAR_RAMPA = 8.33
LIMIAR_CONFIANCA = 0.75


@dataclass(frozen=True)
class Ocorrencia:
    id: str
    origem: str
    tipo: str
    lat: float
    lon: float
    criado_em: datetime
    confianca: float | None
    inclinacao_pct: float | None


def identificador(registro: dict) -> str:
    try:
        return str(UUID(registro.get("id")))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("id_invalido") from None


def numero(registro: dict, campo: str, minimo: float, maximo: float, opcional=False):
    valor = registro.get(campo)
    if opcional and valor is None:
        return None
    if type(valor) not in (int, float) or not minimo <= valor <= maximo or not isfinite(valor):
        raise ValueError(f"{campo}_invalido")
    return float(valor)


def validar(registro: dict, agora: datetime) -> Ocorrencia:
    origem, tipo = registro.get("origem"), registro.get("tipo")
    if not isinstance(origem, str) or origem not in ORIGENS:
        raise ValueError("origem_invalida")
    if not isinstance(tipo, str) or tipo not in TIPOS:
        raise ValueError("tipo_invalido")
    try:
        criado_em = datetime.fromisoformat(registro.get("criado_em"))
        if criado_em.tzinfo is None or criado_em.astimezone(UTC) > agora + timedelta(minutes=5):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError("data_invalida") from None

    foto = registro.get("foto_url")
    if foto is not None:
        try:
            url = urlsplit(foto) if isinstance(foto, str) else None
            relativa = bool(url and foto.startswith("/") and not foto.startswith("//") and not url.netloc)
            absoluta = bool(url and url.scheme in {"http", "https"} and url.hostname and not url.username)
            if not (relativa or absoluta):
                raise ValueError
        except ValueError:
            raise ValueError("foto_url_invalida") from None

    ocorrencia = Ocorrencia(
        identificador(registro), origem, tipo,
        numero(registro, "lat", -90, 90), numero(registro, "lon", -180, 180),
        criado_em.astimezone(UTC), numero(registro, "confianca", 0, 1, opcional=True),
        numero(registro, "inclinacao_pct", -100, 100, opcional=True),
    )
    numero(registro, "vibracao_rms", 0, 1e6, opcional=True)
    if origem == "visao" and ocorrencia.confianca is None:
        raise ValueError("confianca_ausente")
    if tipo == "rampa_irregular" and ocorrencia.inclinacao_pct is None:
        raise ValueError("inclinacao_ausente")
    return ocorrencia


def distancia_m(a: Ocorrencia, b: Ocorrencia) -> float:
    lat_a, lat_b = map(radians, (a.lat, b.lat))
    delta_lon = radians(b.lon - a.lon)
    haversine = sin((lat_b - lat_a) / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 2 * 6_371_008.8 * asin(sqrt(min(1, haversine)))


def referencia_duplicada(ocorrencia: Ocorrencia, referencias: list[Ocorrencia]) -> str | None:
    candidatas = []
    for outra in referencias:
        if outra.id == ocorrencia.id or outra.tipo != ocorrencia.tipo:
            continue
        if abs(ocorrencia.criado_em - outra.criado_em) > JANELA:
            continue
        distancia = distancia_m(ocorrencia, outra)
        if distancia <= RAIO_METROS:
            candidatas.append((distancia, outra.criado_em, outra.id))
    return min(candidatas)[2] if candidatas else None


def e_duplicada(ocorrencia: Ocorrencia, referencias: list[Ocorrencia]) -> bool:
    return referencia_duplicada(ocorrencia, referencias) is not None


def prioridade_e_regra(ocorrencia: Ocorrencia) -> tuple[str, str]:
    if ocorrencia.tipo in {"buraco", "degrau"} and (ocorrencia.confianca or 0) >= LIMIAR_CONFIANCA:
        return "alta", "buraco_degrau_confianca_alta"
    if ocorrencia.tipo == "rampa_irregular" and abs(ocorrencia.inclinacao_pct or 0) > LIMIAR_RAMPA:
        return "alta", "rampa_acima_do_limiar"
    if ocorrencia.tipo in {"trepidacao", "buraco", "degrau", "rampa_irregular"}:
        return "media", "tipo_de_prioridade_media"
    return "baixa", "tipo_de_prioridade_baixa"


def priorizar(ocorrencia: Ocorrencia) -> str:
    return prioridade_e_regra(ocorrencia)[0]
