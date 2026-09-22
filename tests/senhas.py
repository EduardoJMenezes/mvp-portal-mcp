"""Senha e token como o banco os guarda — só para semear os testes.

O adaptador nunca calcula isto em produção: quem confere senha e token é a API.
O SHA-256 daqui é o mesmo do Java; mudar um sem o outro invalida todo token.
"""

from __future__ import annotations

import hashlib
import secrets

import bcrypt


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def novo_token_mcp() -> str:
    return f"pvm_{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
