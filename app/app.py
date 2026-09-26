"""
Protótipo navegável do Painel de Equidade em Saúde (Estação 5).

Segue os wireframes do Kickoff: uma tela por perfil (Coordenação, Gestão de Distrito, Equipe de Saúde).
Lê só dados agregados por equipe, USF e distrito (app/dados, gerados por src/preparar_painel.py):
nenhuma ficha individual chega ao painel.

Protótipo: o perfil é escolhido na barra lateral (no produto, viria do login da Secretaria) e a previsão
de risco usa a baseline de persistência (o modelo de ML entra no lugar dela na Sprint 1).

Uso (na raiz do projeto):  streamlit run app/app.py
"""

from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

DADOS = Path(__file__).resolve().parent / "dados"

AZUL, LARANJA, VERDE_AGUA, AMARELO = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
CATEGORICAS = [AZUL, LARANJA, VERDE_AGUA, AMARELO, "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

MARCADORES = {
    "Orientação sexual": "estado_os",
    "Identidade de gênero": "estado_ig",
    "Raça/cor": "estado_raca",
    "Deficiência": "estado_deficiencia",
}

# Nomes na mesma ordem de src/preparar_painel.py
POPULACOES = [
    "Pessoas negras (pretas e pardas)", "Pessoas trans e travestis", "Pessoas não binárias",
    "Pessoas LGB+ (lésbicas, gays, bissexuais e outras)", "Pessoas com deficiência",
    "Pessoas com deficiência auditiva", "Pessoas com deficiência física",
]

st.set_page_config(page_title="Painel de Equidade em Saúde", page_icon="📊", layout="wide")


# ---------------------------------------------------------------------------
# Dados (carregados uma vez e guardados em cache)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Carregando dados...")
def carregar():
    return {nome: pd.read_parquet(DADOS / f"{nome}.parquet")
            for nome in ["resumo_equipes", "estados_distrito", "populacao_usf", "territorio_usf"]}


def pct(x):
    return f"{x * 100:.0f}%"


dados = carregar()
resumo = dados["resumo_equipes"]
QUADRIMESTRES = sorted(resumo["quadrimestre"].unique())


def proximo(q):
    ano, n = q.split(".")
    return f"{ano}.{int(n) + 1}" if n != "3" else f"{int(ano) + 1}.1"


# ---------------------------------------------------------------------------
# Barra lateral: perfil e período
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### Painel de Equidade em Saúde")
    perfil = st.radio(
        "Perfil de acesso", ["Coordenação", "Gestão de Distrito", "Equipe de Saúde"],
        help="No produto, o perfil vem do login da Secretaria e cada perfil só enxerga o seu recorte.",
    )
    quad = st.select_slider("Quadrimestre", QUADRIMESTRES, value=QUADRIMESTRES[-1])

res_q = resumo[resumo["quadrimestre"] == quad]


# ---------------------------------------------------------------------------
# Tela 01 · Coordenação: visão geral da rede
# ---------------------------------------------------------------------------

def tela_coordenacao():
    st.title("Visão geral da rede")
    st.caption(f"Recife · 8 Distritos Sanitários · quadrimestre {quad}")

    distritos = st.multiselect("Distritos Sanitários", list(range(1, 9)), default=list(range(1, 9)),
                               format_func=lambda d: f"DS {d}")
    if not distritos:
        st.info("Selecione ao menos um distrito.")
        return
    r = res_q[res_q["distrito_sanitario"].isin(distritos)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Equipes", len(r))
    c2.metric("Índice de completude (mediana)", f"{r['indice_completude'].median():.0f} / 100")
    c3.metric("Equipes críticas agora", int(r["critica"].sum()))
    c4.metric(f"Em risco em {proximo(quad)}", int(r["critica"].sum()), help="Baseline de persistência")

    aba_pop, aba_qual = st.tabs(["📍 Onde está a população", "✅ Qualidade do registro"])

    with aba_pop:
        grupo = st.selectbox("População", POPULACOES)
        pop = dados["populacao_usf"]
        por_usf = pop[(pop["quadrimestre"] == quad) & (pop["grupo"] == grupo) & pop["distrito_sanitario"].isin(distritos)]
        por_usf = por_usf.drop(columns="distrito_sanitario").merge(dados["territorio_usf"], on="cnes")
        por_usf["% não perguntado"] = por_usf["sem_pergunta"] / por_usf["elegiveis"]
        por_usf["raio"] = 60 + 900 * (por_usf["pessoas"] / max(por_usf["pessoas"].max(), 1)) ** 0.5
        por_usf["nao_perg_txt"] = (por_usf["% não perguntado"] * 100).round(0).astype(int).astype(str) + "%"

        camada = pdk.Layer(
            "ScatterplotLayer", por_usf, get_position="[longitude, latitude]", get_radius="raio",
            get_fill_color=[42, 120, 214, 150], get_line_color=[255, 255, 255], line_width_min_pixels=1,
            stroked=True, pickable=True,
        )
        st.pydeck_chart(pdk.Deck(
            layers=[camada], map_style=None,
            initial_view_state=pdk.ViewState(latitude=-8.06, longitude=-34.93, zoom=10.6),
            tooltip={"text": "{nome_unidade} · {bairro} (DS {distrito_sanitario})\n{pessoas} pessoas\nNão perguntado: {nao_perg_txt}"},
        ), height=430)
        st.caption("Cada círculo é uma USF.")
        st.markdown(f"**USF com mais {grupo.lower()}**")
        topo = por_usf.sort_values("pessoas", ascending=False).head(10)
        st.dataframe(
            topo[["nome_unidade", "bairro", "distrito_sanitario", "pessoas", "% não perguntado"]], hide_index=True, width="stretch",
            column_config={
                "nome_unidade": "USF", "bairro": "Bairro", "distrito_sanitario": st.column_config.NumberColumn("DS", format="%d"),
                "pessoas": "Pessoas",
                "% não perguntado": st.column_config.ProgressColumn("Não perguntado", format="percent", min_value=0, max_value=1),
            })

    with aba_qual:
        nome_marcador = st.radio("Marcador", list(MARCADORES), horizontal=True)
        col = MARCADORES[nome_marcador]
        est = dados["estados_distrito"]
        estados = est[(est["quadrimestre"] == quad) & (est["marcador"] == col) & est["distrito_sanitario"].isin(distritos)].copy()
        estados["estado"] = estados["estado"].map({"preenchido": "Preenchido", "recusou": "Recusou informar",
                                              "nao_perguntado": "Não perguntado"})
        estados["distrito"] = "DS " + estados["distrito_sanitario"].astype(str)
        grafico = alt.Chart(estados).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("distrito:N", title=None),
            x=alt.X("pct:Q", stack="normalize", axis=alt.Axis(format="%"), title=None),
            color=alt.Color("estado:N", scale=alt.Scale(domain=["Preenchido", "Recusou informar", "Não perguntado"],
                                                          range=[AZUL, LARANJA, VERDE_AGUA]),
                            legend=alt.Legend(orient="top", title=None)),
            order=alt.Order("estado_ordem:Q"),
            tooltip=["distrito", "estado", alt.Tooltip("pct:Q", format=".1%", title="% das fichas")],
        ).transform_calculate(
            estado_ordem="datum.estado == 'Preenchido' ? 0 : datum.estado == 'Recusou informar' ? 1 : 2"
        ).properties(height=280, title=f"{nome_marcador}: estado do registro nas fichas de {quad}")
        st.altair_chart(grafico, width="stretch")

        evol = (resumo[resumo["distrito_sanitario"].isin(distritos)]
                .groupby(["quadrimestre", "distrito_sanitario"])["indice_completude"].median().reset_index())
        evol["distrito"] = "DS " + evol["distrito_sanitario"].astype(str)
        linhas = alt.Chart(evol).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("quadrimestre:O", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("indice_completude:Q", title="Índice (mediana)", scale=alt.Scale(zero=False)),
            color=alt.Color("distrito:N", scale=alt.Scale(range=CATEGORICAS), legend=alt.Legend(orient="top", title=None)),
            tooltip=["distrito", "quadrimestre", alt.Tooltip("indice_completude:Q", format=".1f", title="Índice")],
        ).properties(height=260, title="Evolução do índice de completude por distrito")
        st.altair_chart(linhas, width="stretch")

    st.download_button(
        "⬇️ Exportar tabela das equipes (CSV)",
        r[["nome_equipe", "nome_unidade", "distrito_sanitario", "indice_completude", "os_preenchido",
           "ig_preenchido", "raca_preenchido", "deficiencia_preenchido", "status"]].to_csv(index=False).encode("utf-8"),
        file_name=f"equipes_{quad}.csv", mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Tela 02 · Gestão de Distrito: ranking e alertas
# ---------------------------------------------------------------------------

def tela_distrito():
    ds = st.selectbox("Meu distrito", list(range(1, 9)), format_func=lambda d: f"Distrito Sanitário {d}")
    st.title(f"Distrito Sanitário {ds}")
    r = res_q[res_q["distrito_sanitario"] == ds].sort_values("indice_completude")
    rede = res_q["indice_completude"].median()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Equipes", len(r))
    c2.metric("Índice (mediana)", f"{r['indice_completude'].median():.0f}", f"{r['indice_completude'].median() - rede:+.1f} vs. rede")
    c3.metric("Críticas agora", int(r["critica"].sum()))
    c4.metric(f"Em risco em {proximo(quad)}", int(r["critica"].sum()), help="Baseline de persistência")

    st.subheader("Ranking das equipes · da mais crítica para a melhor")
    tabela = r.assign(risco=r["critica"].map({1: "⚠️ Sim", 0: "Não"}))
    st.dataframe(
        tabela[["nome_equipe", "indice_completude", "os_preenchido", "ig_preenchido",
                "raca_preenchido", "status", "risco"]],
        hide_index=True, width="stretch", height=min(38 * len(tabela) + 40, 520),
        column_config={
            "nome_equipe": "Equipe",
            "indice_completude": st.column_config.ProgressColumn("Índice", format="%.0f", min_value=0, max_value=100),
            "os_preenchido": st.column_config.NumberColumn("Orientação sexual", format="percent"),
            "ig_preenchido": st.column_config.NumberColumn("Identidade de gênero", format="percent"),
            "raca_preenchido": st.column_config.NumberColumn("Raça/cor", format="percent"),
            "status": "Status", "risco": f"Risco em {proximo(quad)}",
        })



# ---------------------------------------------------------------------------
# Tela 03 · Equipe de Saúde: qualidade do próprio cadastro
# ---------------------------------------------------------------------------

def tela_equipe():
    c1, c2 = st.columns(2)
    ds = c1.selectbox("Distrito", list(range(1, 9)), format_func=lambda d: f"Distrito Sanitário {d}")
    opcoes = res_q[res_q["distrito_sanitario"] == ds].sort_values("indice_completude")
    ine = c2.selectbox("Minha equipe", opcoes["ine"], format_func=lambda i: opcoes.set_index("ine").loc[i, "nome_equipe"])
    e = opcoes.set_index("ine").loc[ine]
    media_ds = opcoes["indice_completude"].median()

    st.title(e["nome_equipe"])
    st.caption(f"{e['nome_unidade']} · {e['bairro']} · Distrito Sanitário {ds} · {int(e['n_fichas'])} fichas em {quad}")

    col_nota, col_campos = st.columns([1, 2])
    with col_nota:
        st.metric("Nota de qualidade do cadastro", f"{e['indice_completude']:.0f} / 100",
                  f"{e['indice_completude'] - media_ds:+.1f} vs. mediana do distrito")
        st.markdown(f"Status: **{e['status']}**")
        st.markdown(f"Risco em {proximo(quad)}: **{'⚠️ Sim' if e['critica'] else 'Não'}**")
    with col_campos:
        st.markdown("**Completude por campo**")
        for nome, valor in [("Raça/cor", e["raca_preenchido"]), ("Deficiência", e["deficiencia_preenchido"]),
                            ("Identidade de gênero", e["ig_preenchido"]), ("Orientação sexual", e["os_preenchido"])]:
            st.progress(float(valor), text=f"{nome}: {pct(valor)}")
        st.caption(f"Orientação sexual: {pct(e['os_preenchido'])} informou · {pct(e['os_recusou'])} recusou · "
                   f"**{pct(e['os_nao_perguntado'])} não foi perguntado**")


    hist = resumo[resumo["ine"] == ine]
    limites = resumo.groupby("quadrimestre")["indice_completude"].quantile(0.25).rename("limite").reset_index()
    linha = alt.Chart(hist).mark_line(point=True, color=AZUL, strokeWidth=2).encode(
        x=alt.X("quadrimestre:O", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("indice_completude:Q", title="Índice", scale=alt.Scale(zero=False)),
        tooltip=["quadrimestre", alt.Tooltip("indice_completude:Q", format=".1f", title="Índice")])
    corte = alt.Chart(limites).mark_line(strokeDash=[4, 4], color="#52514e").encode(
        x="quadrimestre:O", y="limite:Q", tooltip=[alt.Tooltip("limite:Q", format=".1f", title="Limite crítico")])
    st.altair_chart((corte + linha).properties(height=240, title="Evolução da nota · tracejado = limite das 25% piores"),
                    width="stretch")


{"Coordenação": tela_coordenacao, "Gestão de Distrito": tela_distrito, "Equipe de Saúde": tela_equipe}[perfil]()
