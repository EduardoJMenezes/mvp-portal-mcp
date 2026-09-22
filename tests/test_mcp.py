"""A borda do MCP: quem entra, e com que identidade."""

import asyncio

import pytest
from fastmcp.server.auth import AuthProvider

from app.mcp_server.auth import TokenDaPlataforma, _consultar
from app.mcp_server.server import mcp

# Importar os módulos de tools é o que dispara os decorators que registram tudo.
import app.mcp_server.tools  # noqa: F401  isort:skip
import app.mcp_server.tools_estrutura  # noqa: F401  isort:skip
import app.mcp_server.tools_importacao  # noqa: F401  isort:skip
import app.mcp_server.tools_simulado  # noqa: F401  isort:skip
from app.identidade import Papel
from tests.modelos import TokenMCP, Usuario
from tests.senhas import hash_senha, hash_token, novo_token_mcp

# Alteram o curso sem rascunho no meio: a confirmação é o preview no chat.
ALTERAM_NA_HORA = {
    "criar_modulo", "criar_submodulo", "editar_modulo", "editar_item",
    "remover_do_curso", "cadastrar_assunto", "classificar_videos",
    "editar_questao", "remover_questao", "editar_simulado", "remover_simulado",
}


def _quem_esta_pedindo(monkeypatch, mundo) -> None:
    """Põe o professor na sessão do MCP.

    Um ponto só, porque hoje há um só: toda tool se identifica em
    `api.comando`, que é quem monta o cabeçalho `X-Operador`. As tools que
    ainda chamam `identidade_da_sessao` direto (as do Vimeo, para barrar aluno
    antes de bater na rede) leem do mesmo lugar.
    """
    import app.mcp_server.api as api
    import app.mcp_server.tools as tools

    for modulo in (api, tools):
        monkeypatch.setattr(modulo, "identidade_da_sessao", lambda: mundo["professor_mcp"])


def _token_para(db, usuario: Usuario, revogado: bool = False) -> str:
    valor = novo_token_mcp()
    db.add(
        TokenMCP(usuario_id=usuario.id, nome="teste", token_hash=hash_token(valor),
                 revogado=revogado)
    )
    db.commit()
    return valor


def _usuario(db, papel: str, email: str) -> Usuario:
    u = Usuario(nome=f"U {papel}", email=email, senha_hash=hash_senha("x"), papel=papel)
    db.add(u)
    db.commit()
    return u


def test_token_de_operador_abre_sessao_com_a_identidade_certa(db, api_java):
    professor = _usuario(db, Papel.ADMIN, "adm@x.demo")
    valor = _token_para(db, professor)

    acesso = _consultar(valor)

    assert acesso is not None
    assert acesso.claims["usuario_id"] == professor.id
    assert acesso.claims["papel"] == Papel.ADMIN


def test_token_de_aluno_nao_abre_o_mcp(db, api_java):
    """Seção 4: aluno não acessa o MCP administrativo."""
    aluno = _usuario(db, Papel.ALUNO, "aluno@x.demo")
    valor = _token_para(db, aluno)

    assert _consultar(valor) is None


def test_token_revogado_nao_vale(db, api_java):
    gerente = _usuario(db, Papel.GERENCIADOR, "ger@x.demo")
    valor = _token_para(db, gerente, revogado=True)

    assert _consultar(valor) is None


def test_token_inventado_nao_vale(db, api_java):
    assert _consultar("pvm_nao_existe") is None


def test_token_nao_fica_em_claro_no_banco(db):
    professor = _usuario(db, Papel.ADMIN, "adm2@x.demo")
    valor = _token_para(db, professor)

    guardado = db.query(TokenMCP).filter_by(usuario_id=professor.id).one()
    assert valor not in guardado.token_hash
    assert guardado.token_hash == hash_token(valor)


def test_servidor_exige_autenticacao():
    # Com OAuth configurado o tipo muda para MultiAuth (ver test_mcp_oauth.py);
    # o que nenhuma configuração pode produzir é um servidor sem autenticação.
    assert mcp.auth is not None, "o MCP não pode subir aberto"
    assert isinstance(mcp.auth, AuthProvider)


