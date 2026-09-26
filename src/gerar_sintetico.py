"""
Gerador da base sintética do Painel de Equidade (Estação 1).

Fabrica um "Recife de mentira" no formato de docs/contrato_dados.md:
  - territorio_equipes.csv   : 142 USF reais (CNES) com equipes sintéticas
  - fichas_cadastro.parquet  : fichas de cadastro individual, jan/2024 a ago/2026

Três camadas de informação:
  [real]      território (CNES + bairros oficiais do Recife) e perfil da população (IBGE, Censo 2022)
  [real]      taxa de ~38% que deseja informar orientação sexual (reunião com a Secretaria, 01/09/2026)
  [hipótese]  comportamento das equipes: quem pergunta, quem erra raça/cor, como isso muda no tempo

A "verdade" escondida (o comportamento real de cada equipe) é salva à parte em
data/raw/_verdade_equipes.parquet. Ela NÃO entra no modelo: serve só para conferir o gerador.

Uso:  python src/gerar_sintetico.py
"""

import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"

SEMENTE = 42
ESCALA = 0.25          # fração da população simulada (0.25 = 1 em cada 4 pessoas, para rodar rápido)
TOTAL_EQUIPES = 384    # [real] briefing da Secretaria

# Oito quadrimestres: jan/2024 a ago/2026 (o de set-dez/2026 ainda está em andamento)
PERIODOS = pd.period_range("2024-01", "2026-08", freq="M")[::4]
INICIO = pd.Timestamp("2024-01-01")

rng = np.random.default_rng(SEMENTE)


