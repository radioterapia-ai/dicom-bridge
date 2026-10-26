# -*- coding: utf-8 -*-
import io
import os
import re
import struct
import zlib

EXTENSOES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")

_PAD_SERIE_INST = re.compile(
    r"^(?P<base>.*?)[_\-]?s(?P<serie>\d+)[_\-]i[_\-]?(?P<inst>\d+)$", re.I)
_NUMERO = re.compile(r"(\d+)")

ORIENTACOES = {
    "axial":    (1, 0, 0, 0, 1, 0),
    "coronal":  (1, 0, 0, 0, 0, -1),
    "sagital":  (0, 1, 0, 0, 0, -1),
}

CONVERSOES = {
    "WSD": u"produzida numa estação de trabalho",
    "DF":  u"digitalizada de filme",
    "SI":  u"digitalizada de imagem",
    "DV":  u"digitalizada de vídeo",
}

DESCONHECIDO = u"DESCONHECIDO"
PREFIXO_DO_ID = u"EXTERNO"
NOME_DO_LEIA_ME = u"LEIA-ME.txt"
FOV_SUGERIDO_MM = {"MR": 240.0, "CT": 400.0}
ESPESSURA_SUGERIDA_MM = {"MR": 5.0, "CT": 3.0}
TETO_DO_VOLUME = 384
TITULO_DO_CARIMBO = (u"Há texto do visualizador gravado na imagem (pode conter "
                     u"identificação)")
TITULO_SEM_CONFERIR_O_CARIMBO = (u"Com uma imagem só não dá para conferir se há "
                                 u"texto do visualizador gravado nela (pode "
                                 u"conter identificação)")
TITULO_DO_CARIMBO_NAO_CONFERIDO = (u"Não consegui conferir se há texto do "
                                   u"visualizador gravado na imagem (pode "
                                   u"conter identificação)")
MINIMO_PARA_O_CARIMBO = 2
DIGITOS_DO_SUFIXO = 4
TITULO_SEM_DONO = u"A imagem não diz de quem é"
# GUARDA: frase inteira, sem %s, para casar a chave do dicionário; os valores
# repetem DESCONHECIDO, PREFIXO_DO_ID e NOME_DO_LEIA_ME.
DETALHE_SEM_DONO = (u"a série sai como paciente DESCONHECIDO, com um ID gerado "
                    u"(EXTERNO com a data, a hora e um sufixo aleatório curto), "
                    u"e a pasta de entrega leva um LEIA-ME.txt. No TPS ela pode "
                    u"virar paciente novo ou ser associada à pessoa errada: quem "
                    u"importa atribui.")
TITULO_DA_ORDEM = u"Não sei em que ordem os cortes vão"
DETALHE_DA_ORDEM = (u"os nomes não trazem número de instância, então a ordem seria "
                    u"a alfabética, que só por acaso é a ordem anatômica. Corte "
                    u"trocado não aparece no axial: aparece no MPR como um degrau, "
                    u"e no contorno, depois.")
FAZ_DA_ORDEM = (u"renomeie com numeração (img_0001, img_0002…) ou confira no MPR "
                u"e confirme a escala e a ordem dos cortes.")
DECISOES = (TITULO_DA_ORDEM,)
TITULO_DO_TAMANHO = u"As imagens não têm todas o mesmo tamanho"
DETALHE_DO_TAMANHO = (u"tamanhos encontrados: %s. Uma série DICOM tem uma matriz "
                      u"só.")
FAZ_DO_TAMANHO = (u"separe as imagens por tamanho em pastas diferentes e converta "
                  u"uma de cada vez.")
# GUARDA: uma frase inteira por campo, sem %s nem o nome interno: a tela casa a
# chave do dicionário pela frase inteira.
FALTAS_DA_GEOMETRIA = (
    ("espacamento_mm", u"A imagem não tem escala",
     u"Um JPEG não guarda milímetro por pixel, e sem a escala a série entra na "
     u"fusão com o tamanho errado: o registro rígido não corrige tamanho.",
     u"meça uma distância conhecida no axial ou informe a escala; ela costuma "
     u"estar no laudo ou no rodapé da própria imagem."),
    ("espessura_mm", u"A imagem não tem espessura de corte",
     u"Um JPEG não guarda a espessura do corte, e sem ela o TPS não sabe a que "
     u"distância um corte fica do outro.",
     u"informe a espessura do corte; ela costuma estar no laudo ou gravada na "
     u"própria imagem."),
    ("orientacao", u"A imagem não tem orientação",
     u"Um JPEG não guarda a orientação do corte, e sem ela o TPS não consegue "
     u"pôr a série no espaço para fundir.",
     u"escolha a orientação (axial, coronal ou sagital); a descrição da série "
     u"costuma dizer."),
    ("posicao_paciente", u"A imagem não tem a posição do paciente",
     u"Um JPEG não guarda a posição do paciente na mesa, e sem ela o TPS não "
     u"sabe para que lado ficam a cabeça e a frente.",
     u"escolha a posição do paciente (HFS, HFP, FFS ou FFP); ela costuma estar "
     u"no laudo."),
)

