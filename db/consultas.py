"""
Consultas SQL do Painel de Equidade (Banco de Dados · Etapa 03).

Fonte única do SQL: a interface (app/paginas/banco_de_dados.py) executa daqui, e
db/gerar_consultas_sql.py gera o consultas.sql da entrega com valores de exemplo.
Parâmetros no formato do psycopg: %(nome)s.
"""

# Junção do território, repetida nas consultas: ficha/indicador -> equipe -> unidade -> bairro (distrito)
TERRITORIO = """
    JOIN equipe        e ON e.ine = {t}.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro"""

CONSULTAS = {
    "ranking": {
        "titulo": "1 · Ranking das equipes mais críticas do distrito",
        "pergunta": "Quais equipes do distrito têm o pior registro dos marcadores de equidade no quadrimestre? "
                    "Pedido central da Secretaria, para decidir onde fazer as oficinas.",
        "tecnicas": "JOIN de 5 tabelas · CTE · funções de janela (RANK, COUNT e AVG com PARTITION BY)",
        "params": ["ano", "numero", "distrito"],
        "sql": """
WITH indicadores AS (
    SELECT b.nr_distrito,
           e.nome  AS equipe,
           u.nome  AS unidade,
           i.indice_completude,
           i.critica,
           i.risco_previsto,
           RANK()  OVER (PARTITION BY b.nr_distrito ORDER BY i.indice_completude) AS posicao,
           COUNT(*) OVER (PARTITION BY b.nr_distrito)                             AS equipes_no_distrito,
           AVG(i.indice_completude) OVER (PARTITION BY b.nr_distrito)             AS media_distrito
    FROM indicador_equipe i
    JOIN quadrimestre q ON q.id_quadrimestre = i.id_quadrimestre""" + TERRITORIO.format(t="i") + """
    WHERE q.ano = %(ano)s AND q.numero = %(numero)s
)
SELECT posicao || 'ª de ' || equipes_no_distrito          AS posicao,
       equipe,
       unidade,
       indice_completude,
       ROUND(indice_completude - media_distrito, 1)        AS diferenca_media_distrito,
       critica,
       risco_previsto
FROM indicadores
WHERE nr_distrito = %(distrito)s
ORDER BY indicadores.posicao
LIMIT 15""",
    },
    "estados": {
        "titulo": "2 · Estado do registro de cada marcador, por distrito",
        "pergunta": "Em cada distrito, que % das fichas do quadrimestre tem o marcador preenchido, recusado pela pessoa "
                    "ou N/I (não informado pela equipe)? Gráfico de barras do painel.",
        "tecnicas": "JOIN com faixa de datas (BETWEEN) · CROSS JOIN LATERAL (VALUES) para transformar 4 colunas em linhas · "
                    "CASE · janela sobre agregado (SUM(COUNT(*)) OVER)",
        "params": ["ano", "numero"],
        "sql": """
SELECT b.nr_distrito AS distrito,
       m.marcador,
       m.estado,
       COUNT(*) AS fichas,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY b.nr_distrito, m.marcador), 1) AS pct
FROM ficha_cadastro f
JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim""" + TERRITORIO.format(t="f") + """
CROSS JOIN LATERAL (VALUES
    ('Orientação sexual',    CASE WHEN f.idade <= 10 THEN NULL          -- crianças fora (regra da Secretaria)
                                  WHEN f.deseja_informar_os = 'sim' THEN 'Preenchido'
                                  WHEN f.deseja_informar_os = 'nao' THEN 'Recusou'
                                  ELSE 'N/I' END),
    ('Identidade de gênero', CASE WHEN f.idade <= 10 THEN NULL
                                  WHEN f.deseja_informar_ig = 'sim' THEN 'Preenchido'
                                  WHEN f.deseja_informar_ig = 'nao' THEN 'Recusou'
                                  ELSE 'N/I' END),
    ('Raça/cor',             CASE WHEN f.raca_cor IS NULL THEN 'N/I' ELSE 'Preenchido' END),
    ('Deficiência',          CASE WHEN f.tem_deficiencia IS NULL THEN 'N/I' ELSE 'Preenchido' END)
) AS m (marcador, estado)
WHERE q.ano = %(ano)s AND q.numero = %(numero)s
  AND m.estado IS NOT NULL
GROUP BY b.nr_distrito, m.marcador, m.estado
ORDER BY distrito, m.marcador, m.estado""",
    },
    "evolucao": {
        "titulo": "3 · Evolução do índice de completude por distrito",
        "pergunta": "O registro está melhorando? Mediana do índice das equipes de cada distrito, quadrimestre a "
                    "quadrimestre, e quantas equipes ficaram críticas. Gráfico de linhas do painel.",
        "tecnicas": "JOIN de 5 tabelas · agregação ordenada (PERCENTILE_CONT ... WITHIN GROUP) · COUNT com FILTER · GROUP BY",
        "params": [],
        "sql": """
SELECT q.ano || '.' || q.numero AS quadrimestre,
       b.nr_distrito            AS distrito,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY i.indice_completude)::numeric, 1) AS indice_mediano,
       COUNT(*) FILTER (WHERE i.critica)                                                  AS equipes_criticas,
       COUNT(*)                                                                           AS equipes
FROM indicador_equipe i
JOIN quadrimestre q ON q.id_quadrimestre = i.id_quadrimestre""" + TERRITORIO.format(t="i") + """
GROUP BY q.ano, q.numero, b.nr_distrito
ORDER BY q.ano, q.numero, distrito""",
    },
    "concentracao": {
        "titulo": "4 · Onde está a população: bairros com mais pessoas do grupo",
        "pergunta": "Em quais bairros se concentram as pessoas do grupo escolhido, entre os cidadãos ativos? Usa a ficha "
                    "mais recente de cada cidadão. Apoia decisões como descentralizar a hormonização ou onde ter Libras.",
        "tecnicas": "DISTINCT ON (ficha mais recente por cidadão) · CTEs encadeadas · CASE parametrizado · "
                    "JOIN com o Censo 2022 (população do bairro)",
        "params": ["grupo"],
        "sql": """
WITH ultima_ficha AS (
    SELECT DISTINCT ON (f.cod_cidadao) f.*
    FROM ficha_cadastro f
    ORDER BY f.cod_cidadao, f.data_envio DESC
),
ativos AS (
    SELECT a.*,
           CASE %(grupo)s
               WHEN 'negras'      THEN a.raca_cor IN ('preta', 'parda')
               WHEN 'trans'       THEN a.identidade_genero IN ('mulher_trans', 'homem_trans', 'travesti')
               WHEN 'nao_binarias' THEN a.identidade_genero = 'nao_binario'
               WHEN 'lgb'         THEN a.orientacao_sexual IN ('gay', 'lesbica', 'bissexual')
               WHEN 'deficiencia' THEN a.tem_deficiencia = 'sim'
           END AS do_grupo
    FROM ultima_ficha a
    WHERE a.situacao = 'ativo'
)
SELECT b.nome                                    AS bairro,
       b.nr_distrito                             AS distrito,
       b.populacao_2022,
       COUNT(*)                                  AS cadastrados_ativos,
       COUNT(*) FILTER (WHERE a.do_grupo)        AS pessoas_do_grupo,
       ROUND(100.0 * COUNT(*) FILTER (WHERE a.do_grupo) / COUNT(*), 2) AS pct_dos_cadastrados
FROM ativos a""" + TERRITORIO.format(t="a") + """
GROUP BY b.id_bairro, b.nome, b.nr_distrito, b.populacao_2022
ORDER BY pessoas_do_grupo DESC
LIMIT 15""",
    },
    "pioraram": {
        "titulo": "5 · Equipes que entraram na lista crítica neste quadrimestre",
        "pergunta": "Quais equipes não eram críticas no quadrimestre anterior e passaram a ser agora, e quanto o índice caiu? "
                    "É o grupo que o modelo de ML tenta antecipar.",
        "tecnicas": "Função de janela LAG com cláusula WINDOW · CTE · JOIN de 5 tabelas · filtro sobre valor da linha anterior",
        "params": ["ano", "numero"],
        "sql": """
WITH historico AS (
    SELECT i.ine, q.ano, q.numero, i.indice_completude, i.critica,
           LAG(i.indice_completude) OVER w AS indice_anterior,
           LAG(i.critica)           OVER w AS critica_anterior
    FROM indicador_equipe i
    JOIN quadrimestre q ON q.id_quadrimestre = i.id_quadrimestre
    WINDOW w AS (PARTITION BY i.ine ORDER BY q.ano, q.numero)
)
SELECT b.nr_distrito                                  AS distrito,
       e.nome                                         AS equipe,
       u.nome                                         AS unidade,
       h.indice_anterior,
       h.indice_completude                            AS indice_atual,
       h.indice_completude - h.indice_anterior        AS variacao
FROM historico h""" + TERRITORIO.format(t="h") + """
WHERE h.ano = %(ano)s AND h.numero = %(numero)s
  AND h.critica AND NOT h.critica_anterior
ORDER BY variacao""",
    },
    "raca": {
        "titulo": "6 · Possível erro sistemático de raça/cor",
        "pergunta": "Quais equipes registram 'branca' muito acima da média do próprio distrito? Exemplo trazido pela "
                    "cliente: equipe que marca quase todo mundo como branco numa área majoritariamente negra.",
        "tecnicas": "Duas CTEs (por equipe e por distrito) ligadas por JOIN · média ponderada · COUNT com FILTER · "
                    "filtro sobre valor calculado",
        "params": ["ano", "numero", "limite_pp"],
        "sql": """
WITH por_equipe AS (
    SELECT e.ine, e.nome AS equipe, b.nr_distrito,
           COUNT(f.raca_cor)                                                    AS fichas_com_raca,
           100.0 * COUNT(*) FILTER (WHERE f.raca_cor = 'branca') / COUNT(f.raca_cor) AS pct_branca
    FROM ficha_cadastro f
    JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim""" + TERRITORIO.format(t="f") + """
    WHERE q.ano = %(ano)s AND q.numero = %(numero)s
    GROUP BY e.ine, e.nome, b.nr_distrito
    HAVING COUNT(f.raca_cor) >= 30
),
por_distrito AS (
    SELECT nr_distrito, SUM(pct_branca * fichas_com_raca) / SUM(fichas_com_raca) AS pct_branca_distrito
    FROM por_equipe
    GROUP BY nr_distrito
)
SELECT pe.nr_distrito                                        AS distrito,
       pe.equipe,
       pe.fichas_com_raca,
       ROUND(pe.pct_branca, 1)                               AS pct_branca_equipe,
       ROUND(pd.pct_branca_distrito, 1)                      AS pct_branca_distrito,
       ROUND(pe.pct_branca - pd.pct_branca_distrito, 1)      AS diferenca_pp
FROM por_equipe pe
JOIN por_distrito pd ON pd.nr_distrito = pe.nr_distrito
WHERE pe.pct_branca - pd.pct_branca_distrito > %(limite_pp)s
ORDER BY diferenca_pp DESC""",
    },
    "esperado_registrado": {
        "titulo": "7 · Esperado × registrado: orientação sexual por distrito",
        "pergunta": "Compara a base proxy da Inferência Estatística (o que a população responderia) com o que as equipes "
                    "registram nas fichas de adultos. Recusa muito acima da esperada e N/I alto indicam que a pergunta "
                    "não está sendo feita.",
        "tecnicas": "Duas CTEs de fontes diferentes (respostas_sinteticas × ficha_cadastro) ligadas por JOIN · "
                    "COUNT com FILTER · NULLIF para evitar divisão por zero",
        "params": ["ano", "numero"],
        "sql": """
WITH esperado AS (
    SELECT nr_distrito,
           100.0 * COUNT(*) FILTER (WHERE informa_orientacao_sexual = 'Não') / COUNT(*)  AS recusa_esperada,
           100.0 * COUNT(*) FILTER (WHERE orientacao_sexual IN ('Gay', 'Lésbica', 'Bissexual'))
                 / NULLIF(COUNT(*) FILTER (WHERE informa_orientacao_sexual = 'Sim'), 0)  AS lgb_esperado
    FROM respostas_sinteticas
    GROUP BY nr_distrito
),
registrado AS (
    SELECT b.nr_distrito,
           COUNT(*)                                                                      AS fichas_adultos,
           100.0 * COUNT(*) FILTER (WHERE f.deseja_informar_os = 'sim') / COUNT(*)       AS informou,
           100.0 * COUNT(*) FILTER (WHERE f.deseja_informar_os = 'nao') / COUNT(*)       AS recusou,
           100.0 * COUNT(*) FILTER (WHERE f.deseja_informar_os IS NULL) / COUNT(*)       AS nao_informado,
           100.0 * COUNT(*) FILTER (WHERE f.orientacao_sexual IN ('gay', 'lesbica', 'bissexual'))
                 / NULLIF(COUNT(*) FILTER (WHERE f.deseja_informar_os = 'sim'), 0)      AS lgb_registrado
    FROM ficha_cadastro f
    JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim""" + TERRITORIO.format(t="f") + """
    WHERE q.ano = %(ano)s AND q.numero = %(numero)s AND f.idade >= 18
    GROUP BY b.nr_distrito
)
SELECT r.nr_distrito                     AS distrito,
       r.fichas_adultos,
       ROUND(r.informou, 1)              AS pct_informou,
       ROUND(r.recusou, 1)               AS pct_recusou,
       ROUND(e.recusa_esperada, 1)       AS pct_recusa_esperada,
       ROUND(r.nao_informado, 1)         AS pct_nao_informado,
       ROUND(r.lgb_registrado, 2)        AS pct_lgb_registrado,
       ROUND(e.lgb_esperado, 2)          AS pct_lgb_esperado
FROM registrado r
JOIN esperado e ON e.nr_distrito = r.nr_distrito
ORDER BY distrito""",
    },
}

# Valores de exemplo (consultas.sql da entrega e valores iniciais da interface)
EXEMPLO = {"ano": 2026, "numero": 2, "distrito": 8, "grupo": "trans", "limite_pp": 15}

GRUPOS = {
    "trans": "Pessoas trans e travestis",
    "nao_binarias": "Pessoas não binárias",
    "lgb": "Lésbicas, gays e bissexuais",
    "negras": "Pessoas negras (pretas e pardas)",
    "deficiencia": "Pessoas com deficiência",
}
