# -*- coding: utf-8 -*-
"""
FotoDicas TV -> lista M3U para SS IPTV
---------------------------------------
Gera a lista fotodicas.m3u a partir de https://fotodicas.com/

O que o script faz, em ordem:
 1. Le o menu/categorias do site e percorre TODAS as paginas ("proximo", "page/N")
    ate nao existir mais conteudo.
 2. Le o sitemap para nao perder nenhum canal publicado fora do menu.
 3. Em cada canal, abre a pagina do player e coleta os links diretos (.m3u8 / .mp4).
 4. Testa cada link: baixa o manifest, baixa um segmento real e decodifica um frame
    (ffprobe/ffmpeg). Link que so responde 200 mas nao entrega video = reprovado.
 5. Reconcilia com estado_canais.json:
      - canal tocando .......... mantem, zera falhas
      - canal com falha ........ +1 falha; so sai da lista apos 6 atualizacoes
      - falha de rede/geo ...... NAO conta falha (inconclusivo)
      - canal novo ............. entra na hora
 6. Grava fotodicas.m3u, estado_canais.json e relatorio_teste.csv.

Sem dependencias externas: so a biblioteca padrao do Python 3.8+.
ffprobe/ffmpeg sao opcionais (melhoram o teste de video).
"""

import os
import re
import sys
import json
import time
import gzip
import zlib
import html as htmlmod
import tempfile
import subprocess
import urllib.request
import urllib.error
import concurrent.futures
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

# ----------------------------------------------------------------------------- config
BASE = "https://fotodicas.com"

ARQ_M3U = "fotodicas.m3u"
ARQ_ESTADO = "estado_canais.json"
ARQ_RELATORIO = "relatorio_teste.csv"

MAX_FALHAS = 6          # remove o canal somente depois de 6 atualizacoes com falha
MIN_PROPORCAO = 0.35    # anti-zebra: se coletar menos que 35% do total anterior, nao publica

THREADS_SITE = 8
THREADS_TESTE = 12
TIMEOUT = 20

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Categorias exatamente como estao no menu do site (ordem do menu).
# A ultima da lista tem prioridade MENOR: se o canal aparece em "Globo" e em
# "TV Aberta", ele fica em "Globo" (categoria mais especifica).
CATEGORIAS = [
    ("Notícias",      "/aovivo/noticias-online-do-brasil-e-do-mundo/"),
    ("Globo",         "/globo-tv-ao-vivo/"),
    ("Record",        "/record-tv-ao-vivo/"),
    ("Band",          "/band-ao-vivo-online/"),
    ("RedeTV",        "/redetv-ao-vivo-online-hd/"),
    ("SBT",           "/aovivo/sbt-ao-vivo/"),
    ("Esporte",       "/esporte-ao-vivo/"),
    ("Filmes",        "/filmes-online-ao-vivo/"),
    ("Religiosos",    "/canais-de-tv-religiosos/"),
    ("Agronegócio",   "/tv-agronegocio-brasil-ao-vivo/"),
    ("Desenhos",      "/desenhos-animados-ao-vivo/"),
    ("Música",        "/assistir-tv-online-musica-e-shows-ao-vivo/"),
    ("Rádios",        "/aovivo/radios-fm-am-do-brasil/"),
    ("Documentário",  "/documentarios-ao-vivo-e-gratis/"),
    ("TV Aberta",     "/"),
]

ARQUIVOS_WP = [
    ("Ao Vivo",   "/aovivo/"),
    ("Notícias",  "/noticias/"),
    ("Esporte",   "/esportes/"),
    ("Rádios",    "/radios/"),
    ("TV Aberta", "/tv-ao-vivo/"),
]

OK, AUDIO, INCONCLUSIVO, QUEBRADO, VOD = "ok", "audio", "inconclusivo", "quebrado", "vod"

# ----------------------------------------------------------------------------- utilidades

def log(msg):
    print(msg, flush=True)


