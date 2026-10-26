# -*- coding: utf-8 -*-
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cleanup
import _componentes
_cleanup.adotar_prefixo('radai_img_')

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "app")
sys.path.insert(0, APP)

_ACERVO = tempfile.mkdtemp(prefix="radai_img_acervo_")
os.environ["RADAI_CALIB_DIR"] = _ACERVO

_ok = 0
_falhas = []


def checar(nome, cond, detalhe=u""):
    global _ok
    if cond:
        _ok += 1
        print(u"    OK     %s" % nome)
    else:
        _falhas.append(nome)
        print(u"    FALHA  %s  %s" % (nome, detalhe))


def secao(t):
    print(u"\n  ── %s %s" % (t, u"─" * max(0, 60 - len(t))))


def temp():
    return tempfile.mkdtemp(prefix="radai_img_")


def escrever_png(caminho, linhas, filtro=0):
    alt = len(linhas)
    larg = len(linhas[0])
    cru = bytearray()
    ant = bytearray(larg)
    for y in range(alt):
        atual = bytearray(linhas[y])
        cru.append(filtro)
        if filtro == 0:
            cru += atual
        elif filtro == 1:
            cru += bytes(((atual[i] - (atual[i - 1] if i else 0)) & 0xFF)
                         for i in range(larg))
        elif filtro == 2:
            cru += bytes(((atual[i] - ant[i]) & 0xFF) for i in range(larg))
        elif filtro == 3:
            cru += bytes(((atual[i] - (((atual[i - 1] if i else 0) + ant[i]) >> 1)) & 0xFF)
                         for i in range(larg))
        else:
            saida = bytearray()
            for i in range(larg):
                a = atual[i - 1] if i else 0
                b = ant[i]
                c = ant[i - 1] if i else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                saida.append((atual[i] - pr) & 0xFF)
            cru += saida
        ant = atual

    def bloco(tipo, dados):
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))
    with open(caminho, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(bloco(b"IHDR", struct.pack(">IIBBBBB", larg, alt, 8, 0, 0, 0, 0)))
        f.write(bloco(b"IDAT", zlib.compress(bytes(cru), 6)))
        f.write(bloco(b"IEND", b""))


def fantoma(pasta, n=6, larg=64, alt=64, carimbo=True, prefixo="img"):
    for k in range(1, n + 1):
        linhas = []
        for y in range(alt):
            if carimbo and (y < 6 or y >= alt - 4):
                linhas.append(bytes(200 if (x % 7 < 2) else 4 for x in range(larg)))
            else:
                linhas.append(bytes(min(255, (x + y + k * 23) % 256)
                                    for x in range(larg)))
        escrever_png(os.path.join(pasta, "%s_%04d.png" % (prefixo, k)),
                     linhas, filtro=(k % 5))
    return pasta


def esfera(pasta, n=20, lado=64, raio_mm=15.0, esc=1.0, esp=2.0):
    import math
    os.makedirs(pasta, exist_ok=True)
    zc = (n - 1) * esp / 2.0
    for k in range(n):
        dz = k * esp - zc
        r2 = raio_mm ** 2 - dz ** 2
        linhas = []
        for y in range(lado):
            linha = []
            for x in range(lado):
                d2 = ((x - lado / 2.0) * esc) ** 2 + ((y - lado / 2.0) * esc) ** 2
                linha.append(220 if r2 > 0 and d2 <= r2 else 0)
            linhas.append(bytes(linha))
        escrever_png(os.path.join(pasta, "esfera_%04d.png" % (k + 1)), linhas)
    del math
    return pasta


GEO = {"espacamento_mm": (0.8, 0.8), "espessura_mm": 5.0,
       "entre_cortes_mm": 5.0, "orientacao": "axial",
       "posicao_paciente": "HFS"}
ID_EXTERNO = re.compile(r"^EXTERNO-\d{8}-\d{6}-[0-9A-F]{4}$")


class Cliente(object):

    def __init__(self, app):
        self.app = app
        self.rotas = {}
        for r in app.routes:
            alvo = getattr(r, "endpoint", None)
            if alvo is None:
                continue
            for m in (getattr(r, "methods", None) or ()):
                self.rotas[(m, r.path)] = alvo

    def tem(self, metodo, caminho):
        return (metodo, caminho) in self.rotas

    def _chamar(self, alvo, *a, **k):
        import asyncio
        import inspect
        if inspect.iscoroutinefunction(alvo):
            return asyncio.run(alvo(*a, **k))
        return alvo(*a, **k)

    def post(self, caminho, corpo=None):
        return self._chamar(self.rotas[("POST", caminho)],
                            PedidoFalso(corpo or {}))

    def get(self, caminho, **params):
        import inspect
        alvo = self.rotas[("GET", caminho)]
        k = dict(params)
        if "request" in inspect.signature(alvo).parameters:
            k["request"] = PedidoFalso({})
        return self._chamar(alvo, **k)


class PedidoFalso(object):
    def __init__(self, corpo):
        self._corpo = corpo
        self.headers = {}

    async def json(self):
        return self._corpo


def _app():
    from fastapi import FastAPI
    import radai_bridge
    return Cliente(radai_bridge.montar(FastAPI()))


def _imagens(cli, pasta):
    r = cli.post("/api/bridge/varrer", {"pasta": pasta})
    return list(r.get("imagens") or []), r


def _pedido(geo, **k):
    p = {"geometria": dict(geo), "modalidade": "MR", "descricao": u"",
         "como": "sc", "aceitar": []}
    p.update(k)
    return p


def _converter(cli, pasta, b, pedido):
    return cli.post("/api/bridge/etapa/converter",
                    {"pasta": pasta, "series": [{"b": b, "imagem": pedido}]})


def _entregar(cli, conversao, destinos):
    return cli.post("/api/bridge/etapa/entregar",
                    {"conversao": conversao, "destinos": list(destinos)})


def _corpo_js(js, nome):
    i = js.find(u"function %s(" % nome)
    if i < 0:
        return u""
    k = js.find(u"{", i)
    prof = 0
    for j in range(k, len(js)):
        if js[j] == u"{":
            prof += 1
        elif js[j] == u"}":
            prof -= 1
            if prof == 0:
                return js[k:j + 1]
    return u""


def _altura_png(dados):
    return struct.unpack(">I", dados[20:24])[0]


def _largura_png(dados):
    return struct.unpack(">I", dados[16:20])[0]


def teste_le_png_sem_pillow():
    secao(u"le PNG sem Pillow, nos cinco filtros")
    import radai_image as RI
    d = temp()
    alvo = [bytes((x * 3 + y) % 256 for x in range(32)) for y in range(16)]
    for f in range(5):
        p = os.path.join(d, "f%d.png" % f)
        escrever_png(p, alvo, filtro=f)
        try:
            g = RI.ler_cinza(p)
            igual = all(int(g[y][x]) == alvo[y][x]
                        for y in range(16) for x in range(32))
        except Exception as e:
            igual = False
            print(u"       (%s)" % e)
        checar(u"filtro %d volta byte a byte" % f, igual)
    checar(u"e as dimensoes saem sem decodificar",
           RI.dimensoes(os.path.join(d, "f0.png")) == (32, 16))


def teste_varrer_agrupa_e_ordena():
    secao(u"varrer agrupa em series e diz COMO ordenou")
    import radai_image as RI
    d = temp()
    fantoma(d, n=5, prefixo="image_s0001_i")
    fantoma(d, n=3, prefixo="image_s0002_i")
    io.open(os.path.join(d, "leiame.txt"), "w").write(u"x")
    r = RI.varrer(d)
    chaves = sorted(s["chave"] for s in r["series"])
    checar(u"achou as duas series", len(r["series"]) == 2, str(chaves))
    checar(u"  e a maior vem primeiro", r["series"][0]["n"] == 5)
    checar(u"  ordenou pelo numero de instancia do nome",
           r["series"][0]["como_ordenou"] == "nome (serie/instancia)")
    checar(u"  e ignorou o que nao e imagem",
           any(n.endswith(".txt") for n, _ in r["ignorados"]))
    d2 = temp()
    fantoma(d2, n=12, prefixo="corte")
    s = RI.varrer(d2)["series"][0]
    nums = [int(a["nome"].split("_")[1].split(".")[0]) for a in s["arquivos"]]
    checar(u"a ordem e numerica, e nao alfabetica (10 depois de 9)",
           nums == sorted(nums), str(nums[:12]))
    d3 = temp()
    for nome in ("alfa", "beta", "gama"):
        escrever_png(os.path.join(d3, nome + ".png"),
                     [bytes(range(16)) for _ in range(8)])
    s3 = RI.varrer(d3)["series"][0]
    checar(u"sem numero no nome, ela ADMITE que a ordem e alfabetica",
           s3["como_ordenou"] == "alfabetica")


def _bloqueiam(laudo):
    return [a["titulo"] for a in laudo["achados"]
            if not a["ok"] and a["resolve"] is False]


def teste_o_laudo_cobra_so_o_que_falta():
    secao(u"o laudo: geometria cobra, identidade e texto no pixel so alertam")
    import radai_image as RI
    d = temp()
    fantoma(d, n=6, prefixo="image_s0001_i")
    s = RI.varrer(d)["series"][0]

    l = RI.conferir(s)
    checar(u"sem geometria, NAO pode converter", l["pode_converter"] is False)
    checar(u"  e a escala esta entre os motivos",
           any(u"escala" in t for t in _bloqueiam(l)), str(_bloqueiam(l)))
    checar(u"a identidade NAO bloqueia mais (a etapa saiu)",
           not any(u"de quem" in t for t in _bloqueiam(l)), str(_bloqueiam(l)))
    sem_dono = [a for a in l["achados"] if a["titulo"] == RI.TITULO_SEM_DONO]
    checar(u"  e vira alerta, dizendo DESCONHECIDO e o LEIA-ME",
           len(sem_dono) == 1 and sem_dono[0]["alerta"]
           and RI.DESCONHECIDO in sem_dono[0]["detalhe"]
           and RI.NOME_DO_LEIA_ME in sem_dono[0]["detalhe"], str(sem_dono)[:160])
    carimbo = [a for a in l["achados"] if a["titulo"] == RI.TITULO_DO_CARIMBO]
    checar(u"o texto no pixel e UM alerta de uma linha, sem detalhe nem opcao",
           len(carimbo) == 1 and carimbo[0]["alerta"] and not carimbo[0]["detalhe"]
           and not carimbo[0]["o_que_faz"] and carimbo[0]["resolve"] is None,
           str(carimbo)[:160])
    checar(u"  e a frase e a do autor",
           RI.TITULO_DO_CARIMBO == u"Há texto do visualizador gravado na imagem "
                                   u"(pode conter identificação)")

    l2 = RI.conferir(s, GEO)
    checar(u"com geometria, converte (o carimbo e a identidade so alertam)",
           l2["pode_converter"] is True and not _bloqueiam(l2),
           str(_bloqueiam(l2)))
    checar(u"o laudo AVISA que a serie nao nasce alinhada",
           any(u"Frame of Reference" in a["titulo"] for a in l2["achados"]))
    isca = {"achados": [{"ok": False, "resolve": False,
                         "titulo": u"A imagem não diz de quem é"}]}
    checar(u"  (isca) a identidade como bloqueio seria acusada",
           any(u"de quem" in t for t in _bloqueiam(isca)))


def teste_o_carimbo_e_detectado_por_estabilidade():
    secao(u"o carimbo queimado, detectado por estabilidade")
    import radai_image as RI
    com = RI.varrer(fantoma(temp(), n=8, carimbo=True, prefixo="image_s0001_i"))["series"][0]
    sem = RI.varrer(fantoma(temp(), n=8, carimbo=False, prefixo="image_s0001_i"))["series"][0]
    c1 = RI.carimbo_estatico(com)
    c2 = RI.carimbo_estatico(sem)
    checar(u"acha a faixa quando ela existe", c1["linhas"] >= 8, str(c1))
    checar(u"  e diz onde ela esta", len(c1["faixas"]) >= 2, str(c1["faixas"]))
    checar(u"e NAO acusa quando nao ha faixa", c2["linhas"] == 0, str(c2))
    d = temp()
    for k in range(1, 7):
        linhas = []
        for y in range(64):
            if y < 10:
                linhas.append(bytes(0 for _ in range(64)))
            else:
                linhas.append(bytes((x + k * 31) % 256 for x in range(64)))
        escrever_png(os.path.join(d, "image_s0001_i%04d.png" % k), linhas)
    s = RI.varrer(d)["series"][0]
    checar(u"faixa PRETA e fixa nao e acusada de carimbo",
           RI.carimbo_estatico(s)["linhas"] == 0,
           u"ar acima do ombro nao muda, e nao e identificacao")

    def _titulos(serie):
        return [a["titulo"] for a in RI.conferir(serie)["achados"]
                if not a["ok"] and a.get("alerta")]
    dois_com = RI.varrer(fantoma(temp(), n=2, carimbo=True,
                                 prefixo="image_s0001_i"))["series"][0]
    dois_sem = RI.varrer(fantoma(temp(), n=2, carimbo=False,
                                 prefixo="image_s0001_i"))["series"][0]
    checar(u"com DUAS imagens o carimbo ja e conferido, e acusado",
           RI.TITULO_DO_CARIMBO in _titulos(dois_com), str(_titulos(dois_com)))
    sem2 = [a for a in RI.conferir(dois_sem)["achados"]
            if a["titulo"] == u"Sem texto queimado detectável"]
    checar(u"  e sem faixa, com duas imagens, diz que nao achou",
           len(sem2) == 1 and RI.TITULO_DO_CARIMBO not in _titulos(dois_sem),
           str(_titulos(dois_sem)))
    uma = RI.varrer(fantoma(temp(), n=1, carimbo=True,
                            prefixo="image_s0001_i"))["series"][0]
    t1 = _titulos(uma)
    checar(u"com UMA imagem o laudo diz que nao da para conferir (alerta)",
           RI.TITULO_SEM_CONFERIR_O_CARIMBO in t1
           and u"Sem texto queimado detectável" not in [
               a["titulo"] for a in RI.conferir(uma)["achados"]], str(t1))
    minimo = RI.MINIMO_PARA_O_CARIMBO
    RI.MINIMO_PARA_O_CARIMBO = 3
    try:
        antigo = [a["titulo"] for a in RI.conferir(dois_com)["achados"]]
    finally:
        RI.MINIMO_PARA_O_CARIMBO = minimo
    checar(u"  (isca) com a regra antiga, de tres imagens, as duas ficavam caladas",
           not any(t in antigo for t in (RI.TITULO_DO_CARIMBO,
                                         u"Sem texto queimado detectável",
                                         RI.TITULO_SEM_CONFERIR_O_CARIMBO)),
           str(antigo))
    original = RI.ler_cinza
    RI.ler_cinza = lambda c: (_ for _ in ()).throw(ValueError("x"))
    try:
        quebrada = _titulos(dois_com)
    finally:
        RI.ler_cinza = original
    checar(u"amostra que nao decodifica nao vira «Sem texto queimado detectável»",
           RI.TITULO_DO_CARIMBO_NAO_CONFERIDO in quebrada, str(quebrada))


def teste_converte_e_confere_o_que_gravou():
    secao(u"a conversao grava, sem dono, e confere sobre o disco")
    import radai_image as RI
    import pydicom
    d = temp()
    fantoma(d, n=7, carimbo=True, prefixo="image_s0001_i")
    s = RI.varrer(d)["series"][0]
    saida = os.path.join(temp(), "saida")
    res = RI.converter(s, saida, GEO, modalidade="MR", como="sc", quem="bateria")
    checar(u"gravou os 7, com o texto no pixel so alertado",
           res["gravados"] == 7 and RI.TITULO_DO_CARIMBO in res["alertas"],
           str(res)[:160])
    dcms = sorted(n for n in os.listdir(saida) if n.endswith(".dcm"))
    checar(u"  e os arquivos estao la", len(dcms) == 7)

    a = pydicom.dcmread(os.path.join(saida, dcms[0]), force=True)
    b = pydicom.dcmread(os.path.join(saida, dcms[-1]), force=True)
    checar(u"o paciente e DESCONHECIDO", str(a.PatientName) == RI.DESCONHECIDO,
           str(a.PatientName))
    checar(u"  com o ID gerado EXTERNO-<data>-<hora>-<sufixo>",
           bool(ID_EXTERNO.match(str(a.PatientID)))
           and str(a.PatientID) == res["id_externo"], str(a.PatientID))
    checar(u"  e o mesmo ID em todos os cortes",
           str(b.PatientID) == str(a.PatientID))
    checar(u"  sem nascimento, sexo nem estudo herdado",
           str(a.PatientBirthDate) == "" and str(a.PatientSex) == ""
           and str(a.AccessionNumber) == "" and bool(str(a.StudyInstanceUID)))
    checar(u"a geometria esta no arquivo",
           [float(x) for x in a.PixelSpacing] == [0.8, 0.8]
           and float(a.SliceThickness) == 5.0)
    checar(u"  e os cortes avancam o espacamento pedido",
           abs((float(b.ImagePositionPatient[2]) - float(a.ImagePositionPatient[2]))
               - 6 * 5.0) < 1e-6,
           str(float(b.ImagePositionPatient[2])))
    checar(u"  e a imagem vai inteira (nada recortado)",
           int(a.Rows) == 64 and int(a.Columns) == 64)
    checar(u"o arquivo diz que e DERIVADO e convertido",
           list(a.ImageType)[:2] == ["DERIVED", "SECONDARY"]
           and str(a.ConversionType) == "WSD")
    checar(u"nao declara escala de Hounsfield",
           not hasattr(a, "RescaleSlope"),
           u"declarar diria que o nivel de exibicao e unidade fisica")

    try:
        RI.converter(s, saida, GEO)
        recusou = False
    except RI.Recusa:
        recusou = True
    checar(u"recusa gravar em pasta que ja tem .dcm", recusou,
           u"contar arquivo e como ela prova que gravou tudo")
    import inspect
    args = inspect.signature(RI.converter).parameters
    checar(u"`converter` nao recebe identidade nem recorte de fora",
           "identidade" not in args and "recortar" not in args, str(list(args)))


def teste_o_id_externo_nao_se_repete():
    secao(u"o ID EXTERNO nao se repete, nem no mesmo segundo, nem entre processos")
    import subprocess
    import time
    import radai_image as RI
    agora = time.mktime((2026, 10, 14, 9, 30, 15, 0, 0, -1))
    ids = [RI.identidade_externa(agora)["patient_id"] for _ in range(3)]
    checar(u"tres series no mesmo segundo, tres IDs", len(set(ids)) == 3, str(ids))
    checar(u"  todos no formato EXTERNO-<data>-<hora>-<sufixo>",
           all(ID_EXTERNO.match(i) for i in ids), str(ids))
    checar(u"  e a data e a hora sao as do instante, sem somar 1 a hora",
           all(i.startswith(u"EXTERNO-20261014-093015-") for i in ids), str(ids))
    isca = [time.strftime("EXTERNO-%Y%m%d-%H%M%S", time.localtime(agora))
            for _ in range(3)]
    checar(u"  (isca) a hora sozinha repetiria o ID", len(set(isca)) == 1)
    codigo = (u"import sys; sys.path[:0] = %r; import radai_image as R; "
              u"print(R.identidade_externa(%r)['patient_id'])"
              % (list(sys.path[:6]), agora))
    outros = []
    for _ in range(6):
        r = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                           text=True, timeout=60)
        outros.append((r.stdout or u"").strip())
    checar(u"seis processos no mesmo segundo, seis IDs (o sufixo nao vive na "
           u"memoria de um processo so)",
           len(set(outros)) == 6 and all(ID_EXTERNO.match(i) for i in outros),
           str(outros))
    fonte = io.open(_componentes.fonte("app/radai_image.py"), encoding="utf-8").read()
    checar(u"  e nao ha mais o contador que somava 1 a hora",
           u"_ULTIMO_ID" not in fonte and u"int(n) + 1" not in fonte)
    checar(u"o nome e DESCONHECIDO",
           RI.identidade_externa()["patient_name"] == u"DESCONHECIDO")
    linha = RI.linha_do_leia_me([ids[0]])
    checar(u"o LEIA-ME e UMA linha, em ASCII, com o pedido do autor e o ID",
           u"\n" not in linha and u"atribua ao paciente certo no tps" in linha.lower()
           and ids[0] in linha and linha.encode("ascii", "strict"), linha)


