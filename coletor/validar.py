"""Coleta suspeita não substitui a última boa (RF08 do SDD)."""
from __future__ import annotations

OBRIGATORIOS = ("idCamara", "chave", "ementa", "faseAtual")


def validar(novo: dict, anterior: dict | None) -> list[str]:
    """Lista de motivos para NÃO publicar; vazia = pode publicar."""
    motivos: list[str] = []
    tram = novo.get("totais", {}).get("tramitando", 0)
    fichas = len(novo.get("projetos", []))
    if novo.get("versao") != 1:
        motivos.append("versão do formato desconhecida")
    if tram == 0:
        motivos.append("nenhum PL do Executivo em tramitação (a CMBH sempre tem algum)")
    if anterior:
        antes = anterior.get("totais", {}).get("tramitando", 0)
        if antes and tram < antes / 2:
            motivos.append(f"em tramitação caiu de {antes} para {tram} (menos da metade)")
    erros = len(novo.get("erros", []))
    if erros and erros > 0.2 * (fichas + erros):
        motivos.append(f"{erros} fichas com erro de leitura (mais de 20%)")
    sem = [p.get("chave", "?") for p in novo.get("projetos", []) if any(not p.get(c) for c in OBRIGATORIOS)]
    if sem and len(sem) > 0.2 * max(fichas, 1):
        motivos.append(f"{len(sem)} PLs sem campo obrigatório: {', '.join(sem[:5])}")
    return motivos
