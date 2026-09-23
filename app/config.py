"""Configuração do adaptador. Tudo vem de variável de ambiente / .env.

Não há URL de banco para o domínio: o adaptador não abre conexão nenhuma.
Tudo que é estado atravessa a ponte HTTP até a API em Java (`API_BASE_URL`).
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- a API ---------------------------------------------------------------
    #
    # Onde mora o Java, e o segredo que prova que o comando veio deste
    # adaptador. O papel de quem pede não vai no cabeçalho: o Java o relê no
    # banco a cada chamada. Ver mcp_server/api.py.
    api_base_url: str = "http://127.0.0.1:8080"
    servico_token: str = ""

    # Vimeo: sem token o adaptador usa o acervo de demonstração embutido.
    vimeo_access_token: str | None = None
    vimeo_api_base: str = "https://api.vimeo.com"

    # OAuth do MCP. O Claude Code manda um header fixo e se contenta com o
    # token opaco; conector remoto (claude.ai) só fala OAuth. Preenchendo as
    # três variáveis abaixo, o servidor passa a aceitar os dois — ver
    # docs/MCP-OAUTH.md. `mcp_base_url` também é a raiz da página de envio.
    mcp_base_url: str | None = None
    # O portal (a API em Java) mora em outro domínio: é para lá que vai o
    # professor aprovar um rascunho quando o cliente não mostra a confirmação.
    portal_url: str | None = None
    mcp_oauth_github_client_id: str | None = None
    mcp_oauth_github_client_secret: str | None = None

    # Quem do GitHub corresponde a qual operador da plataforma:
    # "EduardoJMenezes=professor@escola.demo, outro@git.hub=chefe@escola.demo".
    mcp_oauth_operadores: str = ""

    # Só para o proxy OAuth guardar cliente e token entre um deploy e outro:
    # a tabela `oauth_mcp_kv`, e nada mais. Vazio, o registro fica em memória
    # e o conector do claude.ai cai a cada deploy.
    database_url: str | None = None

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @field_validator("database_url", mode="before")
    @classmethod
    def _sem_driver(cls, valor: object) -> object:
        """Aceita a URL como o Railway a entrega. O store OAuth fala asyncpg."""
        if isinstance(valor, str):
            for prefixo in ("postgresql+psycopg://", "postgres://"):
                if valor.startswith(prefixo):
                    return "postgresql://" + valor[len(prefixo):]
        return valor or None

    @property
    def lista_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def vimeo_real(self) -> bool:
        return bool(self.vimeo_access_token and self.vimeo_access_token.strip())

    @property
    def oauth_mcp_ativo(self) -> bool:
        """Só liga o OAuth quando as três peças existem — meio configurado não
        vale: o cliente descobriria o /authorize e bateria num 500."""
        return bool(
            self.mcp_base_url
            and self.mcp_oauth_github_client_id
            and self.mcp_oauth_github_client_secret
        )

    @property
    def mapa_operadores_oauth(self) -> dict[str, str]:
        """Identificador do GitHub (login ou e-mail) -> e-mail na plataforma."""
        mapa: dict[str, str] = {}
        for par in self.mcp_oauth_operadores.split(","):
            chave, _, valor = par.partition("=")
            if chave.strip() and valor.strip():
                mapa[chave.strip().lower()] = valor.strip().lower()
        return mapa


@lru_cache
def get_settings() -> Settings:
    return Settings()