def http_get(url, referer=None, timeout=TIMEOUT, limite=2_000_000):
    """GET com descompressao gzip/deflate (varios CDNs de TV mandam gzip)."""
    hdr = dict(HEADERS)
    hdr["Accept"] = "*/*"
    if referer:
        hdr["Referer"] = referer
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dados = r.read(limite)
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip" or dados[:2] == b"\x1f\x8b":
            try:
                dados = gzip.decompress(dados)
            except Exception:
                pass
        elif enc == "deflate":
            try:
                dados = zlib.decompress(dados, -15)
            except Exception:
                pass
        return r.status, r.geturl(), dados


def baixar_texto(url, referer=None, tentativas=2):
    for i in range(tentativas):
        try:
            _, _, dados = http_get(url, referer=referer)
            return dados.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return ""
            time.sleep(0.6 + i)
        except Exception:
            time.sleep(0.6 + i)
    return ""


def dehex(s):
    """O site esconde as URLs em \x68\x74\x74\x70... para dificultar copia."""
    s = re.sub(r"\\x([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)
    return s.replace("\\/", "/")


def limpar(txt):
    txt = re.sub(r"<[^>]+>", "", txt or "")
    txt = htmlmod.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def url_abs(u):
    u = htmlmod.unescape(u or "").strip()
    if not u:
        return ""
    if u.startswith("http"):
        return u.rstrip("/") + "/" if not re.search(r"\.(php|html|m3u8|mp4)$", u) else u
    return (BASE + u).rstrip("/") + "/"


def slug(u):
    s = re.sub(r"^https?://[^/]+/", "", u).strip("/")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "canal"


def nome_limpo(titulo):
    """'TV Master Ao Vivo: Assista Online Grátis 24 Horas' -> 'TV Master'."""
    t = limpar(titulo)
    t = re.split(r"\s*[:–—|]\s*|\s+-\s+", t)[0]
    for _ in range(4):
        antes = t
        t = re.sub(r"\s*(ao vivo|assistir|assista|online|gr[áa]tis|hd|full hd|24\s*h(oras)?|"
                   r"em tempo real|agora|aovivo)\s*$", "", t, flags=re.I)
        t = t.strip(" -–—|:.,")
        if t == antes:
            break
    return re.sub(r"\s{2,}", " ", t).strip() or limpar(titulo)


CATEGORIA_POR_NOME = [
    (r"\b(redetv|rede tv)\b", "RedeTV"),
    (r"\b(record|recordtv)\b", "Record"),
    (r"\b(band)\b", "Band"),
    (r"\b(sbt)\b", "SBT"),
    (r"\b(globo|globonews|globonews|eptv|inter ?tv|vanguarda|tv tem|tv integra|tv mirante|"
     r"tv gazeta|tv bahia|tv rio|rpc|tv asa branca|tv liberal|tv morena|tv centro amer|"
     r"tv fronteira|tv anhanguera|tv tribuna|tv cabo branco|tv sert[ãa]o|tv são luís)\b", "Globo"),
    (r"\b(r[áa]dio|radio|fm|am\b)", "Rádios"),
    (r"\b(esporte|sport|futebol|football|luta|ufc|mma)\b", "Esporte"),
    (r"\b(desenho|infantil|kids|cartoon|anime)\b", "Desenhos"),
    (r"\b(filme|cinema|s[ée]rie|novela)\b", "Filmes"),
    (r"\b(document[áa]rio|documentary|natureza)\b", "Documentário"),
    (r"\b(not[íi]cia|news|jornal|24h news)\b", "Notícias"),
    (r"\b(agro|rural|campo|terra)\b", "Agronegócio"),
    (r"\b(gospel|religio|deus|jesus|crist[ãa]o|evang[ée]l|cat[óo]lic|igreja|can[çc][ãa]o nova|"
     r"rit\b|rede vida|tv aparecida|santa)\b", "Religiosos"),
    (r"\b(m[úu]sica|music|show|mtv|kpop)\b", "Música"),
]


def inferir_categoria(nome, id_canal, atual):
    """Quando o site nao diz a categoria, deduz pelo nome do canal."""
    if atual not in ("Outros", "Ao Vivo", ""):
        return atual
    base = f"{nome} {id_canal}".lower()
    for padrao, cat in CATEGORIA_POR_NOME:
        if re.search(padrao, base):
            return cat
    return "Outros"

# ----------------------------------------------------------------------------- coleta no site

def coletar_categorias():
    """Percorre cada categoria do menu e devolve {url_canal: (nome, categoria)}.
    Entende os blocos .epg-bloco, os carrosseis de afiliadas e as listas <h3><a>."""
    mapa = {}
    for ordem, (cat, caminho) in enumerate(CATEGORIAS):
        html = baixar_texto(BASE + caminho)
        if not html:
            log(f"   [aviso] categoria sem resposta: {cat}")
            continue
        achados = []

        # blocos com guia de programacao
        for bloco in re.findall(r'<div class="epg-bloco">(.*?)(?=<div class="epg-bloco">|<div class="final-do-artigo|<section class="faq)', html, re.S):
            t = re.search(r"<h3[^>]*>(.*?)</h3>", bloco, re.S)
            a = re.search(r'<a[^>]+href="([^"]+)"', bloco)
            if t and a:
                achados.append((url_abs(a.group(1)), nome_limpo(t.group(1))))

        # carrossel de afiliadas
        for bloco in re.findall(r'<div class="neon-thumb">(.*?)</li>', html, re.S):
            a = re.search(r'href="([^"]+)"', bloco)
            t = re.search(r"<h3[^>]*>(.*?)</h3>", bloco, re.S)
            if a:
                achados.append((url_abs(a.group(1)), nome_limpo(t.group(1)) if t else ""))

        # listas simples <h3><a href>
        for m in re.finditer(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            achados.append((url_abs(m.group(1)), nome_limpo(m.group(2))))

        for u, nome in achados:
            if not u or "fotodicas.com" not in u:
                continue
            if re.search(r"/(page|tag|author|category|wp-|feed)/", u):
                continue
            # categoria mais especifica vence (TV Aberta e a ultima)
            if u not in mapa:
                mapa[u] = {"nome": nome, "categoria": cat, "ordem": ordem}
        log(f"   {cat:<13} {len(achados):>3} itens")
    return mapa


def coletar_arquivos_wp():
    """Percorre as paginacoes do WordPress (page/2, page/3 ...) ate acabar."""
    mapa = {}
    for cat, caminho in ARQUIVOS_WP:
        pag, total = 1, 0
        while pag <= 60:
            url = BASE + caminho if pag == 1 else f"{BASE}{caminho}page/{pag}/"
            html = baixar_texto(url)
            if not html or 'page-title' not in html:
                break
            links = re.findall(r'<h2 class="entry-title"[^>]*>\s*<a href="([^"]+)"', html)
            if not links:
                break
            for l in links:
                u = url_abs(l)
                if u not in mapa:
                    mapa[u] = {"nome": "", "categoria": cat}
            total += len(links)
            pag += 1
        log(f"   arquivo {cat:<13} {total:>3} posts em {pag-1} pagina(s)")
    return mapa


def coletar_sitemap():
    urls = set()
    for sm in ("post-sitemap.xml", "page-sitemap1.xml", "page-sitemap2.xml"):
        xml = baixar_texto(f"{BASE}/{sm}")
        for loc in re.findall(r"<loc>(.*?)</loc>", xml):
            if re.search(r"\.(jpg|jpeg|png|webp|gif|xml)$", loc, re.I):
                continue
            urls.add(url_abs(loc))
    log(f"   sitemap       {len(urls):>3} URLs")
    return urls


def ler_pagina_canal(url):
    """Extrai nome, logo e o identificador do player de uma pagina de canal."""
    html = baixar_texto(url)
    if not html:
        return None
    titulo = ""
    m = re.search(r'<h1[^>]*class="[^\"]*entry-title[^\"]*"[^>]*>(.*?)</h1>', html, re.S)
    if m:
        titulo = limpar(m.group(1))

    ids = re.findall(r"canal\.php\?id=([^\"&'<>\s]+)", html)
    if not ids:
        ids = re.findall(r'/canal/([A-Za-z0-9_\-\.]+)/?(?:index\.php)?["\']', html)
    ids = [i for i in dict.fromkeys(ids) if i and not i.startswith("_")]

    logo = ""
    m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if m:
        logo = htmlmod.unescape(m.group(1))
    if not logo or "Caricatura" in logo or "Logo_Fotodicas" in logo:
        m = re.search(r'class="epg-thumb-manual"[^>]*>\s*<img[^>]+src="([^"]+)"', html)
        logo = htmlmod.unescape(m.group(1)) if m else ""
    if logo and logo.startswith("/"):
        logo = BASE + logo

    blocos = len(re.findall(r'class="epg-bloco"', html))
    return {"titulo": titulo, "ids": ids, "logo": logo, "blocos": blocos,
            "midia": "content-type=\"video\"" in html}

# ----------------------------------------------------------------------------- player / streams

RE_STREAM = re.compile(r'https?://[^\s"\'<>\\]+\.(?:m3u8|mp4|m4v)(?:\?[^\s"\'<>\\]*)?', re.I)
RE_YT = re.compile(r'youtube\.com/embed/([A-Za-z0-9_\-]{6,})')


def extrair_player(id_canal):
    """Abre as paginas de player do canal e devolve os links diretos encontrados."""
    paginas = [f"{BASE}/iframes/canal.php?id={id_canal}"]
    paginas += [f"{BASE}/canal/{id_canal}/{n}/index.php" for n in (1, 2, 3, 4)]
    paginas.append(f"{BASE}/canal/{id_canal}/index.php")

    streams, yt, embeds = [], [], []
    fila, vistas = paginas[:], set()
    while fila and len(vistas) < 9:
        url = fila.pop(0)
        if url in vistas:
            continue
        vistas.add(url)
        html = baixar_texto(url, referer=BASE + "/")
        if not html:
            continue
        html = dehex(html)

        streams += RE_STREAM.findall(html)
        for v in RE_YT.findall(html):
            if v not in yt:
                yt.append(v)

        for m in re.finditer(r"loadMovieServer\(\s*['\"]([^'\"]*)['\"]", html):
            alvo = dehex(m.group(1))
            if "/contador/" in alvo or "_bem-vindo" in alvo:
                continue
            completo = urljoin(BASE + "/", alvo)
            if re.search(r"\.(m3u8|mp4|m4v)", completo, re.I):
                streams.append(completo)
            elif BASE in completo and ("/canal/" in completo or "/iframes/" in completo):
                fila.append(completo)
            elif "youtube" in completo:
                v = RE_YT.search(completo)
                if v and v.group(1) not in yt:
                    yt.append(v.group(1))
            else:
                embeds.append(completo)

    return list(dict.fromkeys(streams)), list(dict.fromkeys(yt)), list(dict.fromkeys(embeds))

# ----------------------------------------------------------------------------- teste de reproducao

TEM_FFMPEG = None


def tem_ffmpeg():
    global TEM_FFMPEG
    if TEM_FFMPEG is None:
        TEM_FFMPEG = True
        try:
            subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=15)
        except Exception:
            TEM_FFMPEG = False
    return TEM_FFMPEG


def ffprobe_tipos(caminho):
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                            "-of", "json", caminho], capture_output=True, timeout=45)
        if p.returncode != 0:
            return []
        j = json.loads(p.stdout.decode("utf-8", "ignore") or "{}")
        return [s.get("codec_type") for s in j.get("streams", [])]
    except Exception:
        return []


