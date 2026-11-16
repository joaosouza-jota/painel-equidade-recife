-- =====================================================================
-- Painel de Equidade · camada do painel no banco (pipeline automatizada)
-- SGBD: PostgreSQL · rodar depois de schema.sql
--
-- O painel lê só AGREGADOS (por equipe, USF e distrito), nunca ficha de
-- pessoa. Antes eles eram arquivos .parquet gerados por
-- src/preparar_painel.py; agora são VISÕES MATERIALIZADAS: consultas cujo
-- resultado fica guardado no banco e é recalculado por
--     REFRESH MATERIALIZED VIEW <nome>
-- a cada execução da pipeline (src/pipeline.py), por exemplo logo depois
-- de uma importação de fichas. Mesmas regras de src/indicadores.py e
-- src/preparar_painel.py (conferido contra os .parquet).
-- =====================================================================

DROP MATERIALIZED VIEW IF EXISTS mv_resumo_equipe, mv_estados_distrito, mv_populacao_usf;

-- ---------------------------------------------------------------------
-- 1 · Indicadores por equipe e quadrimestre (antigo resumo_equipes.parquet)
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_resumo_equipe AS
WITH base AS (
    SELECT f.ine,
           f.quadrimestre,
           COUNT(*)                                                                         AS n_fichas,
           COUNT(*) FILTER (WHERE f.idade > 10)                                             AS n_elegiveis,
           AVG(CASE WHEN f.estado_raca = 'Preenchido' THEN 1.0 ELSE 0 END)                  AS raca_preenchido,
           AVG(CASE WHEN f.estado_deficiencia = 'Preenchido' THEN 1.0 ELSE 0 END)           AS deficiencia_preenchido,
           AVG(CASE WHEN f.estado_orientacao = 'Preenchido' THEN 1.0 ELSE 0 END) FILTER (WHERE f.idade > 10) AS os_preenchido,
           AVG(CASE WHEN f.estado_orientacao = 'Recusou'    THEN 1.0 ELSE 0 END) FILTER (WHERE f.idade > 10) AS os_recusou,
           AVG(CASE WHEN f.estado_orientacao = 'N/I'        THEN 1.0 ELSE 0 END) FILTER (WHERE f.idade > 10) AS os_nao_perguntado,
           AVG(CASE WHEN f.estado_identidade = 'Preenchido' THEN 1.0 ELSE 0 END) FILTER (WHERE f.idade > 10) AS ig_preenchido,
           AVG(CASE WHEN f.estado_identidade = 'N/I'        THEN 1.0 ELSE 0 END) FILTER (WHERE f.idade > 10) AS ig_nao_perguntado,
           -- % de brancos e de amarelos entre as fichas com raça/cor (base da inconsistência)
           100.0 * COUNT(*) FILTER (WHERE f.raca_cor = 'branca')  / NULLIF(COUNT(f.raca_cor), 0) AS pct_branca,
           100.0 * COUNT(*) FILTER (WHERE f.raca_cor = 'amarela') / NULLIF(COUNT(f.raca_cor), 0) AS pct_amarela
    FROM vw_ficha_marcadores f
    GROUP BY f.ine, f.quadrimestre
),
territorio AS (
    SELECT e.ine, e.nome AS nome_equipe, u.cnes, u.nome AS nome_unidade, b.nome AS bairro,
           b.nr_distrito AS distrito_sanitario
    FROM equipe e
    JOIN unidade_saude u ON u.cnes = e.cnes
    JOIN bairro        b ON b.id_bairro = u.id_bairro
),
indice AS (
    SELECT b.*, t.nome_equipe, t.cnes, t.nome_unidade, t.bairro, t.distrito_sanitario,
           100 * (2 * COALESCE(b.os_preenchido, 0) + 2 * COALESCE(b.ig_preenchido, 0)
                  + b.raca_preenchido + b.deficiencia_preenchido) / 6 AS indice_completude
    FROM base b JOIN territorio t USING (ine)
),
mediana_distrito AS (
    SELECT distrito_sanitario, quadrimestre,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pct_branca)  AS med_branca,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pct_amarela) AS med_amarela
    FROM indice GROUP BY distrito_sanitario, quadrimestre
),
limite AS (
    SELECT quadrimestre, PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY indice_completude) AS limite_critico
    FROM indice GROUP BY quadrimestre
)
SELECT i.ine, i.quadrimestre, i.distrito_sanitario, i.cnes,
       i.n_fichas, i.n_elegiveis,
       i.raca_preenchido::float8, i.deficiencia_preenchido::float8,
       i.os_preenchido::float8, i.os_recusou::float8, i.os_nao_perguntado::float8,
       i.ig_preenchido::float8, i.ig_nao_perguntado::float8,
       i.indice_completude::float8,
       (i.indice_completude <= l.limite_critico)::int                                     AS critica,
       GREATEST(GREATEST(i.pct_branca - m.med_branca, i.pct_amarela - m.med_amarela), 0)::float8 AS inconsistencia_raca,
       i.nome_equipe, i.nome_unidade, i.bairro,
       CASE WHEN CUME_DIST() OVER w <= 0.25 THEN '🔴 Crítica'
            WHEN CUME_DIST() OVER w <= 0.40 THEN '🟡 Atenção'
            ELSE '🟢 OK' END                                                              AS status
FROM indice i
JOIN limite l USING (quadrimestre)
JOIN mediana_distrito m USING (distrito_sanitario, quadrimestre)
WINDOW w AS (PARTITION BY i.quadrimestre ORDER BY i.indice_completude);