def test_tools_registradas_e_anotadas():
    tools = {t.name: t for t in asyncio.run(mcp._list_tools())}

    esperadas = {
        # consulta
        "listar_turmas", "listar_modulos", "listar_assuntos", "buscar_questoes",
        "listar_videos_vimeo", "listar_pastas_vimeo", "simular_importacao_vimeo",
        "listar_rascunhos", "detalhar_rascunho", "buscar_desempenho_aluno",
        "buscar_estatisticas_simulado", "listar_simulados", "detalhar_questao",
        "detalhar_simulado", "buscar_ranking_simulado", "revisar_importacao",
        "importar_simulado_docx", "completar_questao_importada",
        "importar_prints", "ver_prints", "recortar_figura",
        # proposta, que nasce em rascunho
        "criar_questao_rascunho", "importar_videos_como_itens", "criar_simulado_rascunho",
        "importar_pasta_vimeo_como_rascunho", "publicar_rascunho",
        # CRUD do curso, que altera direto e confirma com o professor
        *ALTERAM_NA_HORA,
    }
    assert esperadas <= set(tools)

    # Toda tool precisa de descrição: é o que o modelo lê para decidir usá-la.
    sem_descricao = [n for n, t in tools.items() if not (t.description or "").strip()]
    assert sem_descricao == []

    escritas = {"criar_questao_rascunho", "importar_videos_como_itens",
                "criar_simulado_rascunho", "publicar_rascunho", "importar_simulado_docx",
                "completar_questao_importada", "importar_prints", "recortar_figura",
                "importar_pasta_vimeo_como_rascunho", *ALTERAM_NA_HORA}
    for nome, tool in tools.items():
        esperado = nome not in escritas
        assert tool.annotations.read_only_hint is esperado, f"{nome} com read_only_hint errado"


def test_instrucoes_do_servidor_reforcam_a_regra():
    assert "nunca publique" in (mcp.instructions or "").lower()


def test_tool_que_altera_na_hora_pede_preview_e_ok_no_chat():
    """Sem rascunho entre a decisão e o efeito, a confirmação é esta instrução.

    Foi escolha do professor: o formulário de confirmação era respondido pelo
    próprio app, sem chegar a ele. Tirar a instrução daqui deixaria a tool
    alterando o curso sem ninguém ver antes.
    """
    tools = {t.name: t for t in asyncio.run(mcp._list_tools())}

    def corrido(texto: str | None) -> str:
        return " ".join((texto or "").split())  # a quebra de linha não vale como mudança

    sem_regra = [
        nome for nome in ALTERAM_NA_HORA
        if "mostre ao professor no chat" not in corrido(tools[nome].description)
    ]
    assert sem_regra == []
    assert "só chame depois do ok do professor" in corrido(mcp.instructions)


async def test_cliente_com_lista_de_ferramentas_velha_e_avisado():
    """O conector do claude.ai guarda o catálogo de quando foi ligado.

    Quando uma tool some ou muda de assinatura num deploy, o modelo chama o
    formato antigo — e sem este aviso inventa uma explicação para o professor.
    """
    from fastmcp import Client, FastMCP

    from app.mcp_server.server import CatalogoDesatualizado

    assert any(isinstance(m, CatalogoDesatualizado) for m in mcp.middleware)

    servidor = FastMCP("teste", middleware=[CatalogoDesatualizado()])

    @servidor.tool(name="importar")
    def importar(pasta: str, destinos: list[dict]) -> str:
        return "ok"

    async with Client(servidor) as cliente:
        with pytest.raises(Exception) as sumiu:
            await cliente.call_tool("listar_capitulos", {})
        with pytest.raises(Exception) as mudou:
            await cliente.call_tool("importar", {"pasta": "1", "capitulo": "K01"})

    assert "desatualizada" in str(sumiu.value)
    assert "Ferramentas atuais: importar" in str(sumiu.value)
    assert "que hoje recebe: pasta, destinos" in str(mudou.value)
    assert "desatualizada" in str(mudou.value)


