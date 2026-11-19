# Calçada Segura · Robotic Process Automation

**FIAP · Engenharia de Software 4ES · GS CitizenTech 2026.2**  
Enzo Luiz Goulart · RM 99666, João Pedro Cruz · RM 98650, Victor Eid · RM 98668 e Tiago Paulino · RM 551169. O vídeo e as evidências deste MVP estão em [evidencias](evidencias/). A demonstração usa a API e o painel próprios.

A automação recebe ocorrências da câmera, do robô ou de cidadãos. Valida dados, encontra a subprefeitura, arquiva a decisão de duplicidade, devolve o status e gera a lista de ocorrências para revisão. Trabalha em arquivo JSON ou via API.

## Executar

Na pasta `rpa`, com Python 3.11 ou 3.12:

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m src.rodar --entrada amostras/ocorrencias.json
py -3.12 -m unittest discover -s tests -v
```

A amostra contém seis registros sintéticos e produz duas priorizadas, duas validadas, uma duplicada e uma rejeitada. O retorno é `1` nessa rodada porque a rejeição conta como falha de dados. Para reprocessar a partir de outra entrada, indique uma pasta nova via `--saida`; rodadas seguintes na mesma pasta retomam o estado do primeiro arquivo.

Com a API ativa:

```powershell
$env:CALCADA_API_KEY = 'cole-a-chave-do-ambiente'
py -3.12 -m src.rodar --api http://127.0.0.1:8000 --saida ../.demo
```

Agende esse comando com o Agendador de Tarefas do Windows ou cron, usando a raiz do RPA como diretório de trabalho. Programe uma execução por vez. O comando termina com `0` (sucesso), `1` (lote executado com rejeição ou falha por registro) ou `2` (lote interrompido).

## Regras e resiliência

| Caso | Decisão |
| --- | --- |
| Identificador, tipos, coordenadas, data ou medidas inválidos | Rejeita se houver UUID que permita registrar a decisão. Sem UUID válido, registra a falha e segue. |
| Coordenada fora da camada | Rejeita. Se o ponto pertencer a mais de uma região, registra revisão manual e mantém a ocorrência na fila. |
| Mesmo tipo, até 15 m, até 30 dias | Marca `duplicada`. Compara com a base já triada e com os itens aceitos no lote. Preserva o registro. |
| Buraco ou degrau com confiança ≥ 0,75 | Alta. |
| Rampa identificada com inclinação absoluta acima de 8,33% | Alta. Parâmetro de triagem do protótipo; o laudo exige medição e revisão técnica. |
| Trepidação, buraco/degrau com confiança inferior ou rampa abaixo do limiar | Média. Os demais tipos ficam com baixa. |
| Rede indisponível, 408, 429 ou 5xx | Até três tentativas com pausas de 1 e 2 segundos. O lote grava a falha de leitura, ou segue para o próximo registro quando falha apenas um PATCH. |
| 4xx definitivo | Registra o código. Um PATCH conflitante deixa a nova decisão para revisão. |

O painel mostra a regra aplicada em cada linha que já passou pela triagem. Para uma duplicata, **Ver original** destaca a ocorrência de referência. Se houver mais de uma referência dentro do raio e da janela, o RPA vincula a mais próxima. A prova automática confere esse vínculo na API.

A camada distribuída contém a geometria das 32 subprefeituras, obtida via [WFS do GeoSampa](https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=geoportal:subprefeitura&outputFormat=application%2Fjson&srsName=EPSG%3A4326), com propriedades reduzidas ao nome oficial do dado. Metadados em [Subprefeituras · Prefeitura de São Paulo](https://metadados.geosampa.prefeitura.sp.gov.br/geonetwork/srv/api/records/289e684e-b2be-453d-8d2d-68ec629cd3dc).

`logs/` tem três execuções reais do código com dados sintéticos. Os logs guardam contagens, horário, etapa e códigos de erro. `saida/relatorios.json` traz resumo por subprefeitura sem coordenadas, fotos ou nomes de pessoas. O endereço da foto é validado sintaticamente pelo worker. O armazenamento da mídia e sua disponibilidade cabem ao serviço que a recebeu.

## Demonstração local e vídeo

Na raiz do projeto, rode `python -m integracao.demonstrar_rpa` com as dependências
de RPA e integração instaladas. Execute o lote, confira o painel, verifique o
relatório e simule a falha. Use `--automatico` para rodar as mesmas verificações
sem abrir o navegador. Os registros ficam em `.demo/`.

Na prova de campo, a Visão confirmou `calcada_quebrada` com a API desligada. Depois da retomada, um registro de teste inválido recebeu HTTP 422 e foi separado para revisão. O envio válido preservou o UUID e a foto e acabou no relatório da Sé com coordenadas de teste. A repetição do envio manteve um único registro.

Na raiz, o comando abaixo executa o recorte incluído e abre o painel antes da triagem. Pressione Enter para executar o RPA. A tela atualiza automaticamente e permite abrir a foto e baixar o relatório JSON da seleção. Pressione Enter novamente para encerrar. Os arquivos gerados ficam em `.demo/`.

```powershell
powershell -ExecutionPolicy Bypass -File .\integracao\Demonstrar-RPA.ps1 -Campo
```

[Vídeo final](evidencias/demonstracao-rpa.mp4) com narração sintetizada e legendas em português. Mostra o lote no painel, a regra de duplicidade, o relatório por subprefeitura, a falha de leitura e a recuperação da fila com uma ocorrência vinda da Visão.
