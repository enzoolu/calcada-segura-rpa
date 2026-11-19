"use strict";

const $ = (id) => document.getElementById(id);
const rotulos = {
  nova: "Nova", priorizada: "Prioridade alta", validada: "Validada", duplicada: "Duplicada",
  encaminhada: "Encaminhada", resolvida: "Resolvida", rejeitada: "Rejeitada",
  buraco: "Buraco", calcada_quebrada: "Calçada quebrada", obstaculo: "Obstáculo",
  rampa_irregular: "Rampa irregular", trepidacao: "Trepidação", degrau: "Degrau",
};
const indicadores = ["nova", "priorizada", "validada", "duplicada"];
const regras = {
  mesmo_tipo_ate_15m_em_30d: "Mesmo tipo a até 15 m e 30 dias",
  buraco_degrau_confianca_alta: "Buraco ou degrau com confiança de pelo menos 0,75",
  rampa_acima_do_limiar: "Rampa com inclinação acima do limiar de 8,33%",
  tipo_de_prioridade_media: "Tipo classificado com prioridade média",
  tipo_de_prioridade_baixa: "Tipo classificado com prioridade baixa",
};
const nomesSubprefeituras = {
  "ARICANDUVA-FORMOSA-CARRAO": "Aricanduva / Formosa / Carrão",
  "BUTANTA": "Butantã",
  "CAPELA DO SOCORRO": "Capela do Socorro",
  "CASA VERDE-LIMAO-CACHOEIRINHA": "Casa Verde / Limão / Cachoeirinha",
  "FREGUESIA-BRASILANDIA": "Freguesia / Brasilândia",
  "JACANA-TREMEMBE": "Jaçanã / Tremembé",
  "M BOI MIRIM": "M’Boi Mirim",
  "PIRITUBA-JARAGUA": "Pirituba / Jaraguá",
  "SAO MATEUS": "São Mateus",
  "SAO MIGUEL": "São Miguel",
  "SE": "Sé",
};
const svg = "http://www.w3.org/2000/svg";
const mapa = $("mapa");
const camada = svgElemento("g");
const pontos = svgElemento("g");
mapa.append(camada, pontos);
let geometria;
let atualizando = false;
let ultimoLote;

function nomeRegiao(codigo) {
  return nomesSubprefeituras[codigo] ?? codigo.toLocaleLowerCase("pt-BR").replace(
    /(^|[ -])\p{L}/gu, (inicio) => inicio.toLocaleUpperCase("pt-BR"),
  );
}

function svgElemento(nome, atributos = {}) {
  const no = document.createElementNS(svg, nome);
  Object.entries(atributos).forEach(([chave, valor]) => no.setAttribute(chave, valor));
  return no;
}

function projetar(lon, lat) {
  return [30 + ((lon + 46.84) / .49) * 340, 18 + ((-23.33 - lat) / .70) * 374];
}

async function obter(rota, ausente = null) {
  const resposta = await fetch(rota, {cache: "no-store", signal: AbortSignal.timeout(4500)});
  if (ausente !== null && resposta.status === 404) return ausente;
  if (!resposta.ok) throw Error(resposta.status);
  return resposta.json();
}

function desenharLimites(dados) {
  camada.replaceChildren();
  for (const item of dados.features) {
    const poligonos = item.geometry.type === "Polygon" ? [item.geometry.coordinates] : item.geometry.coordinates;
    const d = poligonos.flat().map((anel) => {
      const coordenadas = anel.map(([lon, lat]) => projetar(lon, lat).map((num) => num.toFixed(1)).join(" "));
      return "M" + coordenadas.join("L") + "Z";
    }).join("");
    camada.append(svgElemento("path", {d, "fill-rule": "evenodd"}));
  }
}

function desenharPontos(registros) {
  pontos.replaceChildren();
  const ordem = {duplicada: 0, nova: 1, validada: 2, priorizada: 3};
  const mapeados = registros.filter((x) => Number.isFinite(x.lat) && Number.isFinite(x.lon) && x.status !== "rejeitada");
  mapeados.sort((a, b) => (ordem[a.status] ?? 0) - (ordem[b.status] ?? 0));
  for (const item of mapeados) {
    const [cx, cy] = projetar(item.lon, item.lat);
    const classe = item.status === "priorizada" ? "alta" : (indicadores.includes(item.status) ? item.status : "validada");
    const no = svgElemento("circle", {cx, cy, r: 7, class: classe});
    const titulo = svgElemento("title");
    titulo.textContent = (rotulos[item.tipo] || item.tipo) + " · " + (rotulos[item.status] || item.status);
    no.append(titulo);
    pontos.append(no);
  }
}

