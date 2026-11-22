"""
Banco de Dados (Etapas 03 a 06): interface sobre o PostgreSQL do projeto.

- Consultas e gráficos: as consultas de db/consultas.py (Etapa 03, Etapa 04 e as visões), com o SQL executado à mostra
- Tabelas: visualização de qualquer tabela ou visão do banco
- CRUD em 4 tabelas: Equipes, Unidades de saúde, Tipos de deficiência e Fichas de cadastro
  (a ficha grava também cidadao e ficha_deficiencia na mesma transação)
- Funções, procedimentos e triggers (Etapa 05): executar e ver os efeitos na tela
- Importar arquivo: ingestão de fichas por CSV ou planilha (db/ingestao.py), com validação e recálculo dos indicadores
- Pipeline: depois de cada importação (ou pelo botão) atualiza os agregados do painel e o modelo de ML (src/pipeline.py)

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import pipeline  # noqa: E402

AZUL, LARANJA, VERDE_AGUA = "#2a78d6", "#eb6834", "#1baf7a"
AMARELO_GRAF = "#eda100"
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
    executados, resultados, avisos = [], [], []
    try:
        with psycopg.connect(URL) as con:
            # RAISE NOTICE dos triggers e procedimentos (Etapa 05) aparece na tela
            con.add_notice_handler(lambda d: avisos.append(d.message_primary))
            with con.transaction(), con.cursor() as cur:
                for comando, params in comandos:
                    if callable(params):
                        params = params(resultados)
                    cur.execute(comando, params)
                    executados.append(psycopg.ClientCursor(con).mogrify(comando, params).strip())
                    resultados.append(cur.fetchall() if cur.description else cur.rowcount)
        for a in avisos:
            st.info(f"Aviso do banco (RAISE NOTICE): {a}")
        st.cache_data.clear()   # Dashboard relê o banco
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

(aba_consultas, aba_tabelas, aba_equipes, aba_unidades, aba_tipos, aba_fichas, aba_rotinas,
 aba_importar, aba_pipeline) = st.tabs(
    ["📊 Consultas e gráficos", "🗂️ Tabelas e visões", "👥 Equipes", "🏥 Unidades de saúde", "♿ Tipos de deficiência",
     "📝 Fichas de cadastro", "🧮 Funções, procedimentos e triggers", "📥 Importar arquivo", "⚙️ Pipeline"])


def rodar_pipeline(gatilho):
    """Roda src/pipeline.py mostrando cada passo e limpa o cache do Painel e das Estatísticas."""
    with st.status("Pipeline: atualizando painel e modelo...", expanded=True) as caixa:
        try:
            r = pipeline.rodar(URL, gatilho=gatilho, log=st.write)
        except Exception as e:
            caixa.update(label="Pipeline falhou (o erro ficou registrado na aba Pipeline)", state="error")
            st.error(str(e))
            return None
        st.cache_data.clear()   # Painel e Estatísticas releem o banco na próxima visita
        caixa.update(label=f"Pipeline concluída em {r['segundos']:.0f} s: painel e risco atualizados", state="complete")
        return r


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
    elif chave == "anti_join":
        st.metric("Equipes sem nenhum registro do grupo em 12 meses", len(df))
        st.altair_chart(alt.Chart(df.assign(distrito=lambda x: "DS " + x["distrito"].astype(str)))
                        .mark_bar(color=LARANJA, cornerRadiusEnd=3).encode(
            y=alt.Y("equipe:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X("fichas_no_periodo:Q", title="Fichas enviadas nos 3 quadrimestres"),
            tooltip=["equipe", "unidade", "distrito", "fichas_no_periodo", "indice_medio"],
        ).properties(height=24 * len(df), title="Muitas fichas e nenhuma pessoa trans, travesti ou não binária"),
            width="stretch")
    elif chave == "full_outer":
        sem_cis = st.checkbox("Esconder pessoas cis (para enxergar as categorias pequenas)", value=True)
        d = df[~df["identidade_genero"].isin(["mulher_cis", "homem_cis"])] if sem_cis else df
        d = d.melt(id_vars=["identidade_genero", "situacao"], value_vars=["pct_esperado", "pct_registrado"],
                   var_name="fonte", value_name="pct")
        d["fonte"] = d["fonte"].map({"pct_esperado": "Esperado (Inferência)", "pct_registrado": "Registrado (fichas)"})
        d["pct"] = d["pct"].astype(float)
        st.altair_chart(alt.Chart(d).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("identidade_genero:N", title=None), yOffset="fonte:N",
            x=alt.X("pct:Q", title="% das respostas / fichas de adultos"),
            color=alt.Color("fonte:N", scale=alt.Scale(range=["#f4b39a", AZUL]), legend=alt.Legend(orient="top", title=None)),
            tooltip=["identidade_genero", "fonte", alt.Tooltip("pct:Q", format=".2f"), "situacao"],
        ).properties(height=320, title=f"DS {distrito} · {quad}: identidade de gênero esperada × registrada"),
            width="stretch")
    elif chave == "libras":
        st.altair_chart(alt.Chart(df.assign(distrito=lambda x: "DS " + x["distrito"].astype(str)))
                        .mark_bar(color=AZUL, cornerRadiusEnd=3).encode(
            y=alt.Y("unidade:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X("pessoas_ativas:Q", title="Pessoas ativas com o tipo escolhido"),
            tooltip=["unidade", "bairro", "distrito", "pessoas_ativas"],
        ).properties(height=28 * len(df), title="Unidades com mais pessoas do tipo de deficiência escolhido"),
            width="stretch")
    elif chave == "persistentes":
        d = df.groupby("distrito", as_index=False).agg(equipes=("equipe", "count"))
        d["distrito"] = "DS " + d["distrito"].astype(str)
        st.metric("Equipes críticas nos 3 quadrimestres seguidos", len(df))
        st.altair_chart(alt.Chart(d).mark_bar(color=LARANJA, cornerRadiusEnd=3).encode(
            x=alt.X("distrito:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("equipes:Q", title="Equipes"),
            tooltip=["distrito", "equipes"],
        ).properties(height=260, title=f"Críticas persistentes até {quad}, por distrito"), width="stretch")
    elif chave == "vw_indicador":
        d = df.assign(indice_completude=lambda x: x["indice_completude"].astype(float),
                      situacao=lambda x: x["critica"].map({True: "Crítica (25% piores)", False: "Não crítica"}))
        st.altair_chart(alt.Chart(d).mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
            x=alt.X("equipe:N", sort="y", title=f"Equipes do DS {distrito} (passe o mouse)", axis=alt.Axis(labels=False, ticks=False)),
            y=alt.Y("indice_completude:Q", title="Índice de completude"),
            color=alt.Color("situacao:N", scale=alt.Scale(domain=["Crítica (25% piores)", "Não crítica"], range=[LARANJA, AZUL]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["equipe", "unidade", "bairro", "qtd_fichas", "indice_completude", "risco_previsto"],
        ).properties(height=300, title=f"Índice de cada equipe do DS {distrito} em {quad}"), width="stretch")
    elif chave == "vw_marcadores":
        d = df.melt(id_vars="unidade", value_vars=["pct_orientacao", "pct_identidade", "pct_raca", "pct_deficiencia"],
                    var_name="marcador", value_name="pct")
        d["marcador"] = d["marcador"].map({"pct_orientacao": "Orientação sexual", "pct_identidade": "Identidade de gênero",
                                           "pct_raca": "Raça/cor", "pct_deficiencia": "Deficiência"})
        d["pct"] = d["pct"].astype(float)
        st.altair_chart(alt.Chart(d).mark_circle(size=90, stroke="#fcfcfb", strokeWidth=1).encode(
            y=alt.Y("unidade:N", sort=list(df["unidade"]), title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X("pct:Q", title="% das fichas com o marcador preenchido"),
            color=alt.Color("marcador:N", scale=alt.Scale(range=CATEGORICAS[:4]), legend=alt.Legend(orient="top", title=None)),
            tooltip=["unidade", "marcador", "pct"],
        ).properties(height=24 * len(df), title=f"Preenchimento por unidade · DS {distrito} · {quad}"), width="stretch")


with aba_consultas:
    etapas = list(dict.fromkeys(c.get("etapa", "Etapa 03") for c in CONSULTAS.values()))
    etapa = st.segmented_control("Grupo", etapas, default=etapas[0]) or etapas[0]
    chave = st.selectbox("Consulta", [k for k, c in CONSULTAS.items() if c.get("etapa", "Etapa 03") == etapa],
                         format_func=lambda k: CONSULTAS[k]["titulo"])
    c = CONSULTAS[chave]
    st.markdown(f"**O que responde:** {c['pergunta']}")
    st.caption(f"Técnicas SQL: {c['tecnicas']}")

    valores = {"ano": ano, "numero": numero, "distrito": distrito}
    if "grupo" in c["params"]:
        valores["grupo"] = st.selectbox("Grupo", list(GRUPOS), format_func=GRUPOS.get)
    if "limite_pp" in c["params"]:
        valores["limite_pp"] = st.slider("Diferença mínima para o distrito (pontos percentuais)", 5, 40, EXEMPLO["limite_pp"])
    if "tipos" in c["params"]:
        todos_tipos = consultar("SELECT descricao FROM tipo_deficiencia ORDER BY categoria, descricao")["descricao"].tolist()
        valores["tipos"] = st.multiselect("Tipos de deficiência", todos_tipos,
                                          [t for t in EXEMPLO["tipos"] if t in todos_tipos]) or EXEMPLO["tipos"]
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
    "agenda_apoio": "id_quadrimestre DESC, nr_distrito, semana", "log_ficha_cadastro": "id_log DESC",
    "execucao_pipeline": "id_execucao DESC",
    "vw_indicador_territorio (visão)": "id_quadrimestre DESC, indice_completude",
    "vw_ficha_marcadores (visão)": "data_envio DESC",
}

with aba_tabelas:
    escolha = st.selectbox("Tabela ou visão", list(TABELAS))
    tabela = escolha.replace(" (visão)", "")
    limite = st.select_slider("Linhas", [20, 50, 100, 200, 500], value=50)
    # nome de tabela não pode ser parâmetro: vem de uma lista fixa e entra como identificador seguro
    total = consultar(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(tabela)))["n"].iloc[0]
    comando = sql.SQL("SELECT * FROM {} ORDER BY {} LIMIT %(limite)s").format(
        sql.Identifier(tabela), sql.SQL(TABELAS[escolha]))
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
# CRUD · Unidades de saúde (unidade_saude)
# ---------------------------------------------------------------------------

with aba_unidades:
    unidades_ds = consultar("""
        SELECT u.cnes, u.nome AS unidade, b.id_bairro, b.nome AS bairro,
               u.latitude::float8 AS latitude, u.longitude::float8 AS longitude,
               (SELECT COUNT(*) FROM equipe e WHERE e.cnes = u.cnes) AS equipes
        FROM unidade_saude u
        JOIN bairro b ON b.id_bairro = u.id_bairro
        WHERE b.nr_distrito = %(distrito)s
        ORDER BY u.nome""", {"distrito": distrito})
    bairros_ds = consultar("SELECT id_bairro, nome FROM bairro WHERE nr_distrito = %(d)s ORDER BY nome", {"d": distrito})
    nome_bairro = dict(zip(bairros_ds["id_bairro"], bairros_ds["nome"]))

    st.markdown(f"**Unidades do DS {distrito}** · {len(unidades_ds)} unidades")
    st.dataframe(unidades_ds.drop(columns="id_bairro"), hide_index=True, width="stretch", height=260)
    acao = st.radio("Operação", ["Inserir", "Alterar", "Excluir"], horizontal=True, key="acao_unidade")

    if acao == "Inserir":
        with st.form("inserir_unidade", clear_on_submit=True):
            c1, c2 = st.columns([1, 3])
            cnes = c1.text_input("CNES (7 dígitos)", max_chars=7)
            nome = c2.text_input("Nome da unidade")
            c3, c4, c5 = st.columns([2, 1, 1])
            id_bairro = c3.selectbox("Bairro", list(nome_bairro), format_func=nome_bairro.get)
            lat = c4.number_input("Latitude", -90.0, 90.0, -8.05, format="%.6f")
            lon = c5.number_input("Longitude", -180.0, 180.0, -34.90, format="%.6f")
            if st.form_submit_button("Inserir unidade", type="primary"):
                mostrar_resultado(*executar([(
                    "INSERT INTO unidade_saude (cnes, nome, latitude, longitude, id_bairro) VALUES (%s, %s, %s, %s, %s)",
                    (cnes, nome, lat, lon, int(id_bairro)))]), f"Unidade {nome} inserida.")

    elif acao == "Alterar" and len(unidades_ds):
        rot = dict(zip(unidades_ds["cnes"], unidades_ds["unidade"]))
        cnes = st.selectbox("Unidade", list(rot), format_func=rot.get, key="alt_unidade")
        atual = unidades_ds.set_index("cnes").loc[cnes]
        with st.form("alterar_unidade"):
            nome = st.text_input("Nome", atual["unidade"])
            c3, c4, c5 = st.columns([2, 1, 1])
            ids = list(nome_bairro)
            id_bairro = c3.selectbox("Bairro", ids, index=ids.index(atual["id_bairro"]) if atual["id_bairro"] in ids else 0,
                                     format_func=nome_bairro.get)
            lat = c4.number_input("Latitude", -90.0, 90.0, float(atual["latitude"] or 0), format="%.6f")
            lon = c5.number_input("Longitude", -180.0, 180.0, float(atual["longitude"] or 0), format="%.6f")
            if st.form_submit_button("Salvar alteração", type="primary"):
                mostrar_resultado(*executar([(
                    "UPDATE unidade_saude SET nome = %s, id_bairro = %s, latitude = %s, longitude = %s WHERE cnes = %s",
                    (nome, int(id_bairro), lat, lon, cnes))]), "Unidade alterada.")

    elif acao == "Excluir" and len(unidades_ds):
        rot = dict(zip(unidades_ds["cnes"], unidades_ds["unidade"]))
        cnes = st.selectbox("Unidade", list(rot), format_func=rot.get, key="exc_unidade")
        n_eq = int(unidades_ds.set_index("cnes").loc[cnes, "equipes"])
        if n_eq:
            st.warning(f"**{rot[cnes]}** tem {n_eq} equipe(s). A chave estrangeira de `equipe` é ON DELETE RESTRICT: "
                       "o banco vai recusar a exclusão até as equipes mudarem de unidade ou serem excluídas.")
        if st.checkbox("Confirmo a exclusão", key="conf_unidade") and st.button("Excluir unidade", type="primary"):
            mostrar_resultado(*executar([("DELETE FROM unidade_saude WHERE cnes = %s", (cnes,))]), "Unidade excluída.")


# ---------------------------------------------------------------------------
# CRUD · Tipos de deficiência (tipo_deficiencia)
# ---------------------------------------------------------------------------

CATEGORIAS_DEF = ["auditiva", "visual", "intelectual", "fisica", "tea", "outra"]

with aba_tipos:
    tipos_def = consultar("""
        SELECT t.id_tipo_deficiencia, t.descricao, t.categoria,
               (SELECT COUNT(*) FROM ficha_deficiencia fd
                WHERE fd.id_tipo_deficiencia = t.id_tipo_deficiencia) AS fichas_que_indicam
        FROM tipo_deficiencia t
        ORDER BY t.categoria, t.descricao""")
    st.markdown(f"**Tipos de deficiência da ficha e-SUS** · {len(tipos_def)} tipos")
    st.dataframe(tipos_def, hide_index=True, width="stretch", height=260)
    acao = st.radio("Operação", ["Inserir", "Alterar", "Excluir"], horizontal=True, key="acao_tipo")
    rot = {r.id_tipo_deficiencia: f"{r.categoria} · {r.descricao}" for r in tipos_def.itertuples()}

    if acao == "Inserir":
        with st.form("inserir_tipo", clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            descricao = c1.text_input("Descrição")
            categoria = c2.selectbox("Categoria", CATEGORIAS_DEF)
            if st.form_submit_button("Inserir tipo", type="primary"):
                mostrar_resultado(*executar([(
                    "INSERT INTO tipo_deficiencia (descricao, categoria) VALUES (%s, %s) RETURNING id_tipo_deficiencia",
                    (descricao, categoria))]), f"Tipo \"{descricao}\" inserido.")

    elif acao == "Alterar" and len(tipos_def):
        id_tipo = st.selectbox("Tipo", list(rot), format_func=rot.get, key="alt_tipo")
        atual = tipos_def.set_index("id_tipo_deficiencia").loc[id_tipo]
        with st.form("alterar_tipo"):
            c1, c2 = st.columns([3, 1])
            descricao = c1.text_input("Descrição", atual["descricao"])
            categoria = c2.selectbox("Categoria", CATEGORIAS_DEF, CATEGORIAS_DEF.index(atual["categoria"]))
            if st.form_submit_button("Salvar alteração", type="primary"):
                mostrar_resultado(*executar([(
                    "UPDATE tipo_deficiencia SET descricao = %s, categoria = %s WHERE id_tipo_deficiencia = %s",
                    (descricao, categoria, int(id_tipo)))]), "Tipo alterado.")

    elif acao == "Excluir" and len(tipos_def):
        id_tipo = st.selectbox("Tipo", list(rot), format_func=rot.get, key="exc_tipo")
        usos = int(tipos_def.set_index("id_tipo_deficiencia").loc[id_tipo, "fichas_que_indicam"])
        if usos:
            st.warning(f"{usos:,} fichas indicam este tipo. `ficha_deficiencia` usa ON DELETE RESTRICT: o banco vai "
                       "recusar a exclusão (o índice ix_fd_tipo da Etapa 04 é o que torna essa checagem rápida).")
        if st.checkbox("Confirmo a exclusão", key="conf_tipo") and st.button("Excluir tipo", type="primary"):
            mostrar_resultado(*executar([("DELETE FROM tipo_deficiencia WHERE id_tipo_deficiencia = %s", (int(id_tipo),))]),
                              "Tipo excluído.")


# ---------------------------------------------------------------------------
# Etapa 05 · funções, procedimentos e triggers: executar e ver os efeitos
# ---------------------------------------------------------------------------

def executar_vendo_avisos(comandos, desfazer=False):
    """Executa (comando, params) numa transação guardando os RAISE NOTICE do banco.
    desfazer=True: termina com ROLLBACK (demonstração que não deixa alteração no banco).
    Devolve (resultados, avisos, sql executado) ou None se o banco recusar."""
    resultados, avisos, executados = [], [], []
    try:
        with psycopg.connect(URL) as con:
            con.add_notice_handler(lambda d: avisos.append(d.message_primary))
            with con.transaction(force_rollback=desfazer), con.cursor() as cur:
                for comando, params in comandos:
                    cur.execute(comando, params)
                    executados.append(psycopg.ClientCursor(con).mogrify(comando, params).strip())
                    resultados.append(
                        pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description]) if cur.description else None)
        return resultados, avisos, executados
    except psycopg.Error as e:
        st.error(f"O banco recusou: {e.diag.message_primary or e}")
        return None


with aba_rotinas:
    st.caption("Funções, procedimentos e triggers criados na Etapa 05 (código em `db/schema.sql`). "
               "Cada bloco executa o objeto no banco e mostra o efeito; os RAISE NOTICE aparecem como avisos.")
    rotina = st.segmented_control(
        "Objeto", ["fn_estado_marcador", "fn_indice_completude", "pr_recalcular_indicadores", "pr_agendar_apoio",
                   "Triggers"], default="fn_estado_marcador") or "fn_estado_marcador"

    if rotina == "fn_estado_marcador":
        st.markdown("**Função 1 · `fn_estado_marcador(marcador, resposta, idade)`**: a regra Preenchido / Recusou / N/I "
                    "num ponto só do banco (com IF / ELSIF / ELSE). Crianças até 10 anos ficam fora de orientação e "
                    "identidade (NULL); marcador desconhecido gera erro.")
        c1, c2, c3 = st.columns(3)
        marcador = c1.selectbox("Marcador", ["orientacao", "identidade", "raca", "deficiencia", "outro (testar o erro)"])
        resposta = c2.selectbox("Resposta na ficha", ["sim", "nao", "(vazio = NULL)", "parda"],
                                help="Orientação/identidade: o campo 'deseja informar'. Raça/deficiência: o próprio campo.")
        idade = c3.number_input("Idade", 0, 110, 30, key="fn1_idade")
        comando = "SELECT fn_estado_marcador(%(m)s, %(r)s, %(i)s) AS estado"
        p_fn = {"m": marcador.split(" ")[0], "r": None if resposta.startswith("(") else resposta, "i": int(idade)}
        r = executar_vendo_avisos([(comando, p_fn)], desfazer=True)
        if r:
            estado = r[0][0].iloc[0, 0]
            st.metric("Resultado da função", estado if estado is not None else "NULL (fora do marcador)")
            st.code(r[2][0] + ";", language="sql")

        st.markdown(f"**A função aplicada às fichas do DS {distrito} em {quad}**")
        comando = """
            SELECT m.marcador, fn_estado_marcador(m.chave, m.resposta, f.idade) AS estado, COUNT(*) AS fichas
            FROM ficha_cadastro f
            JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
            JOIN equipe e ON e.ine = f.ine
            JOIN unidade_saude u ON u.cnes = e.cnes
            JOIN bairro b ON b.id_bairro = u.id_bairro
            CROSS JOIN LATERAL (VALUES ('Orientação sexual', 'orientacao', f.deseja_informar_os),
                                       ('Identidade de gênero', 'identidade', f.deseja_informar_ig),
                                       ('Raça/cor', 'raca', f.raca_cor),
                                       ('Deficiência', 'deficiencia', f.tem_deficiencia)) AS m (marcador, chave, resposta)
            WHERE q.ano = %(ano)s AND q.numero = %(numero)s AND b.nr_distrito = %(distrito)s
            GROUP BY 1, 2 ORDER BY 1, 2"""
        p_ap = {"ano": ano, "numero": numero, "distrito": distrito}
        aplic = consultar(comando, p_ap)
        aplic["estado"] = aplic["estado"].fillna("Fora (criança)")
        st.altair_chart(alt.Chart(aplic).mark_bar(cornerRadius=3, stroke="#fcfcfb", strokeWidth=2).encode(
            y=alt.Y("marcador:N", title=None), x=alt.X("fichas:Q", title="Fichas"),
            color=alt.Color("estado:N", scale=alt.Scale(domain=["Preenchido", "Recusou", "N/I", "Fora (criança)"],
                                                         range=[AZUL, LARANJA, VERDE_AGUA, "#c9c7c1"]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["marcador", "estado", "fichas"]).properties(height=220), width="stretch")
        with st.expander("SQL executado"):
            st.code(sql_executado(comando, p_ap), language="sql")

    elif rotina == "fn_indice_completude":
        st.markdown("**Função 2 · `fn_indice_completude(ine, id_quadrimestre)`**: calcula na hora, direto das fichas, "
                    "o índice da equipe (média ponderada do preenchimento dos 4 marcadores). Abaixo, o valor da função "
                    "ao lado do valor gravado em `indicador_equipe`, em todos os quadrimestres da equipe.")
        eq = consultar("""SELECT e.ine, e.nome FROM equipe e JOIN unidade_saude u ON u.cnes = e.cnes
                          JOIN bairro b ON b.id_bairro = u.id_bairro WHERE b.nr_distrito = %(d)s ORDER BY e.nome""",
                       {"d": distrito})
        rot = dict(zip(eq["ine"], eq["nome"]))
        ine = st.selectbox("Equipe", list(rot), format_func=rot.get, key="fn2_equipe")
        comando = """
            SELECT q.ano || '.' || q.numero                          AS quadrimestre,
                   i.indice_completude                               AS gravado,
                   fn_indice_completude(i.ine, i.id_quadrimestre)    AS calculado_pela_funcao,
                   fn_indice_completude(i.ine, i.id_quadrimestre) - i.indice_completude AS diferenca
            FROM indicador_equipe i
            JOIN quadrimestre q ON q.id_quadrimestre = i.id_quadrimestre
            WHERE i.ine = %(ine)s
            ORDER BY q.ano, q.numero"""
        comp = consultar(comando, {"ine": ine})
        d = comp.melt(id_vars="quadrimestre", value_vars=["gravado", "calculado_pela_funcao"], var_name="origem",
                      value_name="indice")
        d["indice"] = d["indice"].astype(float)
        d["origem"] = d["origem"].map({"gravado": "Gravado em indicador_equipe", "calculado_pela_funcao": "fn_indice_completude"})
        st.altair_chart(alt.Chart(d).mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2).encode(
            x=alt.X("quadrimestre:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("indice:Q", title="Índice de completude", scale=alt.Scale(zero=False)),
            color=alt.Color("origem:N", scale=alt.Scale(range=[AZUL, LARANJA]), legend=alt.Legend(orient="top", title=None)),
            strokeDash=alt.StrokeDash("origem:N", legend=None),
            tooltip=["quadrimestre", "origem", "indice"]).properties(height=280), width="stretch")
        divergencias = int((comp["diferenca"].astype(float).abs() > 0.005).sum())
        st.caption("As duas linhas coincidem quando o indicador gravado está em dia com as fichas. "
                   f"Divergências nesta equipe: **{divergencias}**. Se uma ficha for alterada, a função já mostra o valor "
                   "novo e o gravado fica velho até o procedimento `pr_recalcular_indicadores` rodar.")
        st.dataframe(comp, hide_index=True, width="stretch")
        with st.expander("SQL executado"):
            st.code(sql_executado(comando, {"ine": ine}), language="sql")

    elif rotina == "pr_recalcular_indicadores":
        st.markdown(f"**Procedimento 1 · `pr_recalcular_indicadores(ano, numero)`**: atualiza a quantidade de fichas e o "
                    f"índice das equipes do quadrimestre, insere as equipes que passaram a ter fichas e remarca quem é "
                    f"crítica (P25). Quadrimestre: **{quad}** (barra lateral).")
        resumo_sql = """
            SELECT COUNT(*) AS equipes, SUM(qtd_fichas) AS fichas, ROUND(AVG(indice_completude), 2) AS indice_medio,
                   COUNT(*) FILTER (WHERE critica) AS criticas
            FROM indicador_equipe i JOIN quadrimestre q ON q.id_quadrimestre = i.id_quadrimestre
            WHERE q.ano = %(ano)s AND q.numero = %(numero)s"""
        antes = consultar(resumo_sql, {"ano": ano, "numero": numero})
        st.markdown("**Antes**")
        st.dataframe(antes, hide_index=True, width="stretch")
        if st.button(f"CALL pr_recalcular_indicadores({ano}, {numero})", type="primary"):
            r = executar_vendo_avisos([("CALL pr_recalcular_indicadores(%s, %s)", (ano, numero)),
                                       (resumo_sql, {"ano": ano, "numero": numero})])
            if r:
                for a in r[1]:
                    st.info(f"Aviso do banco (RAISE NOTICE): {a}")
                st.markdown("**Depois**")
                st.dataframe(r[0][1], hide_index=True, width="stretch")
                st.cache_data.clear()
                st.caption("Para o Painel refletir a mudança, rode a pipeline (aba Pipeline): ela atualiza as visões "
                           "materializadas e o risco do modelo.")
                with st.expander("SQL executado", expanded=True):
                    st.code(";\n\n".join(r[2]) + ";", language="sql")

    elif rotina == "pr_agendar_apoio":
        st.markdown(f"**Procedimento 2 · `pr_agendar_apoio(ano, numero, horas_semana)`** (com cursor): monta a agenda "
                    f"do apoiador de cada distrito para as equipes com risco ≥ 50% depois de **{quad}**. Percorre as "
                    "equipes da mais urgente para a menos urgente e encaixa cada uma na primeira semana com horas livres "
                    "(*first-fit*): a semana de cada equipe depende das que vieram antes, por isso o cursor.")
        horas = st.slider("Horas do apoiador por semana", 8, 40, 20, step=2)
        if st.button(f"CALL pr_agendar_apoio({ano}, {numero}, {horas})", type="primary"):
            r = executar_vendo_avisos([("CALL pr_agendar_apoio(%s, %s, %s)", (ano, numero, horas))])
            if r:
                for a in r[1]:
                    st.info(f"Aviso do banco (RAISE NOTICE): {a}")
                with st.expander("SQL executado"):
                    st.code(r[2][0] + ";", language="sql")
        comando = """
            SELECT a.semana, a.inicio_semana, e.nome AS equipe, a.horas, ROUND(100 * a.risco_previsto, 1) AS risco_pct
            FROM agenda_apoio a
            JOIN quadrimestre q ON q.id_quadrimestre = a.id_quadrimestre
            JOIN equipe e ON e.ine = a.ine
            WHERE q.ano = %(ano)s AND q.numero = %(numero)s AND a.nr_distrito = %(distrito)s
            ORDER BY a.semana, a.risco_previsto DESC"""
        agenda = consultar(comando, {"ano": ano, "numero": numero, "distrito": distrito}).astype({"risco_pct": float})
        if agenda.empty:
            st.info(f"Ainda não há agenda gravada para {quad} no DS {distrito}. Clique no botão acima para gerar "
                    "(precisa do risco do modelo nesse quadrimestre; o mais recente sempre tem).")
        else:
            agenda["horas_txt"] = agenda["horas"].astype(str) + " h"
            st.altair_chart(alt.Chart(agenda).mark_bar(stroke="#fcfcfb", strokeWidth=2, cornerRadius=2).encode(
                x=alt.X("semana:O", title="Semana do quadrimestre seguinte", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("horas:Q", title="Horas agendadas"),
                color=alt.Color("horas_txt:N", title="Carga da equipe",
                                scale=alt.Scale(domain=["8 h", "6 h", "4 h"], range=[LARANJA, AMARELO_GRAF, AZUL]),
                                legend=alt.Legend(orient="top")),
                order=alt.Order("risco_pct:Q", sort="descending"),
                tooltip=["semana", "inicio_semana", "equipe", "horas", "risco_pct"],
            ).properties(height=300, title=f"Agenda do apoiador do DS {distrito}: cada bloco é uma equipe"), width="stretch")
            st.dataframe(agenda.drop(columns="horas_txt"), hide_index=True, width="stretch")
            with st.expander("SQL executado"):
                st.code(sql_executado(comando, {"ano": ano, "numero": numero, "distrito": distrito}), language="sql")

    else:
        st.markdown("**Trigger 1 · `trg_ficha_log`** (auditoria, LGPD): toda alteração ou exclusão de ficha grava em "
                    "`log_ficha_cadastro` quem, quando, quais campos mudaram, a ficha antes e depois.  \n"
                    "**Trigger 2 · `trg_ficha_sem_deficiencia`**: se a ficha deixa de ter `tem_deficiencia = 'sim'`, "
                    "os tipos de deficiência ligados a ela são removidos (coerência).")
        st.markdown("##### Demonstração (dentro de uma transação desfeita no fim: não altera o banco)")
        candidata = consultar("""
            SELECT f.id_ficha FROM ficha_cadastro f
            JOIN equipe e ON e.ine = f.ine JOIN unidade_saude u ON u.cnes = e.cnes JOIN bairro b ON b.id_bairro = u.id_bairro
            WHERE f.tem_deficiencia = 'sim' AND f.idade > 10 AND b.nr_distrito = %(d)s
              AND EXISTS (SELECT 1 FROM ficha_deficiencia fd WHERE fd.id_ficha = f.id_ficha)
            ORDER BY f.id_ficha DESC LIMIT 1""", {"d": distrito})
        if candidata.empty:
            st.info("Nenhuma ficha com deficiência neste distrito para a demonstração.")
        else:
            id_demo = st.number_input("Ficha usada (com deficiência e tipos indicados)", min_value=1,
                                      value=int(candidata.iloc[0, 0]), step=1)
            st.caption("O botão faz: UPDATE da ficha mudando `tem_deficiencia` para 'nao' e informando a orientação "
                       "sexual → lê os tipos de deficiência e o log → ROLLBACK.")
            if st.button("Executar a demonstração", type="primary"):
                tipos_sql = """SELECT t.descricao FROM ficha_deficiencia fd
                               JOIN tipo_deficiencia t ON t.id_tipo_deficiencia = fd.id_tipo_deficiencia
                               WHERE fd.id_ficha = %(id)s"""
                p_demo = {"id": int(id_demo)}
                r = executar_vendo_avisos([
                    (tipos_sql, p_demo),
                    ("""UPDATE ficha_cadastro
                           SET tem_deficiencia = 'nao',
                               deseja_informar_os = 'sim',
                               orientacao_sexual = COALESCE(orientacao_sexual, 'heterossexual')
                         WHERE id_ficha = %(id)s AND idade > 10""", p_demo),
                    (tipos_sql, p_demo),
                    ("""SELECT id_log, momento, usuario, operacao, campos_alterados,
                               antes ->> 'tem_deficiencia' AS deficiencia_antes,
                               depois ->> 'tem_deficiencia' AS deficiencia_depois
                        FROM log_ficha_cadastro WHERE id_ficha = %(id)s ORDER BY id_log DESC LIMIT 1""", p_demo),
                ], desfazer=True)
                if r:
                    for a in r[1]:
                        st.info(f"Aviso do banco (RAISE NOTICE, trigger 2): {a}")
                    c1, c2 = st.columns(2)
                    c1.markdown("**Tipos de deficiência antes**")
                    c1.dataframe(r[0][0], hide_index=True, width="stretch")
                    c2.markdown("**Depois do UPDATE (trigger 2 removeu)**")
                    c2.dataframe(r[0][2], hide_index=True, width="stretch")
                    st.markdown("**Linha gravada pelo trigger 1 em `log_ficha_cadastro`**")
                    st.dataframe(r[0][3], hide_index=True, width="stretch")
                    st.success("Transação desfeita (ROLLBACK): a ficha e o log voltaram ao que eram.")
                    with st.expander("SQL executado"):
                        st.code(";\n\n".join(r[2]) + ";\n\nROLLBACK;", language="sql")

        st.markdown("##### Log real das alterações e exclusões feitas na aba Fichas de cadastro")
        log = consultar("""
            SELECT l.id_log, l.momento, l.usuario, l.operacao, l.id_ficha, e.nome AS equipe, l.campos_alterados
            FROM log_ficha_cadastro l LEFT JOIN equipe e ON e.ine = l.ine
            ORDER BY l.id_log DESC LIMIT 30""")
        if log.empty:
            st.info("Nenhuma alteração registrada ainda. Altere ou exclua uma ficha na aba Fichas de cadastro e volte aqui.")
        else:
            log["momento"] = pd.to_datetime(log["momento"]).dt.tz_convert("America/Recife").dt.strftime("%d/%m/%Y %H:%M:%S")
            st.dataframe(log, hide_index=True, width="stretch")


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
    lido = None
    if arquivo is not None:
        try:
            df = ingestao.ler(arquivo, arquivo.name)
            validas, erros = ingestao.validar(df, ingestao.ines_cadastrados(URL))
            lido = True
        except ValueError as e:
            st.error(str(e))

    if lido:
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
                    if r["fichas_inseridas"]:
                        rodar_pipeline("importacao")


# ---------------------------------------------------------------------------
# Pipeline: agregados do painel + modelo de ML, automáticos a cada importação
# ---------------------------------------------------------------------------

with aba_pipeline:
    st.markdown(
        "**Fluxo automático:** arquivo importado → validação → fichas no banco (com data de entrada) → "
        "indicadores das equipes → **agregados do painel** (visões materializadas) → **modelo de ML** "
        "(regressão logística, avaliado contra a persistência) → **risco** de cada equipe no próximo quadrimestre "
        "→ Painel e Estatísticas. Roda sozinho depois de cada importação; o botão abaixo roda na hora "
        "(ex.: depois de cadastrar ou alterar fichas na aba Fichas).")
    if st.button("Rodar pipeline agora", type="primary"):
        rodar_pipeline("manual")
    st.markdown("**Execuções**")
    execucoes = consultar("""
        SELECT id_execucao AS "nº", inicio, gatilho, situacao,
               ROUND(EXTRACT(EPOCH FROM fim - inicio)::numeric, 1) AS segundos,
               fichas_no_banco, ultimo_quadrimestre, modelo, f1_modelo, f1_persistencia, equipes_em_risco, erro
        FROM execucao_pipeline ORDER BY id_execucao DESC LIMIT 20""")
    if len(execucoes):
        execucoes["inicio"] = (pd.to_datetime(execucoes["inicio"]).dt.tz_convert("America/Recife")
                               .dt.strftime("%d/%m/%Y %H:%M:%S"))
    st.dataframe(execucoes, hide_index=True, width="stretch")
    st.caption("F1 = equilíbrio entre achar as equipes que ficaram críticas e não dar alarme falso, medido nos "
               "2 quadrimestres mais recentes com resultado conhecido (o modelo não os vê no treino). "
               "Persistência = regra \"quem é crítica agora continua crítica\", a régua mínima.")
