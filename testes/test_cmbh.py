from pathlib import Path

import pytest

from coletor.cmbh import ErroColeta, ItemBusca, ler_busca, ler_ficha, montar
from coletor.validar import validar

A = Path(__file__).resolve().parent.parent / "amostras"
ler = lambda nome: (A / nome).read_text(encoding="utf-8")


def test_busca_executivo_tramitando():
    total, itens = ler_busca(ler("busca-executivo-tramitando-p1.html"))
    assert total >= 7 and len(itens) == 7
    i = itens[0]
    assert i.ano >= 2025 and i.numero > 0
    assert len(i.id_camara) == 32 and "cmbhsilint" in i.caminho
    assert i.autoria.startswith("Executivo: Mensagem")
    assert i.ementa


def test_busca_recusada_e_vazia():
    with pytest.raises(ErroColeta):
        ler_busca("Pesquisa de fonte não autorizada.")
    assert ler_busca("<h1>Resultados da pesquisa:</h1> Nenhum resultado encontrado.") == (0, [])


def test_ficha_em_tramitacao():
    f = ler_ficha(ler("ficha-pl-971-2026.html"))
    p = montar(ItemBusca(971, 2026, "x?id=abc", "abc", "", ""), f)
    assert p["chave"] == "PL 971/2026"
    assert p["mensagem"] == "31/2026"
    assert p["estado"] == "TRAMITANDO"
    assert p["situacao"] == "Primeiro turno"
    assert p["comissaoAtual"] == "Comissão de Legislação e Justiça"
    assert p["faseAtual"] == "Apreciação pela Comissão/Mesa"
    assert p["prazoComissao"] == "2026-11-25"
    assert p["quorum"].startswith("2/3")
    assert p["emendas"] == "Não há"
    assert p["ementa"].startswith("Cria o Novo Programa")
    assert p["operacaoCredito"] is False
    assert p["leiResultante"] is None
    assert p["url"].endswith("/projeto-de-lei/971/2026")
    assert p["publicadoEm"] == "2026-11-03"
    ult = p["eventos"][-1]
    assert ult["fase"] == "Apreciação pela Comissão/Mesa"
    assert ult["orgao"] == "Comissão de Legislação e Justiça"
    assert ult["documento"].startswith("Comissão de Legislação e Justiça - Designação de relatoria")
    assert ult["data"] == "2026-11-13"
    assert p["eventos"][0] == {"fase": "Autuação", "orgao": None, "documento": "Inicial", "data": "2026-11-03"}


def test_ficha_sancionada_operacao_credito():
    f = ler_ficha(ler("ficha-pl-991-2024.html"))
    p = montar(ItemBusca(991, 2024, "x?id=def", "def", "", ""), f)
    assert p["operacaoCredito"] is True
    assert p["situacao"] == "Lei"
    assert p["leiResultante"] == "11796/2024"
    assert p["sancionadaEm"] == "2024-12-30"
    assert p["eventos"][-1]["fase"] == "Proposição de Lei"
    assert "Proposição de lei nº 188/2024" in p["eventos"][-1]["documento"]


def test_ficha_ilegivel():
    with pytest.raises(ErroColeta):
        ler_ficha("<p>erro</p>")


def _dados(n, erros=0, credito=0):
    projs = [{"idCamara": str(i), "ementa": "x", "chave": f"PL {i}/2026", "faseAtual": "f", "emTramitacao": True, "operacaoCredito": False} for i in range(n)]
    return {"versao": 1, "totais": {"tramitando": n, "operacoesCredito": credito, "fichas": n}, "erros": ["e"] * erros, "projetos": projs}


def test_validacao():
    assert validar(_dados(28), _dados(28)) == []
    assert validar(_dados(28), None) == []
    assert validar(_dados(0), _dados(28))  # vazio
    assert validar(_dados(10), _dados(28))  # menos da metade
    assert validar(_dados(20, erros=6), None)  # mais de 20% de fichas com erro


def test_validacao_lei_sem_fase_passa():
    d = _dados(28)
    d["projetos"] += [{"idCamara": f"c{i}", "ementa": "x", "chave": f"PL {i}/2024", "faseAtual": None, "emTramitacao": False} for i in range(12)]
    assert validar(d, None) == []
    d["projetos"][0]["faseAtual"] = None  # em tramitação sem fase: conta
    assert validar(d, None) == []  # 1 de 40 não passa de 20%