CREATE UNIQUE INDEX ix_mv_resumo ON mv_resumo_equipe (ine, quadrimestre);


-- ---------------------------------------------------------------------
-- 2 · Estado do registro por distrito e marcador (antigo estados_distrito.parquet)
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_estados_distrito AS
SELECT f.quadrimestre,
       f.distrito AS distrito_sanitario,
       CASE m.estado WHEN 'Preenchido' THEN 'preenchido' WHEN 'Recusou' THEN 'recusou'
                     ELSE 'nao_perguntado' END                                            AS estado,
       (COUNT(*)::float8 / SUM(COUNT(*)) OVER (PARTITION BY f.quadrimestre, f.distrito, m.marcador))::float8 AS pct,
       m.marcador
FROM vw_ficha_marcadores f
CROSS JOIN LATERAL (VALUES ('estado_os', f.estado_orientacao), ('estado_ig', f.estado_identidade),
                           ('estado_raca', f.estado_raca), ('estado_deficiencia', f.estado_deficiencia)
) AS m (marcador, estado)
WHERE m.estado IS NOT NULL                    -- crianças ficam fora de orientação e identidade
GROUP BY f.quadrimestre, f.distrito, m.marcador, m.estado;


-- ---------------------------------------------------------------------
-- 3 · Pessoas de cada população por USF (antigo populacao_usf.parquet)
-- Ficha mais recente de cada cidadão ATÉ cada quadrimestre, só quem está ativo.
-- Uma ficha vale "até" o quadrimestre anterior à próxima ficha do mesmo cidadão (LEAD).
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_populacao_usf AS
WITH quads AS (
    SELECT DISTINCT q.ano || '.' || q.numero AS quadrimestre, q.data_fim
    FROM quadrimestre q
    WHERE EXISTS (SELECT 1 FROM ficha_cadastro f WHERE f.data_envio BETWEEN q.data_inicio AND q.data_fim)
),
fichas AS (
    SELECT f.*, LEAD(f.data_envio) OVER (PARTITION BY f.cod_cidadao ORDER BY f.data_envio, f.id_ficha) AS proxima
    FROM vw_ficha_marcadores f
),
tipos AS (
    SELECT fd.id_ficha, BOOL_OR(t.categoria = 'auditiva') AS auditiva, BOOL_OR(t.categoria = 'fisica') AS fisica
    FROM ficha_deficiencia fd JOIN tipo_deficiencia t USING (id_tipo_deficiencia)
    GROUP BY fd.id_ficha
),
atual AS (
    SELECT q.quadrimestre AS quad_ref, f.*, COALESCE(t.auditiva, FALSE) AS auditiva, COALESCE(t.fisica, FALSE) AS fisica
    FROM quads q
    JOIN fichas f ON f.data_envio <= q.data_fim AND (f.proxima IS NULL OR f.proxima > q.data_fim)
    LEFT JOIN tipos t ON t.id_ficha = f.id_ficha
    WHERE f.situacao = 'ativo'
)
SELECT a.cnes, a.distrito AS distrito_sanitario,
       COUNT(*) FILTER (WHERE g.pessoa)                                AS pessoas,
       COUNT(*) FILTER (WHERE g.estado IS NOT NULL)                    AS elegiveis,
       COUNT(*) FILTER (WHERE g.estado = 'N/I')                        AS sem_pergunta,
       a.quad_ref AS quadrimestre, g.grupo
FROM atual a
CROSS JOIN LATERAL (VALUES
    ('Pessoas negras (pretas e pardas)',                   a.raca_cor IN ('preta', 'parda'),                                   a.estado_raca),
    ('Pessoas trans e travestis',                          a.identidade_genero IN ('mulher_trans', 'travesti', 'homem_trans'), a.estado_identidade),
    ('Pessoas não binárias',                               a.identidade_genero = 'nao_binario',                                a.estado_identidade),
    ('Pessoas LGB+ (lésbicas, gays, bissexuais e outras)', a.orientacao_sexual <> 'heterossexual',                             a.estado_orientacao),
    ('Pessoas com deficiência',                            a.tem_deficiencia = 'sim',                                          a.estado_deficiencia),
    ('Pessoas com deficiência auditiva',                   a.auditiva,                                                         a.estado_deficiencia),
    ('Pessoas com deficiência física',                     a.fisica,                                                           a.estado_deficiencia)
) AS g (grupo, pessoa, estado)
GROUP BY a.quad_ref, g.grupo, a.cnes, a.distrito;

CREATE INDEX ix_mv_pop ON mv_populacao_usf (quadrimestre, grupo);


-- ---------------------------------------------------------------------
-- 4 · Registro de cada execução da pipeline
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS execucao_pipeline (
    id_execucao        SERIAL        PRIMARY KEY,
    inicio             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    fim                TIMESTAMPTZ,
    gatilho            VARCHAR(30)   NOT NULL,          -- importacao, manual, linha_de_comando
    fichas_no_banco    INTEGER,
    ultimo_quadrimestre VARCHAR(6),
    modelo             VARCHAR(40),
    f1_modelo          NUMERIC(5,3),                    -- F1 do modelo no teste temporal
    f1_persistencia    NUMERIC(5,3),                    -- F1 da baseline de persistência no mesmo teste
    equipes_em_risco   INTEGER,                         -- equipes com risco >= 0,5 no próximo quadrimestre
    situacao           VARCHAR(10)   NOT NULL DEFAULT 'rodando',
    erro               TEXT,
    CONSTRAINT ck_exec_situacao CHECK (situacao IN ('rodando', 'ok', 'erro'))
);
