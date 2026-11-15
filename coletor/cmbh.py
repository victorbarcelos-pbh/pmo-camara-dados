"""
Leitura do site da Câmara Municipal de Belo Horizonte (CMBH), sem navegador.

A CMBH não tem API. A página de pesquisa de proposições envia o formulário por
AJAX para dois endpoints que devolvem pedaços de HTML:
  - pesquisar.php: lista paginada (7 por página);
  - proxy.php: ficha de uma proposição (o host interno cmbhsilint só é
    acessível por esse proxy).
Exigências do servidor (mapeadas em 14/11/2026): o token `stormCodex` da página,
o cabeçalho Origin, e os campos vazios com o texto de exemplo ("[ano]" etc.).
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE = "https://www.cmbh.mg.gov.br"
PAGINA = f"{BASE}/atividade-legislativa/pesquisar-proposicoes"
PESQUISAR = f"{BASE}/sites/all/modules/proposicoes/pesquisar.php"
PROXY = f"{BASE}/sites/all/modules/proposicoes/proxy.php"
TIPO_PROJETO_DE_LEI = "2c907f7801d41f2001024943e5ec004a"
USER_AGENT = "Mozilla/5.0 (compatible; PBH-PMO-monitor-proposicoes/1.0; dados publicos)"

ROTULOS = ["Autoria", "Ementa", "Assunto", "Quórum", "Observações", "Estado", "Situação",
           "Fase Atual", "Prazo da Comissão", "Publicação", "Emendas"]
FIM_CABECALHO = ("Copiar o link desta proposição", "Visualizar requerimentos relacionados", "Tramitação da proposição")
CREDITO = re.compile(r"(autoriza|altera).*opera[çc](ão|ões|oes) de cr[ée]dito", re.I | re.S)


class ErroColeta(Exception):
    pass


def _data(s: str | None) -> str | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _linhas(html: str) -> list[str]:
    return [l for l in BeautifulSoup(html, "html.parser").get_text("\n", strip=True).split("\n") if l.strip()]


# ---------------------------------------------------------------- busca

@dataclass
class ItemBusca:
    numero: int
    ano: int
    caminho: str
    id_camara: str
    autoria: str
    ementa: str


def ler_busca(html: str) -> tuple[int, list[ItemBusca]]:
    """Total informado pela CMBH e itens da página."""
    if "fonte não autorizada" in html:
        raise ErroColeta("CMBH recusou a pesquisa (fonte não autorizada)")
    s = BeautifulSoup(html, "html.parser")
    texto = s.get_text(" ", strip=True)
    if "Nenhum resultado encontrado" in texto:
        return 0, []
    m = re.search(r"total de (\d+) itens", texto)
    if not m:
        raise ErroColeta("resposta da busca sem o total de itens")
    itens: list[ItemBusca] = []
    for li in s.select("ul.lista-pesquisas > li"):
        titulo = li.select_one("h3 span.detalhar")
        if not titulo:
            continue
        mt = re.search(r"(\d+)/(\d{4})", titulo.get_text())
        caminho = titulo.get("data-caminho", "")
        mi = re.search(r"id=([0-9a-f]+)", caminho)
        if not (mt and mi):
            raise ErroColeta(f"item da busca ilegível: {titulo.get_text()!r}")
        linhas = _linhas(str(li))
        def depois(rotulo: str) -> str:
            for i, l in enumerate(linhas):
                if l.rstrip(":") == rotulo and i + 1 < len(linhas):
                    return linhas[i + 1]
            return ""
        itens.append(ItemBusca(int(mt.group(1)), int(mt.group(2)), caminho, mi.group(1), depois("Autoria"), depois("Ementa")))
    return int(m.group(1)), itens


# ---------------------------------------------------------------- ficha

@dataclass
class Evento:
    fase: str
    orgao: str | None
    documento: str
    data: str | None


@dataclass
class Ficha:
    campos: dict[str, str] = field(default_factory=dict)
    comissao: str | None = None
    eventos: list[Evento] = field(default_factory=list)
    url: str | None = None


def ler_ficha(html: str) -> Ficha:
    linhas = _linhas(html)
    if not linhas or not re.match(r"Projeto de Lei \d+/\d{4}", linhas[0]):
        raise ErroColeta("ficha sem o título 'Projeto de Lei N/AAAA'")
    f = Ficha()
    f.url = next((l for l in linhas if l.startswith(f"{BASE}/atividade-legislativa/pesquisar-proposicoes/")), None)
    # Cabeçalho: "Rótulo:" seguido do valor (uma ou mais linhas) até o próximo rótulo.
    fim = next((i for i, l in enumerate(linhas) if l.startswith(FIM_CABECALHO)), len(linhas))
    atual: str | None = None
    for l in linhas[:fim]:
        r = l.rstrip(":").strip()
        if l.endswith(":") and r in ROTULOS or r == "Observações":
            atual = r
            f.campos.setdefault(r, "")
            continue
        if atual:
            f.campos[atual] = (f.campos[atual] + "\n" + l).strip()
    # Situação = turno; a 2ª linha, quando houver, é a comissão onde está.
    sit = f.campos.get("Situação", "").split("\n")
    f.campos["Situação"] = sit[0] if sit else ""
    f.comissao = sit[1] if len(sit) > 1 else None
    # Tramitação: blocos "fase [órgão] Documentos: (doc, Publicado em)..."
    try:
        ini = linhas.index("Tramitação da proposição") + 1
    except ValueError:
        raise ErroColeta("ficha sem a seção de tramitação")
    corpo = linhas[ini:]
    if corpo and corpo[-1] == "Voltar":
        corpo = corpo[:-1]
    i = 0
    fase, orgao = "", None
    while i < len(corpo):
        if i + 1 < len(corpo) and corpo[i + 1] == "Documentos:":
            fase, orgao, i = corpo[i], None, i + 2
            continue
        if i + 2 < len(corpo) and corpo[i + 2] == "Documentos:":
            fase, orgao, i = corpo[i], corpo[i + 1], i + 3
            continue
        doc = corpo[i]
        data = None
        if i + 1 < len(corpo) and corpo[i + 1].startswith("Publicado em:"):
            data = _data(corpo[i + 1])
            i += 2
        else:
            i += 1
        f.eventos.append(Evento(fase, orgao, doc, data))
    return f


def montar(item: ItemBusca, ficha: Ficha) -> dict:
    c = ficha.campos
    pub = c.get("Publicação", "")
    ml = re.search(r"Lei\s*N[º°o]?\s*([\d.]+/\d{4})", pub)
    mm = re.search(r"Mensagem n[º°o]?\s*(\d+),\s*de\s*\d{2}/\d{2}/(\d{4})", c.get("Autoria") or item.autoria)
    eventos = [e.__dict__ for e in ficha.eventos]
    ementa = c.get("Ementa") or item.ementa
    return {
        "idCamara": item.id_camara,
        "chave": f"PL {item.numero}/{item.ano}",
        "numero": item.numero,
        "ano": item.ano,
        "ementa": ementa,
        "assunto": c.get("Assunto") or None,
        "autoria": c.get("Autoria") or item.autoria,
        "mensagem": f"{mm.group(1)}/{mm.group(2)}" if mm else None,
        "publicadoEm": next((e["data"] for e in eventos if e["data"]), None),
        "estado": c.get("Estado") or None,
        "situacao": c.get("Situação") or None,
        "comissaoAtual": ficha.comissao,
        "faseAtual": c.get("Fase Atual") or None,
        "prazoComissao": _data(c.get("Prazo da Comissão")),
        "quorum": c.get("Quórum") or None,
        "emendas": c.get("Emendas") or None,
        "operacaoCredito": bool(CREDITO.search(ementa or "")),
        "leiResultante": ml.group(1).replace(".", "") if ml else None,
        "sancionadaEm": _data(pub.split("DOM")[-1]) if ml and "DOM" in pub else None,
        "url": ficha.url or f"{PAGINA}/projeto-de-lei/{item.numero}/{item.ano}",
        "eventos": eventos,
        "assinaturaEventos": hashlib.sha1(repr(eventos).encode()).hexdigest(),
    }


# ---------------------------------------------------------------- HTTP

class Cliente:
    """
    Sessão com a CMBH: token, ritmo lento e repetição com espera longa.

    A CMBH bloqueia o IP (a conexão deixa de abrir) quando recebe requisições
    demais em pouco tempo (visto em 14/11/2026, local e no runner do GitHub).
    Por isso a pausa padrão é longa e, quando a conexão falha, a espera é de
    minutos, não segundos. O log com horário de cada requisição serve para
    medir o limite.
    """

    def __init__(self, pausa: float = 8.0, tentativas: int = 4, espera_falha: float = 90.0,
                 sessao: requests.Session | None = None, log=print):
        self.s = sessao or requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.pausa, self.tentativas, self.espera_falha, self.codex = pausa, tentativas, espera_falha, None
        self.log = log
        self.n = 0
        self._ultimo = 0.0
        self._inicio = time.monotonic()

    def _ritmo(self):
        espera = self.pausa - (time.monotonic() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        self._ultimo = time.monotonic()

    def _pedir(self, metodo: str, url: str, **kw) -> requests.Response:
        erro: Exception | None = None
        for n in range(self.tentativas):
            self._ritmo()
            self.n += 1
            t0 = time.monotonic()
            try:
                r = self.s.request(metodo, url, timeout=(20, 90), **kw)
                if r.status_code >= 500 or r.status_code == 429:
                    raise ErroColeta(f"HTTP {r.status_code}")
                r.raise_for_status()
                r.encoding = r.encoding or "utf-8"
                self.log(f"  req {self.n:3d} +{time.monotonic() - self._inicio:6.0f}s {metodo} {url.rsplit('/', 1)[-1]} -> {r.status_code} em {time.monotonic() - t0:.1f}s")
                return r
            except (requests.RequestException, ErroColeta) as e:
                erro = e
                self.log(f"  req {self.n:3d} +{time.monotonic() - self._inicio:6.0f}s {metodo} {url.rsplit('/', 1)[-1]} FALHOU ({type(e).__name__}); espera {self.espera_falha * (n + 1):.0f}s")
                time.sleep(self.espera_falha * (n + 1))
        raise ErroColeta(f"{url}: {erro}")

    def abrir(self):
        html = self._pedir("GET", PAGINA).text
        m = re.search(r'name="stormCodex"[^>]*value="([^"]+)"', html) or re.search(r'value="([^"]+)"[^>]*name="stormCodex"', html)
        if not m:
            raise ErroColeta("página de pesquisa sem o token stormCodex")
        self.codex = m.group(1)

    def _form(self, **filtros) -> dict:
        if not self.codex:
            self.abrir()
        base = {
            "metodo": "", "nomeProposicao": "", "paginaRequerida": "1", "urlProposicao": "", "idProposicao": "",
            "buscarEmendas_proposicoes": "", "idTipoEmenda": "", "idTipoSubemenda": "", "idTipoEmendaDeRedacao": "",
            "drupalUsername": "deslogado-anonimo", "drupalEmail": "", "buscaViaUrl": "", "stormCodex": self.codex,
            "mobile": "0", "tipo": TIPO_PROJETO_DE_LEI, "numero": "[número]", "ano": "[ano]", "buscarPorProtocolo": "false",
            "autor": "[autor]", "assunto": "[assunto]", "assunto2": "[assunto2]", "fase": "[Selecione]", "tramitando": "Tanto faz",
        }
        base.update({k: str(v) for k, v in filtros.items()})
        return base

    def _post(self, url: str, dados: dict) -> str:
        cab = {"X-Requested-With": "XMLHttpRequest", "Referer": PAGINA, "Origin": BASE}
        html = self._pedir("POST", url, data=dados, headers=cab).text
        if "fonte não autorizada" in html:  # token vencido: reabre a sessão uma vez
            self.abrir()
            dados = {**dados, "stormCodex": self.codex}
            html = self._pedir("POST", url, data=dados, headers=cab).text
        return html

    def buscar(self, **filtros) -> list[ItemBusca]:
        """Todas as páginas. Confere o total informado com o que foi lido."""
        total, itens = ler_busca(self._post(PESQUISAR, self._form(paginaRequerida=1, **filtros)))
        pagina = 1
        while len(itens) < total:
            pagina += 1
            if pagina > 200:
                raise ErroColeta("paginação sem fim")
            _, mais = ler_busca(self._post(PESQUISAR, self._form(paginaRequerida=pagina, **filtros)))
            if not mais:
                break
            itens += mais
        unicos = {i.id_camara: i for i in itens}
        if len(unicos) != total:
            raise ErroColeta(f"busca {filtros}: CMBH informa {total} itens, lidos {len(unicos)}")
        return list(unicos.values())

    def ficha(self, item: ItemBusca) -> Ficha:
        return ler_ficha(self._post(PROXY, self._form(urlProposicao=item.caminho)))


def coletar(cliente: Cliente, ano_credito: int = 2021, log=print) -> dict:
    """PLs do Executivo em tramitação + operações de crédito desde `ano_credito`."""
    tramitando = cliente.buscar(autor="Executivo", tramitando="Sim")
    log(f"em tramitação: {len(tramitando)}")
    credito_busca = cliente.buscar(autor="Executivo", assunto="operação de crédito")
    credito = [i for i in credito_busca if i.ano >= ano_credito and CREDITO.search(i.ementa)]
    log(f"operações de crédito desde {ano_credito}: {len(credito)} (de {len(credito_busca)} com o assunto)")
    ids_tram = {i.id_camara for i in tramitando}
    todos = {i.id_camara: i for i in [*tramitando, *credito]}
    projetos, erros = [], []
    for item in todos.values():
        try:
            p = montar(item, cliente.ficha(item))
            p["emTramitacao"] = item.id_camara in ids_tram
            projetos.append(p)
        except ErroColeta as e:
            erros.append(f"PL {item.numero}/{item.ano}: {e}")
    projetos.sort(key=lambda p: (-p["ano"], -p["numero"]))
    return {
        "versao": 1,
        "geradoEm": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "fonte": BASE,
        "totais": {"tramitando": len(tramitando), "operacoesCredito": sum(1 for p in projetos if p["operacaoCredito"]), "fichas": len(projetos)},
        "erros": erros,
        "projetos": projetos,
    }
