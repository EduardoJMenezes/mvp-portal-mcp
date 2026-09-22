# mvp-portal-mcp

O adaptador MCP da plataforma: as tools que o Claude usa para operar o curso.

```
Claude ─► FastMCP (/mcp) ─► HTTP /comandos/* ─► API em Java ─► PostgreSQL
Professor ─► /enviar/<token> ─► lê o .docx ou os prints ─► HTTP /interno/*
```

Este processo **não tem banco**. Tudo que é estado atravessa a ponte HTTP até
a API ([mvp-portal-aluno](https://github.com/EduardoJMenezes/mvp-portal-aluno)),
que relê o papel de quem pede a cada comando. O que mora aqui é o que precisa
de biblioteca que só existe em Python: ler o Vimeo, o `.docx` (com LibreOffice
para as figuras antigas) e recortar figura de print com o Pillow.

## Rodando

Pré-requisitos: Python 3.11+ e a API no ar (`API_BASE_URL`).

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env            # API_BASE_URL, SERVICO_TOKEN, VIMEO_ACCESS_TOKEN
.venv/bin/python -m app.servir  # http://127.0.0.1:8000/mcp
```

Testes: precisam de um Postgres `plataforma_mvp_test` e do jar da API
(`./mvnw -q package -DskipTests` no repositório dela), apontado por `API_JAR`.
O Flyway da API cria o schema; `tests/modelos.py` é só um espelho para semear.

```bash
API_JAR=../mvp-portal-aluno/target/api-0.0.1-SNAPSHOT.jar .venv/bin/python -m pytest -q
```

## Documentação

| documento | para quê |
|---|---|
| [docs/MCP-OAUTH.md](docs/MCP-OAUTH.md) | conector remoto (claude.ai) com login no GitHub |
| [docs/IMPORTADOR-SIMULADO.md](docs/IMPORTADOR-SIMULADO.md) | o `.docx` e os prints virando simulado |
| [docs/VIMEO.md](docs/VIMEO.md) | token, escopos, embed unlisted, filtro de rede |
| [CLAUDE.md](CLAUDE.md) | contexto para trabalhar neste repositório |