def teste_o_frame_of_reference_e_sempre_novo():
    secao(u"o Frame of Reference e proprio, sempre")
    import radai_image as RI
    import pydicom
    d = temp()
    fantoma(d, n=4, carimbo=False, prefixo="image_s0001_i")
    s = RI.varrer(d)["series"][0]
    uids = []
    for k in range(2):
        saida = os.path.join(temp(), "s%d" % k)
        RI.converter(s, saida, GEO)
        uids.append(str(pydicom.dcmread(
            os.path.join(saida, "IM00001.dcm"), force=True).FrameOfReferenceUID))
    checar(u"duas conversoes dao Frames diferentes", uids[0] != uids[1])
    fonte = io.open(_componentes.fonte("app/radai_image.py"), encoding="utf-8").read()
    import inspect
    args = inspect.signature(RI.converter).parameters
    checar(u"`converter` nao aceita frame_of_reference de fora",
           not any("frame" in a.lower() or "for_uid" in a.lower() for a in args),
           str(list(args)))
    checar(u"  e o UID e gerado", "for_uid = generate_uid()" in fonte)
    checar(u"  e o modulo nao le mais DICOM de referencia",
           "def identidade_de" not in fonte and "dcmread" not in fonte)


def teste_o_recibo_nao_carrega_identificacao():
    secao(u"o recibo registra a geometria e o ID gerado, e nada do paciente")
    import radai_image as RI
    d = temp()
    fantoma(d, n=4, carimbo=True, prefixo="image_s0001_i")
    s = RI.varrer(d)["series"][0]
    saida = os.path.join(temp(), "r")
    r = RI.converter(s, saida, GEO, quem="dr_teste",
                     descricao=u"ISCA BELTRANO RM T2")
    p = os.path.join(saida, "_RadAI", RI.NOME_RECIBO)
    checar(u"o recibo existe", os.path.isfile(p))
    txt = io.open(p, encoding="utf-8").read()
    checar(u"  nao leva a descricao digitada (campo livre)", u"BELTRANO" not in txt)
    dado = json.loads(txt)
    checar(u"  e uma lista que ACRESCENTA", isinstance(dado, list) and len(dado) == 1)
    g = dado[0]["geometria_informada"]
    checar(u"  registra a geometria digitada", g["espessura_mm"] == 5.0)
    checar(u"  e diz que ela foi DIGITADA, nao medida",
           "digitada" in g.get("fonte", ""), str(g.get("fonte")))
    checar(u"  e quem digitou", dado[0]["quem"] == "dr_teste")
    checar(u"  e que o Frame e proprio", "proprio" in dado[0]["frame_of_reference"])
    checar(u"  e o paciente DESCONHECIDO com o ID gerado",
           RI.DESCONHECIDO in dado[0]["paciente"]
           and r["id_externo"] in dado[0]["paciente"], dado[0].get("paciente"))
    checar(u"  e so o FATO do texto no pixel", dado[0]["texto_no_pixel"] is True)
    RI.gravar_recibo(saida, s, GEO, {"gravados": 4}, quem="segundo")
    dado2 = json.loads(io.open(p, encoding="utf-8").read())
    checar(u"  e a segunda entrada nao apaga a primeira", len(dado2) == 2)


def teste_a_volta_pelo_dicom_bridge():
    secao(u"a volta: o DicomBridge relendo o que gravamos")
    import radai_image as RI
    import radai_dicom
    d = temp()
    fantoma(d, n=6, carimbo=False, prefixo="image_s0001_i")
    s = RI.varrer(d)["series"][0]
    saida = os.path.join(temp(), "volta")
    RI.converter(s, saida, GEO, modalidade="MR", como="sc")
    v = radai_dicom.varrer(saida)
    checar(u"o bridge ve UMA serie", len(v["series"]) == 1, str(len(v["series"])))
    if not v["series"]:
        return
    ser = v["series"][0]
    checar(u"  com os 6 cortes", int(ser["cortes"]) == 6, str(ser["cortes"]))
    checar(u"  e a modalidade declarada", str(ser["modalidade"]) == "MR")
    checar(u"  e ordenada por POSICAO (a geometria fecha)",
           str(ser["ordenado_por"]) == "posicao", str(ser["ordenado_por"]))
    l = radai_dicom.conferir(ser)
    checar(u"  e o laudo do TPS nao tem impedimento",
           not any(a.get("impede") for a in l["achados"]))
    checar(u"  mas AVISA que nao ha escala de Hounsfield",
           any(u"Rescale" in a["titulo"] for a in l["achados"]),
           str([a["titulo"] for a in l["achados"]]))


