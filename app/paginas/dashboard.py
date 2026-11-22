"""
Dashboard estatístico (Banco de Dados · Etapa 06).

Tudo nesta página vem de SQL executado no PostgreSQL do projeto, na hora, com os filtros da barra lateral
(período e distritos). As medidas estatísticas (média, mediana, moda, variância, desvio padrão, quartis,
correlação e reta de regressão) são calculadas PELO BANCO, com as funções de agregação do PostgreSQL
(AVG, PERCENTILE_CONT, MODE, VAR_SAMP, STDDEV_SAMP, CORR, REGR_SLOPE, REGR_INTERCEPT). O Python só desenha.

Cada bloco tem o expander "SQL executado" com o comando exato que o banco recebeu.
Página do roteador app/app.py.
"""

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dados_painel import url_banco  # noqa: E402

AZUL, LARANJA, VERDE_AGUA, AMARELO, ROSA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
CATEGORICAS = [AZUL, LARANJA, VERDE_AGUA, AMARELO, ROSA, "#008300", "#4a3aa7", "#e34948"]
CINZA = "#8a8a86"
# Cor fixa por distrito (a cor segue o distrito, não a posição: filtrar não repinta os outros)
COR_DISTRITO = {f"DS {d}": CATEGORICAS[d - 1] for d in range(1, 9)}

URL = url_banco()

st.title("Dashboard estatístico")
st.caption("Indicadores e gráficos calculados direto no PostgreSQL · base SINTÉTICA no formato da Ficha de "
           "Cadastro Individual do e-SUS APS (v5.3): os números mostram o que o sistema faz, não descrevem o Recife.")

if not URL:
    st.info("Esta página lê direto do PostgreSQL e precisa da conexão `DATABASE_URL` "
            "(variável de ambiente ou segredo do Streamlit). Veja o README.")
    st.stop()

import psycopg  # noqa: E402


@st.cache_data(ttl=300, show_spinner=False)
def consultar(comando, params=None):
    """Executa um SELECT no banco e devolve (DataFrame, SQL como o banco recebeu)."""
    with psycopg.connect(URL) as con, con.cursor() as cur:
        cur.execute(comando, params)
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
        texto = psycopg.ClientCursor(con).mogrify(comando, params).strip()
    for col in df.columns:   # NUMERIC do PostgreSQL chega como Decimal: vira float para os gráficos
        amostra = df[col].dropna()
        if df[col].dtype == object and len(amostra) and type(amostra.iloc[0]).__name__ == "Decimal":
            df[col] = df[col].astype(float)
    return df, texto


def mostrar_sql(*textos):
    with st.expander("SQL executado"):
        st.code(";\n\n".join(textos) + ";", language="sql")


def fmt(n, casas=0):
    if n is None or pd.isna(n):
        return "–"
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# Território repetido nas consultas de ficha: ficha -> equipe -> unidade -> bairro (distrito)
TERRITORIO = """
    JOIN equipe        e ON e.ine = f.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro"""

# ---------------------------------------------------------------------------
# Filtros (barra lateral): período em quadrimestres e distritos
# ---------------------------------------------------------------------------

quads, _ = consultar("""
    SELECT q.id_quadrimestre, q.ano || '.' || q.numero AS rotulo, q.data_inicio, q.data_fim
    FROM quadrimestre q
    WHERE EXISTS (SELECT 1 FROM indicador_equipe i WHERE i.id_quadrimestre = q.id_quadrimestre)
    ORDER BY q.ano, q.numero""")
rotulos = list(quads["rotulo"])

with st.sidebar:
    st.markdown("### Filtros do dashboard")
    q_ini, q_fim = st.select_slider("Período (quadrimestres)", rotulos, value=(rotulos[-3], rotulos[-1]))
    distritos = st.multiselect("Distritos Sanitários", list(range(1, 9)), default=list(range(1, 9)),
                               format_func=lambda d: f"DS {d}")
    st.caption("Os filtros valem para todos os indicadores e gráficos da página.")

if not distritos:
    st.warning("Escolha pelo menos um distrito.")
    st.stop()

