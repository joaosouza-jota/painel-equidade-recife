"""
Detalhamento das estatísticas de resumo do painel.

Unidade de análise: a equipe no quadrimestre (uma linha de app/dados/resumo_equipes.parquet).
Mostra medidas de posição e dispersão de cada indicador, a distribuição entre as equipes,
a comparação entre distritos, a evolução no tempo e as equipes fora do padrão (regra 1,5 × IIQ).
Lê só dados agregados por equipe, do mesmo lugar que o Painel (app/dados_painel.py).

Página do roteador app/app.py.
"""

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dados_painel import carregar, risco  # noqa: E402

AZUL, LARANJA = "#2a78d6", "#eb6834"

# coluna -> (nome na tela, é proporção 0-1? -> mostra em %)
VARIAVEIS = {
    "indice_completude":      ("Índice de completude (0 a 100)", False),
    "raca_preenchido":        ("Raça/cor preenchida (%)", True),
    "deficiencia_preenchido": ("Deficiência preenchida (%)", True),
    "os_preenchido":          ("Orientação sexual preenchida (%)", True),
    "os_recusou":             ("Orientação sexual: pessoa recusou (%)", True),
    "os_nao_perguntado":      ("Orientação sexual: N/I (%)", True),
    "ig_preenchido":          ("Identidade de gênero preenchida (%)", True),
    "ig_nao_perguntado":      ("Identidade de gênero: N/I (%)", True),
    "inconsistencia_raca":    ("Inconsistência de raça/cor (pontos percentuais)", False),
    "risco":                  ("Risco de ficar crítica no próximo quadrimestre (%)", True),
    "n_fichas":               ("Fichas enviadas no quadrimestre", False),
}


def carregar_resumo():
    dados, _ = carregar()
    df = dados["resumo_equipes"].assign(risco=lambda d: risco(d))
    for col, (_, proporcao) in VARIAVEIS.items():
        if proporcao:
            df[col] = df[col] * 100
    return df


def resumo_estatistico(serie):
    s = serie.dropna()
    q1, mediana, q3 = s.quantile([0.25, 0.5, 0.75])
    media, dp = s.mean(), s.std()
    return {
        "n": len(s),
        "Média": media,
        "Desvio padrão": dp,
        "CV (%)": 100 * dp / media if media else None,
        "Mínimo": s.min(),
        "Q1": q1,
        "Mediana": mediana,
        "Q3": q3,
        "Máximo": s.max(),
        "IIQ": q3 - q1,
        "Assimetria": s.skew(),
    }


def tabela(linhas, indice):
    df = pd.DataFrame(linhas, index=indice)
    df["n"] = df["n"].astype(int)
    return df.style.format({c: "{:.1f}" for c in df.columns if c not in ("n", "Assimetria")}
                           | {"Assimetria": "{:.2f}"})


resumo = carregar_resumo()
QUADRIMESTRES = sorted(resumo["quadrimestre"].unique())

st.title("Estatísticas de resumo")
st.caption("Cada observação é uma equipe em um quadrimestre. Medidas calculadas sobre as equipes do recorte escolhido.")

c1, c2 = st.columns(2)
quad = c1.select_slider("Quadrimestre", QUADRIMESTRES, value=QUADRIMESTRES[-1])
recorte = c2.selectbox("Recorte", ["Rede toda"] + [f"Distrito Sanitário {d}" for d in range(1, 9)])

base = resumo[resumo["quadrimestre"] == quad]
if recorte != "Rede toda":
    base = base[base["distrito_sanitario"] == int(recorte.split()[-1])]

aba_geral, aba_detalhe = st.tabs(["📋 Todos os indicadores", "🔎 Detalhar um indicador"])

# ---------------------------------------------------------------------------
# Aba 1 · tabela de resumo de todos os indicadores
# ---------------------------------------------------------------------------
with aba_geral:
    st.subheader(f"{recorte} · {quad} · {len(base)} equipes")
    st.dataframe(
        tabela([resumo_estatistico(base[c]) for c in VARIAVEIS], [n for n, _ in VARIAVEIS.values()]),
        width="stretch",
    )
    st.caption("CV = desvio padrão ÷ média · IIQ = Q3 − Q1 (intervalo interquartil) · "
               "assimetria > 0: cauda à direita; < 0: cauda à esquerda.")