def normalizar(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper().strip()


def sigmoide(x):
    return 1 / (1 + np.exp(-x))


def logit(p):
    return np.log(p / (1 - p))


# ---------------------------------------------------------------------------
# 1. Território [real]: USF do CNES + Distrito Sanitário pelo mapa oficial de bairros
# ---------------------------------------------------------------------------

# Nomes do CNES que não batem com o nome oficial do bairro
CORRECOES_BAIRRO = {
    "JORDAO BAIXO": "JORDAO",
    "JORDAO ALTO": "JORDAO",
    "IBURA DE BAIXO": "IBURA",
    "POCO DA PANELA": "POCO",
    "UR 07 VARZEA": "VARZEA",
}


def distrito_sanitario(rpa, micro):
    """RPA 1, 2, 4 e 5 coincidem com o DS. A RPA 3 se divide em DS 3 e DS 7, e a RPA 6 em DS 6 e DS 8.
    [inferência] divisão feita pelas microrregiões oficiais; bate com a fala da cliente (DS 8 = Ibura e Jordão)."""
    if rpa == 3:
        return 3 if micro == 1 else 7
    if rpa == 6:
        return 6 if micro == 1 else 8
    return rpa


def _aneis(geometria):
    """Anéis externos de um Polygon/MultiPolygon do GeoJSON, como listas de (lon, lat)."""
    if geometria["type"] == "Polygon":
        return [geometria["coordinates"][0]]
    return [poligono[0] for poligono in geometria["coordinates"]]


def _dentro(lon, lat, aneis):
    """Teste do raio (ray casting): o ponto está dentro de algum dos anéis?"""
    for anel in aneis:
        dentro = False
        for (x1, y1), (x2, y2) in zip(anel, anel[1:] + anel[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                dentro = not dentro
        if dentro:
            return True
    return False


def carregar_unidades():
    bairros = json.load(open(RAW / "bairros_recife_2023.geojson"))["features"]
    ds_por_bairro = {
        normalizar(b["properties"]["EBAIRRNOME"]): distrito_sanitario(b["properties"]["CRPAAACODI"], b["properties"]["CMICROCODI"])
        for b in bairros
    }
    nome_oficial = {normalizar(b["properties"]["EBAIRRNOME"]): b["properties"]["EBAIRRNOMEOF"] for b in bairros}
    aneis_por_bairro = {normalizar(b["properties"]["EBAIRRNOME"]): _aneis(b["geometry"]) for b in bairros}
    aneis_por_ds = {}
    for nome, aneis in aneis_por_bairro.items():
        aneis_por_ds.setdefault(ds_por_bairro[nome], []).extend(aneis)

    cnes = json.load(open(RAW / "cnes" / "estabelecimentos_recife.json"))
    usf = [
        e for e in cnes
        if e["codigo_tipo_unidade"] == 2                                # Centro de Saúde / Unidade Básica
        and e["tipo_gestao"] == "M"                                     # gestão municipal
        and e["codigo_motivo_desabilitacao_estabelecimento"] is None   # ativa
        and e["estabelecimento_faz_atendimento_ambulatorial_sus"] == "SIM"
        and "USF" in e["nome_fantasia"]
    ]
    linhas = []
    for e in usf:
        chave = normalizar(e["bairro_estabelecimento"])
        chave = CORRECOES_BAIRRO.get(chave, chave)
        linhas.append({
            "cnes": str(e["codigo_cnes"]).zfill(7),
            "nome_unidade": re.sub(r"^US \d+ ", "", e["nome_fantasia"]).title().replace("Usf", "USF"),
            "bairro": nome_oficial[chave],
            "distrito_sanitario": ds_por_bairro[chave],
            **coordenada(e, aneis_por_bairro[chave], aneis_por_ds[ds_por_bairro[chave]]),
        })
    unidades = pd.DataFrame(linhas).sort_values("cnes").reset_index(drop=True)

    # Várias USF corrigidas no mesmo bairro cairiam no mesmo ponto: espalha em círculo (~250 m) para aparecerem no mapa
    corrigidas = unidades["coordenada_origem"] == "centro_do_bairro"
    ordem = unidades[corrigidas].groupby("bairro").cumcount()
    angulo = ordem * 2.4
    raio = 0.0022 * np.sqrt(ordem)
    unidades.loc[corrigidas, "latitude"] += raio * np.sin(angulo)
    unidades.loc[corrigidas, "longitude"] += raio * np.cos(angulo)
    return unidades


def coordenada(estabelecimento, aneis_bairro, aneis_distrito):
    """[real] Coordenada do CNES, conferida contra os polígonos oficiais dos bairros.

    O CNES tem coordenadas erradas: USF no mar, fora do Recife e ~20 USF com a mesma coordenada padrão no centro
    da cidade. Aceita o ponto se ele cai no bairro declarado ou em outro bairro do mesmo distrito (divisa);
    se não, usa o centro aproximado do bairro declarado."""
    lat = estabelecimento["latitude_estabelecimento_decimo_grau"]
    lon = estabelecimento["longitude_estabelecimento_decimo_grau"]
    if lat is not None and lon is not None and (_dentro(lon, lat, aneis_bairro) or _dentro(lon, lat, aneis_distrito)):
        return {"latitude": lat, "longitude": lon, "coordenada_origem": "cnes"}
    aneis = aneis_bairro
    maior = max(aneis, key=len)
    return {"latitude": float(np.mean([p[1] for p in maior])), "longitude": float(np.mean([p[0] for p in maior])),
            "coordenada_origem": "centro_do_bairro"}


def criar_equipes(unidades):
    """[hipótese] A CNES aberta não traz as equipes, então elas são sintéticas.
    Cada USF recebe no mínimo 2 equipes (a cliente falou em 2 a 8) e as restantes são sorteadas até fechar 384."""
    n = len(unidades)
    qtd = np.full(n, 2)
    peso = rng.gamma(1.0, size=n)
    while qtd.sum() < TOTAL_EQUIPES:
        i = rng.choice(n, p=peso / peso.sum())
        if qtd[i] < 8:
            qtd[i] += 1
    linhas = []
    for (_, u), k in zip(unidades.iterrows(), qtd):
        for j in range(1, k + 1):
            linhas.append({
                "ine": str(9_000_000_000 + len(linhas) + 1),   # começa com 9 para não parecer um INE real
                "nome_equipe": f"ESF {u['bairro']} {u['cnes'][-3:]}-{j:02d}",
                **u.to_dict(),
                "origem": "cnes",                              # unidade real; a equipe em si é sintética
            })
    colunas = ["ine", "nome_equipe", "cnes", "nome_unidade", "distrito_sanitario", "bairro", "latitude", "longitude", "coordenada_origem", "origem"]
    return pd.DataFrame(linhas)[colunas]


# ---------------------------------------------------------------------------
# 2. População [real]: proporções do Censo 2022 (IBGE) para o Recife
# ---------------------------------------------------------------------------

def distribuicao_idade():
    dados = json.load(open(RAW / "ibge" / "idade_recife_2022.json"))[1:]
    pop = np.zeros(101)
    for r in dados:
        m = re.fullmatch(r"(\d+) anos?", r["D5N"])
        if m:
            pop[int(m.group(1))] = int(r["V"])
        elif r["D5N"] == "Menos de 1 ano":
            pop[0] = int(r["V"])
        elif r["D5N"].startswith("100 anos ou mais"):
            pop[100] = int(r["V"])
    return pop / pop.sum()


def taxa_deficiencia_por_idade():
    """% de pessoas com deficiência por faixa de idade no Recife (Censo 2022, tabela 10131)."""
    dados = json.load(open(RAW / "ibge" / "deficiencia_idade_recife_2022.json"))[0]["resultados"]
    faixas = {}
    for r in dados:
        grupo, existencia = (list(c["categoria"].values())[0] for c in r["classificacoes"])
        faixas.setdefault(grupo, {})[existencia] = int(r["series"][0]["serie"]["2022"])
    taxa = np.zeros(101)
    for grupo, v in faixas.items():
        m = re.fullmatch(r"(\d+) a (\d+) anos", grupo)
        if m and int(m.group(2)) - int(m.group(1)) == 4:          # só as faixas de 5 anos
            a, b = int(m.group(1)), int(m.group(2))
            taxa[a:b + 1] = v["Pessoa com deficiência"] / v["Total"]
    v = faixas["100 anos ou mais"]
    taxa[100] = v["Pessoa com deficiência"] / v["Total"]
    return taxa   # 0 e 1 ano ficam com taxa zero (o Censo só pergunta a partir de 2 anos)


RACA = ["branca", "preta", "parda", "amarela", "indigena"]
PROP_RACA = np.array([578413, 182546, 722555, 2703, 2656]) / 1488920   # [real] Censo 2022, tabela 9605

# Efeito do distrito sobre a proporção de pessoas negras (pretas + pardas).
# [hipótese] DS 6 (Boa Viagem) e DS 3 (zona norte "nobre") mais brancos; DS 2, 7 e 8 (morros e periferia) mais negros.
EFEITO_DS_NEGROS = {1: 0.0, 2: 0.35, 3: -0.45, 4: 0.0, 5: 0.25, 6: -0.55, 7: 0.40, 8: 0.35}

# Tipos entre pessoas com deficiência, Recife (Censo 2022, tabela 10127). Uma pessoa pode ter mais de um.
TIPOS_DEFICIENCIA = {
    "visual": 71402 / 122531,
    "fisica": 55000 / 122531,       # [aprox.] união de "andar/subir degraus" (45.714) e "pegar objetos" (23.859), com sobreposição
    "auditiva": 20525 / 122531,
    "intelectual": 23642 / 122531,  # "comunicar-se ou cuidados pessoais por limitação nas funções mentais"
}

# Orientação sexual: [real] PNS 2019 (IBGE): 1,2% homossexuais, 0,7% bissexuais, 0,1% outra orientação
OS_VALORES = ["heterossexual", "homossexual", "bissexual", "assexual", "pansexual", "outra"]
OS_PROBS = np.array([0.979, 0.012, 0.007, 0.0008, 0.0008, 0.0004])

# Identidade de gênero: [real] Spizzirri et al. (2021, Scientific Reports): 0,69% trans e 1,19% não binários
# [hipótese] divisão entre mulheres trans, travestis e homens trans
IG_TRANS = {"mulher_trans": 0.0028, "travesti": 0.0014, "homem_trans": 0.0027, "nao_binario": 0.0119}


def gerar_populacao(equipes):
    p_idade = distribuicao_idade()
    tx_def = taxa_deficiencia_por_idade()

    # [hipótese] 2.000 a 3.500 pessoas por equipe (PNAB 2017), escaladas por ESCALA
    tamanhos = np.clip(rng.normal(2900, 450, len(equipes)), 2000, 3800) * ESCALA
    tamanhos = tamanhos.astype(int)
    n = tamanhos.sum()

    ine = np.repeat(equipes["ine"].values, tamanhos)
    ds = np.repeat(equipes["distrito_sanitario"].values, tamanhos)
    cnes = np.repeat(equipes["cnes"].values, tamanhos)

    idade = rng.choice(101, size=n, p=p_idade)
    sexo = np.where(rng.random(n) < 0.535, "F", "M")   # [aprox.] Recife tem ~53,5% de mulheres

    # Raça/cor: proporção do Recife deslocada pelo distrito e por um ruído da unidade (bairros diferentes)
    ruido_unidade = {c: rng.normal(0, 0.25) for c in equipes["cnes"].unique()}
    desloc = np.array([EFEITO_DS_NEGROS[d] for d in ds]) + np.array([ruido_unidade[c] for c in cnes])
    p_negro = sigmoide(logit(PROP_RACA[1] + PROP_RACA[2]) + desloc)
    u = rng.random(n)
    parte_preta = PROP_RACA[1] / (PROP_RACA[1] + PROP_RACA[2])
    outros = PROP_RACA[3] + PROP_RACA[4]
    raca = np.where(u < outros / 2, "amarela",
           np.where(u < outros, "indigena",
           np.where(u < outros + (1 - outros) * p_negro * parte_preta, "preta",
           np.where(u < outros + (1 - outros) * p_negro, "parda", "branca"))))

    tem_def = rng.random(n) < tx_def[idade]
    tipos = []
    for tem in tem_def:
        if not tem:
            tipos.append("")
            continue
        escolhidos = [t for t, p in TIPOS_DEFICIENCIA.items() if rng.random() < p]
        if not escolhidos:
            escolhidos = [rng.choice(list(TIPOS_DEFICIENCIA), p=np.array(list(TIPOS_DEFICIENCIA.values())) / sum(TIPOS_DEFICIENCIA.values()))]
        tipos.append(";".join(escolhidos))

    orient = rng.choice(OS_VALORES, size=n, p=OS_PROBS)
    orient = np.where(orient == "homossexual", np.where(sexo == "F", "lesbica", "gay"), orient)

    u = rng.random(n)
    ig = np.where(sexo == "F", "mulher_cis", "homem_cis").astype(object)
    acumulado = 0.0
    for valor, p in IG_TRANS.items():
        ig[(u >= acumulado) & (u < acumulado + p)] = valor
        acumulado += p
    # Pessoas trans e travestis registradas com o sexo de nascimento
    ig = np.where((ig == "mulher_trans") | (ig == "travesti"), np.where(sexo == "M", ig, "mulher_cis"), ig)
    ig = np.where(ig == "homem_trans", np.where(sexo == "F", ig, "homem_cis"), ig)

    return pd.DataFrame({
        "id_cidadao": [f"c{i:07d}" for i in range(1, n + 1)],
        "ine": ine,
        "idade_inicio": idade,
        "sexo": sexo,
        "raca_cor": raca,
        "tem_deficiencia": np.where(tem_def, "sim", "nao"),
        "tipo_deficiencia": tipos,
        "orientacao_sexual": orient,
        "identidade_genero": ig,
    })


# ---------------------------------------------------------------------------
# 3. Comportamento das equipes [hipótese]
# ---------------------------------------------------------------------------

def comportamento_equipes(equipes):
    """Cada equipe tem um jeito próprio de preencher o cadastro, que muda devagar ao longo do tempo.

    Pergunta orientação sexual/identidade de gênero (em escala logit):
      nivel_t = media_equipe + tendencia * t + 0,6 * (desvio do período anterior) + ruído
    A média é calibrada para que ~38% das pessoas informem orientação sexual (0,58 perguntam x 0,65 aceitam),
    que é o número mostrado pela cliente em 01/09.
    """
    n, T = len(equipes), len(PERIODOS)
    efeito_ds = {d: rng.normal(0, 0.3) for d in range(1, 9)}
    media = logit(0.58) + rng.normal(0, 0.9, n) + equipes["distrito_sanitario"].map(efeito_ds).values
    tendencia = rng.normal(0, 0.15, n)

    nivel = np.zeros((n, T))
    desvio = rng.normal(0, 0.45, n)
    for t in range(T):
        if t > 0:
            desvio = 0.6 * desvio + rng.normal(0, 0.45, n)
        nivel[:, t] = media + tendencia * t + desvio

    # Raça/cor: campo obrigatório, então o problema é valor errado (inconsistência)
    erro_raca = rng.beta(1.5, 25, n)
    anomala = rng.random(n) < 0.05                     # ~5% das equipes com erro sistemático
    erro_raca[anomala] = rng.uniform(0.3, 0.5, anomala.sum())
    valor_anomalo = np.where(rng.random(n) < 0.8, "branca", "amarela")   # os dois exemplos da cliente
    inicio_anomalia = np.where(anomala, rng.integers(0, T, n), T)

    verdade = pd.DataFrame({
        "ine": equipes["ine"],
        "media_logit_pergunta": media,
        "tendencia": tendencia,
        "erro_raca": erro_raca,
        "anomala_raca": anomala,
        "valor_anomalo": np.where(anomala, valor_anomalo, ""),
        "periodo_inicio_anomalia": np.where(anomala, inicio_anomalia, -1),
        "vazio_raca": rng.beta(1, 60, n),
        "vazio_deficiencia": rng.beta(1, 40, n),
        "sensibilidade_deficiencia": rng.beta(9, 1, n),
    })
    for t in range(T):
        verdade[f"p_pergunta_t{t}"] = sigmoide(nivel[:, t])
    return verdade


# ---------------------------------------------------------------------------
# 4. Fichas: o que a equipe registrou, período a período
# ---------------------------------------------------------------------------

P_FICHA = 0.30        # [hipótese] chance de uma pessoa ativa ter ficha nova/atualizada no quadrimestre
P_MUDOU = 0.025       # [hipótese] saída por mudança de território, por quadrimestre
P_OBITO = 0.0025      # [hipótese]
P_ACEITA_OS = 0.65    # [hipótese] quando perguntada, a pessoa aceita informar orientação sexual
P_ACEITA_IG = 0.72    # [hipótese]
P_NOME_SOCIAL = 0.6   # [hipótese] pessoa trans/não binária com nome social registrado, se a equipe pergunta


def registrar(pop, comp, t, data_ficha, tipo_ficha, situacao):
    """Aplica o comportamento da equipe no período t às pessoas de `pop` e devolve as fichas."""
    n = len(pop)
    c = comp.set_index("ine").loc[pop["ine"]].reset_index()
    anos = (data_ficha - INICIO).dt.days.values / 365.25
    idade = np.minimum(pop["idade_inicio"].values + anos.astype(int), 110)
    adulto = idade > 10    # regra de gestão: 0 a 10 anos fora de orientação sexual e identidade de gênero

    p_perg = c[f"p_pergunta_t{t}"].values
    perguntou_os = adulto & (rng.random(n) < p_perg)
    perguntou_ig = adulto & (rng.random(n) < np.clip(p_perg + rng.normal(0, 0.05, n), 0, 1))
    aceitou_os = perguntou_os & (rng.random(n) < P_ACEITA_OS)
    aceitou_ig = perguntou_ig & (rng.random(n) < P_ACEITA_IG)

    raca = pop["raca_cor"].values.copy()
    erro_ativo = (c["erro_raca"].values > 0) & (rng.random(n) < c["erro_raca"].values)
    anomalia_ativa = c["anomala_raca"].values & (t >= c["periodo_inicio_anomalia"].values)
    raca = np.where(erro_ativo & anomalia_ativa, c["valor_anomalo"].values, raca)
    erro_comum = erro_ativo & ~anomalia_ativa      # erro comum: vizinho próximo na escala (preta <-> parda <-> branca)
    vizinho = np.where(raca == "parda", np.where(rng.random(n) < 0.5, "branca", "preta"), "parda")
    raca = np.where(erro_comum, vizinho, raca)
    raca = np.where(rng.random(n) < c["vazio_raca"].values, "", raca)

    tem_def = pop["tem_deficiencia"].values
    detectou = (tem_def == "nao") | (rng.random(n) < c["sensibilidade_deficiencia"].values)
    tem_def_reg = np.where(detectou, tem_def, "nao")
    vazio_def = rng.random(n) < c["vazio_deficiencia"].values
    tem_def_reg = np.where(vazio_def, "", tem_def_reg)
    tipo_reg = np.where(tem_def_reg == "sim", pop["tipo_deficiencia"].values, "")

    ig_verdade = pop["identidade_genero"].values
    trans = ~np.isin(ig_verdade, ["mulher_cis", "homem_cis"])
    nome_social = trans & perguntou_ig & (rng.random(n) < P_NOME_SOCIAL)

    return pd.DataFrame({
        "id_cidadao": pop["id_cidadao"].values,
        "ine": pop["ine"].values,
        "data_ficha": data_ficha.values,
        "tipo_ficha": tipo_ficha,
        "situacao": situacao,
        "idade": idade,
        "sexo": pop["sexo"].values,
        "nome_social": nome_social,
        "raca_cor": raca,
        "tem_deficiencia": tem_def_reg,
        "tipo_deficiencia": tipo_reg,
        "deseja_informar_os": np.where(aceitou_os, "sim", np.where(perguntou_os, "nao", "")),
        "orientacao_sexual": np.where(aceitou_os, pop["orientacao_sexual"].values, ""),
        "deseja_informar_ig": np.where(aceitou_ig, "sim", np.where(perguntou_ig, "nao", "")),
        "identidade_genero": np.where(aceitou_ig, ig_verdade, ""),
    })


def datas_no_periodo(periodo, n):
    inicio = periodo.start_time
    fim = (periodo + 4).start_time
    dias = rng.integers(0, (fim - inicio).days, n)
    return pd.Series(inicio + pd.to_timedelta(dias, unit="D"))


def gerar_fichas(pop, comp):
    ativos = pop.copy()
    proximo_id = len(pop) + 1
    lotes = []
    chegaram = []   # novos moradores, guardados para o gabarito da população

    for t, periodo in enumerate(PERIODOS):
        # Saídas do território (a última ficha registra a saída)
        u = rng.random(len(ativos))
        saiu = u < P_MUDOU + P_OBITO

        # Quem tem ficha neste período: sorteados entre os ativos + todos os que saíram
        tem_ficha = (rng.random(len(ativos)) < P_FICHA) | saiu
        grupo = ativos[tem_ficha]
        situacao = np.where(saiu[tem_ficha], np.where(u[tem_ficha] < P_OBITO, "obito", "mudou_se"), "ativo")
        # Quem já está no território foi cadastrado antes (em 2024 ou antes dele): toda ficha nova é atualização.
        # Cadastro "novo" é só de quem chega ao território (ver reposição abaixo).
        lotes.append(registrar(grupo.reset_index(drop=True), comp, t, datas_no_periodo(periodo, len(grupo)), "atualizacao", situacao))

        # Novos moradores repõem quem saiu, na mesma equipe (população estável)
        saidos = ativos[saiu]
        ativos = ativos[~saiu]
        if len(saidos):
            novos = gerar_populacao_reposicao(saidos, proximo_id)
            proximo_id += len(novos)
            chegaram.append(novos)
            lotes.append(registrar(novos.reset_index(drop=True), comp, t, datas_no_periodo(periodo, len(novos)), "novo", "ativo"))
            ativos = pd.concat([ativos, novos], ignore_index=True)

    fichas = pd.concat(lotes, ignore_index=True).sort_values(["data_ficha", "ine"]).reset_index(drop=True)
    fichas.insert(0, "id_ficha", np.arange(1, len(fichas) + 1))
    return fichas, pd.concat([pop, *chegaram], ignore_index=True)


def gerar_populacao_reposicao(saidos, proximo_id):
    """Novos moradores com o mesmo perfil de quem saiu (simplificação: a vizinhança não muda de perfil)."""
    novos = saidos.sample(frac=1, random_state=int(rng.integers(1e9))).reset_index(drop=True)
    novos["id_cidadao"] = [f"c{i:07d}" for i in range(proximo_id, proximo_id + len(novos))]
    return novos


# ---------------------------------------------------------------------------

def main():
    unidades = carregar_unidades()
    equipes = criar_equipes(unidades)
    populacao = gerar_populacao(equipes)
    comportamento = comportamento_equipes(equipes)
    fichas, populacao = gerar_fichas(populacao, comportamento)

    equipes.to_csv(RAW / "territorio_equipes.csv", index=False)
    fichas.to_parquet(RAW / "fichas_cadastro.parquet", index=False)
    comportamento.to_parquet(RAW / "_verdade_equipes.parquet", index=False)
    populacao.to_parquet(RAW / "_verdade_populacao.parquet", index=False)

    print(f"Unidades (USF): {len(unidades)} · Equipes: {len(equipes)} · Distritos: {equipes['distrito_sanitario'].nunique()}")
    print(f"Pessoas simuladas: {len(populacao):,} (escala {ESCALA}) · Fichas: {len(fichas):,}")
    print(f"Períodos: {PERIODOS[0]} a {(PERIODOS[-1] + 3)}")


if __name__ == "__main__":
    main()
