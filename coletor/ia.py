"""
Resumo opcional por IA do que mudou na tramitação. Mesmo padrão e modelos do
informa-damiao (obras-prefeito/api/_ia.js): principal + reserva, repetição com
espera em 429/5xx, raciocínio limitado. Falha nunca derruba a coleta.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import requests

INSTRUCOES = (
    "Você resume a tramitação de um projeto de lei na Câmara Municipal de Belo Horizonte para a "
    "Secretaria Municipal de Governo. Escreva em português, no máximo 3 frases curtas: em que ponto o "
    "projeto está, o que aconteceu de mais recente (com data) e o próximo passo provável. Use só os "
    "dados fornecidos; não invente nomes, datas nem resultados. Sem markdown."
)


def _pensamento(modelo: str):
    manual = os.environ.get("GEMINI_PENSAMENTO")
    if manual == "auto":
        return None
    if manual and manual.lstrip("-").isdigit():
        return int(manual)
    return 128 if "pro" in modelo else 0


def resumir(projeto: dict) -> dict | None:
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        return None
    modelos = [os.environ.get("GEMINI_MODELO") or "gemini-2.5-flash",
               os.environ.get("GEMINI_MODELO_RESERVA") or "gemini-2.5-flash-lite"]
    dados = {k: projeto.get(k) for k in ("chave", "ementa", "situacao", "comissaoAtual", "faseAtual", "prazoComissao", "leiResultante")}
    dados["ultimosEventos"] = projeto.get("eventos", [])[-6:]
    corpo = {
        "systemInstruction": {"parts": [{"text": INSTRUCOES}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(dados, ensure_ascii=False)}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 400},
    }
    for modelo in modelos:
        p = _pensamento(modelo)
        if p is None:
            corpo["generationConfig"].pop("thinkingConfig", None)
        else:
            corpo["generationConfig"]["thinkingConfig"] = {"thinkingBudget": p}
        for tentativa in range(3):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                    headers={"Content-Type": "application/json", "x-goog-api-key": chave},
                    data=json.dumps(corpo), timeout=60,
                )
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(2 ** tentativa)
                    continue
                if not r.ok:
                    break  # configuração: tenta a reserva
                partes = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                texto = "".join(x.get("text", "") for x in partes).strip()
                if texto:
                    return {"texto": texto[:1500], "modelo": modelo,
                            "geradoEm": datetime.utcnow().replace(microsecond=0).isoformat() + "Z"}
                break
            except requests.RequestException:
                time.sleep(2 ** tentativa)
    return None


def aplicar_resumos(novo: dict, anterior: dict | None, log=print) -> None:
    """Gera resumo só para quem mudou de eventos; os demais herdam o resumo anterior."""
    antes = {p["idCamara"]: p for p in (anterior or {}).get("projetos", [])}
    gerados = falhas = 0
    for p in novo["projetos"]:
        velho = antes.get(p["idCamara"])
        if velho and velho.get("assinaturaEventos") == p["assinaturaEventos"] and velho.get("resumoIA"):
            p["resumoIA"] = velho["resumoIA"]
            continue
        r = resumir(p)
        if r:
            p["resumoIA"] = r
            gerados += 1
        else:
            if velho and velho.get("resumoIA"):
                p["resumoIA"] = velho["resumoIA"]
            falhas += 1
    log(f"resumos IA: {gerados} gerados, {falhas} sem resumo novo")