# ---------------------------------------------------------------------------
# Aba 2 · detalhamento de um indicador
# ---------------------------------------------------------------------------
with aba_detalhe:
    col = st.selectbox("Indicador", list(VARIAVEIS), format_func=lambda c: VARIAVEIS[c][0])
    nome = VARIAVEIS[col][0]
    est = resumo_estatistico(base[col])

    m = st.columns(5)
    m[0].metric("Média", f"{est['Média']:.1f}")
    m[1].metric("Mediana", f"{est['Mediana']:.1f}")
    m[2].metric("Desvio padrão", f"{est['Desvio padrão']:.1f}")
    m[3].metric("Mínimo · Máximo", f"{est['Mínimo']:.1f} · {est['Máximo']:.1f}")
    m[4].metric("Q1 · Q3", f"{est['Q1']:.1f} · {est['Q3']:.1f}")

    # Distribuição: histograma com média e mediana
    st.subheader("Distribuição entre as equipes")
    hist = alt.Chart(base).mark_bar(color=AZUL, opacity=0.85).encode(
        x=alt.X(f"{col}:Q", bin=alt.Bin(maxbins=25), title=nome),
        y=alt.Y("count():Q", title="Equipes"),
    )
    linhas = pd.DataFrame({"medida": ["Média", "Mediana"], "valor": [est["Média"], est["Mediana"]]})
    regras = alt.Chart(linhas).mark_rule(strokeWidth=2).encode(
        x="valor:Q",
        color=alt.Color("medida:N", scale=alt.Scale(range=[LARANJA, "#111111"]), title=None),
        strokeDash=alt.StrokeDash("medida:N", legend=None),
        tooltip=["medida", alt.Tooltip("valor:Q", format=".1f")],
    )
    st.altair_chart((hist + regras).properties(height=280), width="stretch")

    # Comparação entre distritos (sempre na rede toda do quadrimestre)
    st.subheader(f"Comparação entre distritos · {quad}")
    rede_q = resumo[resumo["quadrimestre"] == quad]
    box = alt.Chart(rede_q).mark_boxplot(extent=1.5, color=AZUL, size=28).encode(
        x=alt.X("distrito_sanitario:O", title="Distrito Sanitário"),
        y=alt.Y(f"{col}:Q", title=nome),
    )
    st.altair_chart(box.properties(height=300), width="stretch")
    por_distrito = rede_q.groupby("distrito_sanitario")[col]
    st.dataframe(
        tabela([resumo_estatistico(s) for _, s in por_distrito],
               [f"Distrito {d}" for d, _ in por_distrito]),
        width="stretch",
    )

    # Evolução no tempo
    st.subheader(f"Evolução · {recorte}")
    hist_recorte = resumo if recorte == "Rede toda" else \
        resumo[resumo["distrito_sanitario"] == int(recorte.split()[-1])]
    evol = (hist_recorte.groupby("quadrimestre")[col]
            .agg(Média="mean", Mediana="median", Q1=lambda s: s.quantile(0.25), Q3=lambda s: s.quantile(0.75))
            .reset_index())
    faixa = alt.Chart(evol).mark_area(opacity=0.18, color=AZUL).encode(
        x=alt.X("quadrimestre:O", title="Quadrimestre"),
        y=alt.Y("Q1:Q", title=nome), y2="Q3:Q",
    )
    curvas = alt.Chart(evol.melt("quadrimestre", ["Média", "Mediana"], "medida", "valor")).mark_line(point=True).encode(
        x="quadrimestre:O", y="valor:Q",
        color=alt.Color("medida:N", scale=alt.Scale(range=[LARANJA, "#111111"]), title=None),
        tooltip=["quadrimestre", "medida", alt.Tooltip("valor:Q", format=".1f")],
    )
    st.altair_chart((faixa + curvas).properties(height=280), width="stretch")
    st.caption("Faixa sombreada: metade central das equipes (de Q1 a Q3).")

    # Equipes fora do padrão
    st.subheader("Equipes fora do padrão")
    lim_inf, lim_sup = est["Q1"] - 1.5 * est["IIQ"], est["Q3"] + 1.5 * est["IIQ"]
    fora = base[(base[col] < lim_inf) | (base[col] > lim_sup)]
    st.caption(f"Valores abaixo de {lim_inf:.1f} ou acima de {lim_sup:.1f} (Q1 − 1,5 × IIQ e Q3 + 1,5 × IIQ) "
               f"no recorte: {len(fora)} de {len(base)} equipes.")
    if len(fora):
        st.dataframe(
            fora[["distrito_sanitario", "nome_equipe", "nome_unidade", col]]
            .rename(columns={"distrito_sanitario": "Distrito", "nome_equipe": "Equipe",
                             "nome_unidade": "Unidade", col: nome})
            .sort_values(nome).style.format({nome: "{:.1f}"}),
            width="stretch", hide_index=True,
        )
