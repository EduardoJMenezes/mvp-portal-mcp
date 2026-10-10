"""Autenticação do MCP — duas portas, uma identidade.

O servidor aceita credencial de duas origens, porque os clientes MCP não
concordam entre si:

* **Token Bearer opaco**, emitido por `scripts/token_mcp.py`. É o que o Claude
  Code e os scripts usam: um header fixo no arquivo de configuração.
* **OAuth com login no GitHub**, para conector remoto (claude.ai). Lá não
  existe campo para header: ou o servidor fala OAuth, ou não conecta.

As duas terminam no mesmo lugar — um `AccessToken` cujos claims dizem QUEM é a
pessoa. O token não carrega permissão nenhuma; o que ela pode fazer continua
sendo decidido pelo papel dela no backend, a cada chamada. O GitHub é só a
porta de entrada: quem não estiver cadastrado como ADMIN ou GERENCIADOR na
plataforma não abre sessão, por mais válido que seja o login dele.

Ver [docs/MCP-OAUTH.md](../../../docs/MCP-OAUTH.md). A simplificação que a
seção 5 do MVP permitiu (token opaco em vez de servidor de autorização)
continua valendo para o Claude Code; o caminho do OAuth é o que a arquitetura
final pede.
"""

from __future__ import annotations

import logging

import anyio
from fastmcp.server.auth import AccessToken, AuthProvider, MultiAuth, TokenVerifier
from fastmcp.server.auth.providers.github import GitHubProvider

from app.config import get_settings
from app.identidade import Canal, Identidade

logger = logging.getLogger("plataforma.mcp.auth")

# O escopo que o servidor exige de toda sessão. Vem do GitHub (é lá que ele
# significa alguma coisa: ler o perfil de quem entrou), mas quem exige é o
# middleware do FastMCP, de qualquer credencial. Por isso o token opaco também
# o carrega: ele identifica um operador já conferido no banco, então satisfaz
# o que o servidor pede. Sem isso, ligar o OAuth derrubaria o Claude Code com
# "Insufficient scope".
ESCOPOS_EXIGIDOS = ["read:user"]


def _interno(rota: str, **corpo) -> dict | None:
    """Pergunta à API quem é o operador por trás de uma credencial.

    O import mora aqui dentro porque `api.py` importa `identidade_da_sessao`
    deste módulo: no topo, os dois se importariam em círculo.
    """
    from app.mcp_server.api import interno

    return interno(rota, **corpo)


# --- porta 1: token opaco da plataforma --------------------------------------


def _consultar(token: str) -> AccessToken | None:
    """Quem a API reconhece por trás do token Bearer.

    O token vai em claro: o banco guarda só o SHA-256, e quem calcula é o lado
    de lá. A conferência do papel também é de lá — aluno com token válido não
    abre sessão, e assim a credencial dele nem chega a ver o catálogo.
    """
    operador = _interno("token", token=token)
    if operador is None:
        return None

    return AccessToken(
        token=token,
        client_id=f"usuario-{operador['usuario_id']}",
        scopes=list(ESCOPOS_EXIGIDOS),
        subject=str(operador["usuario_id"]),
        claims=operador,
    )