linha_ini = quads.set_index("rotulo").loc[q_ini]
linha_fim = quads.set_index("rotulo").loc[q_fim]
P = {
    "id_ini": int(linha_ini["id_quadrimestre"]), "id_fim": int(linha_fim["id_quadrimestre"]),
    "inicio": linha_ini["data_inicio"], "fim": linha_fim["data_fim"],
    "distritos": [int(d) for d in distritos],
}
pos_fim = rotulos.index(q_fim)
P_ANT = {**P, "id_ultimo": P["id_fim"],
         "id_anterior": int(quads.iloc[pos_fim - 1]["id_quadrimestre"]) if pos_fim > 0 else P["id_fim"]}

st.markdown(f"**Recorte:** {q_ini} a {q_fim} · "
            + ("todos os distritos" if len(distritos) == 8 else ", ".join(f"DS {d}" for d in sorted(distritos))))

# ---------------------------------------------------------------------------
# 1 · Indicadores resumidos (KPIs)
# ---------------------------------------------------------------------------

SQL_KPI_FICHAS = """
SELECT COUNT(*)                                                    AS fichas,
       COUNT(DISTINCT f.cod_cidadao)                               AS pessoas,
       COUNT(DISTINCT f.ine)                                       AS equipes,
       COUNT(DISTINCT u.cnes)                                      AS unidades,
       ROUND(AVG(f.idade), 1)                                      AS idade_media,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.tem_deficiencia = 'sim') / COUNT(*), 2) AS pct_deficiencia,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.raca_cor IS NULL) / COUNT(*), 1)        AS pct_raca_ni,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.idade > 10 AND f.deseja_informar_os IS NULL)
                   / NULLIF(COUNT(*) FILTER (WHERE f.idade > 10), 0), 1)             AS pct_os_ni
FROM ficha_cadastro f""" + TERRITORIO + """
WHERE f.data_envio BETWEEN %(inicio)s AND %(fim)s
  AND b.nr_distrito = ANY(%(distritos)s)"""

# Índice médio e % de críticas no último quadrimestre do período, com a variação para o anterior
SQL_KPI_INDICADOR = """
SELECT v.id_quadrimestre,
       ROUND(AVG(v.indice_completude), 1)                              AS indice_medio,
       ROUND(100.0 * COUNT(*) FILTER (WHERE v.critica) / COUNT(*), 1)  AS pct_criticas,
       ROUND(100 * AVG(v.risco_previsto), 1)                           AS risco_medio
FROM vw_indicador_territorio v
WHERE v.id_quadrimestre IN (%(id_ultimo)s, %(id_anterior)s)
  AND v.distrito = ANY(%(distritos)s)
GROUP BY v.id_quadrimestre"""

with st.spinner("Consultando o banco..."):
    kpi, sql_kpi = consultar(SQL_KPI_FICHAS, P)
    ind, sql_ind = consultar(SQL_KPI_INDICADOR, P_ANT)
k = kpi.iloc[0]
ult = ind.set_index("id_quadrimestre").reindex([P_ANT["id_ultimo"], P_ANT["id_anterior"]])
tem_anterior = P_ANT["id_anterior"] != P_ANT["id_ultimo"]


def delta(col, sufixo=""):
    if not tem_anterior or ult[col].isna().any():
        return None
    return f"{fmt(ult[col].iloc[0] - ult[col].iloc[1], 1)}{sufixo} vs. {rotulos[pos_fim - 1]}"


st.subheader("Indicadores resumidos")
c = st.columns(4)
c[0].metric("Fichas enviadas", fmt(k["fichas"]))
c[1].metric("Pessoas cadastradas", fmt(k["pessoas"]))
c[2].metric("Equipes / unidades", f"{fmt(k['equipes'])} / {fmt(k['unidades'])}")
c[3].metric("Idade média", f"{fmt(k['idade_media'], 1)} anos")
c = st.columns(4)
c[0].metric(f"Índice de completude médio ({q_fim})", fmt(ult["indice_medio"].iloc[0], 1),
            delta("indice_medio", " pts"))
c[1].metric(f"Equipes críticas ({q_fim})", f"{fmt(ult['pct_criticas'].iloc[0], 1)}%",
            delta("pct_criticas", " pp"), delta_color="inverse")
c[2].metric("Orientação sexual N/I", f"{fmt(k['pct_os_ni'], 1)}%",
            help="% das fichas de maiores de 10 anos em que a equipe não registrou a pergunta")
