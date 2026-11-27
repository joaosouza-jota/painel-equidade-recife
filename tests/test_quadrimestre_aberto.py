"""
Quadrimestre aberto não pode entrar no modelo.

Bug: importar o arquivo-modelo que o app oferece para download (3 fichas de setembro de 2026, ou seja,
do 2026.3, que só fecha em 31/12) fazia a pipeline tratar o 2026.3 como completo. A única equipe do
quadrimestre virava "a pior" (crítica) e as equipes em risco caíam de 98 para 0.

Rodar na raiz do projeto: pytest
"""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import pipeline
from quadrimestres import esta_fechado, fim_do_quadrimestre

HOJE = date(2026, 11, 27)   # o 2026.3 vai de 01/09 a 31/12: nesta data ele está aberto
RESUMO = Path(__file__).resolve().parents[1] / "app" / "dados" / "resumo_equipes.parquet"


@pytest.fixture(scope="module")
def resumo():
    return pd.read_parquet(RESUMO)


def com_importacao_parcial(resumo):
    """Simula a importação do arquivo-modelo: uma equipe com 3 fichas no quadrimestre aberto.
    Sozinha no quadrimestre, ela é a pior das equipes dele e fica marcada como crítica."""
    linha = resumo[resumo["quadrimestre"] == "2026.2"].iloc[[0]].copy()
    linha["quadrimestre"] = "2026.3"
    linha["n_fichas"] = 3
    linha["critica"] = 1
    return pd.concat([resumo, linha], ignore_index=True)


def test_fim_do_quadrimestre():
    # As mesmas datas de db/carregar_banco.py
    assert fim_do_quadrimestre("2026.1") == date(2026, 4, 30)
    assert fim_do_quadrimestre("2026.2") == date(2026, 8, 31)
    assert fim_do_quadrimestre("2026.3") == date(2026, 12, 31)


def test_esta_fechado():
    assert esta_fechado("2026.2", HOJE)
    assert not esta_fechado("2026.3", HOJE)
    assert not esta_fechado("2026.3", date(2026, 12, 31))   # no último dia ainda está aberto
    assert esta_fechado("2026.3", date(2027, 1, 1))


def test_quadrimestre_aberto_nao_muda_o_resultado(resumo):
    _, antes = pipeline.treinar_e_prever(resumo, hoje=HOJE)
    _, depois = pipeline.treinar_e_prever(com_importacao_parcial(resumo), hoje=HOJE)
    assert antes["equipes_em_risco"] > 0
    assert depois["ultimo_quadrimestre"] == "2026.2"
    assert depois["equipes_em_risco"] == antes["equipes_em_risco"]
    assert depois["f1_modelo"] == pytest.approx(antes["f1_modelo"])
    assert depois["f1_persistencia"] == pytest.approx(antes["f1_persistencia"])


def test_nao_preve_a_partir_do_quadrimestre_aberto(resumo):
    previsoes, _ = pipeline.treinar_e_prever(com_importacao_parcial(resumo), hoje=HOJE)
    assert "2026.3" not in set(previsoes["quadrimestre"])


def test_quando_o_quadrimestre_fecha_ele_entra(resumo):
    _, metricas = pipeline.treinar_e_prever(com_importacao_parcial(resumo), hoje=date(2027, 1, 5))
    assert metricas["ultimo_quadrimestre"] == "2026.3"
