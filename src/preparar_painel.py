"""
Dados do painel (entre as Estações 4 e 5).

O painel não lê as fichas individuais: lê só tabelas agregadas por equipe, USF e distrito,
preparadas aqui. Duas razões:
  1. Privacidade: o painel nunca toca em dado de pessoa (LGPD, art. 5º, II), só em contagens.
  2. Leveza: ~1 MB em vez de ~770 mil fichas, o que permite publicar o painel na nuvem.

Uso:  python src/preparar_painel.py
Saída: app/dados/*.parquet (versionados no git, porque são agregados e o painel publicado precisa deles)
"""

from pathlib import Path

import pandas as pd

from features import inconsistencia_raca
from indicadores import resumo_equipe_periodo

RAIZ = Path(__file__).resolve().parents[1]
PROCESSED = RAIZ / "data" / "processed"
RAW = RAIZ / "data" / "raw"
SAIDA = RAIZ / "app" / "dados"

MARCADORES = ["estado_os", "estado_ig", "estado_raca", "estado_deficiencia"]

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


def resumo_equipes(fichas, territorio):
    """Indicadores por equipe x quadrimestre, com nome, unidade e status."""
    r = resumo_equipe_periodo(fichas).merge(inconsistencia_raca(fichas), on=["ine", "quadrimestre"], how="left")
    r = r.merge(territorio[["ine", "nome_equipe", "nome_unidade", "bairro"]], on="ine")
    posicao = r.groupby("quadrimestre")["indice_completude"].rank(pct=True)
    r["status"] = pd.cut(posicao, [0, 0.25, 0.40, 1], labels=["🔴 Crítica", "🟡 Atenção", "🟢 OK"], include_lowest=True).astype(str)
    return r


def estados_por_distrito(fichas):
    """% das fichas em cada estado (preenchido, recusou, não perguntado), por distrito, quadrimestre e marcador."""
    partes = []
    for marcador in MARCADORES:
        f = fichas[fichas[marcador] != "nao_se_aplica"]
        p = (f.groupby(["quadrimestre", "distrito_sanitario"])[marcador].value_counts(normalize=True)
             .rename("pct").reset_index().rename(columns={marcador: "estado"}))
        p["marcador"] = marcador
        partes.append(p)
    return pd.concat(partes, ignore_index=True)


def populacao_por_usf(fichas):
    """Pessoas de cada grupo por USF, considerando a ficha mais recente de quem está ativo até cada quadrimestre."""
    partes = []
    ordenadas = fichas.sort_values("data_ficha")
    for q in sorted(fichas["quadrimestre"].unique()):
        atual = ordenadas[ordenadas["quadrimestre"] <= q].groupby("id_cidadao").tail(1)
        atual = atual[atual["situacao"] == "ativo"]
        for grupo, (filtro, marcador) in POPULACOES.items():
            g = (atual.assign(pessoas=filtro(atual), elegiveis=atual[marcador] != "nao_se_aplica",
                              sem_pergunta=atual[marcador] == "nao_perguntado")
                 .groupby(["cnes", "distrito_sanitario"])[["pessoas", "elegiveis", "sem_pergunta"]].sum().reset_index())
            g["quadrimestre"] = q
            g["grupo"] = grupo
            partes.append(g)
    return pd.concat(partes, ignore_index=True)


def main():
    fichas = pd.read_parquet(PROCESSED / "fichas_tratadas.parquet")
    territorio = pd.read_csv(RAW / "territorio_equipes.csv", dtype={"ine": str, "cnes": str})

    SAIDA.mkdir(parents=True, exist_ok=True)
    tabelas = {
        "resumo_equipes": resumo_equipes(fichas, territorio),
        "estados_distrito": estados_por_distrito(fichas),
        "populacao_usf": populacao_por_usf(fichas),
        "territorio_usf": territorio.drop_duplicates("cnes")[
            ["cnes", "nome_unidade", "bairro", "distrito_sanitario", "latitude", "longitude"]],
    }
    for nome, tabela in tabelas.items():
        tabela.to_parquet(SAIDA / f"{nome}.parquet", index=False)
        print(f"{nome}: {len(tabela):,} linhas")


if __name__ == "__main__":
    main()