def testar_hls(url):
    """Baixa o manifest, escolhe a variante, baixa um segmento real e decodifica 1 frame."""
    try:
        _, final, dados = http_get(url)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 451):
            return INCONCLUSIVO, f"HTTP {e.code} (geo/login)"
        return QUEBRADO, f"HTTP {e.code}"
    except Exception as e:
        return INCONCLUSIVO, f"rede: {type(e).__name__}"

    txt = dados.decode("utf-8", "ignore")
    if "#EXTM3U" not in txt:
        return QUEBRADO, "nao e HLS"
    if "#EXT-X-KEY" in txt and "METHOD=NONE" not in txt:
        return QUEBRADO, "criptografado (DRM/AES)"

    base = final.rsplit("/", 1)[0] + "/"
    for _ in range(3):
        if "#EXT-X-STREAM-INF" not in txt:
            break
        linhas = [l.strip() for l in txt.splitlines() if l.strip()]
        variantes = []
        for i, l in enumerate(linhas):
            if l.startswith("#EXT-X-STREAM-INF"):
                bw = re.search(r"BANDWIDTH=(\d+)", l)
                for nxt in linhas[i + 1:]:
                    if not nxt.startswith("#"):
                        variantes.append((int(bw.group(1)) if bw else 0, nxt))
                        break
        if not variantes:
            return QUEBRADO, "master sem variantes"
        variantes.sort(key=lambda x: x[0])          # menor banda = mais leve
        escolhida = variantes[0][1]
        if not escolhida.startswith("http"):
            escolhida = base + escolhida.lstrip("/")
        try:
            _, final, dados = http_get(escolhida)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 451):
                return INCONCLUSIVO, f"variante HTTP {e.code}"
            return QUEBRADO, f"variante HTTP {e.code}"
        except Exception as e:
            return INCONCLUSIVO, f"variante: {type(e).__name__}"
        txt = dados.decode("utf-8", "ignore")
        base = final.rsplit("/", 1)[0] + "/"

    segmentos = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#")]
    if not segmentos:
        return QUEBRADO, "playlist sem segmentos"
    if "#EXT-X-ENDLIST" in txt:
        return VOD, "video sob demanda (nao e transmissao ao vivo)"

    seg = segmentos[0]
    if not seg.startswith("http"):
        seg = base + seg.lstrip("/")
    try:
        _, _, corpo = http_get(seg, timeout=25, limite=3_000_000)
    except urllib.error.HTTPError as e:
        return QUEBRADO, f"segmento HTTP {e.code}"
    except Exception as e:
        return QUEBRADO, f"segmento: {type(e).__name__}"
    if len(corpo) < 1000:
        return QUEBRADO, "segmento vazio"

    if not tem_ffmpeg():
        return OK, "segmento recebido (sem ffmpeg)"

    fd, caminho = tempfile.mkstemp(suffix=".ts")
    os.close(fd)
    try:
        with open(caminho, "wb") as f:
            f.write(corpo)
        tipos = ffprobe_tipos(caminho)
        if not tipos:
            return QUEBRADO, "segmento ilegivel"
        if "video" not in tipos:
            return AUDIO, "somente audio"
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-frames:v", "1", "-f", "null", "-"],
                           capture_output=True, timeout=60)
        if p.returncode == 0:
            return OK, "video ok"
        return QUEBRADO, "frame nao decodifica"
    finally:
        try:
            os.unlink(caminho)
        except Exception:
            pass


