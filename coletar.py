"""
Coleta os projetos de lei do Executivo na CMBH e grava dados/projetos-de-lei.json.

    python coletar.py            # coleta, valida e grava se mudou
    python coletar.py --sem-ia   # pula o resumo por IA

Sai com código 1 (sem gravar) quando a coleta é suspeita; ver coletor/validar.py.
"""
import json
import sys
from pathlib import Path

from coletor.cmbh import Cliente, ErroColeta, coletar
from coletor.ia import aplicar_resumos
from coletor.validar import validar

SAIDA = Path(__file__).resolve().parent / "dados" / "projetos-de-lei.json"


def sem_data(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "geradoEm"}


def main() -> int:
    anterior = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else None
    try:
        novo = coletar(Cliente())
    except ErroColeta as e:
        print(f"FALHA na coleta: {e}")
        return 1
    motivos = validar(novo, anterior)
    if motivos:
        print("Coleta suspeita, nada gravado:\n- " + "\n- ".join(motivos))
        return 1
    if "--sem-ia" not in sys.argv:
        aplicar_resumos(novo, anterior)
    elif anterior:  # mantém os resumos anteriores
        antes = {p["idCamara"]: p.get("resumoIA") for p in anterior.get("projetos", [])}
        for p in novo["projetos"]:
            if antes.get(p["idCamara"]):
                p["resumoIA"] = antes[p["idCamara"]]
    if anterior and sem_data(anterior) == sem_data(novo):
        print("Sem mudanças na CMBH; JSON mantido.")
        return 0
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(novo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    t = novo["totais"]
    print(f"Gravado: {t['tramitando']} em tramitação, {t['operacoesCredito']} operações de crédito, {t['fichas']} fichas, {len(novo['erros'])} erros.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
