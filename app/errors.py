"""Erros de domínio.

Existem para que os services digam o que houve sem saber se quem chamou foi um
controller REST ou uma tool MCP. Cada camada de borda traduz para o seu
formato: HTTP status no REST, ToolError no MCP.
"""


class ErroDominio(Exception):
    """Base de todos os erros previstos do domínio."""


class NaoEncontrado(ErroDominio):
    """Recurso inexistente."""


class NaoAutorizado(ErroDominio):
    """Identidade válida, mas sem permissão para esta operação/recurso."""


class RegraDeNegocio(ErroDominio):
    """Operação válida na forma, recusada pelo estado ou pelas regras."""


class CredenciaisInvalidas(ErroDominio):
    """E-mail ou senha errados — sem dizer qual dos dois, de propósito."""

    def __init__(self) -> None:
        super().__init__("E-mail ou senha incorretos.")


class MuitasTentativas(ErroDominio):
    """Login travado por excesso de tentativas; `segundos` diz quando tentar de novo."""

    def __init__(self, segundos: int) -> None:
        self.segundos = segundos
        minutos = max(1, -(-segundos // 60))
        plural = "s" if minutos > 1 else ""
        super().__init__(f"Muitas tentativas de entrar. Tente de novo em {minutos} minuto{plural}.")


class AprovacaoNecessaria(RegraDeNegocio):
    """Publicação barrada por falta de aprovação humana explícita.

    A separação existe porque este caso não é um erro de uso: é o backend
    fazendo valer a regra fundamental da seção 6 do MVP (a IA propõe, o humano
    aprova). A borda MCP usa este tipo para pedir confirmação ao usuário.
    """