def logo_valido(url):
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": UA, "Accept": "image/*,*/*"})
        with urllib.request.urlopen(req, timeout=10) as r:
            if 200 <= r.status < 300:
                return url
    except Exception:
        pass
    return ""


def testar_stream(url):
    if re.search(r"\.(mp4|m4v)(\?|$)", url, re.I):
        if not tem_ffmpeg():
            return OK, "mp4 (sem ffmpeg)"
        try:
            p = subprocess.run(["ffprobe", "-v", "error", "-rw_timeout", "12000000",
                                "-show_entries", "stream=codec_type", "-of", "json", url],
                               capture_output=True, timeout=50)
            if p.returncode != 0:
                return QUEBRADO, "mp4 ilegivel"
            j = json.loads(p.stdout.decode("utf-8", "ignore") or "{}")
            tipos = [s.get("codec_type") for s in j.get("streams", [])]
            if "video" in tipos:
                return OK, "mp4 ok"
            if "audio" in tipos:
                return AUDIO, "somente audio"
            return QUEBRADO, "mp4 sem trilha"
        except Exception as e:
            return INCONCLUSIVO, f"mp4: {type(e).__name__}"
    return testar_hls(url)

# ----------------------------------------------------------------------------- estado

def carregar_estado():
    if not os.path.exists(ARQ_ESTADO):
        return {"atualizado_em": None, "execucoes": 0, "canais": {}}
    try:
        with open(ARQ_ESTADO, encoding="utf-8") as f:
            est = json.load(f)
        est.setdefault("canais", {})
        est.setdefault("execucoes", 0)
        return est
    except Exception:
        log("[aviso] estado_canais.json invalido, comecando do zero")
        return {"atualizado_em": None, "execucoes": 0, "canais": {}}


