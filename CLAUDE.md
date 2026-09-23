# mvp-portal-mcp

O adaptador MCP da plataforma educacional. FastMCP em `app/mcp_server/`, a
página de envio de `.docx`/prints em `app/api/envio_routes.py` +
`app/paginas/enviar.html`, e as integrações (Vimeo, leitor de `.docx`, Pillow).

## A regra que não muda

**Nenhuma tool toca o banco.** Toda leitura e escrita passa por
`app/mcp_server/api.py` — `comando(nome, **kw)` bate em `/comandos/<nome>` da
API em Java com `X-Servico` (segredo) e `X-Operador` (quem o OAuth
autenticou). O Java relê o papel no banco e fixa o canal MCP: não existe campo
para o adaptador se passar pelo professor no navegador.

"A IA propõe. O humano aprova. O backend publica." — `publicar_rascunho` só
publica depois do aceite do professor (elicitation) ou da aprovação no portal;
quem faz valer isso é a API (`urn:plataforma:aprovacao-necessaria`).

## Onde está o resto

* A API, o portal e o schema: [mvp-portal-aluno](https://github.com/EduardoJMenezes/mvp-portal-aluno).
* O Python antigo (portal em FastAPI, congelado): mvp-portal-legado.

## Testes

`tests/conftest.py` sobe o jar da API (`API_JAR`) com Flyway contra um banco
`*_test` e semeia com `tests/modelos.py` (espelho SQLAlchemy, dev-only). Sem
`API_JAR`, os testes que dependem da ponte pulam; na CI, viram erro. A CI
constrói a API a partir do repositório dela em `API_REF` (fixado de propósito).

## Produção (Railway, serviço `mcp`)

Variáveis: `API_BASE_URL` (endereço interno da API), `SERVICO_TOKEN` (o mesmo
da API), `MCP_BASE_URL` (domínio público deste serviço), `PORTAL_URL` (domínio do portal, para onde
vai o "aprove no portal"), `VIMEO_ACCESS_TOKEN`,
as três `MCP_OAUTH_*` e `DATABASE_URL` (só para o proxy OAuth guardar o
registro do conector entre deploys). Healthcheck em `/saude`.