c[3].metric("Pessoas com deficiência", f"{fmt(k['pct_deficiencia'], 2)}%",
            help="% das fichas do período com 'tem deficiência = sim'")
mostrar_sql(sql_kpi, sql_ind)

# ---------------------------------------------------------------------------
# 2 · Medidas de posição e dispersão (calculadas pelo PostgreSQL)
# ---------------------------------------------------------------------------

# variável -> (rótulo, subconsulta que devolve a coluna x, observação da moda)
VARIAVEIS = {
    "indice": ("Índice de completude das equipes (0 a 100)", """
        SELECT v.indice_completude AS x FROM vw_indicador_territorio v
        WHERE v.id_quadrimestre BETWEEN %(id_ini)s AND %(id_fim)s AND v.distrito = ANY(%(distritos)s)""",
               "moda dos valores arredondados para inteiro (o índice é contínuo)"),
    "fichas": ("Fichas enviadas por equipe no quadrimestre", """
        SELECT v.qtd_fichas AS x FROM vw_indicador_territorio v
        WHERE v.id_quadrimestre BETWEEN %(id_ini)s AND %(id_fim)s AND v.distrito = ANY(%(distritos)s)""",
               "moda dos valores arredondados"),
    "risco": ("Risco previsto pelo modelo de ML (%)", """
        SELECT 100 * v.risco_previsto AS x FROM vw_indicador_territorio v
        WHERE v.id_quadrimestre BETWEEN %(id_ini)s AND %(id_fim)s AND v.distrito = ANY(%(distritos)s)
          AND v.risco_previsto IS NOT NULL""",
              "moda dos valores arredondados"),
    "idade": ("Idade das pessoas nas fichas (anos)", """
        SELECT f.idade AS x FROM ficha_cadastro f""" + TERRITORIO + """
        WHERE f.data_envio BETWEEN %(inicio)s AND %(fim)s AND b.nr_distrito = ANY(%(distritos)s)""",
              "idade mais frequente"),
}

SQL_MEDIDAS = """
SELECT COUNT(x)                                             AS n,
       ROUND(AVG(x)::numeric, 2)                            AS media,
       ROUND(PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY x)::numeric, 2) AS mediana,
       MODE() WITHIN GROUP (ORDER BY ROUND(x::numeric))     AS moda,
       ROUND(VAR_SAMP(x)::numeric, 2)                       AS variancia,
       ROUND(STDDEV_SAMP(x)::numeric, 2)                    AS desvio_padrao,
       ROUND((100 * STDDEV_SAMP(x) / NULLIF(AVG(x), 0))::numeric, 1) AS coef_variacao_pct,
       ROUND(MIN(x)::numeric, 2)                            AS minimo,
       ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY x)::numeric, 2) AS q1,
       ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY x)::numeric, 2) AS q3,
       ROUND(MAX(x)::numeric, 2)                            AS maximo
FROM ({fonte}) AS dados"""

st.divider()
st.subheader("Medidas de posição e dispersão")
var = st.radio("Variável", list(VARIAVEIS), format_func=lambda v: VARIAVEIS[v][0], horizontal=True)
rotulo_var, fonte, obs_moda = VARIAVEIS[var]
med, sql_med = consultar(SQL_MEDIDAS.format(fonte=fonte), P)
m = med.iloc[0]
c = st.columns(6)
c[0].metric("Média", fmt(m["media"], 2))
c[1].metric("Mediana", fmt(m["mediana"], 2))
c[2].metric("Moda", fmt(m["moda"]), help=obs_moda.capitalize())
c[3].metric("Variância", fmt(m["variancia"], 2))
c[4].metric("Desvio padrão", fmt(m["desvio_padrao"], 2))
c[5].metric("Coef. de variação", f"{fmt(m['coef_variacao_pct'], 1)}%")
st.caption(f"{rotulo_var} · n = {fmt(m['n'])} · mínimo {fmt(m['minimo'], 2)} · Q1 {fmt(m['q1'], 2)} · "
           f"Q3 {fmt(m['q3'], 2)} · máximo {fmt(m['maximo'], 2)}. Variância e desvio padrão amostrais "
           f"(VAR_SAMP, STDDEV_SAMP); moda: {obs_moda}.")
