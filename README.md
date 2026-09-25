# Painel de Equidade em Saúde do Recife

Pipeline de dados e Machine Learning para transformar os cadastros do PEC/e-SUS APS em indicadores de equidade (raça/cor, deficiência, orientação sexual e identidade de gênero) e prever quais Equipes de Saúde da Família vão precisar de apoio para qualificar o registro.

Projeto 3 (Dados) + Machine Learning I · CESAR School · 2026.2 · Cliente: Secretaria de Saúde do Recife

> **Base de dados sintética.** A Secretaria não liberou os dados reais do PEC. O projeto usa uma base gerada por código, no formato do PEC (ver `docs/contrato_dados.md`). Quando a extração real existir nesse formato, o pipeline roda sem mudanças.

## Estrutura

```
docs/        contrato de dados e arquitetura
src/         código do pipeline
notebooks/   análise exploratória e experimentos
app/         protótipo navegável
data/        dados gerados (fora do git)
```

*(Instruções de execução entram conforme cada etapa for construída.)*
