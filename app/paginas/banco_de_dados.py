"""
Banco de Dados (Etapa 03): interface sobre o PostgreSQL do projeto.

- Consultas e gráficos: as consultas de db/consultas.py, com o SQL executado à mostra
- Tabelas: visualização de qualquer tabela do banco
- Equipes e Fichas de cadastro: inserção, alteração e exclusão
- Importar arquivo: ingestão de fichas por CSV ou planilha (db/ingestao.py), com validação e recálculo dos indicadores

Todo acesso ao banco é SQL explícito executado pelo psycopg (driver do PostgreSQL para Python).
Conexão pela variável DATABASE_URL ou pelo segredo DATABASE_URL do Streamlit (banco Neon, na nuvem);
sem nenhum dos dois a página não abre.
"""

import os
import sys
from datetime import date
from zoneinfo import ZoneInfo
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "db"))
from consultas import CONSULTAS, EXEMPLO, GRUPOS  # noqa: E402
import ingestao  # noqa: E402

AZUL, LARANJA, VERDE_AGUA = "#2a78d6", "#eb6834", "#1baf7a"
CATEGORICAS = [AZUL, LARANJA, VERDE_AGUA, "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

def _url_banco():
    """Conexão do banco: variável de ambiente DATABASE_URL (local) ou segredo do Streamlit
    (.streamlit/secrets.toml local, ou Settings > Secrets no Streamlit Cloud). Nunca no código."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    try:
        return st.secrets.get("DATABASE_URL")
    except FileNotFoundError:
        return None
    except Exception:  # sem secrets.toml, algumas versões levantam outro erro
        return None


URL = _url_banco()

st.title("Banco de Dados")
st.caption("PostgreSQL · base SINTÉTICA no formato da Ficha de Cadastro Individual do e-SUS APS (v5.3)")

if not URL:
    st.info("Esta página conecta direto no PostgreSQL (Neon) e precisa da conexão `DATABASE_URL` "
            "(variável de ambiente ou segredo do Streamlit). Veja o README.")
    st.stop()

import psycopg  # noqa: E402  (só quando há banco: o painel publicado não precisa do driver)
from psycopg import sql  # noqa: E402


# ---------------------------------------------------------------------------
# Acesso ao banco: toda operação passa por aqui, com o SQL explícito
# ---------------------------------------------------------------------------

def consultar(comando, params=None):
    """Executa um SELECT e devolve um DataFrame."""
    with psycopg.connect(URL) as con, con.cursor() as cur:
        cur.execute(comando, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def sql_executado(comando, params=None):
    """O comando como o PostgreSQL recebe, com os valores no lugar dos parâmetros."""
    with psycopg.connect(URL) as con:
        texto = psycopg.ClientCursor(con).mogrify(comando, params)
    return texto.strip()


def executar(comandos):
    """Executa (comando, params) numa transação só: ou tudo grava, ou nada grava.
    params pode ser uma função dos resultados anteriores (ex.: usar o id que o INSERT anterior gerou).
    Devolve (ok, sql executado, resultados de cada comando)."""
    executados, resultados = [], []
    try:
        with psycopg.connect(URL) as con, con.transaction(), con.cursor() as cur:
            for comando, params in comandos:
                if callable(params):
                    params = params(resultados)
                cur.execute(comando, params)
                executados.append(psycopg.ClientCursor(con).mogrify(comando, params).strip())
                resultados.append(cur.fetchall() if cur.description else cur.rowcount)
        return True, executados, resultados
    except psycopg.errors.IntegrityError as e:
        msg = f"O banco recusou a operação: {e.diag.message_primary}"
        if e.diag.constraint_name:
            msg += f" (restrição `{e.diag.constraint_name}`)"
        st.error(msg)
    except psycopg.Error as e:
        st.error(f"Erro do banco: {e.diag.message_primary or e}")
    return False, executados, None


def mostrar_resultado(ok, executados, _resultados, mensagem):
    if ok:
        st.success(mensagem)
    with st.expander("SQL executado", expanded=ok):
        st.code(";\n\n".join(executados) + ";" if executados else "-- nada executado", language="sql")


def ni(v):
    """Opção 'N/I' (não informado) do formulário vira NULL no banco."""
    return None if v == "N/I" else v


# ---------------------------------------------------------------------------
# Filtros comuns
# ---------------------------------------------------------------------------

quads = consultar("""
    SELECT q.ano, q.numero FROM quadrimestre q
    WHERE EXISTS (SELECT 1 FROM indicador_equipe i WHERE i.id_quadrimestre = q.id_quadrimestre)
    ORDER BY q.ano, q.numero""")
rotulos = [f"{a}.{n}" for a, n in zip(quads["ano"], quads["numero"])]

with st.sidebar:
    st.markdown("### Banco de Dados")
    quad = st.selectbox("Quadrimestre", rotulos, index=len(rotulos) - 1)
    distrito = st.selectbox("Distrito Sanitário", list(range(1, 9)), index=EXEMPLO["distrito"] - 1,
                            format_func=lambda d: f"DS {d}")
ano, numero = (int(x) for x in quad.split("."))

aba_consultas, aba_tabelas, aba_equipes, aba_fichas, aba_importar = st.tabs(
    ["📊 Consultas e gráficos", "🗂️ Tabelas", "👥 Equipes", "📝 Fichas de cadastro", "📥 Importar arquivo"])


# ---------------------------------------------------------------------------
# Consultas e gráficos
# ---------------------------------------------------------------------------

def grafico(chave, df):
    if df.empty:
        return
    if chave == "estados":
        marcador = st.radio("Marcador", ["Orientação sexual", "Identidade de gênero", "Raça/cor", "Deficiência"],
                            horizontal=True)
        d = df[df["marcador"] == marcador].assign(distrito=lambda x: "DS " + x["distrito"].astype(str),
                                                   pct=lambda x: x["pct"].astype(float))
        st.altair_chart(alt.Chart(d).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("distrito:N", title=None),
            x=alt.X("pct:Q", stack="normalize", axis=alt.Axis(format="%"), title=None),
            color=alt.Color("estado:N", scale=alt.Scale(domain=["Preenchido", "Recusou", "N/I"],
                                                         range=[AZUL, LARANJA, VERDE_AGUA]),
                            legend=alt.Legend(orient="top", title=None)),
            order=alt.Order("ordem:Q"),
            tooltip=["distrito", "estado", "fichas", alt.Tooltip("pct:Q", format=".1f", title="% das fichas")],
        ).transform_calculate(ordem="datum.estado == 'Preenchido' ? 0 : datum.estado == 'Recusou' ? 1 : 2")
            .properties(height=340, title=f"{marcador}: estado do registro nas fichas de {quad}"), width="stretch")
    elif chave == "evolucao":
        d = df.assign(distrito=lambda x: "DS " + x["distrito"].astype(str),
                      indice_mediano=lambda x: x["indice_mediano"].astype(float))
        st.altair_chart(alt.Chart(d).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("quadrimestre:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("indice_mediano:Q", title="Índice (mediana)", scale=alt.Scale(zero=False)),
            color=alt.Color("distrito:N", scale=alt.Scale(range=CATEGORICAS), legend=alt.Legend(orient="top", title=None)),
            tooltip=["distrito", "quadrimestre", "indice_mediano", "equipes_criticas"],
        ).properties(height=280, title="Evolução do índice de completude por distrito"), width="stretch")
    elif chave == "ranking":
        d = df.assign(indice_completude=lambda x: x["indice_completude"].astype(float))
        st.altair_chart(alt.Chart(d).mark_bar(color=AZUL, cornerRadiusEnd=3).encode(
            y=alt.Y("equipe:N", sort=None, title=None, axis=alt.Axis(labelLimit=320)), x=alt.X("indice_completude:Q", title="Índice de completude"),
            tooltip=["posicao", "equipe", "unidade", "indice_completude"],
        ).properties(height=34 * len(d), title=f"DS {distrito}: as equipes com o pior índice em {quad}"), width="stretch")
    elif chave == "concentracao":
        st.altair_chart(alt.Chart(df).mark_bar(color=AZUL, cornerRadiusEnd=3).encode(
            y=alt.Y("bairro:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)), x=alt.X("pessoas_do_grupo:Q", title="Pessoas cadastradas ativas"),
            tooltip=["bairro", "distrito", "pessoas_do_grupo", "cadastrados_ativos", "populacao_2022"],
        ).properties(height=30 * len(df), title="Bairros com mais pessoas do grupo"), width="stretch")
    elif chave == "esperado_registrado":
        d = df.melt(id_vars="distrito", value_vars=["pct_recusou", "pct_recusa_esperada", "pct_nao_informado"],
                    var_name="medida", value_name="pct")
        d["medida"] = d["medida"].map({"pct_recusou": "Recusa registrada", "pct_recusa_esperada": "Recusa esperada (proxy)",
                                       "pct_nao_informado": "N/I (equipe não registrou)"})
        d["distrito"] = "DS " + d["distrito"].astype(str)
        d["pct"] = d["pct"].astype(float)
        st.altair_chart(alt.Chart(d).mark_bar().encode(
            x=alt.X("distrito:N", title=None, axis=alt.Axis(labelAngle=0)), xOffset="medida:N",
            y=alt.Y("pct:Q", title="% das fichas de adultos"),
            color=alt.Color("medida:N", scale=alt.Scale(domain=["Recusa registrada", "Recusa esperada (proxy)",
                                                                  "N/I (equipe não registrou)"],
                                                          range=[LARANJA, "#f4b39a", VERDE_AGUA]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["distrito", "medida", alt.Tooltip("pct:Q", format=".1f")],
        ).properties(height=300, title=f"Orientação sexual: registrado × esperado ({quad})"), width="stretch")


with aba_consultas:
    chave = st.selectbox("Consulta", list(CONSULTAS), format_func=lambda k: CONSULTAS[k]["titulo"])
    c = CONSULTAS[chave]
    st.markdown(f"**O que responde:** {c['pergunta']}")
    st.caption(f"Técnicas SQL: {c['tecnicas']}")

    valores = {"ano": ano, "numero": numero, "distrito": distrito}
    if "grupo" in c["params"]:
        valores["grupo"] = st.selectbox("Grupo", list(GRUPOS), format_func=GRUPOS.get)
    if "limite_pp" in c["params"]:
        valores["limite_pp"] = st.slider("Diferença mínima para o distrito (pontos percentuais)", 5, 40, EXEMPLO["limite_pp"])
    params = {p: valores[p] for p in c["params"]}
    if params:
        st.caption("Parâmetros: " + " · ".join(f"{k} = {v}" for k, v in params.items()))

    resultado = consultar(c["sql"], params)
    grafico(chave, resultado)
    st.markdown(f"**Resultado** · {len(resultado)} linhas")
    st.dataframe(resultado, hide_index=True, width="stretch")
    with st.expander("SQL executado"):
        st.code(sql_executado(c["sql"], params), language="sql")


# ---------------------------------------------------------------------------
# Tabelas
# ---------------------------------------------------------------------------

TABELAS = {
    "bairro": "id_bairro", "unidade_saude": "cnes", "equipe": "ine", "cidadao": "cod_cidadao",
    "ficha_cadastro": "id_ficha DESC", "tipo_deficiencia": "id_tipo_deficiencia",
    "ficha_deficiencia": "id_ficha DESC", "quadrimestre": "id_quadrimestre",
    "indicador_equipe": "ine, id_quadrimestre", "respostas_sinteticas": "id_resposta",
}

with aba_tabelas:
    tabela = st.selectbox("Tabela", list(TABELAS))
    limite = st.select_slider("Linhas", [20, 50, 100, 200, 500], value=50)
    # nome de tabela não pode ser parâmetro: vem de uma lista fixa e entra como identificador seguro
    total = consultar(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(tabela)))["n"].iloc[0]
    comando = sql.SQL("SELECT * FROM {} ORDER BY {} LIMIT %(limite)s").format(
        sql.Identifier(tabela), sql.SQL(TABELAS[tabela]))
    st.metric("Linhas na tabela", f"{total:,}".replace(",", "."))
    st.dataframe(consultar(comando, {"limite": limite}), hide_index=True, width="stretch")
    with st.expander("SQL executado"):
        st.code(sql_executado(comando, {"limite": limite}), language="sql")


# ---------------------------------------------------------------------------
# CRUD · Equipes
# ---------------------------------------------------------------------------

with aba_equipes:
    equipes = consultar("""
        SELECT e.ine, e.nome AS equipe, u.cnes, u.nome AS unidade, b.nome AS bairro,
               (SELECT COUNT(*) FROM ficha_cadastro f WHERE f.ine = e.ine) AS fichas
        FROM equipe e
        JOIN unidade_saude u ON u.cnes = e.cnes
        JOIN bairro b ON b.id_bairro = u.id_bairro
        WHERE b.nr_distrito = %(distrito)s
        ORDER BY e.nome""", {"distrito": distrito})
    unidades = consultar("""
        SELECT u.cnes, u.nome FROM unidade_saude u JOIN bairro b ON b.id_bairro = u.id_bairro
        WHERE b.nr_distrito = %(distrito)s ORDER BY u.nome""", {"distrito": distrito})
    nome_unidade = dict(zip(unidades["cnes"], unidades["nome"]))

    st.markdown(f"**Equipes do DS {distrito}** · {len(equipes)} equipes")
    st.dataframe(equipes, hide_index=True, width="stretch", height=260)

    acao = st.radio("Operação", ["Inserir", "Alterar", "Excluir"], horizontal=True, key="acao_equipe")

    if acao == "Inserir":
        with st.form("inserir_equipe", clear_on_submit=True):
            c1, c2 = st.columns(2)
            ine = c1.text_input("INE (10 dígitos)", max_chars=10)
            nome = c2.text_input("Nome da equipe")
            cnes = st.selectbox("Unidade de saúde", list(nome_unidade), format_func=nome_unidade.get)
            if st.form_submit_button("Inserir equipe", type="primary"):
                mostrar_resultado(*executar([("INSERT INTO equipe (ine, nome, cnes) VALUES (%s, %s, %s)",
                                              (ine, nome, cnes))]), f"Equipe {nome} inserida.")

    elif acao == "Alterar" and len(equipes):
        rot = dict(zip(equipes["ine"], equipes["equipe"]))
        ine = st.selectbox("Equipe", list(rot), format_func=rot.get, key="alt_equipe")
        atual = equipes.set_index("ine").loc[ine]
        with st.form("alterar_equipe"):
            nome = st.text_input("Novo nome", atual["equipe"])
            cnes = st.selectbox("Unidade", list(nome_unidade), index=list(nome_unidade).index(atual["cnes"]),
                                format_func=nome_unidade.get)
            if st.form_submit_button("Salvar alteração", type="primary"):
                mostrar_resultado(*executar([("UPDATE equipe SET nome = %s, cnes = %s WHERE ine = %s",
                                              (nome, cnes, ine))]), "Equipe alterada.")

    elif acao == "Excluir" and len(equipes):
        rot = dict(zip(equipes["ine"], equipes["equipe"]))
        ine = st.selectbox("Equipe", list(rot), format_func=rot.get, key="exc_equipe")
        impacto = consultar("""
            SELECT (SELECT COUNT(*) FROM ficha_cadastro WHERE ine = %(ine)s)   AS fichas,
                   (SELECT COUNT(*) FROM indicador_equipe WHERE ine = %(ine)s) AS indicadores""", {"ine": ine}).iloc[0]
        st.warning(f"Excluir **{rot[ine]}**: as {impacto['fichas']:,} fichas dela continuam no banco sem equipe "
                   f"(ON DELETE SET NULL) e os {impacto['indicadores']} indicadores dela são apagados (ON DELETE CASCADE).")
        if st.checkbox("Confirmo a exclusão") and st.button("Excluir equipe", type="primary"):
            mostrar_resultado(*executar([("DELETE FROM equipe WHERE ine = %s", (ine,))]), "Equipe excluída.")


# ---------------------------------------------------------------------------
# CRUD · Fichas de cadastro (campos da ficha e-SUS v5.3)
# ---------------------------------------------------------------------------

RACAS = ["N/I", "branca", "preta", "parda", "amarela", "indigena"]
OS = ["heterossexual", "gay", "lesbica", "bissexual", "assexual", "pansexual", "outra"]
IG = ["homem_cis", "mulher_cis", "homem_trans", "mulher_trans", "travesti", "nao_binario", "outra"]
SIM_NAO = ["N/I", "sim", "nao"]

PROXIMO_CIDADAO = """
    INSERT INTO cidadao (cod_cidadao)
    SELECT 'c' || LPAD((COALESCE(MAX(SUBSTRING(cod_cidadao FROM 2)::int), 0) + 1)::text, 7, '0') FROM cidadao
    RETURNING cod_cidadao"""

INSERIR_FICHA = """
    INSERT INTO ficha_cadastro (data_envio, tipo_ficha, situacao, idade, sexo, usa_nome_social, raca_cor,
                                tem_deficiencia, deseja_informar_os, orientacao_sexual,
                                deseja_informar_ig, identidade_genero, ine, cod_cidadao)
    VALUES (%(data_envio)s, %(tipo_ficha)s, %(situacao)s, %(idade)s, %(sexo)s, %(usa_nome_social)s, %(raca_cor)s,
            %(tem_deficiencia)s, %(deseja_informar_os)s, %(orientacao_sexual)s,
            %(deseja_informar_ig)s, %(identidade_genero)s, %(ine)s, %(cod_cidadao)s)
    RETURNING id_ficha"""

INSERIR_DEFICIENCIA = "INSERT INTO ficha_deficiencia (id_ficha, id_tipo_deficiencia) VALUES (%s, %s)"

COLUNAS_FICHA = """f.id_ficha, f.data_envio, f.tipo_ficha, f.situacao, f.idade, f.sexo, f.usa_nome_social,
                   f.raca_cor, f.tem_deficiencia, f.deseja_informar_os, f.orientacao_sexual,
                   f.deseja_informar_ig, f.identidade_genero, f.cod_cidadao, e.nome AS equipe,
                   f.data_entrada"""


def campos_marcadores(prefixo, atual=None):
    """Bloco 'marcadores de equidade' da ficha. Devolve os valores no formato do banco (N/I -> NULL)."""
    atual = atual or {}

    def idx(lista, v):
        return lista.index(v) if v in lista else 0

    c1, c2 = st.columns(2)
    raca = c1.selectbox("Raça/cor", RACAS, idx(RACAS, atual.get("raca_cor")), key=f"{prefixo}_raca")
    tem_def = c2.selectbox("Tem alguma deficiência?", SIM_NAO, idx(SIM_NAO, atual.get("tem_deficiencia")),
                           key=f"{prefixo}_def")
    c3, c4 = st.columns(2)
    des_os = c3.selectbox("Deseja informar orientação sexual?", SIM_NAO, idx(SIM_NAO, atual.get("deseja_informar_os")),
                          key=f"{prefixo}_dos")
    orient = c3.selectbox("Se sim, qual?", ["-"] + OS, idx(["-"] + OS, atual.get("orientacao_sexual")), key=f"{prefixo}_os")
    des_ig = c4.selectbox("Deseja informar identidade de gênero?", SIM_NAO,
                          idx(SIM_NAO, atual.get("deseja_informar_ig")), key=f"{prefixo}_dig")
    ident = c4.selectbox("Se sim, qual? ", ["-"] + IG, idx(["-"] + IG, atual.get("identidade_genero")), key=f"{prefixo}_ig")
    return {
        "raca_cor": ni(raca), "tem_deficiencia": ni(tem_def),
        "deseja_informar_os": ni(des_os), "orientacao_sexual": orient if des_os == "sim" and orient != "-" else None,
        "deseja_informar_ig": ni(des_ig), "identidade_genero": ident if des_ig == "sim" and ident != "-" else None,
    }


with aba_fichas:
    st.caption("Nos marcadores, **N/I** (não informado) grava vazio (NULL): a equipe não registrou. "
               "**nao** em \"deseja informar\" é a recusa da pessoa. As regras da ficha são restrições do banco (CHECK): "
               "o banco recusa, por exemplo, orientação sexual para menores de 11 anos ou \"sim\" sem a resposta.")
    equipes_ds = consultar("""
        SELECT e.ine, e.nome FROM equipe e JOIN unidade_saude u ON u.cnes = e.cnes
        JOIN bairro b ON b.id_bairro = u.id_bairro WHERE b.nr_distrito = %(distrito)s ORDER BY e.nome""",
                           {"distrito": distrito})
    nome_equipe = dict(zip(equipes_ds["ine"], equipes_ds["nome"]))
    tipos = consultar("SELECT id_tipo_deficiencia, categoria, descricao FROM tipo_deficiencia ORDER BY categoria, descricao")
    nome_tipo = {r.id_tipo_deficiencia: f"{r.categoria} · {r.descricao}" for r in tipos.itertuples()}

    acao = st.radio("Operação", ["Consultar", "Inserir", "Alterar", "Excluir"], horizontal=True, key="acao_ficha")

    if acao == "Consultar":
        ine = st.selectbox("Equipe", list(nome_equipe), format_func=nome_equipe.get, key="cons_ficha")
        comando = f"""SELECT {COLUNAS_FICHA} FROM ficha_cadastro f JOIN equipe e ON e.ine = f.ine
                      WHERE f.ine = %(ine)s ORDER BY f.data_envio DESC, f.id_ficha DESC LIMIT 30"""
        st.dataframe(consultar(comando, {"ine": ine}), hide_index=True, width="stretch")
        with st.expander("SQL executado"):
            st.code(sql_executado(comando, {"ine": ine}), language="sql")

    elif acao == "Inserir":
        with st.form("inserir_ficha"):
            st.markdown("**Identificação**")
            c1, c2, c3 = st.columns(3)
            ine = c1.selectbox("Equipe (INE)", list(nome_equipe), format_func=nome_equipe.get)
            data_envio = c2.date_input("Data", date.today())
            tipo_ficha = c3.selectbox("Tipo", ["novo", "atualizacao"])
            c4, c5 = st.columns(2)
            cidadao = c4.text_input("Código do cidadão (vazio = cidadão novo)", max_chars=8)
            situacao = c5.selectbox("Situação após a ficha", ["ativo", "mudou_se", "obito"])
            c6, c7, c8 = st.columns(3)
            idade = c6.number_input("Idade", 0, 110, 30)
            sexo = c7.selectbox("Sexo", ["F", "M", "I"], help="I = Indeterminado (ficha v5.3)")
            nome_social = c8.checkbox("Usa nome social")
            st.markdown("**Marcadores de equidade**")
            marcadores = campos_marcadores("ins")
            tipos_escolhidos = st.multiselect("Se tem deficiência, qual(is)?", list(nome_tipo), format_func=nome_tipo.get)

            if st.form_submit_button("Inserir ficha", type="primary"):
                ficha = {"data_envio": data_envio, "tipo_ficha": tipo_ficha, "situacao": situacao, "idade": int(idade),
                         "sexo": sexo, "usa_nome_social": nome_social, "ine": ine, **marcadores}
                comandos = []
                if cidadao.strip():
                    ficha["cod_cidadao"] = cidadao.strip()
                    comandos.append((INSERIR_FICHA, ficha))
                else:   # cidadão novo: gera o próximo código e usa na ficha, na mesma transação
                    comandos.append((PROXIMO_CIDADAO, None))
                    comandos.append((INSERIR_FICHA, lambda res: {**ficha, "cod_cidadao": res[0][0][0]}))
                i_ficha = len(comandos) - 1
                if marcadores["tem_deficiencia"] == "sim":
                    for t in tipos_escolhidos:
                        comandos.append((INSERIR_DEFICIENCIA, lambda res, t=t: (res[i_ficha][0][0], t)))
                mostrar_resultado(*executar(comandos), "Ficha inserida.")

    elif acao in ("Alterar", "Excluir"):
        id_ficha = st.number_input("Número da ficha (id_ficha)", min_value=1, step=1,
                                   help="Use a operação Consultar para achar o número")
        comando = f"""SELECT {COLUNAS_FICHA} FROM ficha_cadastro f LEFT JOIN equipe e ON e.ine = f.ine
                      WHERE f.id_ficha = %(id)s"""
        atual = consultar(comando, {"id": int(id_ficha)})
        if atual.empty:
            st.info("Nenhuma ficha com esse número.")
        else:
            st.dataframe(atual, hide_index=True, width="stretch")
            registro = atual.iloc[0].to_dict()
            if acao == "Alterar":
                with st.form("alterar_ficha"):
                    st.markdown("**Marcadores de equidade**")
                    marcadores = campos_marcadores("alt", registro)
                    if st.form_submit_button("Salvar alteração", type="primary"):
                        mostrar_resultado(*executar([("""
                            UPDATE ficha_cadastro
                               SET raca_cor = %(raca_cor)s, tem_deficiencia = %(tem_deficiencia)s,
                                   deseja_informar_os = %(deseja_informar_os)s, orientacao_sexual = %(orientacao_sexual)s,
                                   deseja_informar_ig = %(deseja_informar_ig)s, identidade_genero = %(identidade_genero)s
                             WHERE id_ficha = %(id_ficha)s""", {**marcadores, "id_ficha": int(id_ficha)})]),
                            "Ficha alterada.")
            else:
                st.warning("Excluir a ficha apaga também os tipos de deficiência ligados a ela (ON DELETE CASCADE).")
                if st.checkbox("Confirmo a exclusão", key="conf_ficha") and st.button("Excluir ficha", type="primary"):
                    mostrar_resultado(*executar([("DELETE FROM ficha_cadastro WHERE id_ficha = %s", (int(id_ficha),))]),
                                      "Ficha excluída.")


# ---------------------------------------------------------------------------
# Importar arquivo: ingestão de fichas por CSV ou planilha
# ---------------------------------------------------------------------------

with aba_importar:
    st.caption("Envie um CSV ou uma planilha Excel com fichas de cadastro, uma por linha. O arquivo é conferido "
               "contra as regras do banco antes de gravar. Ao gravar, os indicadores das equipes nos quadrimestres "
               "que receberam fichas são recalculados.")
    c1, c2 = st.columns([3, 1])
    with c2:
        st.download_button("Baixar modelo (.csv)", ingestao.modelo_csv(), "modelo_fichas.csv", "text/csv",
                           width="stretch")
    with c1:
        with st.expander("Colunas do arquivo"):
            st.markdown(
                f"**Obrigatórias:** `{'`, `'.join(ingestao.OBRIGATORIAS)}`  \n"
                f"**Opcionais:** `{'`, `'.join(ingestao.OPCIONAIS)}`  \n"
                "Datas em AAAA-MM-DD ou DD/MM/AAAA · `tipo_deficiencia` com categorias separadas por `;` · "
                "marcador vazio = N/I · `id_ficha` opcional: se vier, reimportar o mesmo arquivo não duplica fichas. "
                "Aceita também os nomes do PEC sintético (`id_cidadao`, `data_ficha`, `nome_social`).")

    with st.expander("Histórico de entradas no banco"):
        st.caption("Cada linha é um momento em que fichas entraram no banco (carga inicial, importação de arquivo "
                   "ou cadastro na tela). `data_envio` é quando a equipe enviou; `data_entrada`, quando chegou ao banco.")
        comando_hist = """
            SELECT f.data_entrada,
                   COUNT(*)                AS fichas,
                   COUNT(DISTINCT f.ine)   AS equipes,
                   MIN(f.data_envio)       AS envio_mais_antigo,
                   MAX(f.data_envio)       AS envio_mais_recente
            FROM ficha_cadastro f
            GROUP BY f.data_entrada
            ORDER BY f.data_entrada DESC
            LIMIT 20"""
        hist = consultar(comando_hist)
        hist["data_entrada"] = pd.to_datetime(hist["data_entrada"]).dt.tz_convert("America/Recife").dt.strftime("%d/%m/%Y %H:%M:%S")
        st.dataframe(hist, hide_index=True, width="stretch")

    arquivo = st.file_uploader("Arquivo de fichas", type=["csv", "xlsx"])
    if arquivo is not None:
        try:
            df = ingestao.ler(arquivo, arquivo.name)
            validas, erros = ingestao.validar(df, ingestao.ines_cadastrados(URL))
        except ValueError as e:
            st.error(str(e))
            st.stop()

        m = st.columns(3)
        m[0].metric("Linhas no arquivo", f"{len(df):,}".replace(",", "."))
        m[1].metric("Prontas para gravar", f"{len(validas):,}".replace(",", "."))
        m[2].metric("Com erro", f"{erros['linha'].nunique():,}".replace(",", "."))

        if len(erros):
            st.markdown("**Linhas com erro** (não serão gravadas)")
            st.dataframe(erros, hide_index=True, width="stretch", height=min(35 * (len(erros) + 1), 300))
            st.download_button("Baixar lista de erros (.csv)", ingestao.erros_csv(erros), "erros_importacao.csv",
                               "text/csv")
        if len(validas):
            with st.expander("Prévia das linhas válidas"):
                st.dataframe(validas.head(50), hide_index=True, width="stretch")

            chave = (arquivo.name, arquivo.size)
            if st.session_state.get("importado") == chave:
                st.info("Este arquivo já foi gravado. Para importar de novo, envie o arquivo outra vez.")
            elif st.button(f"Gravar {len(validas):,} fichas no banco".replace(",", "."), type="primary"):
                try:
                    with st.spinner("Gravando e recalculando os indicadores..."):
                        r, executados = ingestao.gravar(URL, validas)
                except psycopg.Error as e:
                    st.error(f"O banco recusou a importação (nada foi gravado): {e.diag.message_primary or e}")
                else:
                    st.session_state["importado"] = chave
                    st.success(
                        f"{r['fichas_inseridas']:,} fichas gravadas".replace(",", ".")
                        + f" em {r['data_entrada'].astimezone(ZoneInfo('America/Recife')):%d/%m/%Y %H:%M:%S}"
                        + (f" · {r['ja_existiam']:,} já estavam no banco e foram ignoradas".replace(",", ".")
                           if r["ja_existiam"] else "")
                        + f" · {r['cidadaos_novos']} cidadãos novos · {r['deficiencias']} indicações de deficiência"
                        + (f" · indicadores recalculados em {', '.join(r['quadrimestres'])} "
                           f"({r['indicadores']} equipes)" if r["quadrimestres"] else ""))
                    if r["quadrimestres"]:
                        st.dataframe(consultar("""
                            SELECT v.quadrimestre, COUNT(*) AS equipes, SUM(v.qtd_fichas) AS fichas,
                                   ROUND(AVG(v.indice_completude), 1) AS indice_medio,
                                   COUNT(*) FILTER (WHERE v.critica) AS equipes_criticas
                            FROM vw_indicador_territorio v
                            WHERE v.quadrimestre = ANY(%(q)s)
                            GROUP BY v.quadrimestre ORDER BY v.quadrimestre""", {"q": r["quadrimestres"]}),
                            hide_index=True, width="stretch")
                    with st.expander("SQL executado"):
                        st.code(";\n\n".join(executados) + ";", language="sql")