async def test_log_mostra_qual_tool_o_cliente_chamou_sem_os_argumentos(caplog):
    """O log do uvicorn só diz "POST /mcp"; sem isto não se vê o que o modelo escolheu."""
    from fastmcp import Client, FastMCP

    from app.mcp_server.server import RegistroDeChamadas

    assert any(isinstance(m, RegistroDeChamadas) for m in mcp.middleware)

    servidor = FastMCP("teste", middleware=[RegistroDeChamadas()])

    @servidor.tool(name="buscar_desempenho_aluno")
    def buscar(aluno: str) -> str:
        return "ok"

    with caplog.at_level("INFO", logger="plataforma.mcp"):
        async with Client(servidor) as cliente:
            await cliente.list_tools()
            await cliente.call_tool("buscar_desempenho_aluno", {"aluno": "João"})

    assert "mcp tools/list" in caplog.text
    assert "mcp tools/call buscar_desempenho_aluno" in caplog.text
    assert "João" not in caplog.text


def test_cliente_vimeo_le_o_embed_da_api():
    """O campo player_embed_url da API vira o embed_url do nosso domínio."""
    from app.vimeo.client import _para_video

    bruto = {
        "uri": "/videos/76979871",
        "name": "Aula",
        "link": "https://vimeo.com/76979871/8272103f6e",
        "player_embed_url": "https://player.vimeo.com/video/76979871?h=8272103f6e",
        "duration": 300,
    }
    video = _para_video(bruto)

    assert video.id == "76979871"
    assert video.embed_url == "https://player.vimeo.com/video/76979871?h=8272103f6e"


async def test_simulado_pelo_mcp_nasce_num_rascunho_e_se_ajusta_na_hora(db, mundo, api_java, monkeypatch):
    """As tools do simulado de ponta a ponta, com o professor já identificado."""
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)
    nova = {"enunciado": "Figura", "alternativas": {l: l for l in "ABCDE"}, "gabarito": "A",
            "imagem_pendente": True}

    async with Client(mcp) as cliente:
        async def tool(nome, **argumentos):
            return (await cliente.call_tool(nome, argumentos)).data

        criado = await tool(
            "criar_simulado_rascunho", turmas=["Extensivo 2027"], titulo="Simulado 30",
            questoes=[mundo["questoes"][0].id, nova], abre_em="2030-01-10T14:00",
            fecha_em="2030-01-10T18:00", duracao_minutos=90,
        )
        sid = criado["simulado"]["simulado_id"]
        assert criado["simulado"]["abre_em"] == "10/01/2030 às 14:00"
        assert criado["simulado"]["pendencias_para_publicar"] == [
            "questões com imagem pendente: [2]"
        ]

        editado = await tool("editar_simulado", simulado="Simulado 30",
                             questoes=[mundo["questoes"][1].id, mundo["questoes"][0].id])
        assert editado["total_questoes"] == 2

        detalhe = await tool("detalhar_simulado", simulado=str(sid))
        assert detalhe["pendencias_para_publicar"] == [], "a questão com figura saiu da prova"

        with pytest.raises(Exception) as erro:
            await tool("editar_questao", questao=999999, gabarito="A")
        assert "Questão 999999 não existe" in str(erro.value)

        ranking = await tool("buscar_ranking_simulado", simulado="Simulado 30")
        assert ranking["participantes"] == 0 and ranking["parcial"] is True


def _rascunho_de_itens(mundo):
    """Uma proposta de itens, criada pela mesma ponte que as tools usam."""
    from app.mcp_server.api import comando

    return comando(
        "importar_videos_como_itens", turma="Extensivo 2027", modulo="K01 - Estequiometria",
        submodulo="Aulas", videos=[{"vimeo_id": "novo-mcp", "titulo": "Vídeo novo"}],
    )["rascunho"]["rascunho_id"]


def _detalhe(rid: int) -> dict:
    from app.mcp_server.api import comando

    return comando("detalhar_rascunho", rascunho=rid)


async def test_publicar_em_cliente_sem_formulario_manda_aprovar_no_portal(db, mundo, api_java, monkeypatch):
    """O claude.ai não mostra o pedido de confirmação. Sem este desvio, o
    professor via um erro genérico, e nada dizia que a aprovação é no portal."""
    from fastmcp import Client

    _quem_esta_pedindo(monkeypatch, mundo)
    rid = _rascunho_de_itens(mundo)

    async with Client(mcp) as cliente:  # sem handler: não declara que mostra formulário
        saida = (await cliente.call_tool("publicar_rascunho", {"rascunho_id": rid})).data

    assert saida["publicado"] is False
    assert f"#{rid}" in saida["mensagem"] and "Aprovar e publicar" in saida["mensagem"]
    assert _detalhe(rid)["publicado"] is False


