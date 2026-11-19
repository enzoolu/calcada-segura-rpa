# Calçada Segura · Robotic Process Automation

FIAP · Engenharia de Software 4ES · Global Solution CitizenTech 2026.2

O RPA recebe ocorrências por arquivo JSON ou HTTP, confere os dados, localiza a subprefeitura, identifica duplicatas e devolve a prioridade para o painel próprio do protótipo. O relatório territorial organiza os registros aceitos para revisão.

| Integrante | RM |
| --- | --- |
| Enzo Luiz Goulart | 99666 |
| João Pedro Cruz | 98650 |
| Tiago Paulino | 551169 |
| Victor Eid | 98668 |

## Entrega

- [Relatório técnico](rpa/docs/relatorio-rpa.pdf)
- [Vídeo da solução, 1 min 38 s](rpa/evidencias/demonstracao-rpa.mp4)
- [BPMN editável](rpa/docs/triagem.bpmn)
- [Código, regras e instruções](rpa/README.md)
- [Logs de exemplo](rpa/logs/)
- [Evidências da integração](rpa/evidencias/)

## Demonstrar no Windows

Com Python 3.12 instalado, abra o PowerShell na raiz do repositório. O primeiro comando abre o lote sintético e o painel. O segundo processa um trecho real gravado com celular e demonstra a recuperação de uma ocorrência com foto.

```powershell
powershell -ExecutionPolicy Bypass -File .\integracao\Demonstrar-RPA.ps1
powershell -ExecutionPolicy Bypass -File .\integracao\Demonstrar-RPA.ps1 -Campo
```

No modo de campo, confira o registro na fila e pressione Enter no terminal para executar o RPA. O painel muda para Validada e oferece Ver foto e Baixar relatório JSON. Pressione Enter novamente para encerrar a API local. O código da Visão necessário a esse cenário acompanha o repositório.

## Evidências medidas

- O lote sintético gerou 2 priorizadas, 2 validadas e 1 duplicada. A duplicata aponta para a referência original. O relatório da Sé contém 3 registros aceitos.
- Na indisponibilidade da API, o worker registrou 3 tentativas e terminou com código 2.
- Na prova com vídeo de campo, a fila guardou o UUID e a foto até a retomada. Um registro de teste inválido recebeu HTTP 422 e foi separado para revisão. O envio repetido manteve uma única ocorrência. A repetição do RPA processou zero registros.
- O painel consumiu a triagem por HTTP. A foto e o relatório baixado foram conferidos no navegador.

## Testes

Na pasta `rpa`, com as dependências instaladas.

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m unittest discover -s tests -v
```

A API das demonstrações fica restrita ao endereço local. O lote usa dados sintéticos e o cenário de campo usa uma coordenada de teste na Sé. O relatório territorial omite fotos e coordenadas. [Contrato da integração](integracao/CONTRATO.md).
## Repositórios da equipe

- [Visão Computacional](https://github.com/enzoolu/calcada-segura-cv)
- [RPA](https://github.com/enzoolu/calcada-segura-rpa)
