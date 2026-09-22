# Integração própria com o Vimeo — pesquisa de viabilidade

Pesquisa feita antes de qualquer código, como pede o §72 da especificação de
longo prazo: ler a documentação oficial da Vimeo REST API, montar a matriz de
capacidades e só então propor implementação.

## Resposta curta

**Dá para atingir o objetivo com a API oficial.** Descobrir o acervo com
subpastas, importar milhares de vídeos com paginação, manter a identidade por
`vimeo_video_id`, detectar vídeo removido, respeitar o rate limit, restringir o
embed aos nossos domínios e fazer upload e replace têm endpoint documentado.

Cinco pontos mudam o desenho:

1. **Pastas não têm ordem manual na API.** A ordem da importação vem do título, de revisão humana ou de showcase (até 100 vídeos).
2. **Legenda automática só existe para vídeos enviados depois de 25/05/2022**, e gerar transcrição sob demanda é recurso do Enterprise.
3. **A Analytics API é exclusiva do Enterprise.** Métrica de vídeo por aluno virá do Player SDK.
4. **Webhooks estão na referência, mas o guia é fechado e a Central de Ajuda contradiz.** A base será polling com reconciliação.
5. **Não listado + embed só nos nossos domínios exige plano Starter ou superior.**

## Documentos

| # | Documento | Conteúdo |
|---|---|---|
| 1 | [Matriz de capacidades](01-matriz-de-capacidades.md) | 70 capacidades com endpoint, escopo, plano, limitações, necessidade de POC e fonte; respostas às 55 perguntas do §64 |
| 2 | [Gaps e ajustes](02-gaps-e-ajustes.md) | O que a API não entrega e o que faremos; arquitetura × API real; estados da reconciliação; dependências de plano; decisões pendentes |
| 3 | [Plano de implementação](03-plano-de-implementacao.md) | Arquivos, modelo de dados, transporte HTTP, fluxos, tools MCP, roadmap com portões e testes |
| 4 | [Interface do cliente Vimeo](04-vimeo-client.md) | Protocolos só com métodos suportados, DTOs, erros e conjuntos de `fields` |
| 5 | [Plano de POC](05-plano-de-poc.md) | Chamadas reais de leitura, escrita em pasta de teste, upload e webhooks, com critério de saída |

## Método

- Só fontes oficiais: a referência de developer.vimeo.com (OpenAPI da API 3.4.9, embutida nas páginas), os guias de developer.vimeo.com e a Central de Ajuda. Cada linha da matriz cita a fonte.
- Conflitos entre fontes estão marcados com ❓ e viraram passos de POC.
- Nenhuma chamada foi feita contra a conta real.

## Antes de começar a implementar

1. Descobrir o plano da conta Vimeo do professor e se é conta de time.
2. Rodar a POC de leitura (R1–R18).
3. Decidir a estratégia de ordem da importação.
4. Introduzir Alembic: o banco do Railway já tem dados e o `create_all` não altera tabelas.

## Observações

- A especificação original pode ser salva nesta pasta, para que as referências a §N tenham onde apontar.
- `docs/VIMEO.md` e `backend/app/vimeo/client.py` afirmam que não existe MCP oficial do Vimeo. Existe, em beta público (`https://mcp.vimeo.com/mcp`), mas a decisão desta especificação é não depender dele. O texto antigo precisa ser corrigido quando esses arquivos forem mexidos.