class TokenDaPlataforma(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        # O httpx aqui é síncrono; sai do event loop para não travá-lo.
        return await anyio.to_thread.run_sync(_consultar, token)


# --- porta 2: login no GitHub ------------------------------------------------


def _operador_do_github(github_id: str) -> dict | None:
    """Traduz a conta do GitHub que logou no operador cadastrado na plataforma.

    A chave é o **id numérico** da conta, e só ele. Login e e-mail do perfil são
    do dono da conta: ele troca os dois quando quer, um login liberado pode ser
    registrado por outra pessoa, e o e-mail público é só o que o perfil exibe.
    Ligar um operador a qualquer um deles seria entregar a sessão a quem
    escrevesse o valor certo no próprio perfil. Sem entrada no mapa para o id,
    não há sessão — não existe atalho pelo e-mail.

    Quem confirma que o e-mail mapeado é de um operador é a API, que tem a
    tabela e relê o papel.
    """
    email = get_settings().mapa_operadores_oauth.get(github_id)
    if not email:
        return None

    return _interno("operador", identificadores=[email])


class GitHubDaPlataforma(GitHubProvider):
    """O GitHub diz quem entrou; o cadastro daqui diz se essa pessoa opera.

    Sem esta checagem, qualquer conta do GitHub abriria sessão no servidor e só
    esbarraria no papel ao chamar uma tool. Recusar já na verificação do token é
    mais honesto: o cliente recebe 401 em vez de um catálogo de ferramentas que
    ele não pode usar.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        acesso = await super().verify_token(token)
        if acesso is None:
            return None

        claims = acesso.claims or {}
        github_id = str(claims.get("sub") or "").strip()
        operador = (
            await anyio.to_thread.run_sync(_operador_do_github, github_id)
            if github_id.isdigit()
            else None
        )
        if operador is None:
            # O id vai no log de propósito: é ele que entra em MCP_OAUTH_OPERADORES
            # para liberar a conta (`<id>=<e-mail do operador>`).
            logger.warning(
                "conta do GitHub %s (id %s) não corresponde a nenhum operador; sessão recusada",
                claims.get("login") or "(sem login)",
                github_id or "(sem id)",
            )
            return None

        return acesso.model_copy(update={"claims": {**claims, **operador}})


def _armazenamento_oauth():
    """Onde o proxy OAuth guarda registro de cliente e tokens.

    O padrão do FastMCP é um arquivo em disco — e no Railway o disco morre a
    cada deploy, o que derrubaria o conector do claude.ai toda vez que a gente
    sobe uma versão. Guardando no Postgres, a conexão sobrevive ao deploy.
    """
    url = get_settings().database_url
    if "postgresql" not in url:
        return None

    from key_value.aio.stores.postgresql import PostgreSQLStore

    # O store fala asyncpg; a URL do resto do projeto carrega o driver psycopg.
    # A tabela é criada sozinha na primeira gravação.
    return PostgreSQLStore(url=url.replace("+psycopg", ""), table_name="oauth_mcp_kv")


def construir_auth() -> AuthProvider:
    """Monta a autenticação conforme o que estiver configurado.

    Sem as variáveis do GitHub, o servidor fica como sempre foi: só o token
    opaco. É assim que a POC roda na máquina de quem desenvolve, sem precisar
    de app OAuth nenhum.
    """
    settings = get_settings()
    plataforma = TokenDaPlataforma()

    if not settings.oauth_mcp_ativo:
        logger.info("MCP sem OAuth: só o token Bearer da plataforma")
        return plataforma

    github = GitHubDaPlataforma(
        client_id=settings.mcp_oauth_github_client_id,  # type: ignore[arg-type]
        client_secret=settings.mcp_oauth_github_client_secret,  # type: ignore[arg-type]
        # A URL pública da raiz: é dela que saem /authorize, /token e os
        # .well-known, que o cliente procura na raiz do domínio.
        base_url=settings.mcp_base_url,  # type: ignore[arg-type]
        # A POC só lê o perfil, para saber quem entrou.
        required_scopes=list(ESCOPOS_EXIGIDOS),
        client_storage=_armazenamento_oauth(),
    )
    logger.info("MCP com OAuth do GitHub em %s", settings.mcp_base_url)
    if settings.operadores_oauth_ignorados:
        logger.warning(
            "MCP_OAUTH_OPERADORES: %d entrada(s) ignorada(s) (%s). A chave agora é o id "
            "numérico da conta do GitHub, não o login nem o e-mail — ver docs/MCP-OAUTH.md",
            len(settings.operadores_oauth_ignorados),
            ", ".join(settings.operadores_oauth_ignorados),
        )

    # O OAuth responde pelas rotas e pela metadata; o token opaco continua
    # valendo como segunda credencial, para o Claude Code e os scripts.
    return MultiAuth(server=github, verifiers=[plataforma])


# --- identidade da chamada ---------------------------------------------------


def identidade_da_sessao() -> Identidade:
    """Traduz o token da chamada atual na Identidade que os services esperam.

    Vale para as duas portas: quando a sessão veio do GitHub, os claims já
    foram completados com o operador correspondente, na verificação do token.
    """
    from fastmcp.exceptions import ToolError
    from fastmcp.server.dependencies import get_access_token

    token = get_access_token()
    if token is None or not token.claims:
        raise ToolError("Sessão MCP sem identidade. Reconecte o servidor com um token válido.")

    c = token.claims
    if "usuario_id" not in c:
        raise ToolError(
            "Sessão autenticada, mas sem operador correspondente na plataforma. "
            "Peça para vincular este login a um ADMIN ou GERENCIADOR."
        )

    return Identidade(
        usuario_id=c["usuario_id"],
        nome=c["nome"],
        email=c["email"],
        papel=c["papel"],
        canal=Canal.MCP,
    )