mostrar_sql(sql_med)

# ---------------------------------------------------------------------------
# 3 · Gráficos
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Gráficos")


def tabela(df):
    with st.expander("Ver dados do gráfico"):
        st.dataframe(df, hide_index=True, width="stretch")


# --- Gráfico 1 · Linha: tendência do índice por quadrimestre ---------------
SQL_TENDENCIA = """
SELECT v.quadrimestre,
       'DS ' || v.distrito                               AS distrito,
       ROUND(AVG(v.indice_completude), 2)                AS media,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.indice_completude)::numeric, 2) AS mediana,
       ROUND(STDDEV_SAMP(v.indice_completude), 2)        AS desvio_padrao,
       COUNT(*)                                          AS equipes
FROM vw_indicador_territorio v
WHERE v.distrito = ANY(%(distritos)s)
GROUP BY v.ano, v.numero, v.quadrimestre, v.distrito
ORDER BY v.ano, v.numero, v.distrito"""

col1, col2 = st.columns(2)
with col1:
    st.markdown("**1 · Tendência temporal do índice de completude**")
    medida = st.segmented_control("Medida", ["media", "mediana"], default="media", key="g1",
                                  format_func={"media": "Média", "mediana": "Mediana"}.get) or "media"
    tend, sql_tend = consultar(SQL_TENDENCIA, P)
    # o período escolhido aparece destacado; o histórico inteiro fica para dar contexto
    faixa = pd.DataFrame({"ini": [q_ini], "fim": [q_fim]})
    destaque = alt.Chart(faixa).mark_rect(color="#e8e6e1", opacity=0.6).encode(x="ini:O", x2="fim:O")
    sel = alt.selection_point(fields=["distrito"], bind="legend")
    linhas = alt.Chart(tend).mark_line(point=alt.OverlayMarkDef(size=40), strokeWidth=2).encode(
        x=alt.X("quadrimestre:O", title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y(f"{medida}:Q", title=f"Índice ({'média' if medida == 'media' else 'mediana'})",
                scale=alt.Scale(zero=False)),
        color=alt.Color("distrito:N", scale=alt.Scale(domain=list(COR_DISTRITO), range=list(COR_DISTRITO.values())),
                        legend=alt.Legend(orient="top", title=None, columns=8)),
        opacity=alt.condition(sel, alt.value(1), alt.value(0.12)),
        tooltip=["distrito", "quadrimestre", "media", "mediana", "desvio_padrao", "equipes"],
    ).add_params(sel)
    st.altair_chart((destaque + linhas).properties(height=320), width="stretch")
    st.caption("Clique num distrito da legenda para destacá-lo. Faixa cinza = período do filtro.")
    tabela(tend)
    mostrar_sql(sql_tend)

# --- Gráfico 2 · Histograma: distribuição do índice das equipes ------------
SQL_HISTOGRAMA = """
SELECT FLOOR(v.indice_completude / 2.5) * 2.5          AS faixa_inicio,
       FLOOR(v.indice_completude / 2.5) * 2.5 + 2.5    AS faixa_fim,
       COUNT(*)                                        AS equipes
FROM vw_indicador_territorio v
WHERE v.id_quadrimestre BETWEEN %(id_ini)s AND %(id_fim)s
  AND v.distrito = ANY(%(distritos)s)
GROUP BY 1, 2
ORDER BY 1"""

with col2:
    st.markdown("**2 · Distribuição de frequência do índice (histograma)**")
    hist, sql_hist = consultar(SQL_HISTOGRAMA, P)
    medidas_ind, _ = consultar(SQL_MEDIDAS.format(fonte=VARIAVEIS["indice"][1]), P)
    mi = medidas_ind.iloc[0]
    barras = alt.Chart(hist).mark_bar(color=AZUL, cornerRadiusTopLeft=3, cornerRadiusTopRight=3,
                                      stroke="#fcfcfb", strokeWidth=1).encode(
        x=alt.X("faixa_inicio:Q", bin="binned", title="Índice de completude"),
        x2="faixa_fim:Q",
        y=alt.Y("equipes:Q", title="Equipes × quadrimestres"),
        tooltip=[alt.Tooltip("faixa_inicio:Q", title="de"), alt.Tooltip("faixa_fim:Q", title="até"), "equipes"],
    )
    refs = pd.DataFrame({"medida": ["Média", "Mediana", "Moda"],
                         "valor": [mi["media"], mi["mediana"], float(mi["moda"])]})
    regras = alt.Chart(refs).mark_rule(strokeWidth=2, strokeDash=[5, 3]).encode(
        x="valor:Q",
        color=alt.Color("medida:N", scale=alt.Scale(domain=["Média", "Mediana", "Moda"],
                                                    range=[LARANJA, "#0b0b0b", VERDE_AGUA]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["medida", alt.Tooltip("valor:Q", format=".2f")],
    )
    st.altair_chart((barras + regras).properties(height=320), width="stretch")
    st.caption(f"Média {fmt(mi['media'], 2)} · mediana {fmt(mi['mediana'], 2)} · moda {fmt(mi['moda'])} · "
               f"desvio padrão {fmt(mi['desvio_padrao'], 2)}. Média abaixo da mediana = cauda de equipes ruins à esquerda.")
    tabela(hist)
    mostrar_sql(sql_hist)

# --- Gráfico 3 · Boxplot: dispersão entre distritos -------------------------
SQL_BOX = """
SELECT 'DS ' || v.distrito                                                     AS distrito,
       COUNT(*)                                                                AS equipes,
       ROUND(MIN(v.indice_completude), 2)                                      AS minimo,
       ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY v.indice_completude)::numeric, 2) AS q1,
       ROUND(PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY v.indice_completude)::numeric, 2) AS mediana,
       ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY v.indice_completude)::numeric, 2) AS q3,
       ROUND(MAX(v.indice_completude), 2)                                      AS maximo,
       ROUND(AVG(v.indice_completude), 2)                                      AS media,
       ROUND(VAR_SAMP(v.indice_completude), 2)                                 AS variancia,
       ROUND(STDDEV_SAMP(v.indice_completude), 2)                              AS desvio_padrao
FROM vw_indicador_territorio v
WHERE v.id_quadrimestre = %(id_fim)s
  AND v.distrito = ANY(%(distritos)s)
GROUP BY v.distrito
ORDER BY v.distrito"""

col3, col4 = st.columns(2)
with col3:
    st.markdown(f"**3 · Dispersão do índice entre distritos ({q_fim})**")
    box, sql_box = consultar(SQL_BOX, P)
    escala = alt.Scale(domain=list(COR_DISTRITO), range=list(COR_DISTRITO.values()))
    base = alt.Chart(box).encode(y=alt.Y("distrito:N", title=None))
    bigode = base.mark_rule(color=CINZA, strokeWidth=1.5).encode(x=alt.X("minimo:Q", title="Índice de completude",
                                                                          scale=alt.Scale(zero=False)), x2="maximo:Q")
    caixa = base.mark_bar(size=18, cornerRadius=3).encode(
        x="q1:Q", x2="q3:Q", color=alt.Color("distrito:N", scale=escala, legend=None),
        tooltip=["distrito", "equipes", "minimo", "q1", "mediana", "q3", "maximo", "media", "variancia", "desvio_padrao"])
    mediana = base.mark_tick(color="#0b0b0b", thickness=2, size=18).encode(x="mediana:Q")
    media = base.mark_point(shape="diamond", filled=True, color="#fcfcfb", stroke="#0b0b0b", size=50).encode(
        x="media:Q", tooltip=["distrito", "media", "desvio_padrao"])
    st.altair_chart((bigode + caixa + mediana + media).properties(height=320), width="stretch")
    st.caption("Caixa = Q1 a Q3 · traço = mediana · losango = média · linha = mínimo a máximo. "
               "Caixa larga = equipes muito diferentes dentro do mesmo distrito (alto desvio padrão).")
    tabela(box)
    mostrar_sql(sql_box)

# --- Gráfico 4 · Barras empilhadas: estado do registro por marcador ---------
SQL_ESTADOS = """
SELECT m.marcador,
       m.estado,
       COUNT(*)                                                                    AS fichas,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY m.marcador), 1)   AS pct
FROM vw_ficha_marcadores v
CROSS JOIN LATERAL (VALUES ('Orientação sexual',    v.estado_orientacao),
                           ('Identidade de gênero', v.estado_identidade),
                           ('Raça/cor',             v.estado_raca),
                           ('Deficiência',          v.estado_deficiencia)) AS m (marcador, estado)
WHERE v.data_envio BETWEEN %(inicio)s AND %(fim)s
  AND v.distrito = ANY(%(distritos)s)
  AND m.estado IS NOT NULL
GROUP BY m.marcador, m.estado
ORDER BY m.marcador, m.estado"""

with col4:
    st.markdown("**4 · Frequência do estado do registro, por marcador**")
    est, sql_est = consultar(SQL_ESTADOS, P)
    st.altair_chart(alt.Chart(est).mark_bar(cornerRadius=3, stroke="#fcfcfb", strokeWidth=2, size=34).encode(
        y=alt.Y("marcador:N", title=None, sort=["Orientação sexual", "Identidade de gênero", "Raça/cor", "Deficiência"]),
        x=alt.X("fichas:Q", stack="normalize", axis=alt.Axis(format="%"), title="% das fichas"),
        color=alt.Color("estado:N", scale=alt.Scale(domain=["Preenchido", "Recusou", "N/I"],
                                                     range=[AZUL, LARANJA, VERDE_AGUA]),
                        legend=alt.Legend(orient="top", title=None)),
        order=alt.Order("ordem:Q"),
        tooltip=["marcador", "estado", "fichas", alt.Tooltip("pct:Q", title="% das fichas")],
    ).transform_calculate(ordem="datum.estado == 'Preenchido' ? 0 : datum.estado == 'Recusou' ? 1 : 2")
        .properties(height=320), width="stretch")
    st.caption("Usa a visão vw_ficha_marcadores (Etapa 04). Recusa só existe em orientação e identidade; "
               "crianças de 0 a 10 anos ficam fora desses dois marcadores.")
    tabela(est)
    mostrar_sql(sql_est)

# --- Gráfico 5 · Pizza (rosca): raça/cor registrada -------------------------
SQL_RACA = """
SELECT COALESCE(f.raca_cor, 'N/I (não registrada)')                       AS raca_cor,
       COUNT(*)                                                           AS fichas,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)                 AS pct
FROM ficha_cadastro f""" + TERRITORIO + """
WHERE f.data_envio BETWEEN %(inicio)s AND %(fim)s
  AND b.nr_distrito = ANY(%(distritos)s)
GROUP BY 1
ORDER BY fichas DESC"""

col5, col6 = st.columns(2)
with col5:
    st.markdown("**5 · Composição por raça/cor (frequência relativa)**")
    raca, sql_raca = consultar(SQL_RACA, P)
    ordem_raca = ["parda", "branca", "preta", "amarela", "indigena", "N/I (não registrada)"]
    cores_raca = [AZUL, LARANJA, VERDE_AGUA, AMARELO, ROSA, "#c9c7c1"]
    rosca = alt.Chart(raca).mark_arc(innerRadius=70, stroke="#fcfcfb", strokeWidth=2).encode(
        theta=alt.Theta("fichas:Q", stack=True),
        color=alt.Color("raca_cor:N", sort=ordem_raca, scale=alt.Scale(domain=ordem_raca, range=cores_raca),
                        legend=alt.Legend(orient="right", title=None)),
        order=alt.Order("fichas:Q", sort="descending"),
        tooltip=["raca_cor", "fichas", alt.Tooltip("pct:Q", title="%")],
    )
    rotulos_arco = alt.Chart(raca[raca["pct"] >= 5]).mark_text(radius=125, fontSize=12, color="#3a3a38").encode(
        theta=alt.Theta("fichas:Q", stack=True), order=alt.Order("fichas:Q", sort="descending"),
        text=alt.Text("pct:Q", format=".1f"))
    st.altair_chart((rosca + rotulos_arco).properties(height=320), width="stretch")
    moda_raca = raca[~raca["raca_cor"].str.startswith("N/I")].iloc[0]["raca_cor"] if len(raca) else "–"
    st.caption(f"Moda (categoria mais frequente entre as registradas): **{moda_raca}**. "
               "A fatia cinza é a falha de registro que a Secretaria quer reduzir.")
    tabela(raca)
    mostrar_sql(sql_raca)

# --- Gráfico 6 · Dispersão: correlação fichas × índice ----------------------
SQL_CORR = """
SELECT ROUND(CORR(v.qtd_fichas, v.indice_completude)::numeric, 3)          AS correlacao_pearson,
       ROUND(REGR_R2(v.indice_completude, v.qtd_fichas)::numeric, 3)       AS r2,
       REGR_SLOPE(v.indice_completude, v.qtd_fichas)                       AS inclinacao,
       REGR_INTERCEPT(v.indice_completude, v.qtd_fichas)                   AS intercepto,
       ROUND(CORR(v.indice_completude, 100 * v.risco_previsto)::numeric, 3) AS correlacao_indice_risco
FROM vw_indicador_territorio v
WHERE v.id_quadrimestre BETWEEN %(id_ini)s AND %(id_fim)s
  AND v.distrito = ANY(%(distritos)s)"""

SQL_PONTOS = """
SELECT 'DS ' || v.distrito AS distrito, v.equipe, v.quadrimestre, v.qtd_fichas, v.indice_completude, v.critica
FROM vw_indicador_territorio v
WHERE v.id_quadrimestre BETWEEN %(id_ini)s AND %(id_fim)s
  AND v.distrito = ANY(%(distritos)s)"""

with col6:
    st.markdown("**6 · Correlação: volume de fichas × qualidade do registro**")
    corr, sql_corr = consultar(SQL_CORR, P)
    pts, sql_pts = consultar(SQL_PONTOS, P)
    r = corr.iloc[0]
    xs = pd.DataFrame({"qtd_fichas": [pts["qtd_fichas"].min(), pts["qtd_fichas"].max()]})
    xs["indice_completude"] = float(r["intercepto"]) + float(r["inclinacao"]) * xs["qtd_fichas"]
    sel_d = alt.selection_point(fields=["distrito"], bind="legend")
    nuvem = alt.Chart(pts).mark_circle(size=40, stroke="#fcfcfb", strokeWidth=1).encode(
        x=alt.X("qtd_fichas:Q", title="Fichas enviadas no quadrimestre", scale=alt.Scale(zero=False)),
        y=alt.Y("indice_completude:Q", title="Índice de completude", scale=alt.Scale(zero=False)),
        color=alt.Color("distrito:N", scale=alt.Scale(domain=list(COR_DISTRITO), range=list(COR_DISTRITO.values())),
                        legend=alt.Legend(orient="top", title=None, columns=8)),
        opacity=alt.condition(sel_d, alt.value(0.75), alt.value(0.06)),
        tooltip=["equipe", "distrito", "quadrimestre", "qtd_fichas", "indice_completude", "critica"],
    ).add_params(sel_d)
    reta = alt.Chart(xs).mark_line(color="#0b0b0b", strokeWidth=2, strokeDash=[6, 3]).encode(
        x="qtd_fichas:Q", y="indice_completude:Q")
    st.altair_chart((nuvem + reta).properties(height=320).interactive(), width="stretch")
    st.caption(f"Pearson r = **{fmt(r['correlacao_pearson'], 3)}** · R² = {fmt(r['r2'], 3)} · reta: índice = "
               f"{fmt(r['intercepto'], 2)} + {fmt(r['inclinacao'], 4)} × fichas (CORR e REGR_* do PostgreSQL). "
               f"Índice × risco do modelo: r = {fmt(r['correlacao_indice_risco'], 3)}. Arraste/role para dar zoom.")
    tabela(pts)
    mostrar_sql(sql_corr, sql_pts)

# --- Gráfico 7 · Série mensal com média móvel -------------------------------
SQL_MENSAL = """
WITH mensal AS (
    SELECT date_trunc('month', f.data_envio)::date AS mes,
           COUNT(*)                                 AS fichas
    FROM ficha_cadastro f""" + TERRITORIO + """
    WHERE f.data_envio BETWEEN %(inicio)s AND %(fim)s
      AND b.nr_distrito = ANY(%(distritos)s)
    GROUP BY 1
)
SELECT mes,
       fichas,
       ROUND(AVG(fichas) OVER (ORDER BY mes ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 0) AS media_movel_3m
FROM mensal
ORDER BY mes"""

col7, col8 = st.columns(2)
with col7:
    st.markdown("**7 · Fichas enviadas por mês, com média móvel de 3 meses**")
    mensal, sql_mensal = consultar(SQL_MENSAL, P)
    mensal["mes"] = pd.to_datetime(mensal["mes"])
    hover = alt.selection_point(fields=["mes"], nearest=True, on="pointerover", empty=False)
    base_m = alt.Chart(mensal).encode(x=alt.X("yearmonth(mes):T", title=None, axis=alt.Axis(format="%m/%Y")))
    barras_m = base_m.mark_bar(color=AZUL, cornerRadiusTopLeft=3, cornerRadiusTopRight=3, opacity=0.85).encode(
        y=alt.Y("fichas:Q", title="Fichas"),
        tooltip=[alt.Tooltip("yearmonth(mes):T", title="mês", format="%m/%Y"), "fichas", "media_movel_3m"],
    ).add_params(hover)
    linha_m = base_m.mark_line(color=LARANJA, strokeWidth=2).encode(y="media_movel_3m:Q")
    pontos_m = base_m.mark_point(color=LARANJA, filled=True, size=60).encode(
        y="media_movel_3m:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    st.altair_chart((barras_m + linha_m + pontos_m).properties(height=300), width="stretch")
    st.caption("Barras = fichas no mês · linha laranja = média móvel de 3 meses (função de janela AVG OVER no SQL).")
    tabela(mensal)
    mostrar_sql(sql_mensal)

# --- Gráfico 8 · Pirâmide etária por sexo -----------------------------------
SQL_PIRAMIDE = """
SELECT CASE WHEN f.idade <= 10 THEN '00–10'
            WHEN f.idade <= 17 THEN '11–17'
            WHEN f.idade <= 29 THEN '18–29'
            WHEN f.idade <= 44 THEN '30–44'
            WHEN f.idade <= 59 THEN '45–59'
            WHEN f.idade <= 74 THEN '60–74'
            ELSE '75+' END                                   AS faixa_etaria,
       f.sexo,
       COUNT(*)                                              AS fichas,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.tem_deficiencia = 'sim') / COUNT(*), 2) AS pct_com_deficiencia
FROM ficha_cadastro f""" + TERRITORIO + """
WHERE f.data_envio BETWEEN %(inicio)s AND %(fim)s
  AND b.nr_distrito = ANY(%(distritos)s)
  AND f.sexo IN ('F', 'M')
GROUP BY 1, 2
ORDER BY 1, 2"""

with col8:
    st.markdown("**8 · Pirâmide etária das pessoas cadastradas**")
    pir, sql_pir = consultar(SQL_PIRAMIDE, P)
    pir["sexo_nome"] = pir["sexo"].map({"F": "Feminino", "M": "Masculino"})
    pir["valor"] = pir.apply(lambda l: -l["fichas"] if l["sexo"] == "M" else l["fichas"], axis=1)
    faixas = sorted(pir["faixa_etaria"].unique(), reverse=True)
    st.altair_chart(alt.Chart(pir).mark_bar(cornerRadius=3, size=26).encode(
        y=alt.Y("faixa_etaria:N", sort=faixas, title=None),
        x=alt.X("valor:Q", title="Fichas (masculino à esquerda, feminino à direita)",
                axis=alt.Axis(labelExpr="abs(datum.value) >= 1000 ? format(abs(datum.value)/1000, ',.0f') + ' mil' "
                                        ": format(abs(datum.value), ',.0f')")),
        color=alt.Color("sexo_nome:N", scale=alt.Scale(domain=["Masculino", "Feminino"], range=[AZUL, LARANJA]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["faixa_etaria", "sexo_nome", "fichas", alt.Tooltip("pct_com_deficiencia:Q", title="% com deficiência")],
    ).properties(height=300), width="stretch")
    st.caption("Distribuição de frequência por faixa etária e sexo (sexo I = indeterminado fica fora da pirâmide). "
               "O tooltip mostra a prevalência de deficiência em cada faixa.")
    tabela(pir.drop(columns=["valor"]))
    mostrar_sql(sql_pir)
