-- =====================================================================
-- Painel de Equidade em Saúde do Recife
-- Banco de Dados · Etapa 03 · Entregável 2 · SQL das consultas
-- SGBD: PostgreSQL · rodar depois de schema.sql + carregar_banco.py
--
-- Os valores de exemplo (quadrimestre 2026.2, Distrito Sanitário 8...)
-- estão no lugar dos parâmetros. Na interface (página Banco de Dados do
-- app), o usuário escolhe esses valores e o mesmo SQL é executado.
-- Gerado por db/gerar_consultas_sql.py a partir de db/consultas.py.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1 · Ranking das equipes mais críticas do distrito
-- Quais equipes do distrito têm o pior registro dos marcadores de equidade no quadrimestre? Pedido central da Secretaria, para decidir onde fazer as oficinas.
-- Técnicas: JOIN de 5 tabelas · CTE · funções de janela (RANK, COUNT e AVG com PARTITION BY)
-- Parâmetros: ano = 2026, numero = 2, distrito = 8
-- ---------------------------------------------------------------------
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
    JOIN quadrimestre q ON q.id_quadrimestre = i.id_quadrimestre
    JOIN equipe        e ON e.ine = i.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
    WHERE q.ano = 2026 AND q.numero = 2
)
SELECT posicao || 'ª de ' || equipes_no_distrito          AS posicao,
       equipe,
       unidade,
       indice_completude,
       ROUND(indice_completude - media_distrito, 1)        AS diferenca_media_distrito,
       critica,
       risco_previsto
FROM indicadores
WHERE nr_distrito = 8
ORDER BY indicadores.posicao
LIMIT 15;


-- ---------------------------------------------------------------------
-- 2 · Estado do registro de cada marcador, por distrito
-- Em cada distrito, que % das fichas do quadrimestre tem o marcador preenchido, recusado pela pessoa ou N/I (não informado pela equipe)? Gráfico de barras do painel.
-- Técnicas: JOIN com faixa de datas (BETWEEN) · CROSS JOIN LATERAL (VALUES) para transformar 4 colunas em linhas · CASE · janela sobre agregado (SUM(COUNT(*)) OVER)
-- Parâmetros: ano = 2026, numero = 2
-- ---------------------------------------------------------------------
SELECT b.nr_distrito AS distrito,
       m.marcador,
       m.estado,
       COUNT(*) AS fichas,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY b.nr_distrito, m.marcador), 1) AS pct
FROM ficha_cadastro f
JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
    JOIN equipe        e ON e.ine = f.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
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
WHERE q.ano = 2026 AND q.numero = 2
  AND m.estado IS NOT NULL
GROUP BY b.nr_distrito, m.marcador, m.estado
ORDER BY distrito, m.marcador, m.estado;


-- ---------------------------------------------------------------------
-- 3 · Evolução do índice de completude por distrito
-- O registro está melhorando? Mediana do índice das equipes de cada distrito, quadrimestre a quadrimestre, e quantas equipes ficaram críticas. Gráfico de linhas do painel.
-- Técnicas: JOIN de 5 tabelas · agregação ordenada (PERCENTILE_CONT ... WITHIN GROUP) · COUNT com FILTER · GROUP BY
-- Parâmetros: nenhum
-- ---------------------------------------------------------------------
SELECT q.ano || '.' || q.numero AS quadrimestre,
       b.nr_distrito            AS distrito,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY i.indice_completude)::numeric, 1) AS indice_mediano,
       COUNT(*) FILTER (WHERE i.critica)                                                  AS equipes_criticas,
       COUNT(*)                                                                           AS equipes
FROM indicador_equipe i
JOIN quadrimestre q ON q.id_quadrimestre = i.id_quadrimestre
    JOIN equipe        e ON e.ine = i.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
GROUP BY q.ano, q.numero, b.nr_distrito
ORDER BY q.ano, q.numero, distrito;


-- ---------------------------------------------------------------------
-- 4 · Onde está a população: bairros com mais pessoas do grupo
-- Em quais bairros se concentram as pessoas do grupo escolhido, entre os cidadãos ativos? Usa a ficha mais recente de cada cidadão. Apoia decisões como descentralizar a hormonização ou onde ter Libras.
-- Técnicas: DISTINCT ON (ficha mais recente por cidadão) · CTEs encadeadas · CASE parametrizado · JOIN com o Censo 2022 (população do bairro)
-- Parâmetros: grupo = trans
-- ---------------------------------------------------------------------
WITH ultima_ficha AS (
    SELECT DISTINCT ON (f.cod_cidadao) f.*
    FROM ficha_cadastro f
    ORDER BY f.cod_cidadao, f.data_envio DESC
),
ativos AS (
    SELECT a.*,
           CASE 'trans'
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
FROM ativos a
    JOIN equipe        e ON e.ine = a.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
GROUP BY b.id_bairro, b.nome, b.nr_distrito, b.populacao_2022
ORDER BY pessoas_do_grupo DESC
LIMIT 15;


-- ---------------------------------------------------------------------
-- 5 · Equipes que entraram na lista crítica neste quadrimestre
-- Quais equipes não eram críticas no quadrimestre anterior e passaram a ser agora, e quanto o índice caiu? É o grupo que o modelo de ML tenta antecipar.
-- Técnicas: Função de janela LAG com cláusula WINDOW · CTE · JOIN de 5 tabelas · filtro sobre valor da linha anterior
-- Parâmetros: ano = 2026, numero = 2
-- ---------------------------------------------------------------------
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
FROM historico h
    JOIN equipe        e ON e.ine = h.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
WHERE h.ano = 2026 AND h.numero = 2
  AND h.critica AND NOT h.critica_anterior
ORDER BY variacao;


-- ---------------------------------------------------------------------
-- 6 · Possível erro sistemático de raça/cor
-- Quais equipes registram 'branca' muito acima da média do próprio distrito? Exemplo trazido pela cliente: equipe que marca quase todo mundo como branco numa área majoritariamente negra.
-- Técnicas: Duas CTEs (por equipe e por distrito) ligadas por JOIN · média ponderada · COUNT com FILTER · filtro sobre valor calculado
-- Parâmetros: ano = 2026, numero = 2, limite_pp = 15
-- ---------------------------------------------------------------------
WITH por_equipe AS (
    SELECT e.ine, e.nome AS equipe, b.nr_distrito,
           COUNT(f.raca_cor)                                                    AS fichas_com_raca,
           100.0 * COUNT(*) FILTER (WHERE f.raca_cor = 'branca') / COUNT(f.raca_cor) AS pct_branca
    FROM ficha_cadastro f
    JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
    JOIN equipe        e ON e.ine = f.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
    WHERE q.ano = 2026 AND q.numero = 2
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
WHERE pe.pct_branca - pd.pct_branca_distrito > 15
ORDER BY diferenca_pp DESC;


-- ---------------------------------------------------------------------
-- 7 · Esperado × registrado: orientação sexual por distrito
-- Compara a base proxy da Inferência Estatística (o que a população responderia) com o que as equipes registram nas fichas de adultos. Recusa muito acima da esperada e N/I alto indicam que a pergunta não está sendo feita.
-- Técnicas: Duas CTEs de fontes diferentes (respostas_sinteticas × ficha_cadastro) ligadas por JOIN · COUNT com FILTER · NULLIF para evitar divisão por zero
-- Parâmetros: ano = 2026, numero = 2
-- ---------------------------------------------------------------------
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
    JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
    JOIN equipe        e ON e.ine = f.ine
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
    WHERE q.ano = 2026 AND q.numero = 2 AND f.idade >= 18
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
ORDER BY distrito;
