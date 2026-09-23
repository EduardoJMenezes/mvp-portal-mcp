"""O adaptador MCP: o conector do Claude, a página de envio e nada de banco.

    Claude ─► FastMCP (/mcp) ─► HTTP /comandos/* ─► API em Java ─► PostgreSQL
    Professor ─► /enviar/<token> ─► lê o .docx ou os prints ─► HTTP /interno/*

Quem hospeda é o app do MCP. O OAuth do conector precisa de rotas na RAIZ do
domínio (/authorize, /token, /.well-known/...), criadas pelo próprio FastMCP a
partir do `base_url`; o FastAPI do envio entra como último recurso, montado em
"/", porque um mount ali casa com qualquer caminho e encerra o roteamento.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route

from app.api import envio_routes
from app.config import get_settings
from app.errors import NaoAutorizado, NaoEncontrado, RegraDeNegocio

# Importar os módulos de tools registra todas elas na instância `mcp`.
from app.mcp_server import tools as _tools  # noqa: F401
from app.mcp_server import tools_estrutura as _tools_estrutura  # noqa: F401
from app.mcp_server import tools_importacao as _tools_importacao  # noqa: F401
from app.mcp_server import tools_simulado as _tools_simulado  # noqa: F401
from app.mcp_server import tools_aulas as _tools_aulas  # noqa: F401
from app.mcp_server.server import mcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("plataforma")

settings = get_settings()

CAMINHO_MCP = "/mcp"
PAGINA_DE_ENVIO = Path(__file__).resolve().parent / "paginas" / "enviar.html"


class TempoDaResposta:
    """Uma linha por pedido: método, rota, status e milissegundos. O token do
    link de envio nunca cai no log: o caminho registrado é o molde."""

    LENTO_MS = 1000

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/saude":
            await self.app(scope, receive, send)
            return
        comeco = time.perf_counter()
        visto = {"status": 0}

        async def enviar(mensagem) -> None:
            if mensagem["type"] == "http.response.start":
                visto["status"] = mensagem["status"]
            await send(mensagem)

        try:
            await self.app(scope, receive, enviar)
        finally:
            ms = (time.perf_counter() - comeco) * 1000
            caminho = scope.get("path", "") or "/"
            for prefixo in ("/enviar/", "/api/importacoes/"):
                if caminho.startswith(prefixo):
                    caminho = prefixo + "{token}"
            registrar = logger.warning if ms >= self.LENTO_MS else logger.info
            registrar("%s %s %s %.0fms", scope.get("method"), caminho, visto["status"], ms)


class CabecalhosDeSeguranca:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar(mensagem) -> None:
            if mensagem["type"] == "http.response.start":
                headers = MutableHeaders(scope=mensagem)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            await send(mensagem)

        await self.app(scope, receive, enviar)


class BarraFinalDoMcp:
    """Faz /mcp e /mcp/ apontarem para o mesmo lugar."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"] == f"{CAMINHO_MCP}/":
            scope = {**scope, "path": CAMINHO_MCP, "raw_path": CAMINHO_MCP.encode()}
        await self.app(scope, receive, send)


# --- a página de envio e a API dela ------------------------------------------

api = FastAPI(title="Adaptador MCP — envio de arquivos", version="0.2.0")


@api.exception_handler(NaoEncontrado)
def _nao_encontrado(_: Request, exc: NaoEncontrado) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@api.exception_handler(NaoAutorizado)
def _nao_autorizado(_: Request, exc: NaoAutorizado) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@api.exception_handler(RegraDeNegocio)
def _regra(_: Request, exc: RegraDeNegocio) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@api.exception_handler(Exception)
def _erro_inesperado(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Erro interno no servidor. Tente novamente em instantes."})


api.include_router(envio_routes.router)


@api.get("/enviar/{token}", response_class=HTMLResponse, include_in_schema=False)
@api.get("/enviar/", response_class=HTMLResponse, include_in_schema=False)
@api.get("/enviar", response_class=HTMLResponse, include_in_schema=False)
def pagina_de_envio() -> HTMLResponse:
    """Uma página só, sem login: o link é a credencial, e ela lê o token do endereço."""
    return HTMLResponse(PAGINA_DE_ENVIO.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@api.get("/", include_in_schema=False)
def raiz() -> JSONResponse:
    return JSONResponse({"papel": "mcp", "mcp": CAMINHO_MCP, "envio": "/enviar/{token}"})


def montar():
    """O app ASGI. É uma função para o teste poder montar sem reimportar o módulo."""
    app_mcp = mcp.http_app(
        path=CAMINHO_MCP,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=settings.lista_cors,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
            Middleware(BarraFinalDoMcp),
            Middleware(CabecalhosDeSeguranca),
            Middleware(TempoDaResposta),
        ],
    )
    # O Railway precisa de um caminho para aprovar o deploy.
    app_mcp.router.routes.append(
        Route("/saude", lambda _: JSONResponse({"status": "ok", "papel": "mcp"}))
    )
    app_mcp.router.routes.append(Mount("/", app=api))
    return app_mcp


app = montar()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.app_host, port=settings.app_port)


if __name__ == "__main__":
    main()
