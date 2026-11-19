# Contrato para conectar Visão, RPA e dashboard

O contrato abaixo é implementado pela API própria em `integracao/api_local.py` e usado pela Visão, pela triagem e pelo painel.

| Operação | Requisição e comportamento usados nesta entrega |
| --- | --- |
| Criar | `POST /ocorrencias`, multipart. Campos `id` (UUID do cliente), `origem`, `tipo`, `lat`, `lon`, `criado_em` (ISO 8601 com fuso). `confianca` obrigatória para Visão. `inclinacao_pct` obrigatória para rampa, `vibracao_rms` e arquivo `foto` opcionais. Sucesso retorna 2xx. O mesmo UUID e corpo deve sobreviver a retentativas. |
| Listar | `GET /ocorrencias` devolve array JSON. Inclui as novas e as já triadas para a comparação histórica. `?status=nova` funciona para listar a fila. Se houver paginação, adaptar o cliente RPA para buscar todas as páginas qualificadas. |
| Triar | `PATCH /ocorrencias/{id}` com JSON `status`, `prioridade` e `subprefeitura`. O RPA envia `regra_triagem` e, para duplicatas, `duplicada_de` com o UUID da referência. Esses campos são opcionais no contrato. O envio repetido com os mesmos dados é idempotente. A transição parte de `nova`. Prioridade é nula em rejeitadas e duplicadas. |
| Relatório | `GET /relatorios/{subprefeitura}`, alimentado pelo `relatorios.json` gerado pelo RPA. O painel usa essa rota para exibir o total e baixar o JSON da região selecionada. |
| Autorização entre componentes | Header `X-API-Key`, lido de `CALCADA_API_KEY` quando a chave é configurada no ambiente. Os scripts de demonstração inicializam uma instância ligada ao endereço local, com dados descartáveis. |

**Status de saída.** `priorizada` (alta), `validada` (média/baixa), `duplicada` e `rejeitada`. As subprefeituras vêm com os nomes da camada GeoSampa normalizada no pacote, por exemplo `SE` e `MOOCA`.

**Privacidade.** A câmera envia os metadados confirmados. Ao passar `--anexar-foto`, ela inclui um JPEG do quadro da confirmação. A fila local guarda a foto e o UUID juntos até a API aceitar o envio. O cliente recebe coordenadas informadas pelo operador. Na prova de campo, usamos um ponto de teste na Sé.

Recusas de dados no POST e arquivos ilegíveis são movidos para `revisao/` dentro da fila. O envio segue para o próximo registro. Falhas de conexão, indisponibilidade da API e falhas de credencial preservam os registros pendentes para uma nova tentativa.
