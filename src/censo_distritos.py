"""
População adulta por Distrito Sanitário do Recife, a partir do Censo 2022 (IBGE).

O SIDRA só publica a população total por bairro (tabela 9923). Sexo e idade por área só existem nos
"Agregados por Setores Censitários", então este script soma os setores do Recife por bairro e o bairro
pelo Distrito Sanitário (mesma regra de src/gerar_sintetico.py).

Entrada (baixar e descompactar em uma pasta qualquer):
  https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/
    Agregados_por_setores_basico_BR_*.zip      (setor -> bairro)
    Agregados_por_setores_demografia_BR.zip    (sexo x faixa de idade por setor)

Saída: data/raw/ibge/distritos_censo2022.csv (usada pelo notebook 03 e pela carga do banco)

Uso:  python src/censo_distritos.py <pasta_com_os_csv>
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gerar_sintetico import RAW, distrito_sanitario, normalizar  # noqa: E402

RECIFE = "2611606"

# Faixas da demografia: 0-4, 5-9, 10-14, 15-19, 20-24, 25-29, 30-39, 40-49, 50-59, 60-69, 70+
HOMENS = [f"V{i:05d}" for i in range(1009, 1020)]
MULHERES = [f"V{i:05d}" for i in range(1020, 1031)]
FRACAO_18_19 = 0.4   # [hipótese] 18 e 19 anos = 2 das 5 idades da faixa 15-19 (o setor não abre por idade simples)


def bairro_chave(nome):
    # "Sítio dos Pintos - São Brás" no IBGE é "Sítio dos Pintos" no mapa oficial
    return normalizar(str(nome).split(" - ")[0])


def main(pasta):
    pasta = Path(pasta)
    basico = pd.read_csv(next(pasta.glob("Agregados_por_setores_basico_BR*.csv")), sep=";", dtype=str,
                         encoding="latin1", usecols=["CD_SETOR", "CD_MUN", "NM_BAIRRO"])
    basico = basico[basico["CD_MUN"] == RECIFE]
    demo = pd.read_csv(pasta / "Agregados_por_setores_demografia_BR.csv", sep=";", dtype=str, encoding="latin1")
    demo = demo[demo["CD_setor"].isin(basico["CD_SETOR"])]
    colunas = ["V01006", "V01007", "V01008"] + HOMENS + MULHERES
    demo[colunas] = demo[colunas].apply(pd.to_numeric, errors="coerce")   # "X" = sigilo do IBGE -> vazio

    geo = json.load(open(RAW / "bairros_recife_2023.geojson"))
    ds_do_bairro = {normalizar(f["properties"]["EBAIRRNOME"]):
                    distrito_sanitario(f["properties"]["CRPAAACODI"], f["properties"]["CMICROCODI"])
                    for f in geo["features"]}

    setores = demo.merge(basico, left_on="CD_setor", right_on="CD_SETOR")
    setores["distrito"] = setores["NM_BAIRRO"].map(lambda b: ds_do_bairro.get(bairro_chave(b)))
    setores = setores.dropna(subset=["distrito", "V01006"])   # setores vazios ou sob sigilo
    setores["homens_18"] = setores[HOMENS[4:]].sum(axis=1) + FRACAO_18_19 * setores[HOMENS[3]]
    setores["mulheres_18"] = setores[MULHERES[4:]].sum(axis=1) + FRACAO_18_19 * setores[MULHERES[3]]

    t = setores.groupby("distrito").agg(
        populacao=("V01006", "sum"), homens=("V01007", "sum"), mulheres=("V01008", "sum"),
        homens_18=("homens_18", "sum"), mulheres_18=("mulheres_18", "sum"),
    ).round().astype(int)
    t.index = t.index.astype(int)
    t["adultos"] = t["homens_18"] + t["mulheres_18"]
    t.index.name = "distrito_sanitario"
    t.to_csv(RAW / "ibge" / "distritos_censo2022.csv")
    print(t)
    print(f"Total: {t['populacao'].sum():,} pessoas · {t['adultos'].sum():,} adultos "
          f"({len(setores):,} setores com dado)")


if __name__ == "__main__":
    main(sys.argv[1])
