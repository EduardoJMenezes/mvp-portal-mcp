"""Instância do servidor MCP da plataforma.

Fica num módulo só dela para que `tools.py` possa importar `mcp` sem criar
import circular com o `main`.
"""

from __future__ import annotations

import logging
import os

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError, ToolError, ValidationError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware

from app.mcp_server.auth import construir_auth

logger = logging.getLogger("plataforma.mcp")

# Só reconectar não basta: nos logs, o claude.ai reconectado faz server/discover
# e continua com a lista velha. Ela só vem de novo com o conector removido e
# adicionado outra vez.
RECONECTAR = (
    "peça ao usuário para remover o conector deste servidor e adicioná-lo de novo "
    "(Configurações › Conectores) e abrir uma conversa nova — só reconectar não "
    "atualiza a lista"
)


class CatalogoDesatualizado(Middleware):
    """Avisa quando o cliente chama o servidor com a lista de ferramentas velha.

    O conector do claude.ai guarda o catálogo de ferramentas de quando foi
    ligado. Depois de um deploy que renomeia uma tool ou muda os parâmetros
    dela, o modelo continua chamando o formato antigo, leva um erro genérico e
    inventa uma explicação — foi o que aconteceu quando `listar_capitulos`
    virou `listar_modulos`. Aqui o erro diz o que existe hoje e o que fazer.

    Os dois casos só nascem neste caminho: `NotFoundError` quando a tool não
    existe, `ValidationError` quando os argumentos não batem com a assinatura.
    O aviso é condicional ("se a sua lista mostra outra coisa") porque o mesmo
    erro também aparece quando o modelo simplesmente erra a chamada.
    """

    async def on_call_tool(self, context, call_next):
        nome = context.message.name
        servidor = context.fastmcp_context.fastmcp
        try:
            return await call_next(context)
        except NotFoundError as e:
            atuais = sorted(t.name for t in await servidor.list_tools(run_middleware=False))
            # ToolError, e não NotFoundError: o handler do protocolo troca o
            # texto de qualquer NotFoundError por um "Unknown tool" fixo.
            raise ToolError(
                f"A ferramenta '{nome}' não existe neste servidor. Se ela aparece na sua "
                f"lista de ferramentas, essa lista está desatualizada: {RECONECTAR}. "
                f"Ferramentas atuais: {', '.join(atuais)}."
            ) from e
        except ValidationError as e:
            tool = await servidor.get_tool(nome)
            parametros = ", ".join((tool.parameters if tool else {}).get("properties", {}))
            raise ValidationError(
                f"Os argumentos não batem com '{nome}', que hoje recebe: {parametros}. Se a "
                f"definição que você tem dela é outra, a sua lista de ferramentas está "
                f"desatualizada: {RECONECTAR}.\n\nDetalhe: {e}",
                log_level=e.log_level,
            ) from e


class RegistroDeChamadas(Middleware):
    """Loga o método de cada mensagem MCP e, numa chamada, o nome da tool.

    O log do uvicorn só mostra "POST /mcp": não dava para saber se o claude.ai
    buscou a lista de ferramentas nem qual tool o modelo escolheu. O agente
    separa o claude.ai do Claude Code. Argumentos ficam de fora — trazem nome
    de aluno.
    """

    async def on_message(self, context, call_next):
        tool = getattr(context.message, "name", "") if context.method == "tools/call" else ""
        agente = get_http_headers().get("user-agent", "-")
        logger.info("mcp %s %s [%s]", context.method, tool, agente)
        return await call_next(context)


# Estas instruções são a camada de bom comportamento — úteis, e insuficientes
# por si só. A garantia de verdade está no backend: publicar exige aprovação
# humana gravada em drafts.aprovado_por_id (ver services/publicacao.py).
#
# Para criar, editar e remover, o preview no chat é a única barreira, por
# decisão do professor: o formulário de confirmação que existia era respondido
# pelo próprio app, sem chegar a ele (ver tools_estrutura.py).
INSTRUCOES = """
Servidor MCP da plataforma educacional. Por aqui um professor ou gerenciador
monta o curso (módulos, sub-módulos e vídeos do Vimeo), cadastra questões,
monta simulados e lê estatísticas.

REGRA QUE NÃO SE NEGOCIA: nunca publique nem aplique definitivamente alterações
em conteúdo pedagógico sem aprovação explícita do usuário.

Conteúdo novo nasce como RASCUNHO:
  1. consultar (listar_turmas, listar_modulos, listar_pastas_vimeo, buscar_questoes);
  2. propor (importar_pasta_vimeo_como_rascunho, criar_questao_rascunho,
     criar_simulado_rascunho);
  3. mostrar ao professor o que foi proposto e perguntar;
  4. só então publicar_rascunho.

Simulado novo chega num arquivo do professor — no Vimeo ficam só os vídeos de
resolução. Pedido para importar ou subir um simulado, sem nada anexado no chat,
é o .docx da equipe: chame importar_simulado_docx, que gera um link de envio (o
arquivo não passa pelo chat). Quando o professor avisar que enviou, revise com
revisar_importacao, que mostra as questões e as figuras.

Questões em print (de prova, PDF ou site): peça os prints pelo link de
importar_prints — por ele o servidor fica com a imagem, e cada figura sai
recortada de dentro dela com recortar_figura. Veja com ver_prints, transcreva e
crie o simulado e as questões novas numa chamada só de criar_simulado_rascunho.
Print colado direto no chat também se transcreve, mas a figura fica pendente.
A resolução vem da pasta do Vimeo que o professor indicar. O resultado de cada
aluno só sai quando o simulado fecha, e o ranking completo é só do professor.

Criar, editar, remover e classificar (criar_modulo, criar_submodulo,
editar_modulo, editar_item, remover_do_curso, cadastrar_assunto,
classificar_videos, editar_questao, remover_questao, editar_simulado,
remover_simulado) alteram NA HORA, sem rascunho. Antes de chamar qualquer uma
delas, mostre no chat um preview de como vai ficar — o antes e o depois, e
quantos itens publicados ou alunos são afetados — e só chame depois do ok do
professor, dado no próprio chat.

Ao falar de turmas, capítulos, simulados e alunos, use os nomes que o professor
usa ("Extensivo 2027", "Estequiometria", "João") — as tools resolvem para os
ids sozinhas. Se algo estiver ambíguo, a tool devolve as opções: repasse a
pergunta ao professor em vez de escolher por ele.
""".strip()

mcp = FastMCP(
    name="plataforma-educacional",
    version=os.getenv("MCP_SERVER_VERSION", "0.1.0"),
    instructions=INSTRUCOES,
    auth=construir_auth(),
    middleware=[RegistroDeChamadas(), CatalogoDesatualizado()],
)