def agora_br():
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M")

# ----------------------------------------------------------------------------- principal

def reconciliar(estado, resultados):
    """Aplica a regra das 6 atualizacoes.

    - tocando .................. falhas = 0, entra com o link novo
    - falha real (quebrado, sem
      link, YouTube, VOD) ...... +1 falha, SEGUE na lista com o ultimo link bom
    - inconclusivo (geo/rede) .. nao conta falha, segue com o link atual
    - so sai da lista quando chega a 6 falhas
    """
    agora = agora_br()
    antigos = estado["canais"]
    publicaveis = {}
    novos = 0
    removidos = 0

    for idc, r in resultados.items():
        reg = antigos.get(idc) or {}
        st = r["status"]

        if st in (OK, AUDIO):
            falhas = 0
        elif st == INCONCLUSIVO:
            falhas = reg.get("falhas", 0)              # geo/rede nao e culpa do canal
        else:
            falhas = reg.get("falhas", 0) + 1          # falha real

        if not reg:
            novos += 1

        link = r.get("stream") or reg.get("stream", "")
        tocando = st in (OK, AUDIO) or (st == INCONCLUSIVO and bool(link))

        # enquanto nao completa 6 falhas, o canal permanece na lista
        if falhas < MAX_FALHAS and link and (tocando or reg.get("stream")):
            publicaveis[idc] = {**r,
                                "stream": link,
                                "nome": r.get("nome") or reg.get("nome", idc),
                                "categoria": r.get("categoria") or reg.get("categoria", "Outros"),
                                "logo": r.get("logo") or reg.get("logo", "")}
        elif reg.get("ativo"):
            removidos += 1

        antigos[idc] = {
            "nome": r.get("nome") or reg.get("nome", idc),
            "categoria": r.get("categoria") or reg.get("categoria", "Outros"),
            "logo": r.get("logo") or reg.get("logo", ""),
            "url_site": r.get("url") or reg.get("url_site", ""),
            "stream": link,
            "status": st,
            "detalhe": r.get("detalhe", ""),
            "falhas": min(falhas, MAX_FALHAS),
            "ativo": idc in publicaveis,
            "atualizado_em": agora,
        }

    # canal que sumiu do site tambem conta falha
    for idc, reg in list(antigos.items()):
        if idc in resultados:
            continue
        reg["falhas"] = min(reg.get("falhas", 0) + 1, MAX_FALHAS)
        reg["status"] = "ausente"
        reg["atualizado_em"] = agora
        if reg["falhas"] >= MAX_FALHAS:
            if reg.get("ativo"):
                removidos += 1
            reg["ativo"] = False
        elif reg.get("stream"):
            publicaveis[idc] = {**reg, "url": reg.get("url_site", ""), "stream": reg["stream"],
                                "logo": reg.get("logo", ""), "nome": reg["nome"],
                                "categoria": reg.get("categoria", "Outros"),
                                "status": reg["status"], "detalhe": "ausente no site"}
            reg["ativo"] = True
    return publicaveis, novos, removidos