PLANOS_DO_MPR = {
    "axial": {"linha": u"coronal", "coluna": u"sagital"},
    "coronal": {"linha": u"axial", "coluna": u"sagital"},
    "sagital": {"linha": u"axial", "coluna": u"coronal"},
}
EIXOS_NA_TELA = {
    "coronal": {"baixo": (0, 0, -1), "direita": (1, 0, 0)},
    "sagital": {"baixo": (0, 0, -1), "direita": (0, 1, 0)},
    "axial": {"baixo": (0, 1, 0), "direita": (1, 0, 0)},
}
BORDAS_DO_MPR = {
    "coronal": {"cima": u"cranial", "baixo": u"caudal",
                "esquerda": u"direita do paciente",
                "direita": u"esquerda do paciente"},
    "sagital": {"cima": u"cranial", "baixo": u"caudal",
                "esquerda": u"anterior", "direita": u"posterior"},
    "axial": {},
}

_PALAVRAS_DA_ORIENTACAO = {
    "axial": ("axial", "ax", "axi", "tra", "trans", "transversal",
              "transverse", "transverso"),
    "coronal": ("coronal", "cor", "coro"),
    "sagital": ("sagital", "sagittal", "sag"),
}
_PALAVRAS_DA_MODALIDADE = {
    "MR": ("rm", "mr", "mri", "rmn", "ressonancia", "t1", "t2", "flair", "dwi",
           "stir", "adc", "pd"),
    "CT": ("tc", "ct", "tomografia"),
}
_ESPESSURA_NO_TEXTO = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*mm\b", re.I)
_PASTA_NOSSA = re.compile(
    r"^(?:[0-9a-f]{32}|z[0-9a-f]{8}|zip_[0-9a-f]{24}|d[0-9a-f]{8,10})$")
_PASTA_ACHATADA = re.compile(r"^d[0-9a-f]{8}_(.+)$")
_IDS_DADOS = set()


class Recusa(Exception):
    pass


def _achado(ok, titulo, detalhe=u"", resolve=None, o_que_faz=u"",
            alerta=False, impede=False):
    return {"ok": bool(ok), "titulo": titulo, "detalhe": detalhe,
            "resolve": resolve, "o_que_faz": o_que_faz,
            "alerta": bool(alerta), "impede": bool(impede)}


def _palavras(texto):
    import unicodedata
    t = unicodedata.normalize("NFKD", u"%s" % (texto or u""))
    t = t.encode("ascii", "ignore").decode("ascii").lower()
    return [p for p in re.split(r"[^a-z0-9]+", t) if p]


def orientacao_da_descricao(texto):
    achadas = set()
    for p in _palavras(texto):
        for ori, chaves in _PALAVRAS_DA_ORIENTACAO.items():
            if p in chaves:
                achadas.add(ori)
    return achadas.pop() if len(achadas) == 1 else u""


def modalidade_da_descricao(texto):
    achadas = set()
    for p in _palavras(texto):
        for mod, chaves in _PALAVRAS_DA_MODALIDADE.items():
            if p in chaves:
                achadas.add(mod)
    return achadas.pop() if len(achadas) == 1 else u""


def espessura_da_descricao(texto):
    m = _ESPESSURA_NO_TEXTO.search(u"%s" % (texto or u""))
    if not m:
        return None
    v = float(m.group(1).replace(u",", u"."))
    return v if 0.2 <= v <= 20.0 else None


def descricao_sugerida(pasta, chave):
    nome = os.path.basename(os.path.normpath(str(pasta or u"")))
    m = _PASTA_ACHATADA.match(nome)
    if m:
        nome = m.group(1)
    if nome and re.search(u"[A-Za-z]", nome) and not _PASTA_NOSSA.match(nome):
        return nome.replace(u"_", u" ").strip()
    resto = re.sub(r"[#_\-]+", u" ", str(chave or u"")).strip()
    if re.search(u"[A-Za-z]", resto) and not resto.startswith(u"("):
        return resto
    return u"IMAGEM CONVERTIDA"