async def test_publicar_em_cliente_com_formulario_so_publica_depois_do_aceite(db, mundo, api_java, monkeypatch):
    from fastmcp import Client
    from fastmcp.client.elicitation import ElicitResult

    _quem_esta_pedindo(monkeypatch, mundo)
    rid = _rascunho_de_itens(mundo)
    perguntas = []

    async def professor(mensagem, tipo, params, contexto):
        perguntas.append(mensagem)
        return ElicitResult(action="accept", content={"publicar": True})

    async with Client(mcp, elicitation_handler=professor) as cliente:
        saida = (await cliente.call_tool("publicar_rascunho", {"rascunho_id": rid})).data

    assert perguntas, "o professor precisa ter sido perguntado"
    assert saida["publicado"] is True
    assert _detalhe(rid)["aprovado_via"] == "ELICITATION_MCP"


async def test_importacao_pelo_chat_devolve_link_e_a_revisao_mostra_as_figuras(db, mundo, api_java, monkeypatch):
    """O Claude revisa vendo as figuras: elas voltam como imagem, não como texto."""
    from fastapi.testclient import TestClient
    from fastmcp import Client

    from app import main
    from tests.docx_de_teste import docx, figura, p

    _quem_esta_pedindo(monkeypatch, mundo)
    arquivo = docx(p("01. Observe:"), p(figura()), *[p(f"{l}) item {l}") for l in "abcde"],
                   p("GABARITO: A"), p("Porque sim."))

    async with Client(mcp) as cliente:
        link = (await cliente.call_tool("importar_simulado_docx", {"turmas": ["Extensivo 2027"]})).data
        # Pela página mesmo: é ela que lê o .docx e entrega o resultado à API.
        enviado = TestClient(main.app).post(
            f"/api/importacoes/{link['link'].rsplit('/', 1)[-1]}/arquivo",
            files={"arquivo": ("s.docx", arquivo,
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert enviado.status_code == 200, enviado.text
        revisao = await cliente.call_tool("revisar_importacao", {"importacao": link["importacao_id"]})

    imagens = [c for c in revisao.content if c.type == "image"]
    assert len(imagens) == 1 and imagens[0].mime_type == "image/png"
    assert '"gabarito": "A"' in revisao.content[0].text


async def test_prints_pelo_chat_voltam_como_imagem_e_o_recorte_tambem(db, mundo, api_java, monkeypatch):
    """O Claude transcreve vendo o print e confere o recorte vendo a figura."""
    from fastapi.testclient import TestClient
    from fastmcp import Client

    from app import imagens, main
    from tests.docx_de_teste import print_de_questao

    _quem_esta_pedindo(monkeypatch, mundo)

    async with Client(mcp) as cliente:
        link = (await cliente.call_tool("importar_prints", {})).data
        enviado = TestClient(main.app).post(
            f"/api/importacoes/{link['link'].rsplit('/', 1)[-1]}/prints",
            files=[("arquivos", ("q1.png", print_de_questao(), "image/png"))],
        )
        assert enviado.status_code == 200, enviado.text

        rascunho = (await cliente.call_tool("criar_simulado_rascunho", {
            "turmas": ["Extensivo 2027"], "titulo": "P",
            "questoes": [{"enunciado": "Veja ![](figura:pendente)",
                          "alternativas": {l: l for l in "ABCDE"}, "gabarito": "A"}],
        })).data
        vista = await cliente.call_tool("ver_prints", {"importacao": link["importacao_id"]})
        recorte = await cliente.call_tool("recortar_figura", {
            "importacao": link["importacao_id"], "print": 1,
            "questao": rascunho["simulado"]["questoes"][0]["questao_id"], "retangulo": [90, 140, 310, 360],
        })

    largura, altura = imagens._tamanho_da_vista(900, 600)
    assert [c.type for c in vista.content] == ["text", "text", "image"]
    assert f"{largura}×{altura}" in vista.content[1].text
    assert recorte.content[1].type == "image"
    assert '"imagem_pendente": false' in recorte.content[0].text