def teste_as_sugestoes_saem_da_descricao():
    secao(u"orientacao, modalidade, espessura e escala sugeridas")
    import radai_image as RI
    casos = ((u"RM t2 axial", u"axial"), (u"T2_TSE_TRA", u"axial"),
             (u"COR T1 pós", u"coronal"), (u"sag stir", u"sagital"),
             (u"RM T2 SAGITTAL", u"sagital"), (u"TC tórax", u""),
             (u"axial e coronal", u""), (u"RM coração", u""),
             (u"Transversal 3mm", u"axial"))
    for texto, esperado in casos:
        checar(u"«%s» → «%s»" % (texto, esperado or u"(nenhuma)"),
               RI.orientacao_da_descricao(texto) == esperado,
               RI.orientacao_da_descricao(texto))
    checar(u"a modalidade sai da descricao",
           RI.modalidade_da_descricao(u"RM T2 axial") == u"MR"
           and RI.modalidade_da_descricao(u"TC torax") == u"CT"
           and RI.modalidade_da_descricao(u"serie 3") == u"")
    checar(u"a espessura escrita na descricao vira a sugestao",
           RI.espessura_da_descricao(u"RM T2 AX 3mm") == 3.0
           and RI.espessura_da_descricao(u"t1 4,5 mm") == 4.5
           and RI.espessura_da_descricao(u"t1 sem numero") is None)
    s = {"dimensoes": [(512, 512)]}
    g = RI.sugestoes(s, u"RM T2 axial")
    checar(u"a escala sugerida e o campo tipico dividido pela matriz",
           abs(g["espacamento_mm"] - 240.0 / 512) < 0.001
           and g["fov_mm"] == 240.0, str(g))
    checar(u"  e a espessura sugerida existe mesmo sem numero",
           g["espessura_mm"] == RI.ESPESSURA_SUGERIDA_MM["MR"]
           and g["orientacao"] == u"axial", str(g))
    checar(u"  e a TC tem o campo dela",
           RI.sugestoes(s, u"TC abdome")["fov_mm"] == 400.0)
    checar(u"a descricao sugerida vem da pasta da serie",
           RI.descricao_sugerida(u"C:\\x\\RM_T2_AXIAL", u"img_#")
           == u"RM T2 AXIAL")
    checar(u"  e a pasta nossa (sessao, impressao) nao vira descricao",
           RI.descricao_sugerida(u"C:\\t\\" + u"a" * 32, u"rm_t2_axial_#")
           == u"rm t2 axial"
           and RI.descricao_sugerida(u"C:\\t\\d1a2b3c4d5", u"x_#") == u"x")
    checar(u"  e a pasta achatada da area de envio guarda o nome",
           RI.descricao_sugerida(u"C:\\t\\d1a2b3c4d_RM_SAG", u"x_#") == u"RM SAG")


def teste_o_mpr_mostra_a_deformacao():
    secao(u"o MPR: a esfera so sai redonda com a escala e a espessura certas")
    import numpy as np
    import radai_image as RI
    d = esfera(os.path.join(temp(), "esfera"), n=20, esc=1.0, esp=2.0)
    s = RI.varrer(d)["series"][0]
    vol, passo = RI.volume(s)
    checar(u"o volume tem os 20 cortes", vol.shape == (20, 64, 64), str(vol.shape))

    def razao(img):
        ys, xs = np.nonzero(img > 100)
        if not len(ys):
            return 0.0
        return float(ys.max() - ys.min() + 1) / float(xs.max() - xs.min() + 1)
    certo = RI.mpr(vol, passo, "linha", 1.0, 1.0, 2.0, "axial")
    errado = RI.mpr(vol, passo, "linha", 1.0, 1.0, 4.0, "axial")
    col = RI.mpr(vol, passo, "coluna", 1.0, 1.0, 2.0, "axial")
    checar(u"com escala e espessura certas, a esfera sai redonda",
           abs(razao(certo) - 1.0) < 0.15, u"%.2f" % razao(certo))
    checar(u"  nas duas reconstrucoes", abs(razao(col) - 1.0) < 0.15,
           u"%.2f" % razao(col))
    checar(u"com a espessura dobrada, ela sai esticada (o erro APARECE)",
           razao(errado) > 1.6, u"%.2f" % razao(errado))
    checar(u"os planos tem nome pela orientacao",
           RI.PLANOS_DO_MPR["axial"] == {"linha": u"coronal", "coluna": u"sagital"})
    try:
        RI.mpr(vol, passo, "linha", 0, 0, 2.0)
        recusou = False
    except RI.Recusa:
        recusou = True
    checar(u"escala zero e recusada, sem divisao por zero", recusou)
    cli = _app()
    b = _imagens(cli, d)[0][0]["bilhete"]
    m = cli.get("/api/imagem/mpr", b=b, corte="linha", er=1.0, ec=1.0,
                entre=2.0, ori="axial")
    checar(u"a rota do MPR responde PNG com a altura da conta",
           m.status_code == 200 and _altura_png(bytes(m.body)) == 40
           and _largura_png(bytes(m.body)) == 64, str(m.status_code))
    m2 = cli.get("/api/imagem/mpr", b=b, corte="linha", er=1.0, ec=1.0,
                 entre=4.0, ori="axial")
    checar(u"  e muda quando a espessura muda", _altura_png(bytes(m2.body)) == 80)
    m3 = cli.get("/api/imagem/mpr", b="morto", corte="linha", er=1.0, ec=1.0,
                 entre=2.0, ori="axial")
    checar(u"bilhete morto devolve 404", m3.status_code == 404)


TOLERANCIA_DO_REDONDO = 0.06


def esfera_mm(pasta, lado=128, esc=1.875, esp=3.0, raio=45.0, entre=None,
              margem=2):
    import math
    import numpy as np
    os.makedirs(pasta, exist_ok=True)
    passo_z = float(entre or esp)
    n = int(math.ceil(2.0 * raio / passo_z)) + 2 * margem
    zc = (n - 1) * passo_z / 2.0
    yy, xx = np.mgrid[0:lado, 0:lado]
    d2 = ((xx - lado / 2.0) * esc) ** 2 + ((yy - lado / 2.0) * esc) ** 2
    for k in range(n):
        r2 = raio ** 2 - (k * passo_z - zc) ** 2
        corte = np.where((r2 > 0) & (d2 <= r2), 220, 10).astype(np.uint8)
        escrever_png(os.path.join(pasta, "img_%04d.png" % (k + 1)),
                     [corte[y].tobytes() for y in range(lado)])
    return n


def _razao_da_esfera(img):
    import numpy as np
    ys, xs = np.nonzero(np.asarray(img) > 100)
    if not len(ys):
        return 0.0
    return float(ys.max() - ys.min() + 1) / float(xs.max() - xs.min() + 1)


def _png_da_rota(resposta):
    import radai_image as RI
    p = os.path.join(temp(), "mpr.png")
    with open(p, "wb") as f:
        f.write(bytes(resposta.body))
    return RI.ler_cinza(p)


def _mpr_pela_rota(cli, b, esc, entre, ori="axial"):
    fora = {}
    for corte in ("linha", "coluna"):
        m = cli.get("/api/imagem/mpr", b=b, corte=corte, er=esc, ec=esc,
                    entre=entre, ori=ori)
        fora[corte] = (_razao_da_esfera(_png_da_rota(m))
                       if m.status_code == 200 else 0.0)
    return fora


def _redondas(razoes, alvo=1.0, tol=TOLERANCIA_DO_REDONDO):
    return all(abs(r / alvo - 1.0) <= tol for r in razoes)


def _esferas_pelo_pipeline(cli, casos):
    fora = []
    for esp, d in casos:
        f = _imagens(cli, d)[0][0]
        g = f["sugestoes"]
        r = _mpr_pela_rota(cli, f["bilhete"], g["espacamento_mm"],
                           g["espessura_mm"])
        fora.append((esp, g, r))
    return fora


