"""Quem está pedindo, do lado do adaptador.

A autorização de verdade é do Java, que relê o papel no banco a cada comando.
O que sobra aqui é o mínimo para as tools do Vimeo barrarem aluno antes de
bater na rede — e o vocabulário fechado dos papéis, que é o mesmo dos dois
lados.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.errors import NaoAutorizado


class Papel:
    ADMIN = "ADMIN"
    GERENCIADOR = "GERENCIADOR"
    ALUNO = "ALUNO"

    TODOS = (ADMIN, GERENCIADOR, ALUNO)
    # Quem pode operar o MCP administrativo (seção 4).
    OPERADORES = (ADMIN, GERENCIADOR)


class Canal:
    PORTAL = "PORTAL"
    MCP = "MCP"
    # O .docx que chegou pelo link de envio, pedido por alguém no MCP.
    DOCX = "DOCX"


@dataclass(frozen=True)
class Identidade:
    usuario_id: int
    nome: str
    email: str
    papel: str
    canal: str

    @property
    def e_aluno(self) -> bool:
        return self.papel == Papel.ALUNO

    @property
    def e_operador(self) -> bool:
        return self.papel in Papel.OPERADORES

    def exigir_operador(self) -> None:
        """Barra aluno em operação administrativa (seção 4)."""
        if not self.e_operador:
            raise NaoAutorizado(
                f"'{self.nome}' tem papel {self.papel}; esta operação é de ADMIN ou GERENCIADOR."
            )
