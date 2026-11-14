# pmo-camara-dados

Coleta automática de **dados públicos** da Câmara Municipal de Belo Horizonte (CMBH): os projetos
de lei de autoria do Executivo em tramitação e as operações de crédito desde 2021. Alimenta o
monitor de projetos de lei da Secretaria Municipal de Governo (SMGO) no app Projetos
Transformadores da PBH.

- **Saída:** [`dados/projetos-de-lei.json`](dados/projetos-de-lei.json), lido pelo app.
- **Quando:** GitHub Actions nos dias 1, 2, 15 e 16 de cada mês (6h de Brasília), ou manualmente
  ("Run workflow").
- **Como:** HTTP simples na página de pesquisa de proposições da CMBH (sem navegador), com uma
  requisição a cada 2 s e repetição com espera crescente. Ver `coletor/cmbh.py`.
- **Proteção:** uma coleta suspeita (vazia, com menos da metade dos projetos da anterior, ou com
  muitas fichas ilegíveis) **não é publicada**: o job falha e o JSON anterior fica. Ver
  `coletor/validar.py`.
- **Resumo por IA (opcional):** com o segredo `GEMINI_API_KEY`, gera até 3 frases sobre o que mudou
  em cada projeto. Sem a chave, a coleta segue sem resumo.

Este repositório não tem nenhuma credencial do app: quem grava no app é a pessoa logada, pela
função `importarCamara`, que lê este JSON.

## Rodar localmente

```bash
pip install -r requirements.txt
python -m pytest -q testes
python coletar.py --sem-ia
```

Desenho completo: `docs/smgo-projetos-de-lei/` no repositório do app.