def teste_o_mpr_redondo_em_1_3_5_mm():
    secao(u"o MPR da imagem: a esfera sai redonda em 1, 3 e 5 mm pelo pipeline")
    import numpy as np
    import radai_image as RI
    raiz = temp()
    casos = []
    for esp in (1.0, 3.0, 5.0):
        d = os.path.join(raiz, u"RM_T2_AX_%dmm" % int(esp))
        esfera_mm(d, esp=esp)
        casos.append((esp, d))
    cli = _app()
    medidas = _esferas_pelo_pipeline(cli, casos)
    for esp, g, r in medidas:
        checar(u"%d mm: a descrição sugere a espessura e a escala do fantoma"
               % int(esp),
               g["espessura_mm"] == esp and abs(g["espacamento_mm"] - 1.875) < 1e-9,
               str(g))
        checar(u"  e o coronal e o sagital saem redondos (altura/largura %.3f e %.3f)"
               % (r["linha"], r["coluna"]),
               _redondas((r["linha"], r["coluna"])), str(r))

    original = RI.mpr

    def _isca_um_pixel_por_corte(vol, passo, corte, er, ec, entre,
                                 orientacao="axial"):
        n, alt, larg = vol.shape
        plano = vol[:, alt // 2, :] if corte == "linha" else vol[:, :, larg // 2]
        return np.ascontiguousarray(plano[::-1, :])

    def _isca_sem_a_espessura(vol, passo, corte, er, ec, entre,
                              orientacao="axial"):
        return original(vol, passo, corte, er, ec,
                        RI.ESPESSURA_SUGERIDA_MM["MR"], orientacao)

    for nome, isca in ((u"um pixel por corte", _isca_um_pixel_por_corte),
                       (u"a espessura digitada que não chega ao MPR",
                        _isca_sem_a_espessura)):
        RI.mpr = isca
        try:
            med = _esferas_pelo_pipeline(cli, casos)
        finally:
            RI.mpr = original
        todas = [x for _e, _g, r in med for x in (r["linha"], r["coluna"])]
        checar(u"a isca (%s) sai achatada ou esticada e reprova" % nome,
               not _redondas(todas), u"%s" % [round(x, 3) for x in todas])


def teste_achatado_com_a_espessura_certa_e_escala_ou_intervalo():
    secao(u"achatado com a espessura certa: a escala maior que a real, ou o intervalo")
    raiz = temp()
    zoom = os.path.join(raiz, u"RM_T2_AX_3mm")
    esfera_mm(zoom, esc=1.0, raio=30.0, esp=3.0)
    cli = _app()
    f = _imagens(cli, zoom)[0][0]
    g = f["sugestoes"]
    alvo = 1.0 / g["espacamento_mm"]
    r = _mpr_pela_rota(cli, f["bilhete"], g["espacamento_mm"], 3.0)
    checar(u"imagem exportada com zoom (1 mm/pixel) e a escala sugerida (%.3f): "
           u"achatada na razão das escalas (%.3f e %.3f, alvo %.3f)"
           % (g["espacamento_mm"], r["linha"], r["coluna"], alvo),
           _redondas((r["linha"], r["coluna"]), alvo=alvo, tol=0.08), str(r))
    r = _mpr_pela_rota(cli, f["bilhete"], 1.0, 3.0)
    checar(u"  e com a escala real ela sai redonda (%.3f e %.3f)"
           % (r["linha"], r["coluna"]), _redondas((r["linha"], r["coluna"])),
           str(r))

    gap = os.path.join(raiz, u"RM_T2_AX_3mm_gap")
    os.makedirs(gap)
    esfera_mm(os.path.join(gap, u"RM_T2_AX_3mm"), esp=3.0, entre=3.5)
    f = _imagens(cli, os.path.join(gap, u"RM_T2_AX_3mm"))[0][0]
    esc = f["sugestoes"]["espacamento_mm"]
    r = _mpr_pela_rota(cli, f["bilhete"], esc, 3.0)
    checar(u"corte de 3 mm com 3,5 mm entre os cortes, sem a distância: "
           u"achatada em 3/3,5 (%.3f e %.3f)" % (r["linha"], r["coluna"]),
           _redondas((r["linha"], r["coluna"]), alvo=3.0 / 3.5), str(r))
    r = _mpr_pela_rota(cli, f["bilhete"], esc, 3.5)
    checar(u"  e com a distância entre cortes informada ela sai redonda "
           u"(%.3f e %.3f)" % (r["linha"], r["coluna"]),
           _redondas((r["linha"], r["coluna"])), str(r))


def _sinal_fisico_do_dicom(pasta):
    import numpy as np
    import pydicom
    cortes = []
    for n in sorted(os.listdir(pasta)):
        if n.lower().endswith(".dcm"):
            ds = pydicom.dcmread(os.path.join(pasta, n))
            cortes.append((float(ds.ImagePositionPatient[2]), ds))
    cortes.sort(key=lambda x: x[0])
    zs = [z for z, _ds in cortes]
    passos = sorted(round(b - a, 4) for a, b in zip(zs, zs[1:]))
    passo = passos[len(passos) // 2] if passos else 0.0
    com = [ds for _z, ds in cortes if int(ds.pixel_array.max()) > 100]
    meio = com[len(com) // 2].pixel_array
    xs = np.nonzero(meio[meio.shape[0] // 2] > 100)[0]
    ps = [float(x) for x in com[0].PixelSpacing]
    largura_mm = float(xs.max() - xs.min() + 1) * ps[1]
    return {"passo": passo, "ps": ps, "altura_mm": len(com) * passo,
            "largura_mm": largura_mm, "ds": cortes[0][1], "n": len(cortes)}


def teste_o_dicom_convertido_leva_o_espacamento_do_mpr():
    secao(u"o DICOM convertido leva a espessura e o espaçamento que o MPR desenhou")
    import radai_dicom
    import radai_image_screen as RIS
    raiz = temp()
    for entre in (0, 3.5):
        nome = u"RM_T2_AX_3mm"
        d = os.path.join(raiz, u"e%s" % str(entre).replace(".", "_"), nome)
        n = esfera_mm(d, esp=3.0, entre=entre or None)
        s = __import__("radai_image").varrer(d)["series"][0]
        pedido = {"geometria": {"espacamento_mm": [1.875, 1.875],
                                "espessura_mm": 3.0, "entre_cortes_mm": entre,
                                "primeiro_corte_mm": 0, "orientacao": "axial",
                                "posicao_paciente": "HFS"},
                  "descricao": nome, "modalidade": "MR", "como": "sc",
                  "aceitar": []}
        destino = os.path.join(temp(), u"saida")
        RIS.converter_do_pedido(s, destino, pedido)
        esperado = float(entre or 3.0)
        lida = radai_dicom.varrer(destino, relembrar=False)["series"]
        sd = lida[0] if lida else {}
        rotulo = u"entre cortes %s" % (u"vazio" if not entre else u"3,5 mm")
        checar(u"%s: a varredura DICOM da Suite lê %d cortes, espessura 3 e passo %s"
               % (rotulo, n, esperado),
               len(lida) == 1 and sd.get("cortes") == n
               and sd.get("espessura_declarada_mm") == 3.0
               and sd.get("espessura_mm") == esperado,
               str({k: sd.get(k) for k in ("cortes", "espessura_mm",
                                           "espessura_declarada_mm")}))
        fis = _sinal_fisico_do_dicom(destino)
        ds = fis["ds"]
        checar(u"  PixelSpacing, SliceThickness e SpacingBetweenSlices são os informados",
               fis["ps"] == [1.875, 1.875] and float(ds.SliceThickness) == 3.0
               and float(ds.SpacingBetweenSlices) == esperado
               and fis["passo"] == esperado,
               u"%s %s %s %s" % (fis["ps"], ds.SliceThickness,
                                 ds.SpacingBetweenSlices, fis["passo"]))
        razao = fis["altura_mm"] / fis["largura_mm"] if fis["largura_mm"] else 0
        checar(u"  e a esfera, medida em milímetro no DICOM, é redonda (%.3f)" % razao,
               abs(razao - 1.0) <= TOLERANCIA_DO_REDONDO,
               u"%.1f x %.1f mm" % (fis["altura_mm"], fis["largura_mm"]))


def teste_a_ordem_alfabetica_pede_confirmacao():
    secao(u"a ordem alfabetica so passa com a confirmacao")
    import radai_image as RI
    d = temp()
    for nome in ("alfa", "beta", "gama"):
        escrever_png(os.path.join(d, nome + ".png"),
                     [bytes(range(16)) for _ in range(8)])
    s = RI.varrer(d)["series"][0]
    checar(u"a ordem e uma decisao", RI.TITULO_DA_ORDEM in RI.decidiveis(s))
    try:
        RI.converter(s, os.path.join(temp(), "o"), GEO)
        gravou = True
    except RI.Recusa:
        gravou = False
    checar(u"sem confirmar, NAO converte", not gravou)
    r = RI.converter(s, os.path.join(temp(), "o2"), GEO,
                     aceitar=[RI.TITULO_DA_ORDEM])
    checar(u"confirmada, converte", r["gravados"] == 3)
    try:
        RI.converter(s, os.path.join(temp(), "o3"),
                     dict(GEO, espacamento_mm=None),
                     aceitar=[RI.TITULO_DA_ORDEM, RI.FALTAS_DA_GEOMETRIA[0][1]])
        sem = True
    except RI.Recusa:
        sem = False
    checar(u"  e a escala que falta nao se aceita (dado que falta nunca se dispensa)",
           not sem)


def teste_a_tela_esta_costurada():
    secao(u"a costura: o ajuste dentro do pipeline, as rotas e o que saiu")
    import radai_image_screen as T
    import radai_bridge as B
    try:
        cli = _app()
    except Exception as e:
        checar(u"o DicomBridge monta", False, str(e)[:90])
        return
    r = cli.get("/bridge/imagem")
    checar(u"/bridge/imagem leva ao pipeline (307 para /bridge/laudo)",
           getattr(r, "status_code", 0) == 307
           and dict(getattr(r, "headers", {})).get("location") == "/bridge/laudo",
           str(getattr(r, "status_code", r)))
    p = B.pagina()
    bloco = p[p.find(u'id="dc_bloco_imagem"'):p.find(u'id="dc_bloco_dicom"')]
    checar(u"o ajuste da imagem mora na etapa do diagnóstico do pipeline",
           u'id="im_esp"' in bloco and u'id="im_conf_escala"' in bloco
           and p.find(u'id="dc_e3"') < p.find(u'id="dc_bloco_imagem"')
           < p.find(u'id="dc_e4"'), str(len(bloco)))
    checar(u"  e diz, no painel, que o Frame of Reference é próprio",
           T.NOTA_DO_FRAME in bloco and u"Hounsfield" in T.NOTA_DO_FRAME)
    checar(u"a espessura é obrigatória e treme vazia",
           u'required' in bloco
           and u"esp: ['im_esp', 'informe a espessura do corte']" in T.JS
           and u"bgTremer(bgEl(c[0]))" in _corpo_js(T.JS, u"imCobrar"))
    conv = _corpo_js(B.JS, u"dcConverter")
    checar(u"  e «Converter» cobra cada série de imagem antes de pedir a conversão",
           u"imFalta(si)" in conv and u"imCobrar(falta)" in conv
           and conv.find(u"imCobrar(falta)") < conv.find(u"/api/bridge/etapa/converter"),
           conv[:200])
    tremer = _corpo_js(B.JS_COMUM, u"bgTremer")
    checar(u"  e o tremor é o da casca (C3: uiTremer), sem animação própria",
           u"window.uiTremer(el)" in tremer and u"@keyframes" not in B.CSS_COMUM
           and u"classList" not in tremer, tremer[:120])
    falta = _corpo_js(T.JS, u"imFalta")
    checar(u"a escala se confirma num clique, ao lado do MPR",
           u'id="im_mpr_linha"' in bloco and u'id="im_mpr_coluna"' in bloco
           and u"if(!e.escala) return 'escala'" in falta, falta[:200])
    checar(u"  (isca) sem a cobrança da escala, a série passaria",
           u"return 'escala'" not in falta.replace(u"if(!e.escala) return 'escala';", u""))
    checar(u"mudar a escala desfaz a confirmação",
           u"e.escala = false" in _corpo_js(T.JS, u"imEscalaMudou")
           and re.search(r'id="im_esc"[^>]*oninput="imEscalaMudou\(\)"', bloco))
    botao = re.search(r'id="im_conf_escala"[^>]*>(.*?)</button>', bloco, re.S)
    checar(u"o botão diz que se conferiu no MPR a escala e a ordem dos cortes",
           botao and T.BOTAO_CONFIRMAR in botao.group(1)
           and all(p in T.BOTAO_CONFIRMAR for p in (u"MPR", u"escala", u"ordem")),
           botao.group(1)[:120] if botao else u"sem botão")
    checar(u"  com a frase curta do porquê ao lado: a cabeça para cima no coronal e "
           u"no sagital", T.NOTA_DA_CONFIRMACAO in bloco
           and all(p in T.NOTA_DA_CONFIRMACAO for p in (u"cabeça para cima", u"coronal",
                                                         u"sagital", u"registro rígido")))
    inv = _corpo_js(T.JS, u"imInverter")
    checar(u"inverter a ordem desfaz a confirmação", u"e.escala = false" in inv, inv[:160])
    checar(u"  (isca) a inversão antiga, que não a desfazia, é acusada",
           u"e.escala = false" not in u"{ e.invertida = !e.invertida; imMudou(true) }")
    checar(u"a ordem se confirma junto com a escala: o botão separado saiu e a decisão "
           u"da ordem alfabética vai com a confirmação",
           u"im_conf_ordem" not in bloco and u"im_conf_ordem" not in T.JS
           and u"e.ordem" not in T.JS
           and u"e.escala ?" in _corpo_js(T.JS, u"imAceitosDe"), _corpo_js(T.JS, u"imAceitosDe"))
    nota = _corpo_js(T.JS, u"imNotaEscala")
    import radai_phrases as F
    dic = F.construir()
    checar(u"a nota da escala sugerida é a frase com chave, e os números entram como valor",
           u"IM_NOTA_SUGERIDA" in nota and u"sugerida para um campo" not in nota
           and json.dumps(T.NOTA_DA_SUGERIDA, ensure_ascii=False) in T.JS
           and T.NOTA_DA_SUGERIDA.count(u"%s") == 2
           and all((dic[c].get(F.normalizar(T.NOTA_DA_SUGERIDA)) or u"").count(u"%s") == 2
                   for c in F.CODIGOS), nota[:200])
    checar(u"  (isca) a concatenação antiga é acusada",
           u"sugerida para um campo" in u"('sugerida para um campo de ' + imPor(g.fov_mm))")
    ajuda = T.AJUDA_NO_PIPELINE[0]
    checar(u"o «?» do ajuste cita a medida, a inversão e a confirmação da escala e da ordem",
           all(p in ajuda for p in (T.BOTAO_MEDIR, T.BOTAO_INVERTER, u"pés", u"MPR"))
           and u"escala e a ordem" in ajuda, ajuda[:200])
    ligados = dict((m.group(1), m.group(2)) for m in re.finditer(
        r'id="(im_esp|im_entre)"[^>]*oninput="([^"]*)"', bloco))
    checar(u"  e a espessura e a distância entre cortes não a desfazem",
           len(ligados) == 2 and not any(u"imEscalaMudou" in v
                                         for v in ligados.values()), str(ligados))
    checar(u"  (isca) a ligação antiga da espessura seria acusada",
           u"imEscalaMudou" in re.search(
               r'id="im_esp"[^>]*oninput="([^"]*)"',
               u'<input type="text" id="im_esp" oninput="imEscalaMudou()">').group(1))
    checar(u"a distância entre cortes mora ao lado da espessura, fora de «mais ajustes»",
           u'id="im_entre"' in bloco and u'id="im_entre"' not in bloco[
               bloco.find(u"<details"):bloco.find(u"</details>")]
           and bloco.find(u'id="im_esp"') < bloco.find(u'id="im_entre"')
           < bloco.find(u'id="im_esc"'))
    checar(u"  com a frase do que ela é", T.NOTA_DO_ENTRE in bloco
           if hasattr(T, "NOTA_DO_ENTRE") else False)
    checar(u"mudar a geometria descarta a conversão feita com a antiga",
           u"dcImagemMudou(IM.atual)" in _corpo_js(T.JS, u"imMudou")
           and u"dcVoltarA(3)" in _corpo_js(B.JS, u"dcImagemMudou"))
    checar(u"saíram «Ajustar e finalizar» e «Baixar de novo»",
           all(x not in p and x not in B.JS for x in (
               u"Ajustar e finalizar", u"Baixar de novo", u"im_finalizar",
               u"im_de_novo", u"/api/imagem/finalizar")))
    checar(u"o brilho da casca nas prévias e no MPR",
           u"bgBrilho(" in _corpo_js(T.JS, u"imMpr")
           and u"bgBrilho(" in _corpo_js(T.JS, u"imVisor"))
    visor = _corpo_js(T.JS, u"imVisor")
    checar(u"o visor das prévias para o brilho no erro: aoParar e o vigia da casca",
           u"aoParar:" in visor and u"bgVigiarVisor(cx, IM.visor" in visor
           and u"imVisorFalhou(" in visor, visor[:200])
    vigia = _corpo_js(B.JS_COMUM, u"bgVigiarVisor")
    checar(u"  o vigia apaga o brilho quando nenhum corte chega e todos falham",
           u"c.nFalhos" in vigia and u"parar();" in vigia and u"aoFalhar()" in vigia,
           vigia[:200])
    checar(u"  e diz o motivo que o servidor mandou",
           u"X-RadAI-Motivo" in _corpo_js(T.JS, u"imVisorFalhou")
           and u'id="im_visor_msg"' in bloco)
    import radai_image as RI
    original = RI.ler_cinza

    def _recusa(_c):
        raise RI.Recusa(u"este runtime não tem Pillow")
    RI.ler_cinza = _recusa
    try:
        dd = temp()
        fantoma(dd, n=3, prefixo="image_s0001_i")
        b = ((_imagens(cli, dd)[0] or [{}])[0]).get("bilhete") or ""
        rp = cli.get("/api/imagem/previa", b=b, k=1)
    finally:
        RI.ler_cinza = original
    from urllib.parse import unquote
    motivo = unquote(str(getattr(rp, "headers", {}).get("x-radai-motivo") or ""))
    checar(u"a prévia que o runtime não lê responde 422 com o motivo, legível",
           getattr(rp, "status_code", 0) == 422 and u"Pillow" in motivo
           and u"não" in motivo, u"%s %s" % (getattr(rp, "status_code", 0), motivo))
    checar(u"a orientação vem da descrição para conferir",
           u"imOrientacaoDe(" in _corpo_js(T.JS, u"imDescricaoMudou")
           and u"tirada da descrição da série: confira" in T.JS)
    checar(u"a etapa de identidade saiu",
           all(x not in p for x in (u"im_ref_serie", u"Ler identidade",
                                    u"/api/imagem/identidade")))
    checar(u"  e o recorte também", all(x not in p and x not in B.JS for x in (
        u"im_carimbo", u"Recortar as faixas", u"imRecorte", u"recortar:")))
    checar(u"  (isca) a busca acha o recorte antigo",
           u"imRecorte" in u"function imRecorte(liga){}")
    for metodo, rota in (("GET", "/bridge/imagem"),
                         ("POST", "/api/imagem/laudo"),
                         ("GET", "/api/imagem/previa"),
                         ("GET", "/api/imagem/mpr")):
        checar(u"%s %s existe" % (metodo, rota), cli.tem(metodo, rota))
    for metodo, rota in (("POST", "/api/imagem/carregar"),
                         ("POST", "/api/imagem/finalizar"),
                         ("POST", "/api/imagem/de_novo"),
                         ("POST", "/api/imagem/descartar"),
                         ("POST", "/api/imagem/varrer"),
                         ("POST", "/api/imagem/converter"),
                         ("POST", "/api/imagem/identidade"),
                         ("GET", "/api/bridge/baixar")):
        checar(u"%s %s saiu" % (metodo, rota), not cli.tem(metodo, rota))
    import inspect
    for rota in ("/api/imagem/previa", "/api/imagem/mpr"):
        args = inspect.signature(cli.rotas[("GET", rota)]).parameters
        checar(u"%s não recebe caminho" % rota,
               not any(n in args for n in ("pasta", "caminho", "dir", "raiz")),
               str(list(args)))
    fonte = io.open(_componentes.fonte("app/radai_image_screen.py"),
                    encoding="utf-8").read()
    checar(u"o módulo não usa mais o .zip de entrega",
           u"radai_delivery_tps" not in fonte and u"empacotar" not in fonte)


def teste_o_fluxo_da_tela_ponta_a_ponta():
    secao(u"o fluxo no pipeline, chamando as rotas de verdade")
    import pydicom
    import radai_image as RI
    try:
        cli = _app()
    except Exception as e:
        checar(u"o DicomBridge monta", False, str(e)[:90])
        return
    d = temp()
    serie = os.path.join(d, u"RM_T2_AXIAL")
    os.makedirs(serie)
    fantoma(serie, n=6, carimbo=True, prefixo="rm_t2_ax")
    fantoma(os.path.join(d, u"OUTRA"), n=0)
    imgs, r = _imagens(cli, d)
    checar(u"a carga do pipeline acha a série de imagem, na subpasta", len(imgs) == 1,
           str(r)[:160])
    if not imgs:
        return
    s = imgs[0]
    checar(u"  devolve um BILHETE, e nenhum caminho",
           bool(s.get("bilhete")) and d not in json.dumps(r, ensure_ascii=False))
    checar(u"  e entra na grade como série de imagem, que não se segmenta",
           s.get("imagem") is True and s.get("modalidade") == u"JPEG/PNG"
           and s.get("cortes") == 6, str(s)[:160])
    checar(u"  com a descrição da pasta e a orientação tirada dela",
           s["descricao"] == u"RM T2 AXIAL"
           and s["sugestoes"]["orientacao"] == u"axial", str(s)[:160])
    checar(u"  e a escala e a espessura sugeridas",
           s["sugestoes"]["espacamento_mm"] and s["sugestoes"]["espessura_mm"])
    vazio, rv = _imagens(cli, temp())
    checar(u"pasta sem imagem não lista imagem", vazio == [] and not rv.get("erro"),
           str(rv)[:90])

    l = cli.post("/api/imagem/laudo", {"b": s["bilhete"], "geometria": {}})
    checar(u"o laudo cobra a escala", any(u"escala" in t for t in _bloqueiam(l)))
    checar(u"  e alerta o texto no pixel e a identidade",
           sum(1 for a in l["achados"] if a.get("alerta")) == 2,
           str([a["titulo"] for a in l["achados"] if a.get("alerta")]))
    carimbo = [a for a in l["achados"] if a.get("titulo") == RI.TITULO_DO_CARIMBO]
    checar(u"  o texto no pixel é UMA linha, sem pergunta e sem detalhe",
           len(carimbo) == 1 and not carimbo[0].get("detalhe")
           and not carimbo[0].get("o_que_faz") and carimbo[0].get("resolve") is None,
           str(carimbo)[:160])

    geo = {"espacamento_mm": [0.8, 0.8], "espessura_mm": 5.0,
           "orientacao": "axial", "posicao_paciente": "HFS"}
    sem_esp = _converter(cli, d, s["bilhete"], _pedido(dict(geo, espessura_mm=0)))
    checar(u"sem espessura, a conversão RECUSA a série",
           not sem_esp.get("conversao") and sem_esp.get("recusadas"),
           str(sem_esp)[:160])
    dest1, dest2 = temp(), temp()
    c = _converter(cli, d, s["bilhete"], _pedido(geo, descricao=u"RM T2 AXIAL"))
    ex = c.get("exportadas") or []
    checar(u"«Converter» converte a imagem, com o ID gerado",
           c.get("conversao") and len(ex) == 1 and ex[0].get("imagem") is True
           and ex[0].get("cortes") == 6 and ID_EXTERNO.match(ex[0].get("id_externo") or ""),
           str(c)[:200])
    if not c.get("conversao"):
        return
    f = _entregar(cli, c["conversao"], [dest1, dest2])
    checar(u"«Entregar» grava numa pasta DICOM_BRIDGE_<data_hora>",
           not f.get("erro") and re.match(r"^DICOM_BRIDGE_\d{8}_\d{6}$",
                                          f.get("nome") or ""), str(f)[:160])
    if f.get("erro"):
        return
    p1 = os.path.join(dest1, f["nome"])
    checar(u"  copiada ao outro destino", os.path.isdir(os.path.join(dest2, f["nome"])))
    checar(u"  sem .zip em lugar nenhum",
           not any(n.lower().endswith(".zip") for dd in (dest1, dest2)
                   for n in os.listdir(dd)))
    leia = os.path.join(p1, RI.NOME_DO_LEIA_ME)
    texto = io.open(leia, encoding="ascii").read() if os.path.isfile(leia) else u""
    idx = ex[0]["id_externo"]
    checar(u"  com o LEIA-ME.txt de uma linha", texto.count(u"\n") == 1
           and u"atribua ao paciente certo no tps" in texto.lower()
           and idx in texto, texto)
    checar(u"  e a resposta diz o ID para a tela", f.get("ids_externos") == [idx],
           str(f.get("ids_externos")))
    dcms = sorted(n for n in os.listdir(os.path.join(p1, u"IMAGEM"))
                  if n.endswith(".dcm"))
    checar(u"  e os 6 cortes", len(dcms) == 6)
    a = pydicom.dcmread(os.path.join(p1, u"IMAGEM", dcms[0]), force=True)
    checar(u"  como paciente DESCONHECIDO, com o ID da resposta",
           str(a.PatientName) == u"DESCONHECIDO" and str(a.PatientID) == idx)
    checar(u"  e a descrição digitada", str(a.SeriesDescription) == u"RM T2 AXIAL")
    de_novo = _entregar(cli, c["conversao"], [dest1])
    checar(u"a conversão entregue não se entrega de novo (converta de novo)",
           u"converta de novo" in str(de_novo.get("erro")), str(de_novo)[:120])
    ruim = cli.post("/api/imagem/laudo", {"b": "naoexiste", "geometria": geo})
    checar(u"bilhete morto pede a pasta de novo, e não serve outra série",
           u"carregue a pasta" in str(ruim.get("erro", u"")), str(ruim)[:90])
    shutil.rmtree(dest1, ignore_errors=True)
    shutil.rmtree(dest2, ignore_errors=True)


def teste_o_destino_que_sincroniza_e_recusado():
    secao(u"destino que sincroniza é recusado, nos dois conversores")
    import radai_image as RI
    import radai_archive as RA

    d = temp()
    fantoma(d, n=4, prefixo="image_s0001_i")
    s = RI.varrer(d)["series"][0]
    geo = {"espacamento_mm": (0.8, 0.8), "espessura_mm": 3.0,
           "orientacao": "axial", "posicao_paciente": "HFS"}

    orig = RA.em_pasta_sincronizada
    try:
        RA.em_pasta_sincronizada = lambda c=None: (True, u"Drive espelha X")
        erro = u""
        gravou = False
        try:
            RI.converter(s, temp(), geo)
            gravou = True
        except RI.Recusa as e:
            erro = u"%s" % e
        checar(u"destino que sincroniza NÃO converte", not gravou,
               u"gravou serie em raiz espelhada")
        checar(u"e a recusa diz por que", u"nuvem" in erro.lower(), erro[:130])
        RA.em_pasta_sincronizada = orig
        cli = _app()
        b = _imagens(cli, d)[0][0]["bilhete"]
        c = _converter(cli, d, b, _pedido(dict(geo, espacamento_mm=[0.8, 0.8])))
        nuvem = temp()
        RA.em_pasta_sincronizada = (
            lambda x=None: (os.path.normcase(str(x or u"")).startswith(
                os.path.normcase(nuvem)), u"Drive espelha X"))
        f = _entregar(cli, c.get("conversao"), [nuvem])
        checar(u"  e o pipeline recusa o destino antes de gravar",
               u"nuvem" in str(f.get("erro")) and os.listdir(nuvem) == [],
               str(f)[:120])

        def _explode(c=None):
            raise RuntimeError("sqlite nao abriu")
        RA.em_pasta_sincronizada = _explode
        ok = False
        try:
            r = RI.converter(s, temp(), geo)
            ok = int(r.get("gravados") or 0) == 4
        except Exception as e:
            erro = u"%s: %s" % (type(e).__name__, e)
        checar(u"detector que FALHA não bloqueia a conversão", ok, erro[:130])

        RA.em_pasta_sincronizada = lambda c=None: (False, u"")
        ok2 = False
        try:
            r = RI.converter(s, temp(), geo)
            ok2 = int(r.get("gravados") or 0) == 4
        except Exception as e:
            erro = u"%s: %s" % (type(e).__name__, e)
        checar(u"destino fora de raiz espelhada converte", ok2, erro[:130])
    finally:
        RA.em_pasta_sincronizada = orig

    dic = open(_componentes.fonte("app/radai_dicom.py"),
               encoding="utf-8").read()
    checar(u"`radai_dicom.converter` também confere o destino",
           "em_pasta_sincronizada" in dic, u"o gemeo ficou sem guarda")


def teste_a_tela_nao_oferece_o_frame_da_tc():
    secao(u"a tela não tem como declarar a série já alinhada à TC")
    import inspect
    import pydicom
    try:
        cli = _app()
    except Exception as e:
        checar(u"o DicomBridge monta", False, str(e)[:90])
        return
    d = temp()
    fantoma(d, n=4, carimbo=False, prefixo="image_s0001_i")
    b = _imagens(cli, d)[0][0]["bilhete"]
    geo = {"espacamento_mm": [1.0, 1.0], "espessura_mm": 3.0,
           "orientacao": "axial", "posicao_paciente": "HFS"}
    forjado = "9.9.9.99999.1.2.3"
    uids = []
    for k in range(2):
        alvo = temp()
        c = cli.post("/api/bridge/etapa/converter", {
            "pasta": d, "frame_of_reference": forjado,
            "series": [{"b": b, "frame_of_reference_uid": forjado,
                        "imagem": _pedido(geo, frame_of_reference=forjado,
                                          frame_of_reference_uid=forjado)}]})
        r = _entregar(cli, c.get("conversao"), [alvo]) if c.get("conversao") else c
        checar(u"a conversão %d passou" % (k + 1),
               (c.get("exportadas") or [{}])[0].get("cortes") == 4 and r.get("nome"),
               str(r)[:110])
        if r.get("nome"):
            uids.append(str(pydicom.dcmread(os.path.join(
                alvo, r["nome"], u"IMAGEM", "IM00001.dcm"),
                force=True).FrameOfReferenceUID))
    checar(u"o Frame forjado no corpo do POST foi ignorado",
           forjado not in uids, str(uids))
    checar(u"  e duas conversões dão Frames diferentes",
           len(uids) == 2 and uids[0] != uids[1])
    for nome in ("app/radai_image_screen.py", "app/radai_bridge.py"):
        fonte = io.open(_componentes.fonte(nome), encoding="utf-8").read()
        checar(u"`%s` não lê nenhum campo de frame do corpo" % nome.split("/")[-1],
               "frame_of_reference" not in fonte.lower().replace(
                   "frame of reference", ""),
               u"parametro que ninguem deve usar e parametro que alguem vai usar")
    checar(u"  e `converter` continua sem parâmetro de frame",
           not any("frame" in a.lower()
                   for a in inspect.signature(
                       __import__("radai_image").converter).parameters))


def _serie_numerada(pasta, n=8, lado=32):
    os.makedirs(pasta, exist_ok=True)
    for k in range(n):
        v = 20 + 10 * k
        escrever_png(os.path.join(pasta, "img_%04d.png" % (k + 1)),
                     [bytes([v] * lado) for _ in range(lado)])
    return [20 + 10 * k for k in range(n)]


def _cortes_do_dicom(pasta):
    import pydicom
    fora = []
    for nome in sorted(os.listdir(pasta)):
        if nome.lower().endswith(".dcm"):
            ds = pydicom.dcmread(os.path.join(pasta, nome))
            fora.append((int(ds.InstanceNumber),
                         float(ds.ImagePositionPatient[2]),
                         int(ds.pixel_array[0, 0])))
    return sorted(fora)


def teste_a_ordem_dos_cortes_se_inverte():
    secao(u"a ordem dos cortes: inverter vira o MPR e o DICOM exportado")
    import radai_image as RI
    import radai_image_screen as RIS
    d = os.path.join(temp(), u"RM_T2_AX")
    valores = _serie_numerada(d)
    n = len(valores)
    cli = _app()
    b = _imagens(cli, d)[0][0]["bilhete"]

    def _coronal(inv, rota=True):
        k = dict(b=b, corte="linha", er=1.0, ec=1.0, entre=1.0, ori="axial")
        if inv is not None:
            k["inv"] = inv
        m = cli.get("/api/imagem/mpr", **k)
        if m.status_code != 200:
            return None
        px = _png_da_rota(m)
        return [min(range(n), key=lambda k: abs(valores[k] * 255 / 256.0
                                                 - int(px[i, 0])))
                for i in range(px.shape[0])]

    em_cima_o_ultimo = list(range(n))[::-1]
    padrao = _coronal(None)
    checar(u"padrão de hoje: no coronal do axial, o primeiro arquivo embaixo "
           u"e o último em cima", padrao == em_cima_o_ultimo, str(padrao))
    invertido = _coronal(1)
    checar(u"invertida: o primeiro arquivo em cima e o último embaixo",
           invertido == list(range(n)), str(invertido))
    checar(u"  inv=0 é o padrão", _coronal(0) == em_cima_o_ultimo)
    original = RI.mpr

    def _isca_ignora(vol, passo, corte, er, ec, entre, orientacao="axial",
                     inverter=False):
        return original(vol, passo, corte, er, ec, entre, orientacao)
    RI.mpr = _isca_ignora
    try:
        isca = _coronal(1)
    finally:
        RI.mpr = original
    checar(u"  (isca) o MPR que ignora a inversão reprova",
           isca != list(range(n)), str(isca))

    geo = {"espacamento_mm": [1.0, 1.0], "espessura_mm": 3.0,
           "entre_cortes_mm": 3.0, "primeiro_corte_mm": 0,
           "orientacao": "axial", "posicao_paciente": "HFS"}

    def _converter_pedido(geometria):
        destino = os.path.join(temp(), u"saida")
        RIS.converter_do_pedido(RI.varrer(d)["series"][0], destino,
                                _pedido(geometria))
        return destino, _cortes_do_dicom(destino)

    _dest, cortes = _converter_pedido(geo)
    checar(u"DICOM padrão: a instância 1 é o primeiro arquivo, no z mais baixo",
           [c[2] for c in cortes] == valores
           and [c[1] for c in cortes] == [3.0 * i for i in range(n)],
           str(cortes))
    dest, cortes = _converter_pedido(dict(geo, ordem_invertida=True))
    checar(u"DICOM invertido: a instância 1 é o ÚLTIMO arquivo, no z mais baixo, "
           u"e o primeiro arquivo fica no topo",
           [c[2] for c in cortes] == valores[::-1]
           and [c[1] for c in cortes] == [3.0 * i for i in range(n)],
           str(cortes))
    recibo = json.loads(io.open(os.path.join(dest, "_RadAI", RI.NOME_RECIBO),
                                encoding="utf-8").read())
    checar(u"  e o recibo registra a ordem invertida",
           recibo[-1]["geometria_informada"].get("ordem_invertida") is True,
           str(recibo[-1]["geometria_informada"]))
    _dest, cortes = _converter_pedido(dict(geo, ordem_invertida="true"))
    checar(u"  só o true literal inverte (o texto «true» não)",
           [c[2] for c in cortes] == valores, str(cortes))
    original_g = RIS.geometria_do_pedido

    def _isca_sem_ordem(c):
        g = original_g(c)
        g.pop("ordem_invertida", None)
        return g
    RIS.geometria_do_pedido = _isca_sem_ordem
    try:
        _dest, isca = _converter_pedido(dict(geo, ordem_invertida=True))
    finally:
        RIS.geometria_do_pedido = original_g
    checar(u"  (isca) o pedido que perde a ordem no caminho reprova",
           [c[2] for c in isca] != valores[::-1], str(isca))


FANTOMA_XYZ = (48, 40, 56)
LADO_DO_VOXEL_MM = 2.0
SALTO_DOS_CORTES = 2
MARCAS = {"cabeca": 250, "frente": 180, "esquerda": 120}
TELA_PADRAO = {"coronal": {"cima": (0, 0, 1), "direita": (1, 0, 0)},
               "sagital": {"cima": (0, 0, 1), "direita": (0, 1, 0)},
               "axial": {"cima": (0, -1, 0), "direita": (1, 0, 0)}}
ONDE_NA_TELA = {"coronal": {"cabeca": "cima", "esquerda": "direita"},
                "sagital": {"cabeca": "cima", "frente": "esquerda"},
                "axial": {"frente": "cima", "esquerda": "direita"}}


def _fantoma_lps():
    import numpy as np
    X, Y, Z = FANTOMA_XYZ
    v = np.full((X, Y, Z), 10, dtype=np.uint8)
    v[4:X - 4, 3:Y - 3, 3:Z - 3] = 60
    cx, cy, cz = X // 2, Y // 2, Z // 2
    v[cx - 2:cx + 3, cy - 2:cy + 3, Z - 9:Z - 4] = MARCAS["cabeca"]
    v[cx - 2:cx + 3, 3:8, cz - 2:cz + 3] = MARCAS["frente"]
    v[X - 9:X - 4, cy - 2:cy + 3, cz - 2:cz + 3] = MARCAS["esquerda"]
    return v


def _cortes_do_fantoma(ori):
    v = _fantoma_lps()
    X, Y, Z = v.shape
    s = SALTO_DOS_CORTES
    if ori == "axial":
        return [v[:, :, z].T for z in range(0, Z, s)]
    if ori == "coronal":
        return [v[:, y, ::-1].T for y in range(0, Y, s)]
    return [v[x, :, ::-1].T for x in range(X - 1, -1, -s)]


def _serie_do_fantoma(pasta, ori, de_tras_para_frente=False):
    os.makedirs(pasta, exist_ok=True)
    cortes = _cortes_do_fantoma(ori)
    if de_tras_para_frente:
        cortes = cortes[::-1]
    for k, a in enumerate(cortes):
        escrever_png(os.path.join(pasta, "img_%04d.png" % (k + 1)),
                     [a[y].tobytes() for y in range(a.shape[0])])
    return len(cortes)


def _centro_das_marcas(img):
    import numpy as np
    a = np.asarray(img).astype(int)
    fora = {}
    for nome, valor in MARCAS.items():
        ys, xs = np.nonzero(np.abs(a - int(valor * 255 / 256)) <= 4)
        if len(ys) >= 4:
            fora[nome] = (float(ys.mean() + 0.5) / a.shape[0],
                          float(xs.mean() + 0.5) / a.shape[1])
    return fora


def _verdade_do_fantoma():
    import numpy as np
    v = _fantoma_lps()
    corpo = np.argwhere(v >= 50).mean(axis=0) * LADO_DO_VOXEL_MM
    return dict((k, np.argwhere(v == val).mean(axis=0) * LADO_DO_VOXEL_MM - corpo)
                for k, val in MARCAS.items())


def _mundo_do_dicom(pasta):
    import numpy as np
    import pydicom
    soma = dict((k, [np.zeros(3), 0]) for k in list(MARCAS) + ["corpo"])
    for nome in os.listdir(pasta):
        if not nome.lower().endswith(".dcm"):
            continue
        ds = pydicom.dcmread(os.path.join(pasta, nome))
        a = ds.pixel_array.astype(int)
        ipp = np.array([float(x) for x in ds.ImagePositionPatient])
        iop = [float(x) for x in ds.ImageOrientationPatient]
        r, c = np.array(iop[:3]), np.array(iop[3:])
        dr, dc = float(ds.PixelSpacing[0]), float(ds.PixelSpacing[1])
        for nome_m, cond in [(k, a == val) for k, val in MARCAS.items()] + [
                ("corpo", a >= 50)]:
            ys, xs = np.nonzero(cond)
            if not len(ys):
                continue
            pts = ipp + np.outer(xs * dc, r) + np.outer(ys * dr, c)
            soma[nome_m][0] += pts.sum(axis=0)
            soma[nome_m][1] += len(ys)
    corpo = soma["corpo"][0] / max(1, soma["corpo"][1])
    return dict((k, soma[k][0] / soma[k][1] - corpo)
                for k in MARCAS if soma[k][1])


def _mpr_do_fantoma(cli, b, ori, inv=0):
    fora = {}
    for corte in ("linha", "coluna"):
        m = cli.get("/api/imagem/mpr", b=b, corte=corte, er=LADO_DO_VOXEL_MM,
                    ec=LADO_DO_VOXEL_MM,
                    entre=LADO_DO_VOXEL_MM * SALTO_DOS_CORTES, ori=ori, inv=inv)
        fora[corte] = _png_da_rota(m) if m.status_code == 200 else None
    return fora


def _apresentacao_padrao(ori, planos):
    import radai_image as RI
    X, Y, Z = FANTOMA_XYZ
    forma = {"coronal": (Z, X), "sagital": (Z, Y), "axial": (Y, X)}
    erros = []
    for corte, img in sorted(planos.items()):
        nome = RI.PLANOS_DO_MPR[ori][corte]
        if img is None:
            erros.append(u"%s sem imagem" % nome)
            continue
        if tuple(img.shape) != forma[nome]:
            erros.append(u"%s %s, esperado %s" % (nome, tuple(img.shape), forma[nome]))
        c = _centro_das_marcas(img)
        for marca, borda in ONDE_NA_TELA[nome].items():
            if marca not in c:
                erros.append(u"%s sem a marca %s" % (nome, marca))
                continue
            y, x = c[marca]
            certo = {"cima": y < 0.35, "direita": x > 0.65, "esquerda": x < 0.35}[borda]
            if not certo:
                erros.append(u"%s: %s em (%.2f, %.2f), esperada a %s"
                             % (nome, marca, y, x, borda))
    return erros


def _coerencia(ori, planos, mundo):
    import numpy as np
    import radai_image as RI
    erros = []
    for corte, img in sorted(planos.items()):
        nome = RI.PLANOS_DO_MPR[ori][corte]
        if img is None:
            erros.append(u"%s sem imagem" % nome)
            continue
        c = _centro_das_marcas(img)
        for marca, (y, x) in c.items():
            w = mundo.get(marca)
            if w is None:
                erros.append(u"%s fora do DICOM" % marca)
                continue
            for eixo, tela in (("cima", 0.5 - y), ("direita", x - 0.5)):
                mm = float(np.dot(w, TELA_PADRAO[nome][eixo]))
                if abs(mm) >= 10 and (tela > 0) != (mm > 0):
                    lado = {("cima", True): u"acima", ("cima", False): u"abaixo",
                            ("direita", True): u"à direita",
                            ("direita", False): u"à esquerda"}[(eixo, tela > 0)]
                    erros.append(u"%s: %s %s do centro na tela, %+.0f mm no DICOM"
                                 % (nome, marca, lado, mm))
    return erros


def _mpr_antigo(vol, passo, corte, er, ec, entre, orientacao="axial", inverter=False):
    import numpy as np
    n, alt, larg = vol.shape
    if corte == "linha":
        plano, lado_mm = vol[:, alt // 2, :], float(ec) * passo
    else:
        plano, lado_mm = vol[:, :, larg // 2], float(er) * passo
    virar = (str(orientacao) == "axial") != bool(inverter)
    if virar:
        plano = plano[::-1, :]
    linhas = max(1, min(int(round(n * float(entre) / lado_mm)), 4 * plano.shape[1]))
    idx = np.clip((np.arange(linhas) * n / float(linhas)).astype(np.int64), 0, n - 1)
    return np.ascontiguousarray(plano[idx, :])


def teste_os_planos_de_serie_coronal_e_sagital():
    secao(u"os planos reconstruídos de série coronal e sagital na apresentação padrão")
    import numpy as np
    import radai_image as RI
    import radai_image_screen as RIS
    raiz = temp()
    cli = _app()
    verdade = _verdade_do_fantoma()
    bilhetes = {}
    for ori in ("axial", "coronal", "sagital"):
        for tras in (False, True):
            d = os.path.join(raiz, u"%s_%s" % (ori.upper(), u"TRAS" if tras else u"PADRAO"))
            _serie_do_fantoma(d, ori, de_tras_para_frente=tras)
            bilhetes[(ori, tras)] = (d, _imagens(cli, d)[0][0]["bilhete"])

    for ori in ("axial", "coronal", "sagital"):
        planos = _mpr_do_fantoma(cli, bilhetes[(ori, False)][1], ori)
        erros = _apresentacao_padrao(ori, planos)
        checar(u"série %s: os dois planos com o eixo dos cortes no lugar e a cabeça, a "
               u"frente e a esquerda do paciente onde a apresentação padrão põe" % ori,
               not erros, u" | ".join(erros[:3]))
    original = RI.mpr
    RI.mpr = _mpr_antigo
    try:
        iscas = dict((ori, _apresentacao_padrao(
            ori, _mpr_do_fantoma(cli, bilhetes[(ori, False)][1], ori)))
            for ori in ("axial", "coronal", "sagital"))
    finally:
        RI.mpr = original
    checar(u"  (isca) o MPR de antes, girado 90 graus, reprova no coronal e no sagital "
           u"e passa no axial", iscas["coronal"] and iscas["sagital"]
           and not iscas["axial"], str(dict((k, len(v)) for k, v in iscas.items())))

    geo = {"espacamento_mm": [LADO_DO_VOXEL_MM] * 2,
           "espessura_mm": LADO_DO_VOXEL_MM * SALTO_DOS_CORTES,
           "entre_cortes_mm": LADO_DO_VOXEL_MM * SALTO_DOS_CORTES,
           "primeiro_corte_mm": 0, "posicao_paciente": "HFS"}

    def _dicom(ori, tras, invertida, orientacoes=None):
        d = bilhetes[(ori, tras)][0]
        destino = os.path.join(temp(), u"saida")
        g = dict(geo, orientacao=ori)
        if invertida:
            g["ordem_invertida"] = True
        guardadas = dict(RI.ORIENTACOES)
        if orientacoes:
            RI.ORIENTACOES.update(orientacoes)
        try:
            RIS.converter_do_pedido(RI.varrer(d)["series"][0], destino, _pedido(g))
        finally:
            RI.ORIENTACOES.clear()
            RI.ORIENTACOES.update(guardadas)
        return _mundo_do_dicom(destino)

    def _igual_a_verdade(mundo):
        return all(k in mundo and float(np.abs(mundo[k] - verdade[k]).max()) <= 4.5
                   for k in MARCAS)

    for ori in ("axial", "coronal", "sagital"):
        mundo = _dicom(ori, False, False)
        checar(u"série %s: o DICOM exportado põe a cabeça, a frente e a esquerda no "
               u"espaço do paciente onde o fantoma as tem (ImageOrientationPatient e "
               u"ImagePositionPatient)" % ori, _igual_a_verdade(mundo),
               str(dict((k, [round(float(x)) for x in v]) for k, v in mundo.items())))
        mundo_t = _dicom(ori, True, True)
        checar(u"  e a série exportada de trás para a frente, invertida, também",
               _igual_a_verdade(mundo_t),
               str(dict((k, [round(float(x)) for x in v]) for k, v in mundo_t.items())))
    girado = _dicom("coronal", False, False,
                    {"coronal": (0, 0, -1, 1, 0, 0)})
    checar(u"  (isca) o DICOM coronal girado 90 graus reprova", not _igual_a_verdade(girado),
           str(dict((k, [round(float(x)) for x in v]) for k, v in girado.items())))

    for ori in ("axial", "coronal", "sagital"):
        for tras, inv in ((False, 0), (True, 0), (True, 1)):
            planos = _mpr_do_fantoma(cli, bilhetes[(ori, tras)][1], ori, inv=inv)
            erros = _coerencia(ori, planos, _dicom(ori, tras, bool(inv)))
            checar(u"série %s %s%s: o que o MPR mostra em cada ponta é o que o DICOM "
                   u"grava" % (ori, u"de trás para a frente" if tras else u"no padrão",
                               u", invertida" if inv else u""),
                   not erros, u" | ".join(erros[:3]))
    planos = _mpr_do_fantoma(cli, bilhetes[("axial", True)][1], "axial", inv=0)
    errado = _apresentacao_padrao("axial", planos)
    checar(u"  e a série axial exportada da cabeça para os pés, sem inverter, mostra a "
           u"cabeça embaixo, junto de «caudal»: é o que a pessoa vê para inverter",
           any(u"cabeca" in e for e in errado), u" | ".join(errado[:2]))

    def _isca_ignora(vol, passo, corte, er, ec, entre, orientacao="axial",
                     inverter=False):
        return original(vol, passo, corte, er, ec, entre, orientacao)
    RI.mpr = _isca_ignora
    try:
        planos = _mpr_do_fantoma(cli, bilhetes[("coronal", True)][1], "coronal", inv=1)
    finally:
        RI.mpr = original
    checar(u"  (isca) o MPR que ignora a inversão de uma série coronal deixa a tela "
           u"contra o DICOM e reprova",
           bool(_coerencia("coronal", planos, _dicom("coronal", True, True))))

    checar(u"as pontas do coronal e do sagital dizem cranial em cima e caudal embaixo",
           all(RI.BORDAS_DO_MPR[p].get("cima") == u"cranial"
               and RI.BORDAS_DO_MPR[p].get("baixo") == u"caudal"
               for p in ("coronal", "sagital")), str(RI.BORDAS_DO_MPR))
    checar(u"  e os lados: no coronal a direita do paciente à esquerda da tela, no "
           u"sagital a frente à esquerda; o axial sem rótulo",
           RI.BORDAS_DO_MPR["coronal"].get("esquerda") == u"direita do paciente"
           and RI.BORDAS_DO_MPR["coronal"].get("direita") == u"esquerda do paciente"
           and RI.BORDAS_DO_MPR["sagital"].get("esquerda") == u"anterior"
           and RI.BORDAS_DO_MPR["sagital"].get("direita") == u"posterior"
           and not RI.BORDAS_DO_MPR.get("axial"), str(RI.BORDAS_DO_MPR))
    palavra = {(0, 0, 1): u"cranial", (0, 0, -1): u"caudal",
               (-1, 0, 0): u"direita do paciente", (1, 0, 0): u"esquerda do paciente",
               (0, -1, 0): u"anterior", (0, 1, 0): u"posterior"}
    lados = {"cima": ("baixo", -1), "baixo": ("baixo", 1),
             "esquerda": ("direita", -1), "direita": ("direita", 1)}
    trocadas = [(p, lado) for p, b in RI.BORDAS_DO_MPR.items() for lado, t in b.items()
                if palavra.get(tuple(lados[lado][1] * v for v in
                                     RI.EIXOS_NA_TELA[p][lados[lado][0]])) != t]
    checar(u"  e cada rótulo é a direção do paciente que os eixos da tela (os mesmos do "
           u"MPR) põem naquela ponta", not trocadas, str(trocadas))
    checar(u"  e os eixos da tela são os da apresentação padrão que o fantoma mediu",
           all(tuple(-v for v in RI.EIXOS_NA_TELA[p]["baixo"]) == TELA_PADRAO[p]["cima"]
               and tuple(RI.EIXOS_NA_TELA[p]["direita"]) == TELA_PADRAO[p]["direita"]
               for p in TELA_PADRAO), str(RI.EIXOS_NA_TELA))


def teste_a_previa_diz_o_passo_para_a_medida():
    secao(u"a medida na prévia: a ficha diz quantos pixels da imagem cabem num da prévia")
    import radai_image_screen as RIS
    cli = _app()
    for lado, alto, passo in ((64, 64, 1), (1600, 1200, 2), (2400, 900, 3)):
        d = os.path.join(temp(), u"RM_%d" % lado)
        os.makedirs(d)
        linha = bytes([90] * lado)
        for k in range(2):
            escrever_png(os.path.join(d, "img_%04d.png" % (k + 1)),
                         [linha] * alto)
        f = _imagens(cli, d)[0][0]
        checar(u"%dx%d: a ficha leva o passo da prévia (%d)" % (lado, alto, passo),
               f.get("passo_previa") == passo, str(f.get("passo_previa")))
        r = cli.get("/api/imagem/previa", b=f["bilhete"], k=0)
        larg = _largura_png(bytes(r.body)) if r.status_code == 200 else 0
        checar(u"  e a prévia servida tem a largura da imagem dividida por ele (%d)"
               % larg, larg == -(-lado // passo), str(r.status_code))
    checar(u"o passo é uma conta só, usada pela prévia e pela ficha",
           RIS.passo_da_previa(1600) == 2 and RIS.passo_da_previa(767) == 1
           and u"passo_da_previa(" in _corpo_fonte_py(RIS, "_previa"))


def _corpo_fonte_py(modulo, nome):
    src = io.open(modulo.__file__, encoding="utf-8").read()
    i = src.find(u"def %s(" % nome)
    if i < 0:
        return u""
    j = src.find(u"\n    @app.", i + 1)
    k = src.find(u"\ndef ", i + 1)
    fim = min(x for x in (j, k, len(src)) if x > 0)
    return src[i:fim]


def _detalhe_no_fonte(src, titulo):
    import ast
    for no in ast.walk(ast.parse(src)):
        if not (isinstance(no, ast.Call) and getattr(no.func, "id", "") == "_achado"):
            continue
        if len(no.args) > 1 and getattr(no.args[1], "id", "") == titulo:
            if len(no.args) > 2:
                return no.args[2]
            for k in no.keywords:
                if k.arg == "detalhe":
                    return k.value
    return None


def teste_o_alerta_sem_dono_e_frase_inteira():
    secao(u"o alerta da imagem sem dono: título e detalhe inteiros, nos doze idiomas")
    import ast
    import radai_image as RI
    import radai_phrases as F
    src = io.open(_componentes.fonte("app/radai_image.py"), encoding="utf-8").read()
    no = _detalhe_no_fonte(src, "TITULO_SEM_DONO")
    checar(u"o detalhe é uma frase inteira, e não um molde com %s",
           no is not None and not isinstance(no, ast.BinOp),
           ast.dump(no)[:120] if no is not None else u"não achei")
    isca = _detalhe_no_fonte(
        u"_achado(False, TITULO_SEM_DONO, u'sai como %s' % DESCONHECIDO)",
        "TITULO_SEM_DONO")
    checar(u"  (isca) o molde de hoje com %s é acusado", isinstance(isca, ast.BinOp))
    d = temp()
    fantoma(d, n=3, prefixo="image_s0001_i")
    achado = [a for a in RI.conferir(RI.varrer(d)["series"][0])["achados"]
              if a["titulo"] == RI.TITULO_SEM_DONO][0]
    checar(u"  e diz os valores no próprio texto (DESCONHECIDO, EXTERNO, LEIA-ME.txt)",
           all(v in achado["detalhe"] for v in (RI.DESCONHECIDO, RI.PREFIXO_DO_ID,
                                                RI.NOME_DO_LEIA_ME)),
           achado["detalhe"])
    dic = F.construir()
    for nome, t in ((u"título", achado["titulo"]), (u"detalhe", achado["detalhe"])):
        faltam = [c for c in F.CODIGOS if not dic[c].get(F.normalizar(t))]
        checar(u"  o %s tem as onze traduções" % nome, not faltam, u", ".join(faltam))
    checar(u"  (isca) frase sem chave é acusada",
           not dic["en"].get(F.normalizar(achado["detalhe"] + u" isca")))


_MARCA_DO_MOLDE = re.compile(r"%s|%d|\{\d+\}")
_CAMPOS_INTERNOS = ("espacamento_mm", "espessura_mm", "entre_cortes_mm",
                    "orientacao", "posicao_paciente", "primeiro_corte_mm")


def _traducao(dic, cod, texto):
    import radai_phrases as F
    k = F.normalizar(texto)
    d = dic.get(cod) or {}
    if d.get(k):
        return d[k]
    for chave, tr in d.items():
        km = _MARCA_DO_MOLDE.findall(chave)
        if not km or not tr or len(_MARCA_DO_MOLDE.findall(tr)) != len(km):
            continue
        partes = _MARCA_DO_MOLDE.split(chave)
        if len(u"".join(partes)) < 12:
            continue
        if re.match(u"^" + u"(.+?)".join(re.escape(p) for p in partes) + u"$", k):
            return tr
    return None


def _alertas_do_laudo():
    import radai_image as RI
    casos = []
    d = temp()
    fantoma(d, n=4, prefixo="image_s0001_i")
    casos.append(RI.conferir(RI.varrer(d)["series"][0], {}))
    d = temp()
    for nome in ("alfa", "beta", "gama"):
        escrever_png(os.path.join(d, nome + ".png"), [bytes(range(16)) for _ in range(8)])
    casos.append(RI.conferir(RI.varrer(d)["series"][0], GEO))
    d = temp()
    for k, lado in enumerate((16, 16, 24)):
        escrever_png(os.path.join(d, "img_%04d.png" % (k + 1)),
                     [bytes(lado) for _ in range(lado)])
    casos.append(RI.conferir(RI.varrer(d)["series"][0], GEO))
    d = temp()
    fantoma(d, n=1, prefixo="image_s0001_i")
    casos.append(RI.conferir(RI.varrer(d)["series"][0], GEO))
    sumida = temp()
    casos.append(RI.conferir(
        {"n": 3, "uniforme": True, "dimensoes": [(8, 8)],
         "como_ordenou": "numero no nome",
         "arquivos": [{"nome": "x%d.png" % i,
                       "caminho": os.path.join(sumida, "x%d.png" % i)}
                      for i in range(3)]}, GEO))
    return [a for c in casos for a in c["achados"] if not a["ok"]]


def teste_todo_alerta_do_laudo_e_frase_com_chave():
    secao(u"os alertas do laudo da imagem: frase inteira, com chave nos doze idiomas")
    import ast
    import radai_image as RI
    import radai_phrases as F
    alertas = _alertas_do_laudo()
    titulos = set(a["titulo"] for a in alertas)
    esperados = set([RI.TITULO_DO_TAMANHO, RI.TITULO_DA_ORDEM, RI.TITULO_SEM_DONO,
                     RI.TITULO_DO_CARIMBO, RI.TITULO_SEM_CONFERIR_O_CARIMBO,
                     RI.TITULO_DO_CARIMBO_NAO_CONFERIDO]
                    + [f[1] for f in RI.FALTAS_DA_GEOMETRIA])
    checar(u"os casos alcançam todo alerta que a tela mostra (%d)" % len(esperados),
           esperados <= titulos, u" | ".join(sorted(esperados - titulos)))
    src = io.open(_componentes.fonte("app/radai_image.py"), encoding="utf-8").read()
    chamadas = [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_achado"
                and n.args and isinstance(n.args[0], ast.Constant)
                and n.args[0].value is False]
    checar(u"  e o conferir não tem achado que cobra ou alerta fora deles (7 lugares)",
           len(chamadas) == 7, str(len(chamadas)))
    dic = F.construir()
    textos = sorted(set(t for a in alertas
                        for t in (a["titulo"], a["detalhe"], a["o_que_faz"]) if t))
    sem = [(c, t) for t in textos for c in F.CODIGOS if not _traducao(dic, c, t)]
    checar(u"  cada título, detalhe e «o que fazer» tem as onze traduções (%d frases)"
           % len(textos), not sem,
           u" | ".join(u"%s: %s" % (c, t[:40]) for c, t in sem[:5]))
    internos = [t for t in textos if any(k in t for k in _CAMPOS_INTERNOS)]
    checar(u"  e nenhum diz o nome interno de um campo", not internos,
           u" | ".join(t[:60] for t in internos[:3]))
    velho = (u"falta: orientacao. Um JPEG não guarda milímetro por pixel, espessura "
             u"de corte nem orientação — e sem isso o TPS não consegue pôr a série "
             u"no espaço para fundir.")
    checar(u"  (isca) o molde antigo, com o nome interno, sem chave e reprova",
           not _traducao(dic, "en", velho) and any(k in velho for k in _CAMPOS_INTERNOS))
    falso = {"en": {RI.DETALHE_DO_TAMANHO: u"sizes found. One matrix only."}}
    checar(u"  (isca) o molde cuja tradução perdeu o valor não casa",
           not _traducao(falso, "en", RI.DETALHE_DO_TAMANHO % u"8x8, 16x16")
           and _traducao(dic, "en", RI.DETALHE_DO_TAMANHO % u"8x8, 16x16"))

    tela = {"espacamento_mm": u"escala", "espessura_mm": u"espessura",
            "orientacao": u"orientação", "posicao_paciente": u"posição"}
    d = temp()
    fantoma(d, n=3, prefixo="image_s0001_i")
    s = RI.varrer(d)["series"][0]
    titulos_das_faltas = set(f[1] for f in RI.FALTAS_DA_GEOMETRIA)
    for campo, palavra in sorted(tela.items()):
        g = dict(GEO)
        g[campo] = None
        faltas = [a for a in RI.conferir(s, g, com_carimbo=False)["achados"]
                  if a["titulo"] in titulos_das_faltas]
        checar(u"sem %s, um alerta só, que diz «%s» com a palavra da tela"
               % (campo, palavra),
               len(faltas) == 1 and palavra in faltas[0]["titulo"]
               and faltas[0]["resolve"] is False, str([a["titulo"] for a in faltas]))
    todas = [a for a in RI.conferir(s, {}, com_carimbo=False)["achados"]
             if a["titulo"] in titulos_das_faltas]
    checar(u"sem nada, os quatro, cada um com a sua frase", len(todas) == 4
           and len(set(a["detalhe"] for a in todas)) == 4, str(len(todas)))


def teste_a_matriz_diferente_nao_se_aceita():
    secao(u"as imagens de tamanhos diferentes não convertem, nem confirmadas")
    import radai_image as RI
    d = temp()
    for k, lado in enumerate((16, 16, 24)):
        escrever_png(os.path.join(d, "img_%04d.png" % (k + 1)),
                     [bytes(lado) for _ in range(lado)])
    s = RI.varrer(d)["series"][0]
    checar(u"o tamanho diferente não é decisão", RI.TITULO_DO_TAMANHO not in RI.decidiveis(s),
           str(RI.decidiveis(s)))
    achado = [a for a in RI.conferir(s, GEO)["achados"]
              if a["titulo"] == RI.TITULO_DO_TAMANHO]
    checar(u"  e o laudo o marca como o que impede a conversão",
           len(achado) == 1 and achado[0]["impede"] is True
           and achado[0]["resolve"] is False, str(achado)[:160])
    try:
        RI.converter(s, os.path.join(temp(), "o"), GEO, aceitar=[RI.TITULO_DO_TAMANHO])
        gravou = True
    except RI.Recusa:
        gravou = False
    checar(u"  e a conversão recusa mesmo com ele «aceito»", not gravou)
    sonda = RI.conferir(s, GEO, com_carimbo=False)["achados"]
    velho = set(a["titulo"] for a in sonda if (not a["ok"]) and a["resolve"] is False)
    checar(u"  (isca) a regra antiga (todo achado que não se resolve era decisão) o aceitaria",
           RI.TITULO_DO_TAMANHO in velho)


def main():
    print(u"=" * 70)
    print(u"  IMAGEM -> DICOM: o exame que chegou como figura, pronto para fusao")
    print(u"=" * 70)
    for t in (teste_le_png_sem_pillow,
              teste_varrer_agrupa_e_ordena,
              teste_o_laudo_cobra_so_o_que_falta,
              teste_o_carimbo_e_detectado_por_estabilidade,
              teste_converte_e_confere_o_que_gravou,
              teste_o_id_externo_nao_se_repete,
              teste_o_frame_of_reference_e_sempre_novo,
              teste_o_recibo_nao_carrega_identificacao,
              teste_a_volta_pelo_dicom_bridge,
              teste_as_sugestoes_saem_da_descricao,
              teste_o_mpr_mostra_a_deformacao,
              teste_o_mpr_redondo_em_1_3_5_mm,
              teste_achatado_com_a_espessura_certa_e_escala_ou_intervalo,
              teste_o_dicom_convertido_leva_o_espacamento_do_mpr,
              teste_a_ordem_dos_cortes_se_inverte,
              teste_os_planos_de_serie_coronal_e_sagital,
              teste_a_previa_diz_o_passo_para_a_medida,
              teste_o_alerta_sem_dono_e_frase_inteira,
              teste_todo_alerta_do_laudo_e_frase_com_chave,
              teste_a_matriz_diferente_nao_se_aceita,
              teste_a_ordem_alfabetica_pede_confirmacao,
              teste_a_tela_esta_costurada,
              teste_o_fluxo_da_tela_ponta_a_ponta,
              teste_o_destino_que_sincroniza_e_recusado,
              teste_a_tela_nao_oferece_o_frame_da_tc):
        try:
            t()
        except Exception as e:
            import traceback
            checar(u"%s (excecao inesperada)" % t.__name__, False,
                   u"%s: %s" % (type(e).__name__, e))
            traceback.print_exc()
    print(u"\n" + u"=" * 70)
    if _falhas:
        print(u"FALHOU: %d de %d checagens" % (len(_falhas), _ok + len(_falhas)))
        for f in _falhas:
            print(u"    - %s" % f)
        print(u"=" * 70)
        return 1
    print(u"OK: %d checagens, todas passaram" % _ok)
    print(u"=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
