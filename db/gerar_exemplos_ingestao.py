"""
Gera arquivos de exemplo para testar a aba "Importar arquivo" (db/ingestao.py), a partir da base sintética.

Saída em data/exemplos/:
  - fichas_2026-3.csv   · ~5 mil fichas do quadrimestre em andamento (set-nov/2026): amostra das fichas
                          de mai-jul/2026 com a data movida 4 meses. Mesmo formato do PEC sintético
                          (id_cidadao, data_ficha, nome_social...), com id_ficha novo a partir de 1.000.001
  - fichas_2026-3.xlsx  · as mesmas fichas, em planilha
  - fichas_com_erros.csv· 20 fichas válidas + 8 com um erro cada, para ver a validação

Uso (na raiz do projeto):  python db/gerar_exemplos_ingestao.py
"""

from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "data" / "exemplos"
SAIDA.mkdir(parents=True, exist_ok=True)

f = pd.read_parquet(RAIZ / "data" / "raw" / "fichas_cadastro.parquet")
base = f[(f["data_ficha"] >= "2026-05-01") & (f["data_ficha"] <= "2026-07-15")].sample(frac=0.08, random_state=42)
base = base.sort_values(["data_ficha", "id_ficha"]).copy()
base["data_ficha"] = (base["data_ficha"] + pd.DateOffset(months=4)).dt.strftime("%Y-%m-%d")
base["id_ficha"] = range(1_000_001, 1_000_001 + len(base))

base.to_csv(SAIDA / "fichas_2026-3.csv", index=False)
base.to_excel(SAIDA / "fichas_2026-3.xlsx", index=False)

erros = base.head(28).copy().astype(str)
erros["id_ficha"] = [str(2_000_001 + i) for i in range(len(erros))]
quebras = [
    ("ine", "1234567890"),                 # equipe que não existe
    ("data_ficha", "2027-01-10"),          # data no futuro
    ("idade", "130"),                      # idade fora de 0 a 110
    ("sexo", "X"),                         # sexo fora da lista
    ("raca_cor", "morena"),                # raça/cor fora da lista do e-SUS
    ("id_cidadao", "123"),                 # código pseudônimo fora do formato
    ("tipo_deficiencia", "cognitiva"),     # categoria de deficiência inexistente
    ("deseja_informar_os", "sim"),         # disse que informa, mas a resposta está vazia
]
for i, (coluna, valor) in enumerate(quebras):
    linha = 20 + i
    erros.iloc[linha, erros.columns.get_loc(coluna)] = valor
    if coluna == "tipo_deficiencia":
        erros.iloc[linha, erros.columns.get_loc("tem_deficiencia")] = "sim"
    if coluna == "deseja_informar_os":
        erros.iloc[linha, erros.columns.get_loc("idade")] = "40"
        erros.iloc[linha, erros.columns.get_loc("orientacao_sexual")] = ""
erros.to_csv(SAIDA / "fichas_com_erros.csv", index=False)

print(f"fichas_2026-3: {len(base):,} fichas · {base['ine'].nunique()} equipes · "
      f"{base['data_ficha'].min()} a {base['data_ficha'].max()}")
print(f"fichas_com_erros: {len(erros)} linhas (8 com erro)")
