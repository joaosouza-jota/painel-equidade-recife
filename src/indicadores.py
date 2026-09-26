"""
Indicadores de qualidade do registro por equipe e quadrimestre (Estação 3, parte 1).

Um lugar só para as fórmulas, usado pela análise exploratória, pelo modelo e pelo painel.
Assim o número mostrado no painel é exatamente o mesmo que o modelo aprendeu.
"""

import pandas as pd

# Pesos do índice de completude (docs/contrato_dados.md): orientação sexual e identidade de gênero
# pesam o dobro porque é onde está o problema, segundo a Secretaria.
PESOS = {"os": 2, "ig": 2, "raca": 1, "deficiencia": 1}
PERCENTIL_CRITICO = 0.25   # equipe crítica = entre as 25% piores do quadrimestre


def resumo_equipe_periodo(fichas):
    """Uma linha por equipe x quadrimestre com as taxas de preenchimento e o índice de completude (0 a 100).

    Orientação sexual e identidade de gênero são medidas só entre maiores de 10 anos (regra da Secretaria).
    """
    f = fichas.assign(
        elegivel=fichas["estado_os"] != "nao_se_aplica",
        os_preenchido=fichas["estado_os"] == "preenchido",
        os_recusou=fichas["estado_os"] == "recusou",
        os_nao_perguntado=fichas["estado_os"] == "nao_perguntado",
        ig_preenchido=fichas["estado_ig"] == "preenchido",
        ig_nao_perguntado=fichas["estado_ig"] == "nao_perguntado",
        raca_preenchido=fichas["estado_raca"] == "preenchido",
        deficiencia_preenchido=fichas["estado_deficiencia"] == "preenchido",
    )
    g = f.groupby(["ine", "quadrimestre"])
    r = g.agg(
        distrito_sanitario=("distrito_sanitario", "first"),
        cnes=("cnes", "first"),
        n_fichas=("id_ficha", "size"),
        n_elegiveis=("elegivel", "sum"),
        raca_preenchido=("raca_preenchido", "mean"),
        deficiencia_preenchido=("deficiencia_preenchido", "mean"),
    )
    elegiveis = f[f["elegivel"]].groupby(["ine", "quadrimestre"])
    for coluna in ["os_preenchido", "os_recusou", "os_nao_perguntado", "ig_preenchido", "ig_nao_perguntado"]:
        r[coluna] = elegiveis[coluna].mean()

    r["indice_completude"] = 100 * (
        PESOS["os"] * r["os_preenchido"]
        + PESOS["ig"] * r["ig_preenchido"]
        + PESOS["raca"] * r["raca_preenchido"]
        + PESOS["deficiencia"] * r["deficiencia_preenchido"]
    ) / sum(PESOS.values())

    # Crítica = entre as 25% piores DO MESMO quadrimestre (a régua é relativa ao período)
    limite = r.groupby("quadrimestre")["indice_completude"].transform(lambda s: s.quantile(PERCENTIL_CRITICO))
    r["critica"] = (r["indice_completude"] <= limite).astype(int)
    return r.reset_index()
