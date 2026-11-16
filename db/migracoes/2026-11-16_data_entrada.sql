-- =====================================================================
-- Migração 16/11/2026 · ficha_cadastro.data_entrada
-- Para bancos criados antes desta data (o schema.sql já cria a coluna).
--
-- As fichas que já estavam no banco recebem a data da carga inicial
-- (03/11/2026 16:42:29, quando db/carregar_banco.py criou as tabelas;
-- conferido pela data de criação dos arquivos das tabelas no disco).
-- As próximas recebem now(), a hora em que entrarem.
-- ADD COLUMN com valor constante não reescreve a tabela: é instantâneo.
-- =====================================================================
BEGIN;
ALTER TABLE ficha_cadastro
    ADD COLUMN IF NOT EXISTS data_entrada TIMESTAMPTZ NOT NULL DEFAULT '2026-11-03 16:42:29-03';
ALTER TABLE ficha_cadastro ALTER COLUMN data_entrada SET DEFAULT now();
COMMIT;

-- vw_ficha_marcadores passa a mostrar data_entrada (coluna nova no fim)
CREATE OR REPLACE VIEW vw_ficha_marcadores AS
SELECT f.id_ficha,
       f.cod_cidadao,
       f.data_envio,
       q.ano,
       q.numero,
       q.ano || '.' || q.numero  AS quadrimestre,
       f.tipo_ficha,
       f.situacao,
       f.idade,
       f.sexo,
       f.raca_cor,
       f.orientacao_sexual,
       f.identidade_genero,
       f.tem_deficiencia,
       CASE WHEN f.idade <= 10                   THEN NULL
            WHEN f.deseja_informar_os = 'sim'    THEN 'Preenchido'
            WHEN f.deseja_informar_os = 'nao'    THEN 'Recusou'
            ELSE 'N/I' END                       AS estado_orientacao,
       CASE WHEN f.idade <= 10                   THEN NULL
            WHEN f.deseja_informar_ig = 'sim'    THEN 'Preenchido'
            WHEN f.deseja_informar_ig = 'nao'    THEN 'Recusou'
            ELSE 'N/I' END                       AS estado_identidade,
       CASE WHEN f.raca_cor IS NULL              THEN 'N/I'
            ELSE 'Preenchido' END                AS estado_raca,
       CASE WHEN f.tem_deficiencia IS NULL       THEN 'N/I'
            ELSE 'Preenchido' END                AS estado_deficiencia,
       f.ine,
       e.nome                    AS equipe,
       u.cnes,
       u.nome                    AS unidade,
       b.nome                    AS bairro,
       b.nr_distrito             AS distrito,
       f.data_entrada
FROM ficha_cadastro f
JOIN quadrimestre  q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
JOIN equipe        e ON e.ine = f.ine
JOIN unidade_saude u ON u.cnes = e.cnes
JOIN bairro        b ON b.id_bairro = u.id_bairro;
