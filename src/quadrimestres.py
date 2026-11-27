"""
Calendário dos quadrimestres, usado pela pipeline e pelo painel.

As datas são as mesmas da tabela quadrimestre (db/carregar_banco.py):
1º quadrimestre até 30/04, 2º até 31/08, 3º até 31/12.

Um quadrimestre só "fecha" depois do último dia. Antes disso ele está em andamento: as fichas ainda
estão chegando, o índice é parcial e a regra de crítica (as 25% piores) compara equipes com dados
incompletos. Por isso a pipeline não treina nem prevê a partir de um quadrimestre aberto.
"""
from datetime import date

FIM = {"1": (4, 30), "2": (8, 31), "3": (12, 31)}


def fim_do_quadrimestre(quad):
    """'2026.3' -> date(2026, 12, 31)."""
    ano, numero = quad.split(".")
    mes, dia = FIM[numero]
    return date(int(ano), mes, dia)


def esta_fechado(quad, hoje=None):
    """True se o quadrimestre já terminou (o último dia ficou para trás)."""
    return fim_do_quadrimestre(quad) < (hoje or date.today())
