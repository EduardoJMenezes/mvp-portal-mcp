"""Erros da integração com o Vimeo.

Cada erro carrega o código interno que a seção 47 do MVP pede, o status HTTP, o
`error_code` do Vimeo e se vale repetir a chamada. A mensagem do Vimeo
(`developer_message`) fica guardada para o log; quem fala com o professor é a
borda, com texto nosso.

Códigos de erro do Vimeo que aparecem na documentação oficial: 2204 parâmetro
inválido, 5000 pasta inexistente, 8000 credencial inválida e 9000 rate limit.
"""

from __future__ import annotations

from typing import Any


class VimeoErro(Exception):
    """Base de todos os erros da integração."""

    codigo = "VIMEO_ERROR"
    retentavel = False

    def __init__(
        self,
        mensagem: str,
        *,
        status: int | None = None,
        error_code: int | None = None,
        developer_message: str | None = None,
        espera_segundos: float | None = None,
    ) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.error_code = error_code
        self.developer_message = developer_message
        self.espera_segundos = espera_segundos

    def para_log(self) -> dict[str, Any]:
        """O que vai para o log estruturado (sem token, sem corpo inteiro)."""
        return {
            "codigo": self.codigo,
            "status": self.status,
            "error_code": self.error_code,
            "retentavel": self.retentavel,
            "developer_message": self.developer_message,
        }

    def __str__(self) -> str:
        partes = [self.mensagem]
        if self.status:
            partes.append(f"HTTP {self.status}")
        if self.error_code:
            partes.append(f"error_code {self.error_code}")
        return " | ".join(partes)


class VimeoCredencialInvalida(VimeoErro):
    codigo = "VIMEO_AUTH_INVALID"


class VimeoSemPermissao(VimeoErro):
    codigo = "VIMEO_PERMISSION_DENIED"


class VimeoNaoEncontrado(VimeoErro):
    codigo = "VIMEO_RESOURCE_NOT_FOUND"


class VimeoParametroInvalido(VimeoErro):
    codigo = "VIMEO_INVALID_PARAMETER"


class VimeoLimiteDeRequisicoes(VimeoErro):
    codigo = "VIMEO_RATE_LIMITED"
    retentavel = True


class VimeoConflitoDeOffset(VimeoErro):
    """409 no upload tus: o offset enviado não é o que o Vimeo tem."""

    codigo = "VIMEO_UPLOAD_OFFSET_CONFLICT"
    retentavel = True


class VimeoIndisponivel(VimeoErro):
    codigo = "VIMEO_TEMPORARY_ERROR"
    retentavel = True


class VimeoRotaBloqueada(VimeoErro):
    """Erro nosso, não do Vimeo: alguém chamou uma rota fora da allowlist.

    Existe para que um endpoint destrutivo (apagar vídeo, apagar pasta, remover
    itens) não seja alcançável nem por engano. Ver o gap 14 em
    `docs/vimeo-integracao/02-gaps-e-ajustes.md`.
    """

    codigo = "VIMEO_ROUTE_NOT_ALLOWED"


_POR_STATUS: dict[int, type[VimeoErro]] = {
    400: VimeoParametroInvalido,
    401: VimeoCredencialInvalida,
    402: VimeoSemPermissao,
    403: VimeoSemPermissao,
    404: VimeoNaoEncontrado,
    409: VimeoConflitoDeOffset,
    429: VimeoLimiteDeRequisicoes,
}

_MENSAGENS: dict[str, str] = {
    "VIMEO_AUTH_INVALID": "O Vimeo recusou a credencial da plataforma.",
    "VIMEO_PERMISSION_DENIED": "A credencial do Vimeo não tem permissão para esta operação.",
    "VIMEO_RESOURCE_NOT_FOUND": "O recurso não existe mais no Vimeo.",
    "VIMEO_INVALID_PARAMETER": "O Vimeo recusou os parâmetros da requisição.",
    "VIMEO_RATE_LIMITED": "O Vimeo limitou temporariamente as requisições.",
    "VIMEO_UPLOAD_OFFSET_CONFLICT": "O envio do arquivo saiu de sincronia com o Vimeo.",
    "VIMEO_TEMPORARY_ERROR": "O Vimeo está indisponível no momento.",
    "VIMEO_ERROR": "O Vimeo respondeu de forma inesperada.",
}


def erro_de_resposta(
    status: int, corpo: Any = None, *, espera_segundos: float | None = None
) -> VimeoErro:
    """Traduz uma resposta de erro do Vimeo no nosso erro correspondente."""
    classe = _POR_STATUS.get(status)
    if classe is None:
        classe = VimeoIndisponivel if status >= 500 else VimeoErro
    error_code = None
    developer_message = None
    if isinstance(corpo, dict):
        bruto = corpo.get("error_code")
        if isinstance(bruto, (int, str)):
            try:
                error_code = int(bruto)
            except (TypeError, ValueError):
                error_code = None
        developer_message = corpo.get("developer_message") or corpo.get("error")
    return classe(
        _MENSAGENS.get(classe.codigo, _MENSAGENS["VIMEO_ERROR"]),
        status=status,
        error_code=error_code,
        developer_message=developer_message,
        espera_segundos=espera_segundos,
    )