function atualizarRegistros(registros) {
  for (const status of indicadores) {
    $(status).textContent = registros.filter((x) => x.status === status).length;
  }
  const ids = new Set(registros.map((item) => item.id));
  const linhas = registros.map((item) => {
    const linha = document.createElement("tr");
    linha.id = "ocorrencia-" + item.id;
    linha.tabIndex = -1;
    const tipo = linha.insertCell();
    tipo.textContent = rotulos[item.tipo] ?? item.tipo;
    const estado = document.createElement("span");
    estado.className = "pilula " + (item.status === "priorizada" ? "alta" : item.status);
    estado.textContent = rotulos[item.status] ?? item.status;
    linha.insertCell().append(estado);
    linha.insertCell().textContent = item.subprefeitura ? nomeRegiao(item.subprefeitura) : "—";
    const decisao = linha.insertCell();
    decisao.textContent = Object.hasOwn(regras, item.regra_triagem)
      ? regras[item.regra_triagem] : (item.regra_triagem || "—");
    if (item.status === "duplicada" && ids.has(item.duplicada_de)) {
      const original = document.createElement("a");
      original.href = "#ocorrencia-" + item.duplicada_de;
      original.textContent = "Ver original";
      decisao.append(document.createElement("br"), original);
    }
    const evidencia = linha.insertCell();
    if (item.foto_url === `/fotos/${item.id}`) {
      const link = document.createElement("a");
      link.href = item.foto_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Ver foto";
      evidencia.append(link);
    } else {
      evidencia.textContent = "—";
    }
    return linha;
  });
  if (!linhas.length) {
    const linha = document.createElement("tr");
    const celula = linha.insertCell();
    celula.colSpan = 5;
    celula.textContent = "Nenhuma ocorrência registrada.";
    linhas.push(linha);
  }
  $("registros").replaceChildren(...linhas);
  const seletor = $("regiao");
  const anterior = seletor.value;
  const regioes = [...new Set(registros.map((x) => x.subprefeitura).filter(Boolean))].sort();
  seletor.replaceChildren(...regioes.map((codigo) => new Option(nomeRegiao(codigo), codigo)));
  seletor.disabled = !regioes.length;
  if (regioes.includes(anterior)) seletor.value = anterior;
  desenharPontos(registros);
}

async function atualizarRelatorio() {
  const nome = $("regiao").value;
  const rota = "relatorios/" + encodeURIComponent(nome);
  const download = $("baixar-relatorio");
  if (download.getAttribute("href") !== rota) download.hidden = true;
  try {
    const dados = nome ? await obter(rota, {}) : {};
    if (nome !== $("regiao").value) return;
    const temRelatorio = Number.isInteger(dados.total);
    const mensagem = temRelatorio
      ? dados.total + (dados.total === 1 ? " ocorrência aceita no relatório." : " ocorrências aceitas no relatório.")
      : "Sem relatório no lote atual.";
    if ($("relatorio").textContent !== mensagem) $("relatorio").textContent = mensagem;
    if (temRelatorio) {
      download.href = rota;
      download.download = "relatorio-" + nome.toLocaleLowerCase("pt-BR").replaceAll(" ", "-") + ".json";
    }
    download.hidden = !temRelatorio;
  } catch {
    if (nome !== $("regiao").value) return;
    download.hidden = true;
    $("relatorio").textContent = "Relatório temporariamente indisponível.";
  }
}

async function atualizar() {
  if (atualizando) return;
  atualizando = true;
  $("atualizar").disabled = true;
  try {
    if (!geometria) {
      geometria = await obter("painel/subprefeituras.geojson");
      desenharLimites(geometria);
    }
    const registros = await obter("ocorrencias");
    const lote = JSON.stringify(registros);
    if (lote !== ultimoLote) {
      atualizarRegistros(registros);
      ultimoLote = lote;
    }
    await atualizarRelatorio();
    const mensagem = registros.length + (registros.length === 1 ? " ocorrência consultada." : " ocorrências consultadas.");
    if ($("info").textContent !== mensagem) $("info").textContent = mensagem;
    $("info").classList.remove("falha");
  } catch {
    $("baixar-relatorio").hidden = true;
    $("info").textContent = "API indisponível. O painel preserva a última consulta.";
    $("info").classList.add("falha");
  } finally {
    atualizando = false;
    $("atualizar").disabled = false;
  }
}

$("atualizar").addEventListener("click", atualizar);
$("regiao").addEventListener("change", atualizarRelatorio);
atualizar();
window.setInterval(() => {
  if (document.visibilityState === "visible") atualizar();
}, 5000);
