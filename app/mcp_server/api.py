"""A ponte para a API: é por aqui que toda ferramenta grava e lê.

Nenhuma tool toca o banco — essa é a invariante que faz a divisão em duas
linguagens valer a pena. O que prova quem está pedindo são dois cabeçalhos:

* `X-Servico`, o segredo que diz "veio deste adaptador, não de alguém na rede
  interna";
* `X-Operador`, o id de quem o OAuth autenticou. O Java **relê o papel no
  banco** a cada chamada, então quem foi rebaixado perde o acesso no comando
  seguinte, sem esperar token expirar.

O canal não vai em cabeçalho de propósito: quem chega por esta porta é o MCP, e
o Java fixa `Canal.MCP`. Sem campo para mentir, não há como um agente se passar
pelo professor no navegador e escapar do `exigir_humano_no_portal`.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

import anyio
import httpx
from fastmcp.exceptions import ToolError

from app.config import get_settings
from app.mcp_server.auth import identidade_da_sessao

logger = logging.getLogger(__name__)

# O tipo que o Java carimba quando a publicação parou por falta de aprovação.
# É por ele que `publicar_rascunho` sabe que deve pedir a confirmação, em vez
# de só repassar o erro.
APROVACAO_NECESSARIA = "urn:plataforma:aprovacao-necessaria"

_cliente: httpx.Client | None = None


class PrecisaDeAprovacao(Exception):
    """A publicação parou porque falta o "pode" de um humano.

    Espelha a `AprovacaoNecessaria` do domínio, que agora vive do lado Java.
    """


def cliente() -> httpx.Client:
    """Um cliente só, reaproveitado: a conexão fica de pé entre as chamadas."""
    global _cliente
    if _cliente is None:
        s = get_settings()
        _cliente = httpx.Client(
            base_url=s.api_base_url.rstrip("/"),
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"X-Servico": s.servico_token},
        )
    return _cliente


def comando(nome: str, /, **argumentos: Any) -> Any:
    """Chama um comando da API em nome de quem está na sessão do MCP.

    Argumento em `None` não vai: do outro lado, ausente quer dizer "não mexa
    nisso", que é exatamente o que a tool quer dizer quando o professor não
    falou daquele campo.

    O nome do comando é posicional-only (`/`) porque vários comandos têm um
    argumento chamado `nome` — sem a barra, `comando("anexar_figura", nome=…)`
    estoura com "got multiple values".
    """
    ident = identidade_da_sessao()
    corpo = {chave: valor for chave, valor in argumentos.items() if valor is not None}

    try:
        resposta = cliente().post(
            f"/comandos/{nome}",
            json=corpo,
            headers={"X-Operador": str(ident.usuario_id)},
        )
    except httpx.HTTPError as e:
        logger.warning("api fora do ar em %s: %s", nome, type(e).__name__)
        raise ToolError(
            "A API da plataforma não respondeu. Tente de novo em instantes; se persistir, "
            "avise quem cuida do deploy."
        ) from None

    if resposta.is_success:
        return None if not resposta.content else resposta.json()

    _levantar(nome, resposta)


def _levantar(nome: str, resposta: httpx.Response) -> None:
    """Traduz a recusa da API no erro que o modelo lê.

    A mensagem de domínio vai **inteira** para o modelo: é ela que ele usa para
    se corrigir. Já a recusa de autenticação não tem corpo de propósito (o Java
    não diz se o id existe), então aqui ela vira um recado de configuração.
    """
    if resposta.status_code in (401, 403) and not resposta.content:
        logger.error("api recusou %s com %s: confira SERVICO_TOKEN e o papel do operador",
                     nome, resposta.status_code)
        raise ToolError(
            "A API recusou esta chamada. Isso é configuração do servidor, não do seu pedido — "
            "avise quem cuida do deploy."
        )

    try:
        problema = resposta.json()
    except ValueError:
        problema = {}

    detalhe = problema.get("detail") or f"A API respondeu {resposta.status_code}."
    if problema.get("type") == APROVACAO_NECESSARIA:
        raise PrecisaDeAprovacao(detalhe)
    raise ToolError(detalhe)


def interno(rota: str, /, **corpo: Any) -> Any:
    """As portas de `/interno`: as que o adaptador chama **antes** de ter um operador.

    Só o token de serviço vai — não há `X-Operador` para mandar, já que é
    justamente ele que estas chamadas descobrem. Por isso não passam por
    `comando()`: ele exigiria a identidade que ainda não existe.

    Devolve `None` quando a credencial não corresponde a operador nenhum, e
    também quando a API não responde: sem conseguir confirmar quem é, a sessão
    não abre. Falhar fechado é o único jeito seguro de errar aqui.
    """
    try:
        resposta = cliente().post(f"/interno/{rota}", json=corpo)
        resposta.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(
            "não deu para conferir a credencial em /interno/%s (%s): a sessão foi recusada",
            rota, type(e).__name__,
        )
        return None
    return resposta.json() if resposta.content else None


def interno_ou_erro(rota: str, /, **corpo: Any) -> Any:
    """O mesmo `/interno`, para quem precisa da mensagem em vez de um "não".

    A página de envio mostra a recusa ao professor — "este link expirou", "este
    link já foi usado" —, então aqui o erro da API volta como erro de domínio, e
    o handler do FastAPI o traduz em status. A diferença para `interno()` é de
    propósito: lá, quem chama está conferindo credencial e não deve saber por
    que ela não serviu.
    """
    from app.errors import NaoEncontrado, RegraDeNegocio

    try:
        resposta = cliente().post(f"/interno/{rota}", json=corpo)
    except httpx.HTTPError as e:
        logger.warning("api fora do ar em /interno/%s: %s", rota, type(e).__name__)
        raise RegraDeNegocio(
            "A plataforma não respondeu. Tente enviar de novo em instantes."
        ) from None

    if resposta.is_success:
        return resposta.json() if resposta.content else None

    try:
        problema = resposta.json()
    except ValueError:
        problema = {}
    detalhe = problema.get("detail") or f"A plataforma respondeu {resposta.status_code}."
    erro = NaoEncontrado if resposta.status_code == 404 else RegraDeNegocio
    raise erro(detalhe)


async def comando_async(nome: str, /, **argumentos: Any) -> Any:
    """A mesma chamada, de dentro de uma tool async.

    O cliente é síncrono de propósito — é uma chamada por tool, não um laço —,
    então ele vai para uma thread em vez de travar o event loop.
    """
    return await anyio.to_thread.run_sync(functools.partial(comando, nome, **argumentos))
