"""
Protótipo navegável do Painel de Equidade em Saúde (Estação 5).

Segue os wireframes do Kickoff: uma tela por perfil (Coordenação, Gestão de Distrito, Equipe de Saúde).
Lê os dados produzidos pelo pipeline (data/processed), não imagens.

Protótipo: o perfil é escolhido na barra lateral (no produto, viria do login da Secretaria) e a previsão
de risco usa a baseline de persistência (o modelo de ML entra no lugar dela na Sprint 1).

Uso (na raiz do projeto):  streamlit run app/app.py
"""

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from indicadores import resumo_equipe_periodo  # noqa: E402
from features import inconsistencia_raca  # noqa: E402

PROCESSED = RAIZ / "data" / "processed"
RAW = RAIZ / "data" / "raw"

AZUL, LARANJA, VERDE_AGUA, AMARELO = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
CATEGORICAS = [AZUL, LARANJA, VERDE_AGUA, AMARELO, "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
LIMITE_INCONSISTENCIA = 15   # pontos acima da mediana do distrito (notebook 01)

MARCADORES = {
    "Orientação sexual": "estado_os",
    "Identidade de gênero": "estado_ig",
    "Raça/cor": "estado_raca",
    "Deficiência": "estado_deficiencia",
}

# Populações das políticas de equidade: filtro sobre a ficha mais recente + marcador que as registra
POPULACOES = {
    "Pessoas negras (pretas e pardas)": (lambda d: d["raca_cor"].isin(["preta", "parda"]), "estado_raca"),
    "Pessoas trans e travestis": (lambda d: d["identidade_genero"].isin(["mulher_trans", "travesti", "homem_trans"]), "estado_ig"),
    "Pessoas não binárias": (lambda d: d["identidade_genero"] == "nao_binario", "estado_ig"),
    "Pessoas LGB+ (lésbicas, gays, bissexuais e outras)": (
        lambda d: ~d["orientacao_sexual"].isin(["heterossexual", ""]), "estado_os"),
    "Pessoas com deficiência": (lambda d: d["tem_deficiencia"] == "sim", "estado_deficiencia"),
    "Pessoas com deficiência auditiva": (lambda d: d["tipo_deficiencia"].str.contains("auditiva"), "estado_deficiencia"),
    "Pessoas com deficiência física": (lambda d: d["tipo_deficiencia"].str.contains("fisica"), "estado_deficiencia"),
}

st.set_page_config(page_title="Painel de Equidade em Saúde", page_icon="📊", layout="wide")


# ---------------------------------------------------------------------------
# Dados (carregados uma vez e guardados em cache)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Carregando dados do pipeline...")
def carregar():
    fichas = pd.read_parquet(PROCESSED / "fichas_tratadas.parquet")
    territorio = pd.read_csv(RAW / "territorio_equipes.csv", dtype={"ine": str, "cnes": str})
    resumo = resumo_equipe_periodo(fichas).merge(inconsistencia_raca(fichas), on=["ine", "quadrimestre"], how="left")
    resumo = resumo.merge(territorio[["ine", "nome_equipe", "nome_unidade", "bairro"]], on="ine")
    pct = resumo.groupby("quadrimestre")["indice_completude"].rank(pct=True)
    resumo["status"] = pd.cut(pct, [0, 0.25, 0.40, 1], labels=["🔴 Crítica", "🟡 Atenção", "🟢 OK"], include_lowest=True).astype(str)
    return fichas, territorio, resumo


@st.cache_data(show_spinner="Calculando a população ativa...")
def populacao_ativa(ate_quadrimestre):
    """Ficha mais recente de cada pessoa até o quadrimestre, só de quem continua no território."""
    fichas, _, _ = carregar()
    f = fichas[fichas["quadrimestre"] <= ate_quadrimestre]
    atual = f.sort_values("data_ficha").groupby("id_cidadao").tail(1)
    return atual[atual["situacao"] == "ativo"]


def pct(x):
    return f"{x * 100:.0f}%"


fichas, territorio, resumo = carregar()
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
    st.divider()
    st.caption(
        "⚠️ **Protótipo com dados sintéticos.** Unidades reais (CNES) e perfil da população do Censo 2022; "
        "fichas simuladas a 25% da população. Nenhum dado real de pessoa."
    )

res_q = resumo[resumo["quadrimestre"] == quad]
elegiveis_q = fichas[fichas["quadrimestre"] == quad]


def rodape_previsao():
    st.caption(
        f"**Risco no próximo quadrimestre ({proximo(quad)})**: previsão provisória pela regra de persistência "
        "(quem é crítica agora tende a continuar). Na Sprint 1, o modelo de Machine Learning substitui esta regra."
    )


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
    f = elegiveis_q[elegiveis_q["distrito_sanitario"].isin(distritos)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Equipes", len(r))
    c2.metric("Índice de completude (mediana)", f"{r['indice_completude'].median():.0f} / 100")
    c3.metric("Equipes críticas agora", int(r["critica"].sum()))
    c4.metric(f"Em risco em {proximo(quad)}", int(r["critica"].sum()), help="Baseline de persistência")

    aba_pop, aba_qual = st.tabs(["📍 Onde está a população", "✅ Qualidade do registro"])

    with aba_pop:
        grupo = st.selectbox("População", list(POPULACOES))
        filtro, marcador = POPULACOES[grupo]
        atual = populacao_ativa(quad)
        atual = atual[atual["distrito_sanitario"].isin(distritos)]
        por_usf = (atual.assign(no_grupo=filtro(atual), sem_pergunta=atual[marcador] == "nao_perguntado",
                                elegivel=atual[marcador] != "nao_se_aplica")
                   .groupby("cnes").agg(pessoas=("no_grupo", "sum"), elegiveis=("elegivel", "sum"),
                                        sem_pergunta=("sem_pergunta", "sum")).reset_index())
        por_usf["% não perguntado"] = por_usf["sem_pergunta"] / por_usf["elegiveis"]
        usf = territorio.drop_duplicates("cnes")[["cnes", "nome_unidade", "bairro", "distrito_sanitario", "latitude", "longitude"]]
        por_usf = por_usf.merge(usf, on="cnes")
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
        st.caption("Cada círculo é uma USF (localização do CNES, conferida contra o mapa oficial de bairros). "
                   "Tamanho = pessoas do grupo registradas. Passe o mouse para ver os números.")
        st.markdown(f"**USF com mais {grupo.lower()}**")
        topo = por_usf.sort_values("pessoas", ascending=False).head(10)
        st.dataframe(
            topo[["nome_unidade", "bairro", "distrito_sanitario", "pessoas", "% não perguntado"]], hide_index=True, width="stretch",
            column_config={
                "nome_unidade": "USF", "bairro": "Bairro", "distrito_sanitario": st.column_config.NumberColumn("DS", format="%d"),
                "pessoas": "Pessoas",
                "% não perguntado": st.column_config.ProgressColumn("Não perguntado", format="percent", min_value=0, max_value=1),
            })
        st.warning(
            "**Leia a concentração junto com a qualidade.** Uma USF com poucas pessoas registradas pode ter pouca "
            "população do grupo **ou** simplesmente não estar perguntando. A coluna \"Não perguntado\" mostra isso."
        )

    with aba_qual:
        nome_marcador = st.radio("Marcador", list(MARCADORES), horizontal=True)
        col = MARCADORES[nome_marcador]
        base = f[f[col] != "nao_se_aplica"]
        estados = (base.groupby("distrito_sanitario")[col].value_counts(normalize=True).rename("pct").reset_index())
        estados["estado"] = estados[col].map({"preenchido": "Preenchido", "recusou": "Recusou informar",
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
    rodape_previsao()


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

    st.subheader("Alertas")
    anterior = resumo[(resumo["quadrimestre"] < quad) & (resumo["distrito_sanitario"] == ds)]
    alertas = []
    for _, e in r.iterrows():
        if e["inconsistencia_raca"] > LIMITE_INCONSISTENCIA:
            alertas.append(f"**{e['nome_equipe']}**: pessoas brancas ou amarelas {e['inconsistencia_raca']:.0f} pontos acima "
                           "do distrito. Possível erro de registro de raça/cor: revisar a autodeclaração.")
        hist = anterior[anterior["ine"] == e["ine"]].sort_values("quadrimestre")
        if len(hist) and e["indice_completude"] - hist["indice_completude"].iloc[-1] <= -8:
            alertas.append(f"**{e['nome_equipe']}**: índice caiu {hist['indice_completude'].iloc[-1] - e['indice_completude']:.0f} "
                           "pontos em relação ao quadrimestre anterior.")
        if len(hist) >= 2 and e["critica"] == 1 and hist["critica"].tail(2).sum() == 2:
            alertas.append(f"**{e['nome_equipe']}**: crítica há 3 quadrimestres seguidos. Prioridade para oficina.")
    if alertas:
        for a in alertas:
            st.warning(a, icon="⚠️")
    else:
        st.success("Nenhum alerta neste quadrimestre.")
    rodape_previsao()


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

    st.subheader("O que precisa ser corrigido · sugestões priorizadas")
    f = elegiveis_q[elegiveis_q["ine"] == ine]
    rede = res_q.median(numeric_only=True)
    sugestoes = []
    n_os = int((f["estado_os"] == "nao_perguntado").sum())
    if e["os_nao_perguntado"] > rede["os_nao_perguntado"]:
        sugestoes.append((e["os_nao_perguntado"] - rede["os_nao_perguntado"],
                          f"{n_os} fichas sem a pergunta de orientação sexual ({pct(e['os_nao_perguntado'])}, a rede tem "
                          f"{pct(rede['os_nao_perguntado'])}). Reforçar o roteiro de abordagem com os ACS."))
    n_ig = int((f["estado_ig"] == "nao_perguntado").sum())
    if e["ig_nao_perguntado"] > rede["ig_nao_perguntado"]:
        sugestoes.append((e["ig_nao_perguntado"] - rede["ig_nao_perguntado"],
                          f"{n_ig} fichas sem a pergunta de identidade de gênero. Revisar na próxima visita domiciliar."))
    if e["inconsistencia_raca"] > LIMITE_INCONSISTENCIA:
        sugestoes.append((1.0, f"Proporção de pessoas brancas ou amarelas {e['inconsistencia_raca']:.0f} pontos acima do distrito. "
                               "Conferir se a raça/cor está sendo autodeclarada pela pessoa."))
    n_raca = int((f["estado_raca"] == "nao_perguntado").sum())
    if n_raca:
        sugestoes.append((0.01, f"{n_raca} ficha(s) com raça/cor em branco. Campo obrigatório: completar no próximo atendimento."))
    n_def = int((f["estado_deficiencia"] == "nao_perguntado").sum())
    if n_def:
        sugestoes.append((0.01, f"{n_def} ficha(s) com deficiência em branco. Campo obrigatório: completar no próximo atendimento."))
    if sugestoes:
        for i, (_, texto) in enumerate(sorted(sugestoes, reverse=True)):
            st.checkbox(texto, key=f"sug_{ine}_{i}")
    else:
        st.success("Cadastro acima da mediana da rede em todos os campos. 👏")

    hist = resumo[resumo["ine"] == ine]
    limites = resumo.groupby("quadrimestre")["indice_completude"].quantile(0.25).rename("limite").reset_index()
    linha = alt.Chart(hist).mark_line(point=True, color=AZUL, strokeWidth=2).encode(
        x=alt.X("quadrimestre:O", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("indice_completude:Q", title="Índice", scale=alt.Scale(zero=False)),
        tooltip=["quadrimestre", alt.Tooltip("indice_completude:Q", format=".1f", title="Índice")])
    corte = alt.Chart(limites).mark_line(strokeDash=[4, 4], color="#52514e").encode(
        x="quadrimestre:O", y="limite:Q", tooltip=[alt.Tooltip("limite:Q", format=".1f", title="Limite crítico")])
    st.altair_chart((corte + linha).properties(height=240, title="Evolução da nota · tracejado = limite das 25% piores"),
                    width="stretch")
    rodape_previsao()


{"Coordenação": tela_coordenacao, "Gestão de Distrito": tela_distrito, "Equipe de Saúde": tela_equipe}[perfil]()