def executar(testar=True):
    t0 = time.time()
    log("=" * 62)
    log("FotoDicas TV -> M3U para SS IPTV")
    log("=" * 62)

    estado = carregar_estado()
    antigos = estado["canais"]
    total_antes = len([c for c in antigos.values() if c.get("ativo")])

    # 1) categorias do menu
    log("\n[1/5] Lendo categorias do site...")
    mapa = coletar_categorias()

    # 2) arquivos paginados ("proximo"/"page/N")
    log("\n[2/5] Percorrendo paginacao (proximo/load more) ate o fim...")
    for u, info in coletar_arquivos_wp().items():
        mapa.setdefault(u, info)

    # 3) sitemap, para nao perder canal fora do menu
    log("\n[3/5] Conferindo sitemap...")
    for u in coletar_sitemap():
        mapa.setdefault(u, {"nome": "", "categoria": "Outros"})

    log(f"\n   total de paginas a inspecionar: {len(mapa)}")

    # 4) cada pagina: nome, logo e id do player
    def inspecionar(item):
        url, info = item
        try:
            d = ler_pagina_canal(url)
        except Exception:
            return None
        if not d:
            return None
        if not d["ids"] or d["blocos"] > 1:
            return None                    # pagina de categoria/indice, nao e canal
        nome = info.get("nome") or nome_limpo(d["titulo"])
        cat = info.get("categoria") or "Outros"
        if cat in ("Outros", "Ao Vivo"):
            cat = inferir_categoria(nome, d["ids"][0], cat)
        return {
            "url": url,
            "id": d["ids"][0],
            "nome": nome,
            "categoria": cat,
            "logo": d["logo"],
        }

    canais = {}
    with concurrent.futures.ThreadPoolExecutor(THREADS_SITE) as ex:
        for r in ex.map(inspecionar, list(mapa.items())):
            if not r:
                continue
            # mesmo player em varias paginas -> fica a primeira (categoria mais especifica)
            if r["id"] in canais:
                if len(r["nome"]) > len(canais[r["id"]]["nome"]):
                    canais[r["id"]].setdefault("apelidos", []).append(canais[r["id"]]["nome"])
                    canais[r["id"]]["nome"] = r["nome"]
                else:
                    canais[r["id"]].setdefault("apelidos", []).append(r["nome"])
                continue
            canais[r["id"]] = r

    log(f"   canais encontrados: {len(canais)}")

    # 5) player -> links diretos -> teste de reproducao
    log("\n[4/5] Abrindo o player de cada canal e testando o video...")

    def processar(item):
        idc, info = item
        try:
            streams, yt, embeds = extrair_player(idc)
        except Exception:
            streams, yt, embeds = [], [], []

        if not streams:
            if yt:
                return idc, {**info, "status": "youtube", "detalhe": "player do YouTube (nao abre no SS IPTV)",
                             "stream": ""}
            if embeds:
                return idc, {**info, "status": "embed", "detalhe": "player de terceiros (sem link direto)",
                             "stream": "", "embed": embeds[0]}
            return idc, {**info, "status": "sem_link", "detalhe": "sem link no site", "stream": ""}

        if not testar:
            return idc, {**info, "status": OK, "detalhe": "teste desativado", "stream": streams[0]}

        pior = (QUEBRADO, "sem resposta")
        for u in streams[:4]:
            st, det = testar_stream(u)
            if st in (OK, AUDIO):
                return idc, {**info, "logo": logo_valido(info.get("logo", "")),
                             "status": st, "detalhe": det, "stream": u}
            if st == INCONCLUSIVO:
                pior = (INCONCLUSIVO, det)
        return idc, {**info, "logo": logo_valido(info.get("logo", "")),
                     "status": pior[0], "detalhe": pior[1], "stream": streams[0]}

    resultados = {}
    with concurrent.futures.ThreadPoolExecutor(THREADS_TESTE) as ex:
        for idc, r in ex.map(processar, list(canais.items())):
            resultados[idc] = r

    # 6) reconciliacao com o estado (regra das 6 atualizacoes)
    publicaveis, novos, removidos = reconciliar(estado, resultados)

    # anti-zebra: site fora do ar nao pode zerar a lista
    if total_antes >= 20 and len(publicaveis) < total_antes * MIN_PROPORCAO:
        log("\n[ABORTADO] coleta muito menor que a anterior "
            f"({len(publicaveis)} x {total_antes}). Lista anterior preservada.")
        return 2

    # 7) grava M3U
    agora = agora_br()

    def ordem(c):
        cats = [x[0] for x in CATEGORIAS]
        cat = c.get("categoria", "Outros")
        return (cats.index(cat) if cat in cats else 99, c.get("nome", "").lower())

    vistos = set()
    linhas = ["#EXTM3U"]
    publicados = 0
    for idc, c in sorted(publicaveis.items(), key=lambda kv: ordem(kv[1])):
        u = c.get("stream", "")
        if not u or u in vistos:
            continue                     # evita canal repetido com o mesmo link
        vistos.add(u)
        nome = c.get("nome") or idc
        nome = nome.replace(",", " ").strip()
        cat = c.get("categoria", "Outros")
        logo = c.get("logo", "") or ""
        linha = (f'#EXTINF:-1 tvg-id="{idc}" tvg-name="{nome}" tvg-logo="{logo}" '
                 f'group-title="{cat}",{nome}')
        linhas.append(linha)
        linhas.append(u)
        publicados += 1

    with open(ARQ_M3U, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(linhas) + "\n")

    estado["execucoes"] = estado.get("execucoes", 0) + 1
    estado["atualizado_em"] = agora
    estado["total_publicado"] = publicados
    with open(ARQ_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)

    # 8) relatorio
    with open(ARQ_RELATORIO, "w", encoding="utf-8", newline="") as f:
        f.write("canal;categoria;status;detalhe;falhas;link\n")
        for idc, r in sorted(resultados.items(), key=lambda kv: (kv[1]["categoria"], kv[1]["nome"])):
            f.write(f'{r["nome"]};{r["categoria"]};{r["status"]};{r.get("detalhe","")};'
                    f'{antigos.get(idc,{}).get("falhas",0)};{r.get("stream","")}\n')

    contagem = {}
    for r in resultados.values():
        contagem[r["status"]] = contagem.get(r["status"], 0) + 1

    log("\n" + "=" * 62)
    log(f"Canais encontrados no site : {len(resultados)}")
    log(f"  video confirmado         : {contagem.get(OK, 0)}")
    log(f"  somente audio            : {contagem.get(AUDIO, 0)}")
    log(f"  inconclusivo (rede/geo)  : {contagem.get(INCONCLUSIVO, 0)}")
    log(f"  quebrado                 : {contagem.get(QUEBRADO, 0)}")
    log(f"  YouTube (nao serve)      : {contagem.get('youtube', 0)}")
    log(f"  player de terceiros      : {contagem.get('embed', 0)}")
    log(f"  sem link no site         : {contagem.get('sem_link', 0)}")
    log(f"Canais na lista M3U        : {publicados}")
    log(f"Novos / removidos          : {novos} / {removidos}")
    log(f"Tempo                      : {int(time.time()-t0)}s")
    log("=" * 62)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sem_teste = "--sem-teste" in sys.argv
    sys.exit(executar(testar=not sem_teste))
