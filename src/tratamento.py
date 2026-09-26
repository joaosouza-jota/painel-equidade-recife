"""
Tratamento das fichas de cadastro (Estação 2).

Lê o que chega da extração (hoje: o gerador sintético; amanhã: o PEC) e entrega uma base
padronizada e validada para as análises e para o modelo.

Três tarefas:
  1. Padronizar: textos em minúsculas, sem acento e sem espaço; datas como data.
  2. Validar: cada valor precisa estar na lista do contrato de dados; cada ficha precisa de uma
     equipe que exista no território. O que falhar é contado e reportado, nunca descartado em silêncio.
  3. Derivar: quadrimestre, faixa etária e o ESTADO de cada marcador
     (preenchido / recusou / nao_perguntado / nao_se_aplica), que é a distinção central do projeto.

Uso:  python src/tratamento.py
Saída: data/processed/fichas_tratadas.parquet
"""

import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"
PROCESSED = RAIZ / "data" / "processed"

# Valores aceitos, conforme docs/contrato_dados.md ("" = campo vazio)
VALORES_VALIDOS = {
    "tipo_ficha": {"novo", "atualizacao"},
    "situacao": {"ativo", "mudou_se", "obito"},
    "sexo": {"f", "m"},
    "raca_cor": {"branca", "preta", "parda", "amarela", "indigena", ""},
    "tem_deficiencia": {"sim", "nao", ""},
    "deseja_informar_os": {"sim", "nao", ""},
    "orientacao_sexual": {"heterossexual", "gay", "lesbica", "bissexual", "assexual", "pansexual", "outra", ""},
    "deseja_informar_ig": {"sim", "nao", ""},
    "identidade_genero": {"mulher_cis", "homem_cis", "mulher_trans", "homem_trans", "travesti", "nao_binario", "outra", ""},
}
TIPOS_DEFICIENCIA = {"auditiva", "visual", "intelectual", "fisica", "outra"}

FAIXAS_ETARIAS = [0, 10, 19, 39, 59, 200]
ROTULOS_FAIXAS = ["0-10", "11-19", "20-39", "40-59", "60+"]


def padronizar_texto(serie):
    """'  Não ' -> 'nao'. Resolve acento, maiúscula e espaço sobrando, comuns em exportações de sistemas."""
    return (
        serie.fillna("").astype(str).str.strip().str.lower()
        .map(lambda s: unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode())
        .str.replace(" ", "_")
    )


def quadrimestre(datas):
    """2024-03-10 -> '2024.1' (jan-abr = 1, mai-ago = 2, set-dez = 3)."""
    return datas.dt.year.astype(str) + "." + ((datas.dt.month - 1) // 4 + 1).astype(str)


def estado_com_pergunta(deseja_informar, elegivel):
    """Orientação sexual e identidade de gênero: o PEC pergunta antes se a pessoa deseja informar."""
    return np.select(
        [~elegivel, deseja_informar == "sim", deseja_informar == "nao"],
        ["nao_se_aplica", "preenchido", "recusou"],
        default="nao_perguntado",
    )


def estado_obrigatorio(valor):
    """Raça/cor e deficiência são obrigatórios: não existe 'recusou', só preenchido ou vazio."""
    return np.where(valor == "", "nao_perguntado", "preenchido")


def validar(fichas, territorio):
    """Conta os problemas de qualidade da extração. Não altera nada."""
    problemas = {}
    for coluna, validos in VALORES_VALIDOS.items():
        invalidos = ~fichas[coluna].isin(validos)
        if invalidos.any():
            problemas[f"{coluna}: valor fora do contrato"] = int(invalidos.sum())

    tipos = fichas["tipo_deficiencia"].str.split(";").explode()
    invalidos = ~tipos.isin(TIPOS_DEFICIENCIA | {""})
    if invalidos.any():
        problemas["tipo_deficiencia: valor fora do contrato"] = int(invalidos.sum())

    sem_equipe = ~fichas["ine"].isin(territorio["ine"])
    if sem_equipe.any():
        problemas["ine: equipe inexistente no território"] = int(sem_equipe.sum())

    if fichas["id_ficha"].duplicated().any():
        problemas["id_ficha: duplicado"] = int(fichas["id_ficha"].duplicated().sum())

    # Coerência entre campos: resposta preenchida sem a pessoa ter aceitado informar
    for pergunta, resposta in [("deseja_informar_os", "orientacao_sexual"), ("deseja_informar_ig", "identidade_genero")]:
        incoerente = (fichas[resposta] != "") & (fichas[pergunta] != "sim")
        if incoerente.any():
            problemas[f"{resposta}: preenchido sem '{pergunta} = sim'"] = int(incoerente.sum())

    incoerente = (fichas["tipo_deficiencia"] != "") & (fichas["tem_deficiencia"] != "sim")
    if incoerente.any():
        problemas["tipo_deficiencia: preenchido sem 'tem_deficiencia = sim'"] = int(incoerente.sum())

    return problemas


def tratar(fichas, territorio):
    f = fichas.copy()

    # 1. Padronizar
    texto = [c for c in VALORES_VALIDOS] + ["tipo_deficiencia"]
    for coluna in texto:
        f[coluna] = padronizar_texto(f[coluna])
    f["ine"] = f["ine"].astype(str).str.strip().str.zfill(10)
    f["data_ficha"] = pd.to_datetime(f["data_ficha"], errors="coerce")
    f["idade"] = pd.to_numeric(f["idade"], errors="coerce")

    # 2. Validar
    problemas = validar(f, territorio)

    # 3. Derivar
    f["quadrimestre"] = quadrimestre(f["data_ficha"])
    f["faixa_etaria"] = pd.cut(f["idade"], FAIXAS_ETARIAS, labels=ROTULOS_FAIXAS, include_lowest=True).astype(str)
    elegivel = f["idade"] > 10     # regra da Secretaria: 0 a 10 anos fora de orientação sexual e identidade de gênero
    f["estado_os"] = estado_com_pergunta(f["deseja_informar_os"], elegivel)
    f["estado_ig"] = estado_com_pergunta(f["deseja_informar_ig"], elegivel)
    f["estado_raca"] = estado_obrigatorio(f["raca_cor"])
    f["estado_deficiencia"] = estado_obrigatorio(f["tem_deficiencia"])

    # Traz o território para cada ficha (distrito, unidade, bairro)
    f = f.merge(territorio[["ine", "cnes", "nome_unidade", "distrito_sanitario", "bairro"]], on="ine", how="left")
    return f, problemas


def main():
    fichas = pd.read_parquet(RAW / "fichas_cadastro.parquet")
    territorio = pd.read_csv(RAW / "territorio_equipes.csv", dtype=str)
    territorio["distrito_sanitario"] = territorio["distrito_sanitario"].astype(int)

    tratadas, problemas = tratar(fichas, territorio)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    tratadas.to_parquet(PROCESSED / "fichas_tratadas.parquet", index=False)

    print(f"Fichas tratadas: {len(tratadas):,} · Quadrimestres: {', '.join(sorted(tratadas['quadrimestre'].unique()))}")
    if problemas:
        print("Problemas de qualidade encontrados na extração:")
        for descricao, qtd in problemas.items():
            print(f"  - {descricao}: {qtd:,}")
    else:
        print("Validação: nenhum problema encontrado (todos os valores dentro do contrato de dados).")


if __name__ == "__main__":
    main()