def sugestoes(serie, descricao):
    mod = modalidade_da_descricao(descricao) or u"MR"
    dims = (serie.get("dimensoes") or [(0, 0)])[0]
    lado = max(int(dims[0] or 0), int(dims[1] or 0))
    escala = round(FOV_SUGERIDO_MM[mod] / lado, 3) if lado else None
    return {"modalidade": mod,
            "orientacao": orientacao_da_descricao(descricao),
            "espessura_mm": (espessura_da_descricao(descricao)
                             or ESPESSURA_SUGERIDA_MM[mod]),
            "espacamento_mm": escala,
            "fov_mm": FOV_SUGERIDO_MM[mod]}


def identidade_externa(agora=None):
    import secrets
    import time
    t = time.localtime(agora if agora is not None else time.time())
    base = u"%s-%s" % (PREFIXO_DO_ID, time.strftime("%Y%m%d-%H%M%S", t))
    # GUARDA: o sufixo aleatório separa duas estações ou dois processos no
    # mesmo segundo; o TPS juntaria duas séries sem dono no mesmo paciente.
    while True:
        ident = u"%s-%s" % (base, secrets.token_hex(
            DIGITOS_DO_SUFIXO // 2).upper())
        if ident not in _IDS_DADOS:
            break
    if len(_IDS_DADOS) > 4096:
        _IDS_DADOS.clear()
    _IDS_DADOS.add(ident)
    return {"patient_id": ident, "patient_name": DESCONHECIDO}


def linha_do_leia_me(ids):
    return (u"Atribua ao paciente certo no TPS: a serie convertida de imagem "
            u"chegou sem dono, como paciente %s, ID %s."
            % (DESCONHECIDO, u", ".join(ids)))


def _png_dimensoes(caminho):
    with open(caminho, "rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            return None
        f.read(4)
        if f.read(4) != b"IHDR":
            return None
        w, h = struct.unpack(">II", f.read(8))
        prof, cor = struct.unpack("BB", f.read(2))
    return {"largura": int(w), "altura": int(h), "bits": int(prof),
            "cor": int(cor)}


def _png_cinza(caminho):
    d = _png_dimensoes(caminho)
    if not d:
        raise ValueError("nao e PNG")
    if d["bits"] != 8 or d["cor"] not in (0, 2, 6):
        raise NotImplementedError(
            "PNG de %d bits, tipo de cor %d: este leitor so faz 8 bits em "
            "cinza (0), RGB (2) ou RGBA (6)" % (d["bits"], d["cor"]))
    canais = {0: 1, 2: 3, 6: 4}[d["cor"]]
    dados = io.BytesIO()
    with open(caminho, "rb") as f:
        f.read(8)
        while True:
            cab = f.read(8)
            if len(cab) < 8:
                break
            n, tipo = struct.unpack(">I", cab[:4])[0], cab[4:8]
            corpo = f.read(n)
            f.read(4)
            if tipo == b"IDAT":
                dados.write(corpo)
            elif tipo == b"IEND":
                break
            elif tipo == b"IHDR" and corpo[12:13] not in (b"\x00",):
                raise NotImplementedError("PNG entrelacado")
    cru = zlib.decompress(dados.getvalue())
    larg, alt = d["largura"], d["altura"]
    passo = larg * canais
    fora = bytearray(alt * passo)
    ant = bytearray(passo)
    p = 0
    for y in range(alt):
        filtro = cru[p]
        p += 1
        linha = bytearray(cru[p:p + passo])
        p += passo
        if filtro == 1:
            for i in range(canais, passo):
                linha[i] = (linha[i] + linha[i - canais]) & 0xFF
        elif filtro == 2:
            for i in range(passo):
                linha[i] = (linha[i] + ant[i]) & 0xFF
        elif filtro == 3:
            for i in range(passo):
                e = linha[i - canais] if i >= canais else 0
                linha[i] = (linha[i] + ((e + ant[i]) >> 1)) & 0xFF
        elif filtro == 4:
            for i in range(passo):
                a = linha[i - canais] if i >= canais else 0
                b = ant[i]
                c = ant[i - canais] if i >= canais else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                linha[i] = (linha[i] + pr) & 0xFF
        elif filtro != 0:
            raise ValueError("filtro PNG %d desconhecido" % filtro)
        fora[y * passo:(y + 1) * passo] = linha
        ant = linha
    import numpy as np
    a = np.frombuffer(bytes(fora), dtype=np.uint8).reshape(alt, larg, canais)
    if canais == 1:
        return a[:, :, 0]
    return a[:, :, :3].mean(axis=2).astype(np.uint8)


def ler_cinza(caminho):
    if str(caminho).lower().endswith(".png"):
        try:
            return _png_cinza(caminho)
        except NotImplementedError:
            pass
    try:
        from PIL import Image
    except ImportError:
        raise Recusa(
            u"este runtime não tem Pillow, então só consigo ler PNG de 8 bits. "
            u"Na estação instalada o Pillow existe e todos os formatos abrem.")
    import numpy as np
    with Image.open(caminho) as im:
        return np.asarray(im.convert("L"))


def dimensoes(caminho):
    if str(caminho).lower().endswith(".png"):
        d = _png_dimensoes(caminho)
        if d:
            return (d["largura"], d["altura"])
    if str(caminho).lower().endswith((".jpg", ".jpeg")):
        d = _jpeg_dimensoes(caminho)
        if d:
            return d
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            return im.size
    except Exception:
        return None


def _jpeg_dimensoes(caminho):
    try:
        with open(caminho, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return None
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return None
                m = b[0]
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                         0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return (int(w), int(h))
                n = struct.unpack(">H", f.read(2))[0]
                f.seek(n - 2, 1)
    except Exception:
        return None


def _chave_ordem(nome):
    base = os.path.splitext(os.path.basename(nome))[0]
    m = _PAD_SERIE_INST.match(base)
    if m:
        return ("s%s" % m.group("serie"), (int(m.group("inst")),), "nome (serie/instancia)")
    nums = list(_NUMERO.finditer(base))
    if nums:
        u = nums[-1]
        chave = base[:u.start()] + "#" + base[u.end():]
        return (chave, tuple(int(m.group(1)) for m in nums), "numero no nome")
    return ("", (base,), "alfabetica")


def varrer(pasta):
    achados = {}
    ignorados = []
    try:
        nomes = sorted(os.listdir(pasta))
    except Exception as e:
        return {"series": [], "ignorados": [("(a pasta)", str(e)[:120])]}
    for n in nomes:
        p = os.path.join(pasta, n)
        if not os.path.isfile(p):
            continue
        if not n.lower().endswith(EXTENSOES):
            ignorados.append((n, u"extensão não é de imagem"))
            continue
        d = dimensoes(p)
        if not d:
            ignorados.append((n, u"não consegui ler as dimensões"))
            continue
        chave, ordem, como = _chave_ordem(n)
        achados.setdefault(chave, {"chave": chave, "como_ordenou": como,
                                   "arquivos": [], "dims": set()})
        achados[chave]["arquivos"].append((ordem, n, p))
        achados[chave]["dims"].add(d)
    series = []
    for chave, s in sorted(achados.items()):
        s["arquivos"].sort(key=lambda x: x[0])
        larguras = sorted(s["dims"])
        series.append({
            "chave": chave or u"(sem padrão de nome)",
            "arquivos": [{"nome": n, "caminho": p} for _, n, p in s["arquivos"]],
            "n": len(s["arquivos"]),
            "dimensoes": larguras,
            "uniforme": len(larguras) == 1,
            "como_ordenou": s["como_ordenou"],
        })
    series.sort(key=lambda x: -x["n"])
    return {"series": series, "ignorados": ignorados}


def carimbo_estatico(serie, amostra=6, tolerancia=0.5):
    import numpy as np
    arqs = serie.get("arquivos") or []
    if len(arqs) < MINIMO_PARA_O_CARIMBO:
        return {"linhas": 0, "fracao": 0.0, "faixas": [], "amostrados": len(arqs)}
    passo = max(1, len(arqs) // max(2, amostra))
    escolhidos = arqs[::passo][:amostra]
    try:
        imgs = [ler_cinza(a["caminho"]).astype(np.int16) for a in escolhidos]
    except Exception:
        return {"linhas": 0, "fracao": 0.0, "faixas": [], "amostrados": 0,
                "erro": u"não consegui decodificar a amostra"}
    forma = imgs[0].shape
    imgs = [g for g in imgs if g.shape == forma]
    if len(imgs) < MINIMO_PARA_O_CARIMBO:
        return {"linhas": 0, "fracao": 0.0, "faixas": [], "amostrados": len(imgs)}
    ref = imgs[0]
    dif = np.zeros(forma[0], dtype=float)
    for g in imgs[1:]:
        dif = np.maximum(dif, np.abs(g - ref).mean(axis=1))
    estaticas = np.where(dif < tolerancia)[0]
    faixas = []
    if len(estaticas):
        ini = estaticas[0]
        for a, b in zip(estaticas, estaticas[1:]):
            if b != a + 1:
                faixas.append((int(ini), int(a)))
                ini = b
        faixas.append((int(ini), int(estaticas[-1])))
    faixas = [(i0, i1) for i0, i1 in faixas
              if i1 - i0 >= 2 and float(ref[i0:i1 + 1].max()) > 8]
    linhas = sum(i1 - i0 + 1 for i0, i1 in faixas)
    return {"linhas": int(linhas), "fracao": float(linhas) / forma[0],
            "faixas": faixas, "amostrados": len(imgs)}


def conferir(serie, geometria=None, com_carimbo=True):
    achados = []
    n = int(serie.get("n") or 0)

    achados.append(_achado(
        True, u"Formato de arquivo",
        u"%d imagem(ns) legível(is)." % n,
        resolve=True,
        o_que_faz=u"decodifica e grava como DICOM sem compressão (Implicit VR "
                  u"Little Endian, a sintaxe de transferência padrão do DICOM), "
                  u"que é o que todo TPS lê."))

    if not serie.get("uniforme", True):
        achados.append(_achado(
            False, TITULO_DO_TAMANHO,
            DETALHE_DO_TAMANHO
            % ", ".join("%dx%d" % d for d in serie.get("dimensoes", [])),
            resolve=False, o_que_faz=FAZ_DO_TAMANHO, impede=True))
    else:
        d = (serie.get("dimensoes") or [(0, 0)])[0]
        achados.append(_achado(True, u"Matriz uniforme",
                               u"todas as imagens são %dx%d." % d))

    como = serie.get("como_ordenou") or "alfabetica"
    if como == "alfabetica" and n > 1:
        achados.append(_achado(False, TITULO_DA_ORDEM, DETALHE_DA_ORDEM,
                               resolve=False, o_que_faz=FAZ_DA_ORDEM))
    else:
        achados.append(_achado(
            True, u"Ordem dos cortes", u"veio do nome do arquivo (%s)." % como))

    g = dict(geometria or {})
    faltas = [f for f in FALTAS_DA_GEOMETRIA if not g.get(f[0])]
    for _campo, titulo, detalhe, o_que_faz in faltas:
        achados.append(_achado(False, titulo, detalhe, resolve=False,
                               o_que_faz=o_que_faz))
    if not faltas:
        achados.append(_achado(
            True, u"Geometria informada",
            u"%s x %s mm/pixel, corte de %s mm, %s, %s."
            % (_mm(g["espacamento_mm"][0]), _mm(g["espacamento_mm"][1]),
               _mm(g["espessura_mm"]), g["orientacao"],
               g["posicao_paciente"])))

    achados.append(_achado(False, TITULO_SEM_DONO, DETALHE_SEM_DONO,
                           alerta=True))

    achados.append(_achado(
        True, u"A série entra com Frame of Reference PRÓPRIO",
        u"ela NÃO é declarada como já alinhada à TC. O TPS vai exigir um "
        u"registro, e é isso que se quer: a geometria aqui foi digitada, não "
        u"medida. Declarar alinhamento faria o TPS sobrepor as duas sem pedir "
        u"nada, e o desenho sairia sobre uma fusão que nunca aconteceu."))

    if com_carimbo and n >= MINIMO_PARA_O_CARIMBO:
        c = carimbo_estatico(serie)
        if c.get("linhas"):
            # GUARDA: só alerta; recortar mudaria a geometria da fusão.
            achados.append(_achado(False, TITULO_DO_CARIMBO, alerta=True))
        elif c.get("erro") or (c.get("amostrados") or 0) < MINIMO_PARA_O_CARIMBO:
            achados.append(_achado(False, TITULO_DO_CARIMBO_NAO_CONFERIDO,
                                   alerta=True))
        else:
            achados.append(_achado(
                True, u"Sem texto queimado detectável",
                u"nenhuma faixa de linhas ficou estática entre os cortes."))
    elif com_carimbo and n == 1:
        achados.append(_achado(False, TITULO_SEM_CONFERIR_O_CARIMBO,
                               alerta=True))
    return {"achados": achados,
            "pode_converter": not any((not a["ok"]) and a["resolve"] is False
                                      for a in achados)}


def _mm(v):
    return (u"%.3f" % float(v)).rstrip(u"0").rstrip(u".")


def decidiveis(serie):
    sonda = conferir(serie, {"espacamento_mm": (1.0, 1.0), "espessura_mm": 1.0,
                             "orientacao": "axial", "posicao_paciente": "HFS"},
                     com_carimbo=False)
    return set(a["titulo"] for a in sonda["achados"]
               if (not a["ok"]) and a["resolve"] is False
               and a["titulo"] in DECISOES)


def volume(serie, teto=TETO_DO_VOLUME):
    import numpy as np
    arqs = serie.get("arquivos") or []
    if not serie.get("uniforme", True):
        raise Recusa(u"as imagens não têm todas o mesmo tamanho")
    cortes, passo = [], 1
    for a in arqs:
        px = ler_cinza(a["caminho"])
        if not cortes:
            passo = max(1, int(-(-max(px.shape) // int(teto))))
        cortes.append(px[::passo, ::passo])
    if not cortes:
        raise Recusa(u"a série está vazia")
    return np.stack(cortes), passo


def apresentacao_do_mpr(orientacao, corte):
    # GUARDA: os eixos saem de ORIENTACOES, a mesma tabela que grava o IOP e o
    # IPP do DICOM; a tela mostra o que o DICOM diz, invertido ou não.
    ori = str(orientacao) if str(orientacao) in ORIENTACOES else "axial"
    r, c = ORIENTACOES[ori][:3], ORIENTACOES[ori][3:]
    cortes = (r[1] * c[2] - r[2] * c[1], r[2] * c[0] - r[0] * c[2],
              r[0] * c[1] - r[1] * c[0])
    lado = r if corte == "linha" else c
    tela = EIXOS_NA_TELA[PLANOS_DO_MPR[ori]["linha" if corte == "linha"
                                            else "coluna"]]

    def _dot(a, b):
        return sum(float(x) * float(y) for x, y in zip(a, b))
    if abs(_dot(cortes, tela["baixo"])) < 0.5:
        return (True, _dot(cortes, tela["direita"]) < 0,
                _dot(lado, tela["baixo"]) < 0)
    return (False, _dot(cortes, tela["baixo"]) < 0,
            _dot(lado, tela["direita"]) < 0)


def mpr(vol, passo, corte, er, ec, entre, orientacao="axial", inverter=False):
    import numpy as np
    n, alt, larg = vol.shape
    if corte == "linha":
        plano = vol[:, alt // 2, :]
        lado_mm = float(ec) * passo
    else:
        plano = vol[:, :, larg // 2]
        lado_mm = float(er) * passo
    if lado_mm <= 0 or float(entre) <= 0:
        raise Recusa(u"escala e espessura precisam ser maiores que zero")
    deitar, virar, espelhar = apresentacao_do_mpr(orientacao, corte)
    if inverter:
        virar = not virar
    if virar:
        plano = plano[::-1, :]
    amostras = int(round(n * float(entre) / lado_mm))
    amostras = max(1, min(amostras, 4 * plano.shape[1]))
    idx = np.clip((np.arange(amostras) * n / float(amostras)).astype(np.int64),
                  0, n - 1)
    plano = plano[idx, :]
    if espelhar:
        plano = plano[:, ::-1]
    if deitar:
        plano = plano.T
    return np.ascontiguousarray(plano)


def converter(serie, destino, geometria, modalidade="MR", como="sc",
              conversao="WSD", descricao=u"", numero_serie=900, aceitar=(),
              quem=u"", log=None, agora=None):
    import numpy as np
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import (ExplicitVRLittleEndian, generate_uid,
                             SecondaryCaptureImageStorage,
                             MRImageStorage, CTImageStorage)

    def _diz(m):
        if log:
            try:
                log(m)
            except Exception:
                pass

    laudo = conferir(serie, geometria)
    # GUARDA: só se aceita o que a sonda reconhece como decisão; dado que
    # falta nunca se dispensa.
    aceitos = set(aceitar or ()) & decidiveis(serie)

    pend = [a for a in laudo["achados"]
            if (not a["ok"]) and a["resolve"] is False and a["titulo"] not in aceitos]
    if pend:
        raise Recusa(
            u"a conversão parou: %d ponto(s) que ela não resolve e que você "
            u"ainda não decidiu. %s"
            % (len(pend), u" | ".join(a["titulo"] for a in pend)))

    try:
        import radai_archive
        _nuvem, _motivo = radai_archive.em_pasta_sincronizada(destino)
    except Exception as _e:
        _nuvem, _motivo = False, u""
        _diz(u"nao consegui conferir se o destino sincroniza (%s) — vou "
             u"gravar assim mesmo" % str(_e)[:120])
    if _nuvem:
        raise Recusa(
            u"o destino sincroniza com a nuvem (%s). A imagem convertida pode "
            u"levar identificação do paciente gravada no pixel — escolha uma "
            u"pasta fora dessa raiz." % (_motivo or u"raiz espelhada"))

    arqs = serie.get("arquivos") or []
    if not arqs:
        raise Recusa(u"a série está vazia")

    g = dict(geometria)
    if g.get("ordem_invertida") is True:
        arqs = list(reversed(arqs))
    ori = ORIENTACOES.get(str(g.get("orientacao", "axial")).lower())
    if ori is None:
        raise Recusa(u"orientação `%s` desconhecida; use %s"
                     % (g.get("orientacao"), ", ".join(sorted(ORIENTACOES))))
    er, ec = float(g["espacamento_mm"][0]), float(g["espacamento_mm"][1])
    esp = float(g["espessura_mm"])
    entre = float(g.get("entre_cortes_mm") or esp)
    z0 = float(g.get("primeiro_corte_mm") or 0.0)

    for_uid = generate_uid()
    serie_uid = generate_uid()
    estudo_uid = generate_uid()
    identidade = identidade_externa(agora)

    import radai_dicom
    _sintaxe = radai_dicom.sintaxe_de_saida()

    sop = {"sc": SecondaryCaptureImageStorage,
           "modalidade": (MRImageStorage if str(modalidade).upper() == "MR"
                          else CTImageStorage)}.get(como)
    if sop is None:
        raise Recusa(u"`como` deve ser 'sc' ou 'modalidade'")

    if not os.path.isdir(destino):
        os.makedirs(destino)
    ja = [n for n in os.listdir(destino) if n.lower().endswith(".dcm")]
    if ja:
        raise Recusa(
            u"a pasta de destino já tem %d arquivo .dcm. Escolha uma pasta "
            u"vazia: contar os arquivos gravados é como esta conversão prova "
            u"que gravou tudo, e arquivo de outra série falseia a conta." % len(ja))

    gravados = []
    for i, a in enumerate(arqs, start=1):
        px = ler_cinza(a["caminho"])
        px = np.ascontiguousarray(px.astype(np.uint8))
        alt, larg = px.shape

        fm = Dataset()
        fm.MediaStorageSOPClassUID = sop
        fm.MediaStorageSOPInstanceUID = generate_uid()
        fm.TransferSyntaxUID = ExplicitVRLittleEndian
        fm.ImplementationClassUID = generate_uid()
        ds = FileDataset(None, {}, file_meta=fm, preamble=b"\0" * 128)
        ds.SpecificCharacterSet = "ISO_IR 100"

        ds.SOPClassUID = sop
        ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
        ds.PatientID = identidade["patient_id"]
        ds.PatientName = identidade["patient_name"]
        ds.PatientBirthDate = ""
        ds.PatientSex = ""
        ds.StudyInstanceUID = estudo_uid
        ds.StudyID = ""
        ds.StudyDate = ""
        ds.StudyTime = ""
        ds.AccessionNumber = ""
        ds.SeriesInstanceUID = serie_uid
        ds.SeriesNumber = int(numero_serie)
        ds.InstanceNumber = i
        ds.Modality = str(modalidade).upper()
        ds.PatientPosition = str(g.get("posicao_paciente") or "HFS")

        ds.ImageType = ["DERIVED", "SECONDARY", "OTHER"]
        ds.ConversionType = str(conversao)
        ds.DerivationDescription = (
            u"Convertida de imagem %s pelo Radioterapia.AI DicomBridge. "
            u"Geometria informada pelo operador, nao medida. Referencia "
            u"visual para fusao: NAO usar para calculo de dose."
            % os.path.splitext(a["nome"])[1].lstrip(".").upper())[:1024]
        ds.SeriesDescription = (descricao or
                                u"CONVERTIDA DE IMAGEM - referencia p/ fusao")[:64]

        ds.FrameOfReferenceUID = for_uid
        ds.ImageOrientationPatient = [float(x) for x in ori]
        r = np.array(ori[:3], dtype=float)
        c = np.array(ori[3:], dtype=float)
        nrm = np.cross(r, c)
        pos = nrm * (z0 + (i - 1) * entre)
        ds.ImagePositionPatient = [float(x) for x in pos]
        ds.PixelSpacing = [float(er), float(ec)]
        ds.SliceThickness = float(esp)
        ds.SpacingBetweenSlices = float(entre)

        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.Rows = int(alt)
        ds.Columns = int(larg)
        ds.BitsAllocated = 8
        ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.WindowCenter = 128
        ds.WindowWidth = 256
        ds.PixelData = px.tobytes()

        if como == "sc":
            ds.ConversionType = str(conversao)
        else:
            if str(modalidade).upper() == "MR":
                ds.ScanningSequence = "RM"
                ds.SequenceVariant = "NONE"
                ds.ScanOptions = ""
                ds.MRAcquisitionType = ""
                ds.RepetitionTime = ""
                ds.EchoTime = ""
                ds.EchoTrainLength = ""
            else:
                ds.KVP = ""
                ds.RescaleSlope = 1
                ds.RescaleIntercept = 0
                ds.RescaleType = "US"

        alvo = os.path.join(destino, "IM%05d.dcm" % i)
        radai_dicom._gravar_na_sintaxe(ds, alvo, _sintaxe)
        gravados.append(alvo)
        if log and (i % 50 == 0 or i == len(arqs)):
            _diz(u"gravadas %d de %d" % (i, len(arqs)))

    no_disco = [n for n in os.listdir(destino) if n.lower().endswith(".dcm")]
    if len(no_disco) != len(arqs):
        raise Recusa(
            u"gravei %d arquivo(s) mas a pasta tem %d. Não confio na conversão "
            u"e não vou dizer que deu certo." % (len(arqs), len(no_disco)))
    _diz(u"conversão conferida: %d arquivo(s) na pasta" % len(no_disco))

    resultado = {"gravados": len(no_disco), "pasta": destino,
                 "serie_uid": serie_uid, "frame_of_reference": for_uid,
                 "estudo_uid": estudo_uid, "modalidade": str(modalidade).upper(),
                 "como": como, "id_externo": identidade["patient_id"],
                 "alertas": [a["titulo"] for a in laudo["achados"]
                             if a.get("alerta")]}
    gravar_recibo(destino, serie, g, resultado, quem=quem, aceitos=aceitos,
                  laudo=laudo)
    return resultado


NOME_RECIBO = "recibo_conversao_imagem.json"
VERSAO_RECIBO = 1


def gravar_recibo(destino, serie, geometria, resultado, quem=u"",
                  aceitos=(), laudo=None):
    try:
        import json
        from datetime import datetime
        pasta = os.path.join(destino, "_RadAI")
        if not os.path.isdir(pasta):
            os.makedirs(pasta)
        caminho = os.path.join(pasta, NOME_RECIBO)
        antigos = []
        if os.path.isfile(caminho):
            try:
                with io.open(caminho, encoding="utf-8") as f:
                    antigos = json.load(f)
                if not isinstance(antigos, list):
                    antigos = []
            except Exception:
                try:
                    os.replace(caminho, caminho + ".ilegivel")
                except Exception:
                    pass
                antigos = []
        g = dict(geometria or {})
        carimbo = any(a["titulo"] == TITULO_DO_CARIMBO
                      for a in ((laudo or {}).get("achados") or []))
        antigos.append({
            "versao_recibo": VERSAO_RECIBO,
            "quando": datetime.now().astimezone().isoformat(timespec="seconds"),
            "maquina": os.environ.get("COMPUTERNAME", ""),
            "quem": str(quem or ""),
            "origem": {"formato": u"imagem (nao-DICOM)",
                       "arquivos": int(serie.get("n") or 0),
                       "ordenado_por": serie.get("como_ordenou", ""),
                       "matriz": ["%dx%d" % d for d in serie.get("dimensoes", [])]},
            "geometria_informada": {
                "espacamento_mm": list(g.get("espacamento_mm") or ()),
                "espessura_mm": g.get("espessura_mm"),
                "entre_cortes_mm": g.get("entre_cortes_mm"),
                "orientacao": g.get("orientacao"),
                "posicao_paciente": g.get("posicao_paciente"),
                "ordem_invertida": g.get("ordem_invertida") is True,
                "fonte": u"digitada pelo operador — nao medida pelo equipamento",
            },
            "saida": {"cortes": resultado.get("gravados"),
                      "modalidade": resultado.get("modalidade"),
                      "como": resultado.get("como")},
            "paciente": u"%s, ID gerado %s: a atribuicao e ato de quem "
                        u"importa no TPS" % (DESCONHECIDO,
                                             resultado.get("id_externo")),
            "frame_of_reference": u"proprio (a serie NAO nasce alinhada a TC; "
                                  u"o registro e ato do operador no TPS)",
            "nao_quantitativo": u"sem RescaleSlope/Intercept: o valor do pixel "
                                u"e nivel de exibicao, nao unidade fisica",
            "aceitos": sorted(str(x) for x in (aceitos or ())),
            "texto_no_pixel": bool(carimbo),
            "conferido": u"contagem de arquivos no destino apos gravar",
        })
        with io.open(caminho, "w", encoding="utf-8") as f:
            f.write(json.dumps(antigos, ensure_ascii=False, indent=1))
        return caminho
    except Exception:
        return ""
