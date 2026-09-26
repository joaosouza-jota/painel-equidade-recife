"""
Base do modelo (Estação 3, parte 2): uma linha por equipe x quadrimestre, com variáveis e alvo.

Pergunta do modelo: olhando a equipe até o quadrimestre t, ela vai estar CRÍTICA em t+1?
(crítica = entre as 25% piores do quadrimestre no índice de completude, ver src/indicadores.py)

Regra de ouro contra vazamento: toda variável da linha t usa só informação disponível até o fim de t.
Nada de t+1 entra como variável; t+1 só aparece no alvo.

Uso:  python src/features.py
Saída: data/processed/base_modelo.parquet
"""

from pathlib import Path

import numpy as np
import pandas as pd

from indicadores import resumo_equipe_periodo

RAIZ = Path(__file__).resolve().parents[1]
PROCESSED = RAIZ / "data" / "processed"

ALVO = "critica_prox"

# Variáveis que o modelo pode usar (todas calculadas até o quadrimestre t)
VARIAVEIS = [
    # Situação atual da equipe
    "indice_completude", "posicao_na_rede", "critica",
    "os_preenchido", "os_recusou", "os_nao_perguntado", "ig_preenchido",
    "raca_preenchido", "deficiencia_preenchido",
    # Histórico
    "indice_anterior", "variacao_indice", "media_historica", "fracao_critica",
    # Contexto
    "n_fichas", "inconsistencia_raca",
] + [f"ds_{d}" for d in range(1, 9)]


def inconsistencia_raca(fichas):
    """Quantos pontos a % de brancos/amarelos da equipe fica acima da mediana do seu distrito, no quadrimestre.
    É a regra que o notebook 01 mostrou separar as equipes com erro sistemático de raça/cor."""
    f = fichas[fichas["raca_cor"] != ""]
    g = f.groupby(["ine", "quadrimestre"]).agg(
        distrito_sanitario=("distrito_sanitario", "first"),
        branca=("raca_cor", lambda s: (s == "branca").mean() * 100),
        amarela=("raca_cor", lambda s: (s == "amarela").mean() * 100),
    )
    mediana = g.groupby(["distrito_sanitario", "quadrimestre"])[["branca", "amarela"]].transform("median")
    excesso = np.maximum(g["branca"] - mediana["branca"], g["amarela"] - mediana["amarela"])
    return excesso.clip(lower=0).rename("inconsistencia_raca").reset_index()


def montar_base(fichas):
    r = resumo_equipe_periodo(fichas).sort_values(["ine", "quadrimestre"]).reset_index(drop=True)
    r = r.merge(inconsistencia_raca(fichas), on=["ine", "quadrimestre"], how="left")
    por_equipe = r.groupby("ine")

    # Posição relativa na rede no próprio quadrimestre (0 = pior equipe, 1 = melhor)
    r["posicao_na_rede"] = r.groupby("quadrimestre")["indice_completude"].rank(pct=True)

    # Histórico: só o passado e o presente da equipe
    r["indice_anterior"] = por_equipe["indice_completude"].shift(1)
    r["variacao_indice"] = r["indice_completude"] - r["indice_anterior"]
    r["media_historica"] = por_equipe["indice_completude"].transform(lambda s: s.expanding().mean())
    # Fração (e não contagem) para não crescer só com o passar do tempo: no teste, que são os períodos
    # mais recentes, uma contagem teria valores que o modelo nunca viu no treino
    r["fracao_critica"] = por_equipe["critica"].transform(lambda s: s.expanding().mean())

    for d in range(1, 9):
        r[f"ds_{d}"] = (r["distrito_sanitario"] == d).astype(int)

    # Alvo: a equipe estará crítica no quadrimestre seguinte?
    r[ALVO] = por_equipe["critica"].shift(-1)

    # O 1º quadrimestre não tem "anterior": fica fora da base do modelo
    return r[r["indice_anterior"].notna()].reset_index(drop=True)


def main():
    fichas = pd.read_parquet(PROCESSED / "fichas_tratadas.parquet")
    base = montar_base(fichas)
    base.to_parquet(PROCESSED / "base_modelo.parquet", index=False)

    rotulada = base[base[ALVO].notna()]
    print(f"Base do modelo: {len(base):,} linhas (equipe x quadrimestre) · {len(VARIAVEIS)} variáveis")
    print(f"Com alvo conhecido: {len(rotulada):,} · % críticas no período seguinte: {rotulada[ALVO].mean():.1%}")
    print(f"Sem alvo (último quadrimestre, a prever): {base[ALVO].isna().sum()} equipes")


if __name__ == "__main__":
    main()
