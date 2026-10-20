# -*- coding: utf-8 -*-
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AQUI = os.path.dirname(os.path.abspath(__file__))


def pasta_app(aqui):
    for c in (os.path.join(aqui, "..", "app"), os.path.join(aqui, "..")):
        if os.path.exists(os.path.join(c, "radai_watcher.py")):
            return os.path.abspath(c)
    return os.path.abspath(os.path.join(aqui, "..", "app"))


APP = pasta_app(AQUI)
sys.path.insert(0, APP)
sys.path.insert(0, AQUI)

import _cleanup
import _componentes
_cleanup.adotar_prefixo("radai_bm_")
os.environ["RADAI_CALIB_DIR"] = tempfile.mkdtemp(prefix="radai_bm_calib_")
os.environ["RADAI_TMP"] = tempfile.mkdtemp(prefix="radai_bm_tmp_")
_CONFIG = os.path.join(tempfile.mkdtemp(prefix="radai_bm_cfg_"),
                       "radai_watcher.config")
os.environ["RADAI_CONFIG"] = _CONFIG

VERBOSO = "-v" in sys.argv
_RESULTADOS = []

CT = "1.2.840.10008.5.1.4.1.1.2"
MR = "1.2.840.10008.5.1.4.1.1.4"
SC = "1.2.840.10008.5.1.4.1.1.7"


def checar(nome, ok, detalhe=""):
    _RESULTADOS.append((nome, bool(ok), detalhe))
    if VERBOSO or not ok:
        print("  %s  %s%s" % ("OK   " if ok else "FALHA", nome,
                              ("  [%s]" % detalhe) if detalhe else ""))
    return bool(ok)


def secao(t):
    print(u"\n-- %s --" % t)


def novo_temp():
    return tempfile.mkdtemp(prefix="radai_bm_")


def tps(valor):
    with io.open(_CONFIG, "w", encoding="utf-8") as f:
        f.write(u"TPS_DESTINO=%s\n" % valor if valor else u"")


def serie(pasta, n=6, modalidade="CT", uid=None, numero=1, descricao=u"CT",
          lado=16, sop=None, cor=False, sem_pos=False, sem_rescale=False,
          sem_for=False, slice_loc=None, valor=320, passo=3.0,
          conversao=None, passo_torto=None, comprimir=False,
          sem_ipp_em=(), sem_iop=False, frames=None):
    import numpy as np
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid, RLELossless
    os.makedirs(pasta, exist_ok=True)
    uid = uid or generate_uid()
    sop = sop or (MR if modalidade == "MR" else CT)
    frame = generate_uid()
    z = 0.0
    sops = []
    for i in range(n):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = sop
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = sop
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.SeriesInstanceUID = uid
        ds.StudyInstanceUID = "1.2.3.4.5"
        ds.Modality = modalidade
        ds.SeriesNumber = numero
        ds.SeriesDescription = descricao
        ds.InstanceNumber = i + 1
        ds.Rows, ds.Columns = lado, lado
        ds.PixelSpacing = [1.0, 1.0]
        ds.SliceThickness = passo
        ds.PatientPosition = "HFS"
        if conversao:
            ds.ConversionType = conversao
        if not sem_pos:
            if not sem_iop:
                ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            if i not in sem_ipp_em:
                ds.ImagePositionPatient = [-40.0, 25.0, -300.0 + z]
        if slice_loc is not None:
            ds.SliceLocation = slice_loc[i]
        if frames is not None:
            if frames[i]:
                ds.FrameOfReferenceUID = frames[i]
        elif not sem_for:
            ds.FrameOfReferenceUID = frame
        if cor:
            ds.SamplesPerPixel = 3
            ds.PhotometricInterpretation = "RGB"
            ds.PlanarConfiguration = 0
            ds.BitsAllocated = 8
            ds.BitsStored = 8
            ds.HighBit = 7
            ds.PixelRepresentation = 0
            px = np.zeros((lado, lado, 3), dtype=np.uint8)
            px[..., 0] = 255
            px[:, : lado // 2, 1] = 255
            ds.PixelData = px.tobytes()
        else:
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.BitsAllocated = 16
            ds.BitsStored = 16
            ds.HighBit = 15
            ds.PixelRepresentation = 0
            if modalidade == "CT" and not sem_rescale:
                ds.RescaleSlope = 1
                ds.RescaleIntercept = -1024
            px = (np.arange(lado * lado, dtype=np.uint16).reshape(lado, lado)
                  % 50 + valor + 7 * i).astype(np.uint16)
            ds.PixelData = px.tobytes()
            if comprimir:
                ds.compress(RLELossless, px, generate_instance_uid=False)
        sops.append(str(ds.SOPInstanceUID))
        ds.save_as(os.path.join(pasta, "IM%03d.dcm" % i),
                   enforce_file_format=True)
        z += (passo_torto[1] if (passo_torto and i + 1 == passo_torto[0])
              else passo)
    return uid, sops


class PedidoFalso(object):
    def __init__(self, corpo=None, headers=None, bruto=b""):
        self._corpo = corpo
        self._bruto = bruto
        self.headers = dict((k.lower(), v)
                            for k, v in (headers or {}).items())

    async def json(self):
        return self._corpo

    async def body(self):
        return self._bruto


class Resposta(object):
    def __init__(self, bruto):
        self._bruto = bruto
        self.status_code = getattr(bruto, "status_code", 200)
        self.content = getattr(bruto, "body", b"") or b""

    def json(self):
        return self._bruto


class Cliente(object):
    def __init__(self, app):
        self.rotas = {}
        for r in app.routes:
            alvo = getattr(r, "endpoint", None)
            for m in (getattr(r, "methods", None) or ()):
                if alvo is not None:
                    self.rotas[(m, r.path)] = alvo

    def _chamar(self, alvo, *a, **k):
        import asyncio
        import inspect
        if inspect.iscoroutinefunction(alvo):
            return asyncio.run(alvo(*a, **k))
        return alvo(*a, **k)

    def post(self, caminho, json=None, headers=None, bruto=b""):
        alvo = self.rotas[("POST", caminho)]
        return Resposta(self._chamar(alvo, PedidoFalso(json or {}, headers,
                                                       bruto)))

    def get(self, caminho, params=None):
        alvo = self.rotas[("GET", caminho)]
        import inspect
        k = dict(params or {})
        if "request" in inspect.signature(alvo).parameters:
            k["request"] = PedidoFalso({}, {})
        return Resposta(self._chamar(alvo, **k))


def cliente():
    from fastapi import FastAPI
    import radai_bridge
    return Cliente(radai_bridge.montar(FastAPI()))


def ler(caminho):
    import pydicom
    return pydicom.dcmread(caminho, force=True)


def dcms(pasta):
    fora = []
    for raiz, _d, arqs in os.walk(pasta):
        for a in sorted(arqs):
            if a.lower().endswith(".dcm"):
                fora.append(os.path.join(raiz, a))
    return fora


def teste_miniatura_de_rm_usa_a_janela_da_propria_imagem():
    secao(u"a miniatura de RM usa a janela da propria imagem (D6, E15)")
    import radai_dicom
    import radai_recon3d as R
    import radai_thumbnail as M
    base = novo_temp()
    serie(os.path.join(base, "rm"), n=5, modalidade="MR", valor=900,
          descricao=u"T1")
    serie(os.path.join(base, "tc"), n=5, numero=2, descricao=u"TC")
    radai_dicom.esquecer_varredura()
    ss = radai_dicom.varrer(base)["series"]
    vistas, original = {}, R.para_png
    try:
        for s in ss:
            def _cap(arr, c, l, _m=s["modalidade"]):
                vistas[_m] = (float(c), float(l))
                return original(arr, c, l)
            R.para_png = _cap
            b = M.bilhete(base, s["uid"])
            M.png_central(b)
    finally:
        R.para_png = original
    rm = vistas.get("MR")
    checar(u"a RM nao sai na janela de mediastino da TC",
           rm is not None and rm != tuple(map(float,
                                              R.JANELAS["mediastino"])),
           str(rm))
    checar(u"e a janela cobre os valores da propria RM",
           rm is not None and rm[0] > 800, str(rm))
    checar(u"a TC continua em mediastino",
           vistas.get("CT") == tuple(map(float, R.JANELAS["mediastino"])),
           str(vistas.get("CT")))
    cli = cliente()
    radai_dicom.esquecer_varredura()
    r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    por = dict((s["modalidade"], s) for s in r.get("series") or [])
    checar(u"a varredura manda a janela da modalidade ao cartao",
           por.get("MR", {}).get("janela") == "auto"
           and por.get("CT", {}).get("janela") == "mediastino", str(por)[:120])
    if "MR" in por:
        rc = cli.get("/api/bridge/corte", params={
            "b": por["MR"]["bilhete"], "corte": 1, "janela": "auto"})
        checar(u"e o visor da serie aberta serve a RM na janela automatica",
               rc.status_code == 200, str(rc.status_code))
    fonte = io.open(_componentes.fonte("app/radai_bridge.py"),
                    encoding="utf-8").read()
    checar(u"a serie aberta comeca na janela que o servidor mandou",
           "DC.janela = s.janela" in fonte)


def teste_colorida_e_captura_identificadas():
    secao(u"a imagem colorida e a captura sao identificadas (D2b)")
    base = novo_temp()
    serie(os.path.join(base, "cap"), n=3, sop=SC, modalidade="OT", cor=True,
          descricao=u"IMPRESSAO", numero=7)
    serie(os.path.join(base, "tc"), n=4, numero=2, descricao=u"TC AX")
    cli = cliente()
    import radai_dicom
    radai_dicom.esquecer_varredura()
    r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    por = dict((s.get("descricao"), s) for s in r.get("series") or [])
    cap, tc = por.get(u"IMPRESSAO") or {}, por.get(u"TC AX") or {}
    checar(u"a captura vem marcada colorida", cap.get("colorida") is True,
           str(cap)[:120])
    checar(u"e marcada captura", cap.get("captura") is True, str(cap)[:120])
    checar(u"a TC nao e colorida nem captura",
           tc.get("colorida") is False and tc.get("captura") is False,
           str(tc)[:120])
    checar(u"cada cartao traz descricao e modalidade",
           tc.get("modalidade") == "CT" and cap.get("modalidade") == "OT")
    checar(u"e o numero de imagens", tc.get("cortes") == 4)
    checar(u"e a espessura medida", tc.get("espessura_mm") == 3.0,
           str(tc.get("espessura_mm")))


def teste_a_miniatura_le_um_arquivo_so():
    secao(u"a miniatura le UM arquivo, sem revarrer o estudo (D7, E14)")
    import pydicom
    import radai_dicom
    import radai_thumbnail as M
    base = novo_temp()
    for k in range(3):
        serie(os.path.join(base, "s%d" % k), n=9, numero=k + 1,
              modalidade=("MR" if k == 1 else "CT"), descricao=u"S%d" % k)
    cli = cliente()
    radai_dicom.esquecer_varredura()
    r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    lidos, varridas = [], [0]
    orig_ler, orig_varrer = pydicom.dcmread, radai_dicom.varrer

    def _ler(c, *a, **k):
        lidos.append(str(c))
        return orig_ler(c, *a, **k)

    def _varrer(*a, **k):
        varridas[0] += 1
        return orig_varrer(*a, **k)
    pydicom.dcmread, radai_dicom.varrer = _ler, _varrer
    try:
        por_serie = []
        for s in r["series"]:
            antes = len(lidos)
            d, _i = M.png_central(s["bilhete"])
            por_serie.append((bool(d), len(set(lidos[antes:]))))
    finally:
        pydicom.dcmread, radai_dicom.varrer = orig_ler, orig_varrer
    checar(u"as tres miniaturas sairam", all(x[0] for x in por_serie),
           str(por_serie))
    checar(u"cada miniatura abriu um arquivo so",
           all(x[1] == 1 for x in por_serie), str(por_serie))
    checar(u"e nenhuma revarreu a pasta", varridas[0] == 0, str(varridas[0]))


def teste_o_cache_sai_da_pasta_do_exame():
    secao(u"o cache da miniatura sai da pasta do exame e usa o UID inteiro")
    import radai_dicom
    import radai_thumbnail as M
    base = novo_temp()
    a = "1.2.826.0.1.3680043.111.12345678"
    b = "1.2.826.0.1.3680043.222.12345678"
    serie(os.path.join(base, "a"), n=5, uid=a, numero=1, valor=100,
          descricao=u"A")
    serie(os.path.join(base, "b"), n=5, uid=b, numero=2, valor=3000,
          descricao=u"B")
    radai_dicom.esquecer_varredura()
    radai_dicom.varrer(base)
    da, ia = M.png_central(M.bilhete(base, a))
    db, ib = M.png_central(M.bilhete(base, b))
    checar(u"as duas miniaturas sairam", bool(da) and bool(db))
    checar(u"mesmos 8 ultimos caracteres, imagens diferentes", da != db)
    checar(u"e etiquetas diferentes", ia.get("etag") != ib.get("etag"),
           "%s %s" % (ia.get("etag"), ib.get("etag")))
    dentro = [r for r, _d, _a in os.walk(base) if "_RadAI" in r]
    checar(u"nada foi gravado dentro da pasta do exame", not dentro,
           str(dentro[:2]))
    radai_dicom.esquecer_varredura()
    r = radai_dicom.varrer(base)
    checar(u"e a varredura seguinte nao conta arquivo ignorado",
           not r["ignorados"], str(r["ignorados"][:3]))
    pasta = M._pasta_cache({"uid": a, "arquivos": []})
    checar(u"o cache mora no temporario local",
           bool(pasta) and os.path.abspath(pasta).startswith(
               os.path.abspath(os.environ["RADAI_TMP"])), str(pasta))
    nomes = os.listdir(pasta) if pasta and os.path.isdir(pasta) else []
    checar(u"e o nome do arquivo nao e o uid8",
           nomes and not any("12345678" in n for n in nomes), str(nomes[:3]))
    da2, ia2 = M.png_central(M.bilhete(base, a))
    checar(u"a segunda leitura vem do disco", ia2.get("de") == "disco",
           str(ia2.get("de")))


def teste_a_varredura_pula_o_que_e_nosso():
    secao(u"a varredura pula _RadAI e DICOM_BRIDGE_")
    import radai_dicom
    base = novo_temp()
    uid, _s = serie(os.path.join(base, "tc"), n=4)
    serie(os.path.join(base, radai_dicom.PREFIXO_SAIDA + "20261004_101010",
                       "x"), n=4, uid=uid)
    os.makedirs(os.path.join(base, "tc", "_RadAI", "miniaturas"))
    with open(os.path.join(base, "tc", "_RadAI", "miniaturas", "a.png"),
              "wb") as f:
        f.write(b"\x89PNG....")
    radai_dicom.esquecer_varredura()
    r = radai_dicom.varrer(base)
    checar(u"a serie tem os 4 cortes, e nao 8",
           len(r["series"]) == 1 and r["series"][0]["cortes"] == 4,
           str([s["cortes"] for s in r["series"]]))
    checar(u"e o PNG antigo nao vira arquivo ignorado", not r["ignorados"],
           str(r["ignorados"]))


def teste_a_exportacao_devolve_a_lista():
    secao(u"a exportacao devolve a lista do que foi exportado (D2b, B-SEL)")
    base = novo_temp()
    serie(os.path.join(base, "a"), n=4, numero=1, descricao=u"T1 AX")
    serie(os.path.join(base, "b"), n=6, numero=2, descricao=u"T2 AX",
          modalidade="MR")
    cli = cliente()
    import radai_dicom
    radai_dicom.esquecer_varredura()
    r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    ped = [{"b": s["bilhete"]} for s in r["series"]]
    d = cli.post("/api/bridge/etapa/converter",
                 json={"pasta": base, "series": ped}).json()
    ex = d.get("exportadas") or []
    checar(u"a conversao devolve as duas", len(ex) == 2, str(d)[:160])
    checar(u"com descricao, modalidade e cortes",
           sorted((x.get("descricao"), x.get("modalidade"), x.get("cortes"))
                  for x in ex) == [(u"T1 AX", "CT", 4), (u"T2 AX", "MR", 6)],
           str(ex)[:160])
    checar(u"e cada uma diz de qual cartao veio (o bilhete)",
           sorted(x["b"] for x in ex) == sorted(p["b"] for p in ped))
    cli.post("/api/bridge/etapa/descartar", json={"conversao": d.get("conversao")})


def teste_descomprimir_preserva_os_uids():
    secao(u"descomprimir nao gera UID novo (E18)")
    import radai_dicom
    tps("")
    base = novo_temp()
    uid, sops = serie(os.path.join(base, "s"), n=4, comprimir=True)
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    checar(u"o fantoma esta comprimido (RLE)",
           s["arquivos"][0]["sintaxe"] == "1.2.840.10008.1.2.5",
           s["arquivos"][0]["sintaxe"])
    dest = os.path.join(novo_temp(), "out")
    radai_dicom.converter(s, dest)
    saida = [ler(p) for p in dcms(dest)]
    checar(u"os SOPInstanceUID dos cortes ficaram",
           sorted(str(x.SOPInstanceUID) for x in saida) == sorted(sops))
    checar(u"e o MediaStorageSOPInstanceUID acompanha",
           all(str(x.file_meta.MediaStorageSOPInstanceUID)
               == str(x.SOPInstanceUID) for x in saida))
    checar(u"o SeriesInstanceUID ficou",
           all(str(x.SeriesInstanceUID) == uid for x in saida))
    checar(u"e o pixel saiu nativo",
           all(not x.file_meta.TransferSyntaxUID.is_compressed
               for x in saida))


def teste_a_colorida_vira_escala_de_cinza():
    secao(u"a imagem colorida vira MONOCHROME2 e a captura ganha "
          u"ConversionType (D2)")
    import numpy as np
    import radai_dicom
    tps("")
    base = novo_temp()
    serie(os.path.join(base, "s"), n=3, sop=SC, modalidade="OT", cor=True,
          descricao=u"MAPA")
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    laudo = radai_dicom.conferir(s)
    cor = [a for a in laudo["achados"] if not a["ok"]
           and u"colorida" in a["titulo"].lower()]
    checar(u"o laudo nomeia a imagem colorida", len(cor) == 1,
           "; ".join(a["titulo"] for a in laudo["achados"]))
    checar(u"e diz que a conversao resolve",
           cor and cor[0]["resolve"] is True)
    dest = os.path.join(novo_temp(), "out")
    radai_dicom.converter(s, dest)
    xs = [ler(p) for p in dcms(dest)]
    checar(u"tres cortes", len(xs) == 3, str(len(xs)))
    x = xs[0] if xs else None
    checar(u"SamplesPerPixel 1",
           x is not None and int(x.SamplesPerPixel) == 1)
    checar(u"MONOCHROME2",
           x is not None and x.PhotometricInterpretation == "MONOCHROME2")
    checar(u"sem PlanarConfiguration",
           x is not None and "PlanarConfiguration" not in x)
    arr = x.pixel_array if x is not None else None
    checar(u"a luminancia do vermelho puro e ~76",
           arr is not None and arr.ndim == 2
           and abs(int(arr[0, -1]) - 76) <= 1, str(arr[0, -1]
                                                    if arr is not None
                                                    else None))
    checar(u"a captura ganhou ConversionType",
           x is not None and str(getattr(x, "ConversionType", "")) != "")
    tc = os.path.join(novo_temp(), "tc")
    serie(tc, n=3, sop=SC, modalidade="OT", descricao=u"CAP CINZA")
    radai_dicom.esquecer_varredura()
    s2 = radai_dicom.varrer(tc)["series"][0]
    d2 = os.path.join(novo_temp(), "out")
    radai_dicom.converter(s2, d2)
    y = ler(dcms(d2)[0])
    checar(u"a captura em cinza tambem ganha ConversionType",
           str(getattr(y, "ConversionType", "")) == "WSD",
           str(getattr(y, "ConversionType", None)))
    checar(u"e continua em escala de cinza, com os mesmos UIDs",
           y.PhotometricInterpretation == "MONOCHROME2"
           and str(y.SeriesInstanceUID) == s2["uid"])
    del np


def teste_a_sintaxe_e_a_mesma_nos_dois_tps():
    secao(u"a sintaxe de saida e Implicit VR Little Endian nos dois TPS, "
          u"como o RTSTRUCT do motor")
    import radai_dicom
    base = novo_temp()
    serie(os.path.join(base, "s"), n=3)
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    gravadas = {}
    for valor in ("monaco", "eclipse", ""):
        tps(valor)
        d = os.path.join(novo_temp(), valor or "sem")
        r = radai_dicom.converter(s, d)
        x = ler(dcms(d)[0])
        gravadas[valor or "sem"] = (str(x.file_meta.TransferSyntaxUID),
                                    r.get("sintaxe"), x.is_implicit_VR,
                                    x.pixel_array.shape)
    tps("")
    implicita = ("1.2.840.10008.1.2", "1.2.840.10008.1.2", True, (16, 16))
    checar(u"Xio / Focal (monaco): Implicit VR Little Endian, e o resultado "
           u"diz a sintaxe gravada, e o pixel le de volta",
           gravadas["monaco"] == implicita, str(gravadas["monaco"]))
    checar(u"Eclipse / Monaco (eclipse): a mesma Implicit VR Little Endian",
           gravadas["eclipse"] == implicita, str(gravadas["eclipse"]))
    checar(u"sem configuracao, a mesma",
           gravadas["sem"] == implicita
           and radai_dicom.sintaxe_de_saida() == "1.2.840.10008.1.2",
           str(gravadas["sem"]))
    checar(u"o conversor de imagem usa a mesma regra",
           "sintaxe_de_saida" in io.open(_componentes.fonte("app/radai_image.py"),
                                         encoding="utf-8").read())


def teste_subpastas_nao_colidem_pelo_uid8():
    secao(u"duas series com os mesmos 8 ultimos caracteres nao colidem")
    base = novo_temp()
    serie(os.path.join(base, "a"), n=4, numero=1,
          uid="1.2.826.0.1.3680043.111.87654321")
    serie(os.path.join(base, "b"), n=6, numero=2,
          uid="1.2.826.0.1.3680043.222.87654321")
    cli = cliente()
    import radai_dicom
    radai_dicom.esquecer_varredura()
    r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    ped = [{"b": s["bilhete"]} for s in r["series"]]
    destino = novo_temp()
    c = cli.post("/api/bridge/etapa/converter", json={
        "pasta": base, "series": ped}).json()
    checar(u"as duas converteram", not c.get("recusadas")
           and len(c.get("exportadas") or []) == 2, str(c)[:160])
    e = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": c.get("conversao"), "destinos": [destino]}).json()
    dest = os.path.join(destino, e.get("nome") or "x")
    subs = sorted(n for n in os.listdir(dest)
                  if os.path.isdir(os.path.join(dest, n))) \
        if os.path.isdir(dest) else []
    checar(u"duas subpastas", len(subs) == 2, str(subs))
    contagem = sorted(len(dcms(os.path.join(dest, n))) for n in subs)
    checar(u"e cada uma inteira", contagem == [4, 6], str(contagem))
    checar(u"os nomes saem da funcao do modulo",
           radai_dicom.nomes_de_subpasta(
               ["1.2.111.87654321", "1.2.222.87654321"])[0]
           != radai_dicom.nomes_de_subpasta(
               ["1.2.111.87654321", "1.2.222.87654321"])[1])


def teste_a_conversao_forcada_sem_geometria():
    secao(u"a conversao forcada: sem posicao, sem reescala, sem FoR (C1)")
    import numpy as np
    import radai_dicom
    tps("")
    base = novo_temp()
    locs = [12.0, 9.0, 6.0, 3.0, 0.0]
    uid, sops = serie(os.path.join(base, "s"), n=5, sem_pos=True,
                      sem_rescale=True, sem_for=True, slice_loc=locs,
                      passo=3.0, descricao=u"LAUDO SF OSSO")
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    laudo = radai_dicom.conferir(s)
    alertas = [a for a in laudo["achados"] if a.get("alerta")]
    checar(u"o laudo tem os tres alertas", len(alertas) >= 3,
           "; ".join(a["titulo"] for a in alertas))
    checar(u"e devolve a contagem", laudo.get("n_alertas") == len(alertas),
           str(laudo.get("n_alertas")))
    checar(u"nenhum achado pede decisao", laudo.get("precisam_decisao") == 0,
           str(laudo.get("precisam_decisao")))
    geo = [a for a in alertas if "ImagePositionPatient" in a["titulo"]]
    checar(u"o alerta da geometria diz o criterio",
           geo and u"SliceLocation" in (geo[0]["o_que_faz"] or u""),
           geo[0]["o_que_faz"][:120] if geo else u"")
    dest = os.path.join(novo_temp(), "out")
    try:
        r = radai_dicom.converter(s, dest)
        passou = True
    except radai_dicom.Recusa as e:
        r, passou = {}, False
        checar(u"converte sem pedir decisao", False, str(e)[:160])
    if not passou:
        return
    checar(u"converte sem pedir decisao", r.get("cortes") == 5)
    xs = [ler(p) for p in dcms(dest)]
    por_loc = dict((float(x.SliceLocation), x) for x in xs)
    central = por_loc.get(6.0)
    checar(u"todos com posicao e orientacao",
           all("ImagePositionPatient" in x and "ImageOrientationPatient" in x
               for x in xs))
    if central is not None:
        ipp = np.array([float(v) for v in central.ImagePositionPatient])
        centro = ipp + np.array([7.5, 7.5, 0.0])
        checar(u"a origem e o centro geometrico do corte central",
               np.allclose(centro, 0.0, atol=1e-6), str(centro))
    zs = sorted(float(x.ImagePositionPatient[2]) for x in xs)
    checar(u"o passo sai do SliceLocation",
           np.allclose(np.diff(zs), 3.0), str(zs))
    checar(u"o z acompanha o SliceLocation",
           all(abs(float(x.ImagePositionPatient[2])
                   - (float(x.SliceLocation) - 6.0)) < 1e-6 for x in xs))
    frs = set(str(getattr(x, "FrameOfReferenceUID", "")) for x in xs)
    checar(u"um FrameOfReferenceUID novo, o mesmo em todos",
           len(frs) == 1 and "" not in frs, str(frs))
    checar(u"reescala 1 e 0, sem prometer HU",
           all(float(x.RescaleSlope) == 1.0 and float(x.RescaleIntercept) == 0
               and str(x.RescaleType) == "US" for x in xs))
    checar(u"o alerta vai dentro do DICOM, na descricao da serie",
           all(u"ALERTA" in str(x.SeriesDescription) for x in xs),
           str(xs[0].SeriesDescription) if xs else u"")
    checar(u"e o texto inteiro nos comentarios da imagem",
           all(u"origem" in str(getattr(x, "ImageComments", "")).lower()
               for x in xs))
    checar(u"geometria inventada: serie e cortes com UID novo",
           all(str(x.SeriesInstanceUID) != uid for x in xs)
           and not (set(str(x.SOPInstanceUID) for x in xs) & set(sops)))
    checar(u"e o recibo diz o porque do UID novo",
           bool((r.get("recibo") or {}).get("uid_regerado")),
           str(r.get("recibo"))[:160])
    checar(u"o resultado leva os alertas",
           len(r.get("alertas") or []) == len(alertas))


def _converter_e_ler(s, radai_dicom):
    dest = os.path.join(novo_temp(), "out")
    try:
        r = radai_dicom.converter(s, dest)
    except radai_dicom.Recusa as e:
        return None, [], str(e)
    return r, [ler(p) for p in dcms(dest)], u""


def teste_posicao_parcial_preserva_a_medida():
    secao(u"um corte sem posicao nao apaga a posicao medida dos outros (C1)")
    import radai_dicom
    tps("")
    base = novo_temp()
    serie(os.path.join(base, "s"), n=6, passo=3.0, sem_ipp_em=(2,))
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    laudo = radai_dicom.conferir(s)
    geo = [a for a in laudo["achados"]
           if "ImagePositionPatient" in a["titulo"]]
    checar(u"o laudo diz quantos cortes estao sem posicao",
           geo and u"1 de 6" in geo[0]["titulo"],
           geo[0]["titulo"] if geo else u"")
    r, xs, erro = _converter_e_ler(s, radai_dicom)
    checar(u"converte", len(xs) == 6, erro)
    if not xs:
        return
    por_inst = dict((int(x.InstanceNumber), x) for x in xs)
    medidas = all(
        [round(float(v), 4) for v in por_inst[i + 1].ImagePositionPatient]
        == [-40.0, 25.0, -300.0 + 3.0 * i] for i in range(6) if i != 2)
    checar(u"os cortes com posicao saem com a posicao medida", medidas,
           str([list(map(float, por_inst[i + 1].ImagePositionPatient))
                for i in range(6)]))
    faltou = [float(v) for v in por_inst[3].ImagePositionPatient]
    checar(u"o corte sem posicao fica entre os vizinhos medidos",
           [round(v, 4) for v in faltou] == [-40.0, 25.0, -294.0], str(faltou))


def teste_ipp_sem_iop_preserva_a_posicao():
    secao(u"com ImagePositionPatient e sem orientacao, a posicao fica (C1)")
    import radai_dicom
    tps("")
    base = novo_temp()
    serie(os.path.join(base, "s"), n=5, passo=2.5, sem_iop=True)
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    laudo = radai_dicom.conferir(s)
    titulos = [a["titulo"] for a in laudo["achados"] if a.get("alerta")]
    checar(u"o laudo nomeia a orientacao que falta",
           any("ImageOrientationPatient" in t for t in titulos)
           and not any(u"Sem `ImagePositionPatient`" in t for t in titulos),
           u"; ".join(titulos))
    r, xs, erro = _converter_e_ler(s, radai_dicom)
    checar(u"converte", len(xs) == 5, erro)
    if not xs:
        return
    ok = all([round(float(v), 4) for v in x.ImagePositionPatient]
             == [-40.0, 25.0, -300.0 + 2.5 * (int(x.InstanceNumber) - 1)]
             for x in xs)
    checar(u"a posicao medida de cada corte fica", ok,
           str([list(map(float, x.ImagePositionPatient)) for x in xs]))
    checar(u"e a orientacao assumida e gravada",
           all([float(v) for v in x.ImageOrientationPatient]
               == [1, 0, 0, 0, 1, 0] for x in xs))


def teste_for_ausente_nao_funde_referenciais_diferentes():
    secao(u"FoR ausente: os cortes com FoR diferentes nao viram um so (C1)")
    import radai_dicom
    from pydicom.uid import generate_uid
    tps("")
    a, b = generate_uid(), generate_uid()
    base = novo_temp()
    serie(os.path.join(base, "s"), n=5, frames=[a, a, b, b, ""])
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    r, xs, erro = _converter_e_ler(s, radai_dicom)
    checar(u"converte", len(xs) == 5, erro)
    if not xs:
        return
    por_inst = dict((int(x.InstanceNumber),
                     str(getattr(x, "FrameOfReferenceUID", "") or ""))
                    for x in xs)
    checar(u"todo corte sai com FoR", all(por_inst.values()), str(por_inst))
    checar(u"os do mesmo FoR original continuam juntos",
           por_inst[1] == por_inst[2] and por_inst[3] == por_inst[4])
    checar(u"e os de FoR diferentes continuam separados",
           len(set([por_inst[1], por_inst[3], por_inst[5]])) == 3,
           str(por_inst))


def teste_o_que_nao_se_corrige_vira_alerta_e_nao_trava():
    secao(u"irregular e duplicado: alerta, e nao trava")
    import radai_dicom
    tps("")
    base = novo_temp()
    sys.path.insert(0, AQUI)
    serie(os.path.join(base, "s"), n=8, passo=3.0, passo_torto=(4, 4.5))
    radai_dicom.esquecer_varredura()
    s = radai_dicom.varrer(base)["series"][0]
    laudo = radai_dicom.conferir(s)
    irr = [a for a in laudo["achados"] if "irregular" in a["titulo"].lower()]
    checar(u"o irregular continua nomeado", len(irr) == 1)
    checar(u"como alerta", irr and irr[0].get("alerta") is True)
    dest = os.path.join(novo_temp(), "out")
    try:
        r = radai_dicom.converter(s, dest)
        checar(u"converte sem aceite", r.get("cortes") == 8)
    except radai_dicom.Recusa as e:
        checar(u"converte sem aceite", False, str(e)[:120])
        return
    x = ler(dcms(dest)[0])
    checar(u"e o alerta vai no DICOM",
           u"irregular" in str(getattr(x, "ImageComments", "")).lower())
    checar(u"sem geometria inventada, os UIDs ficam",
           str(x.SeriesInstanceUID) == s["uid"])


def _enviar(cli, sessao, rel, dados, pedaco=7000):
    from urllib.parse import quote
    r = None
    for i in range(0, max(1, len(dados)), pedaco):
        parte = dados[i:i + pedaco]
        r = cli.post("/api/bridge/receber", bruto=parte, headers={
            "X-RadAI-Sessao": sessao, "X-RadAI-Arquivo": quote(rel),
            "X-RadAI-Offset": str(i)}).json()
        sessao = r.get("sessao") or sessao
    return r


def teste_o_conteudo_enviado_vira_pasta_local():
    secao(u"a rota recebe o que o navegador envia (D4, B10, B12)")
    import radai_archive
    origem = novo_temp()
    serie(os.path.join(origem, "Exame", "T1"), n=4, descricao=u"T1")
    serie(os.path.join(origem, "Exame", "T2"), n=3, numero=2,
          descricao=u"T2")
    cli = cliente()
    r = cli.post("/api/bridge/receber", bruto=b"", headers={}).json()
    checar(u"sem arquivo, a rota recusa", bool(r.get("erro")), str(r)[:120])
    sessao = ""
    for raiz, _d, arqs in os.walk(origem):
        for a in arqs:
            cheio = os.path.join(raiz, a)
            rel = os.path.relpath(cheio, origem).replace(os.sep, "/")
            with open(cheio, "rb") as f:
                rr = _enviar(cli, sessao, rel, f.read())
            sessao = rr.get("sessao") or sessao
    checar(u"a sessao foi criada", bool(sessao), str(sessao))
    mau = cli.post("/api/bridge/receber", bruto=b"x", headers={
        "X-RadAI-Sessao": sessao, "X-RadAI-Arquivo": "../../fora.dcm",
        "X-RadAI-Offset": "0"}).json()
    checar(u"caminho com .. e recusado", bool(mau.get("erro")), str(mau)[:120])
    fim = cli.post("/api/bridge/receber/fim", json={"sessao": sessao}).json()
    pasta = fim.get("pasta") or ""
    checar(u"o fim devolve a pasta de trabalho", os.path.isdir(pasta),
           str(fim)[:160])
    nuvem, _m = radai_archive.em_pasta_sincronizada(pasta)
    checar(u"fora de pasta que sincroniza", not nuvem)
    checar(u"no temporario local",
           os.path.abspath(pasta).startswith(
               os.path.abspath(os.environ["RADAI_TMP"])), pasta)
    import radai_dicom
    radai_dicom.esquecer_varredura()
    v = cli.post("/api/bridge/varrer", json={"pasta": pasta}).json()
    checar(u"as duas series, inteiras",
           sorted(s["cortes"] for s in v.get("series") or []) == [3, 4],
           str(v)[:160])
    lp = cli.post("/api/bridge/limpar", json={"sessao": sessao}).json()
    checar(u"limpar apaga a pasta de trabalho",
           lp.get("ok") and not os.path.exists(pasta), str(lp))


def teste_o_zip_digitado_e_o_enviado_abrem():
    secao(u"o .zip digitado e o enviado abrem (D5, E13)")
    origem = novo_temp()
    serie(os.path.join(origem, "s"), n=5, descricao=u"CT ZIP")
    zp = os.path.join(novo_temp(), "Exame.zip")
    with zipfile.ZipFile(zp, "w") as z:
        for p in dcms(origem):
            z.write(p, os.path.relpath(p, origem))
        z.writestr("../fora.txt", b"x")
    cli = cliente()
    import radai_dicom
    radai_dicom.esquecer_varredura()
    v = cli.post("/api/bridge/varrer", json={"pasta": zp}).json()
    ss = v.get("series") or []
    checar(u"o .zip digitado varre", len(ss) == 1 and ss[0]["cortes"] == 5,
           str(v)[:160])
    checar(u"o membro com .. nao saiu do lugar",
           not os.path.exists(os.path.join(os.path.dirname(zp), "fora.txt")))
    if ss:
        lau = cli.post("/api/bridge/laudo", json={
            "pasta": zp, "indice": 0, "b": ss[0]["bilhete"]}).json()
        checar(u"o laudo abre pelo mesmo .zip", "achados" in lau,
               str(lau)[:120])
        c = cli.post("/api/bridge/etapa/converter", json={
            "pasta": zp, "series": [{"b": ss[0]["bilhete"]}]}).json()
        checar(u"e converte", [x.get("cortes") for x in c.get("exportadas") or []]
               == [5], str(c)[:160])
        cli.post("/api/bridge/etapa/descartar",
                 json={"conversao": c.get("conversao")})
    with open(zp, "rb") as f:
        dados = f.read()
    rr = _enviar(cli, "", "Exame.zip", dados)
    fim = cli.post("/api/bridge/receber/fim",
                   json={"sessao": rr.get("sessao")}).json()
    radai_dicom.esquecer_varredura()
    v2 = cli.post("/api/bridge/varrer",
                  json={"pasta": fim.get("pasta") or ""}).json()
    checar(u"o .zip enviado e aberto na pasta de trabalho",
           [s["cortes"] for s in v2.get("series") or []] == [5],
           str(v2)[:160])


def teste_a_entrega_e_uma_pasta_nova_sem_zip():
    secao(u"Entregar: pasta nova DICOM_BRIDGE_, copiada aos outros destinos, sem .zip")
    import re
    import radai_bridge_entrada as E
    base = novo_temp()
    serie(os.path.join(base, "a"), n=4, numero=1, descricao=u"A")
    serie(os.path.join(base, "b"), n=3, numero=2, descricao=u"B")
    cli = cliente()
    d = cli.get("/api/bridge/destinos").json()
    checar(u"o destino padrao e a pasta Downloads",
           os.path.basename(d.get("downloads") or "").lower() in
           ("downloads", "transferencias", u"transferências"),
           str(d)[:120])
    import radai_dicom
    radai_dicom.esquecer_varredura()
    v = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    ped = [{"b": s["bilhete"]} for s in v["series"]]
    c = cli.post("/api/bridge/etapa/converter",
                 json={"pasta": base, "series": ped}).json()
    trabalho = E.pasta_da_conversao(c.get("conversao"))
    checar(u"a conversao mora na pasta de trabalho, fora do destino",
           bool(trabalho) and os.path.abspath(trabalho).startswith(
               os.path.abspath(E.raiz())), str(trabalho))
    d1, d2 = novo_temp(), novo_temp()
    e = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": c.get("conversao"), "destinos": [d1, d2]}).json()
    nome = e.get("nome") or ""
    checar(u"uma pasta DICOM_BRIDGE_<data_hora>",
           re.match(r"^DICOM_BRIDGE_\d{8}_\d{6}$", nome), str(e)[:160])
    checar(u"  no primeiro destino, com as duas series inteiras",
           len(dcms(os.path.join(d1, nome))) == 7)
    checar(u"  e copiada ao segundo, com o mesmo nome",
           len(dcms(os.path.join(d2, nome))) == 7)
    checar(u"  e nenhum .zip em lugar nenhum",
           not any(n.lower().endswith(".zip") for dd in (d1, d2)
                   for n in os.listdir(dd)), str(os.listdir(d1)))
    checar(u"a resposta diz, por serie, a pasta entregue e as copias",
           sorted(len(x["copias"]) for x in e.get("series") or []) == [1, 1]
           and all(x["pasta"].startswith(os.path.join(d1, nome))
                   and x["copias"][0].startswith(os.path.join(d2, nome))
                   for x in e.get("series") or []), str(e.get("series"))[:200])
    checar(u"  com o UID que a serie ENTREGUE tem",
           sorted(x["uid"] for x in e["series"])
           == sorted(s["uid"] for s in radai_dicom.varrer(
               os.path.join(d1, nome), False)["series"]))
    checar(u"a pasta de trabalho sai depois da entrega",
           not os.path.exists(trabalho or "x")
           and E.pasta_da_conversao(c.get("conversao")) is None)
    de_novo = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": c.get("conversao"), "destinos": [d1]}).json()
    checar(u"entregar de novo a mesma conversao pede converter de novo",
           u"converta de novo" in str(de_novo.get("erro")), str(de_novo)[:120])
    c2 = cli.post("/api/bridge/etapa/converter",
                  json={"pasta": base, "series": ped}).json()
    e2 = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": c2.get("conversao"), "destinos": [base]}).json()
    checar(u"a pasta de origem do estudo serve de destino",
           not e2.get("erro") and len(e2.get("series") or []) == 2, str(e2)[:160])
    radai_dicom.esquecer_varredura()
    v2 = radai_dicom.varrer(base)
    checar(u"e a varredura seguinte da origem nao duplica a serie",
           sorted(s["cortes"] for s in v2["series"]) == [3, 4],
           str([s["cortes"] for s in v2["series"]]))
    c3 = cli.post("/api/bridge/etapa/converter",
                  json={"pasta": base, "series": ped}).json()
    t3 = E.pasta_da_conversao(c3.get("conversao"))
    ds = cli.post("/api/bridge/etapa/descartar",
                  json={"conversao": c3.get("conversao")}).json()
    checar(u"descartar apaga a conversao que nao foi entregue",
           ds.get("ok") and not os.path.exists(t3 or "x"))
    vazio = cli.post("/api/bridge/etapa/converter",
                     json={"pasta": base, "series": []}).json()
    checar(u"nenhuma serie pedida e recusado", bool(vazio.get("erro")))
    import radai_archive as RA
    orig = RA.em_pasta_sincronizada
    c4 = cli.post("/api/bridge/etapa/converter",
                  json={"pasta": base, "series": ped[:1]}).json()
    try:
        RA.em_pasta_sincronizada = lambda c=None: (True, u"Drive espelha X")
        e4 = cli.post("/api/bridge/etapa/entregar", json={
            "conversao": c4.get("conversao"), "destinos": [novo_temp()]}).json()
    finally:
        RA.em_pasta_sincronizada = orig
    checar(u"destino que sincroniza e recusado", u"nuvem" in str(e4.get("erro")),
           str(e4)[:120])
    cli.post("/api/bridge/etapa/descartar", json={"conversao": c4.get("conversao")})


def teste_a_entrega_recusa_destino_dentro_do_root_do_vigia():
    secao(u"Entregar nao grava dentro do ROOT do vigia (E10)")
    import radai_dicom
    share = novo_temp()
    serie(os.path.join(share, "PAC", "CT"), n=3, descricao=u"CT")
    with io.open(_CONFIG, "w", encoding="utf-8") as f:
        f.write(u"ROOT=%s\n" % share)
    try:
        cli = cliente()
        radai_dicom.esquecer_varredura()
        v = cli.post("/api/bridge/varrer", json={"pasta": share}).json()
        ped = [{"b": s["bilhete"]} for s in v.get("series") or []]
        c = cli.post("/api/bridge/etapa/converter",
                     json={"pasta": share, "series": ped}).json()
        r = cli.post("/api/bridge/etapa/entregar", json={
            "conversao": c.get("conversao"),
            "destinos": [os.path.join(share, "PAC")]}).json()
        checar(u"destino dentro do ROOT e recusado", bool(r.get("erro")),
               str(r)[:160])
        sobras = [n for n in os.listdir(os.path.join(share, "PAC"))
                  if n.startswith(radai_dicom.PREFIXO_SAIDA)]
        checar(u"e nada foi gravado no share", not sobras, str(sobras))
        fora = novo_temp()
        r2 = cli.post("/api/bridge/etapa/entregar", json={
            "conversao": c.get("conversao"), "destinos": [fora]}).json()
        checar(u"a mesma conversao, fora do ROOT, entrega",
               len(r2.get("series") or []) == 1, str(r2)[:160])
    finally:
        tps("")


def _convertida(cli, n_series=1):
    import radai_dicom
    base = novo_temp()
    for k in range(n_series):
        serie(os.path.join(base, "s%d" % k), n=3 + k, numero=k + 1,
              descricao=u"S%d" % k)
    radai_dicom.esquecer_varredura()
    v = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    ped = [{"b": s["bilhete"]} for s in v["series"]]
    return cli.post("/api/bridge/etapa/converter",
                    json={"pasta": base, "series": ped}).json()


def _entregar_antigo(E, origem, destinos):
    destinos = E.conferir_destinos(destinos)
    for d in destinos:
        os.makedirs(d, exist_ok=True)
    nome = E._nome_livre(destinos)
    pastas = [os.path.join(d, nome) for d in destinos]
    shutil.move(E.no_disco(origem), pastas[0])
    for p in pastas[1:]:
        shutil.copytree(pastas[0], p)
    return nome, pastas


def teste_a_entrega_que_falha_no_meio():
    secao(u"Entregar: a copia que falha no meio diz o que chegou onde")
    import radai_bridge_entrada as E
    cli = cliente()
    c = _convertida(cli)
    token = c.get("conversao")
    d1, d2, d3 = novo_temp(), novo_temp(), novo_temp()
    original = shutil.copytree

    def quebra_no_d2(src, dst, *a, **k):
        if os.path.abspath(E.sem_prefixo(dst)).startswith(os.path.abspath(d2)):
            os.makedirs(dst)
            io.open(os.path.join(dst, "meio.dcm"), "wb").write(b"x")
            raise OSError(28, "No space left on device")
        return original(src, dst, *a, **k)
    shutil.copytree = quebra_no_d2
    try:
        e = cli.post("/api/bridge/etapa/entregar", json={
            "conversao": token, "destinos": [d1, d2, d3]}).json()
    finally:
        shutil.copytree = original
    nome = e.get("nome") or ""
    checar(u"a entrega nao vira erro: o DICOM chegou a dois destinos",
           not e.get("erro") and [os.path.dirname(o["pasta"])
                                  for o in e.get("saidas") or []] == [d1, d3],
           str(e)[:200])
    checar(u"  e diz qual destino nao recebeu, com o motivo",
           [f["destino"] for f in e.get("falhas") or []] == [d2]
           and u"No space" in (e.get("falhas") or [{}])[0].get("motivo", u""),
           str(e.get("falhas")))
    checar(u"  o destino que falhou nao guarda a pasta pela metade",
           os.listdir(d2) == [], str(os.listdir(d2)))
    checar(u"  o primeiro e o terceiro tem a serie inteira",
           len(dcms(os.path.join(d1, nome))) == 3
           and len(dcms(os.path.join(d3, nome))) == 3)
    checar(u"  as copias da segmentacao apontam so para o que recebeu",
           all(x["copias"] == [os.path.join(d3, nome, os.path.basename(x["pasta"]))]
               for x in e.get("series") or []), str(e.get("series"))[:200])
    checar(u"  e a conversao foi esquecida: nenhum token aponta para pasta movida",
           E.pasta_da_conversao(token) is None)

    c2 = _convertida(cli)
    t2 = c2.get("conversao")
    base2 = E.pasta_da_conversao(t2)
    ruim = os.path.join(novo_temp(), "arquivo.txt")
    io.open(ruim, "w").write(u"x")
    shutil.copytree = lambda *a, **k: (_ for _ in ()).throw(OSError(13, "Permission denied"))
    renomear = os.rename
    os.rename = lambda *a, **k: (_ for _ in ()).throw(OSError(18, "cross-device"))
    try:
        r = cli.post("/api/bridge/etapa/entregar", json={
            "conversao": t2, "destinos": [novo_temp()]}).json()
    finally:
        shutil.copytree = original
        os.rename = renomear
    checar(u"nenhum destino recebeu: erro claro, e a conversao continua aqui",
           u"nenhum destino" in str(r.get("erro"))
           and E.pasta_da_conversao(t2) == base2 and len(dcms(base2)) == 3,
           str(r)[:160])
    d4 = novo_temp()
    r2 = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": t2, "destinos": [os.path.join(ruim, "sub"), d4]}).json()
    checar(u"  e entregar de novo funciona; o destino impossivel vira falha e o "
           u"seguinte vira o primeiro",
           not r2.get("erro") and len(r2.get("series") or []) == 1
           and r2["series"][0]["pasta"].startswith(d4)
           and [f["destino"] for f in r2.get("falhas") or []]
           == [os.path.join(ruim, "sub")], str(r2)[:200])

    c3 = _convertida(cli)
    t3 = c3.get("conversao")
    base3 = E.pasta_da_conversao(t3)
    a1, a2 = novo_temp(), novo_temp()
    shutil.copytree = quebra_no_d2
    d2_salvo = d2
    try:
        d2 = a2
        try:
            _entregar_antigo(E, base3, [a1, a2])
            quebrou = False
        except OSError:
            quebrou = True
    finally:
        shutil.copytree = original
        d2 = d2_salvo
    checar(u"  (isca) o algoritmo antigo estourava com o DICOM ja no primeiro "
           u"destino e o token apontando para pasta que nao existe",
           quebrou and os.listdir(a1) and not os.path.isdir(base3)
           and E.pasta_da_conversao(t3) is None
           and t3 in E._CONVERSOES, str(os.listdir(a1)))
    E.esquecer_conversao(t3)


def teste_a_origem_com_prefixo_de_caminho_longo():
    secao(u"a pasta de origem: a area de envio com o prefixo \\\\?\\ nao vira origem")
    import radai_bridge_entrada as E
    import radai_dicom
    cli = cliente()
    r = E.receber("", "a/IM1.dcm", 0, b"DICM")
    pasta = os.path.join(E.raiz(), r["sessao"])
    radai_dicom.esquecer_varredura()
    sem = cli.post("/api/bridge/varrer", json={"pasta": pasta}).json()
    checar(u"a area de envio sem prefixo nao e oferecida como origem",
           sem.get("origem") == u"", str(sem.get("origem")))
    if os.name == "nt":
        pre = E._com_prefixo(pasta)
        radai_dicom.esquecer_varredura()
        com = cli.post("/api/bridge/varrer", json={"pasta": pre}).json()
        checar(u"  nem com o prefixo de caminho longo",
               com.get("origem") == u"" and not com.get("erro"), str(com)[:160])
        try:
            raiz = os.path.normcase(os.path.abspath(E.raiz()))
            os.path.commonpath([raiz, os.path.normcase(os.path.abspath(pre))])
            antigo_quebra = False
        except ValueError:
            antigo_quebra = True
        checar(u"  (isca) a comparacao antiga, sem tirar o prefixo, levantava e "
               u"devolvia a temporaria", antigo_quebra)
        fora = novo_temp()
        outra = cli.post("/api/bridge/varrer",
                         json={"pasta": E._com_prefixo(fora)}).json()
        checar(u"  pasta comum digitada com prefixo volta como origem, sem ele",
               outra.get("origem") == fora, str(outra.get("origem")))
    E.limpar(r["sessao"])


def teste_o_texto_declarado_no_dicom():
    secao(u"texto queimado no DICOM: BurnedInAnnotation e captura secundaria")
    import pydicom
    import radai_bridge as B
    import radai_dicom

    def _marcar(pasta, valor, so_um=False):
        for k, c in enumerate(dcms(pasta)):
            if so_um and k != 1:
                continue
            ds = pydicom.dcmread(c, force=True)
            ds.BurnedInAnnotation = valor
            ds.save_as(c, enforce_file_format=True)

    def _laudo(pasta):
        radai_dicom.esquecer_varredura()
        s = radai_dicom.varrer(pasta)["series"][0]
        return [a for a in B.laudo_da_serie(s)["achados"] if a.get("alerta")], s
    sim = novo_temp()
    serie(sim, n=4, descricao=u"CT SIM")
    _marcar(sim, "YES", so_um=True)
    al, s_sim = _laudo(sim)
    checar(u"um corte com BurnedInAnnotation YES vira UM alerta de uma linha",
           [a["titulo"] for a in al if a["titulo"] == B.TITULO_DO_TEXTO_DECLARADO]
           == [B.TITULO_DO_TEXTO_DECLARADO]
           and all(not a["detalhe"] and not a["impede"] for a in al
                   if a["titulo"] == B.TITULO_DO_TEXTO_DECLARADO), str(al)[:200])
    checar(u"  (isca) o laudo da Suite sozinho nao o acusa",
           not any(B.TITULO_DO_TEXTO_DECLARADO == a["titulo"]
                   for a in radai_dicom.conferir(s_sim)["achados"]))
    sc = novo_temp()
    serie(sc, n=3, sop=SC, descricao=u"CAPTURA", conversao="WSD")
    al_sc, _s = _laudo(sc)
    checar(u"captura secundaria sem declaracao vira alerta",
           any(a["titulo"] == B.TITULO_DA_CAPTURA for a in al_sc), str(al_sc)[:200])
    sc_nao = novo_temp()
    serie(sc_nao, n=3, sop=SC, descricao=u"CAPTURA", conversao="WSD")
    _marcar(sc_nao, "NO")
    al_nao, _s = _laudo(sc_nao)
    checar(u"  e a que declara NO nao alerta",
           not any(a["titulo"] in (B.TITULO_DA_CAPTURA, B.TITULO_DO_TEXTO_DECLARADO)
                   for a in al_nao), str(al_nao)[:200])
    limpa = novo_temp()
    serie(limpa, n=3, descricao=u"CT LIMPA")
    al_l, _s = _laudo(limpa)
    checar(u"  e a serie comum, sem declaracao, nao alerta",
           not any(a["titulo"] in (B.TITULO_DA_CAPTURA, B.TITULO_DO_TEXTO_DECLARADO)
                   for a in al_l))
    longa = novo_temp()
    serie(longa, n=30, descricao=u"CT LONGA")
    c26 = dcms(longa)[25]
    ds = pydicom.dcmread(c26, force=True)
    ds.BurnedInAnnotation = "YES"
    ds.save_as(c26, enforce_file_format=True)
    abertos = []
    original = B._anotacao_queimada

    def _espiao(caminho):
        abertos.append(caminho)
        return original(caminho)
    B._anotacao_queimada = _espiao
    try:
        al_lg, s_lg = _laudo(longa)
        checar(u"o corte 26 de 30 com YES alerta, pela leitura da varredura",
               any(a["titulo"] == B.TITULO_DO_TEXTO_DECLARADO for a in al_lg)
               and not abertos, u"%d aberto(s)" % len(abertos))
        sem_campo = dict(s_lg, arquivos=[dict((k, v) for k, v in a.items()
                                              if k != "anotacao")
                                         for a in s_lg["arquivos"]])
        checar(u"  e serie de fora da varredura e lida corte a corte",
               B.texto_no_pixel(sem_campo) and len(abertos) == 30,
               u"%d aberto(s)" % len(abertos))
    finally:
        B._anotacao_queimada = original
    passo = max(1, 30 // 12)
    checar(u"  (isca) a amostra antiga de 12 cortes mais o ultimo nao o veria",
           25 not in list(range(30))[::passo][:12] + [29])
    cli = cliente()
    radai_dicom.esquecer_varredura()
    v = cli.post("/api/bridge/varrer", json={"pasta": sim}).json()
    b = v["series"][0]["bilhete"]
    la = cli.post("/api/bridge/laudo", json={"pasta": sim, "b": b}).json()
    checar(u"a rota do laudo traz o alerta",
           any(a["titulo"] == B.TITULO_DO_TEXTO_DECLARADO
               for a in la.get("achados") or []), str(la)[:160])
    c = cli.post("/api/bridge/etapa/converter",
                 json={"pasta": sim, "series": [{"b": b}]}).json()
    ex = (c.get("exportadas") or [{}])[0]
    checar(u"  e a conversao o leva junto dos outros alertas",
           B.TITULO_DO_TEXTO_DECLARADO in (ex.get("alertas") or []), str(ex)[:200])
    import radai_bridge_entrada as E
    feito = dcms(E.pasta_da_conversao(c.get("conversao")) or "x")
    gravado = ler(feito[0]) if feito else None
    checar(u"  gravado dentro do DICOM (descricao e comentario)",
           gravado is not None
           and u"ALERTA" in str(gravado.SeriesDescription)
           and u"texto gravado na imagem" in str(getattr(gravado, "ImageComments", "")),
           str(getattr(gravado, "ImageComments", ""))[:160])
    cli.post("/api/bridge/etapa/descartar", json={"conversao": c.get("conversao")})


def teste_o_corte_truncado_nao_chega_ao_tps():
    secao(u"o corte truncado: o laudo impede e a conversao nao grava nada")
    import io as _io
    import radai_dicom
    import radai_bridge_entrada as E
    for comprimir in (False, True):
        pasta = novo_temp()
        serie(pasta, n=5, descricao=u"CT CORTADA", comprimir=comprimir)
        alvo = dcms(pasta)[2]
        bruto = _io.open(alvo, "rb").read()
        _io.open(alvo, "wb").write(bruto[:len(bruto) - 120])
        rotulo = u"encapsulado" if comprimir else u"nativo"
        cli = cliente()
        radai_dicom.esquecer_varredura()
        v = cli.post("/api/bridge/varrer", json={"pasta": pasta}).json()
        b = v["series"][0]["bilhete"]
        la = cli.post("/api/bridge/laudo", json={"pasta": pasta, "b": b}).json()
        impede = [a for a in la.get("achados") or [] if a.get("impede")]
        checar(u"%s: o laudo impede e diz o corte 3" % rotulo,
               not la.get("pode_converter") and impede
               and u"corte 3:" in impede[0].get("detalhe", u""),
               str(impede)[:160])
        c = cli.post("/api/bridge/etapa/converter",
                     json={"pasta": pasta, "series": [{"b": b}]}).json()
        feito = dcms(E.pasta_da_conversao(c.get("conversao")) or "x") \
            if c.get("conversao") else []
        checar(u"  e a conversao recusa sem deixar arquivo",
               c.get("erro") and not c.get("exportadas") and not feito,
               str(c)[:160])


def teste_a_guarda_da_fila():
    secao(u"a guarda da entrega: conferir no disco e por de novo, sem caminho no navegador")
    import radai_bridge as B
    os.environ["RADAI_FILA_DIR"] = novo_temp()
    cli = cliente()
    c = _convertida(cli, 2)
    d1, d2 = novo_temp(), novo_temp()
    e = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": c.get("conversao"), "destinos": [d1, d2]}).json()
    series = e.get("series") or []
    itens = [{"pasta": x["pasta"], "uid": x["uid"], "modo": "fast", "chaves": {},
              "copiar_rs_para": x["copias"], "origem": "dicombridge",
              "rotulo": u"CT · S"} for x in series]
    estranho = dict(itens[0], pasta=novo_temp())
    g0 = cli.post("/api/bridge/fila/guardar", json={"itens": [estranho]}).json()
    checar(u"a guarda recusa pasta que esta tela nao entregou",
           g0.get("guarda") == u"", str(g0))
    g = cli.post("/api/bridge/fila/guardar", json={"itens": itens}).json().get("guarda")
    checar(u"e guarda as series entregues, devolvendo so um bilhete opaco",
           bool(g) and len(g) == 32 and d1 not in g)
    r0 = cli.post("/api/bridge/fila/conferir",
                  json={"guarda": g, "quais": [0, 1]}).json()
    checar(u"conferir: sem RTSTRUCT ao lado, nao finge que chegou",
           r0.get("ok") and [x["rs"] for x in r0["series"]] == [False, False]
           and d1 not in json.dumps(r0), str(r0)[:160])
    uid0 = itens[0]["uid"]
    rs = u"RS_RadAI_FULL_%s.dcm" % uid0[-8:]
    io.open(os.path.join(itens[0]["pasta"], rs), "wb").write(b"x")
    r1 = cli.post("/api/bridge/fila/conferir",
                  json={"guarda": g, "quais": [0]}).json()
    checar(u"  com o RTSTRUCT ao lado: chegou, e a copia que falta aparece",
           r1["series"] == [{"i": 0, "rs": True, "copias": 0, "de": 1}],
           str(r1)[:160])
    io.open(os.path.join(itens[0]["copiar_rs_para"][0], rs), "wb").write(b"x")
    r2 = cli.post("/api/bridge/fila/conferir",
                  json={"guarda": g, "quais": [0, "x", 9]}).json()
    checar(u"  e com a copia no outro destino, conta; lixo na lista e ignorado",
           r2["series"] == [{"i": 0, "rs": True, "copias": 1, "de": 1}],
           str(r2)[:160])
    sg = cli.post("/api/bridge/fila/conferir",
                  json={"guarda": "0" * 32, "quais": [0]}).json()
    checar(u"guarda desconhecida responde sem_guarda", sg.get("sem_guarda") is True)
    dn = cli.post("/api/bridge/fila/de_novo", json={"guarda": g, "quais": [1]}).json()
    ids = [x["id"] for x in dn.get("cartoes") or []]
    checar(u"por de novo pela guarda poe a serie na fila unica (C1, em Python)",
           dn.get("ok") and len(ids) == 1, str(dn)[:160])
    try:
        import radai_queue_state as Q
        est = Q.estado_publico(ids)
        checar(u"  e a fila tem o cartao, de origem DicomBridge",
               [x["origem"] for x in est["cartoes"]] == [u"dicombridge"],
               str(est)[:160])
        Q.remover(itens[1]["uid"], itens[1]["pasta"])
        checar(u"  (e a bateria tira o cartao que pos)",
               not Q.estado_publico(ids)["cartoes"])
    except Exception as ex:
        checar(u"  a fila unica responde em Python", False, str(ex)[:120])
    dn0 = cli.post("/api/bridge/fila/de_novo",
                   json={"guarda": "0" * 32, "quais": [0]}).json()
    checar(u"  sem a guarda, diz que a entrega nao esta mais guardada",
           dn0.get("ok") is False and dn0.get("sem_guarda") is True, str(dn0))
    checar(u"a guarda nao passa do teto", B.TETO_DE_GUARDAS >= 8)


def _uid64(semente):
    base = "1.2.826.0.1.3680043.8.498."
    return base + "".join(str(1 + (semente * 7 + i * 3) % 9)
                          for i in range(64 - len(base)))


def _estudo_de_caminho_longo(raiz):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    paciente = u"PACIENTE_FANTOMA_" + u"SOBRENOME_COMPRIDO_" * 5
    estudo, serie_uid = _uid64(1), _uid64(2)
    pasta = os.path.join(raiz, paciente, estudo, serie_uid)
    os.makedirs(pasta, exist_ok=True)
    for i in range(4):
        sop = _uid64(10 + i)
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = CT
        ds.file_meta.MediaStorageSOPInstanceUID = sop
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID, ds.SOPInstanceUID = CT, sop
        ds.SeriesInstanceUID, ds.StudyInstanceUID = serie_uid, estudo
        ds.Modality, ds.SeriesNumber, ds.InstanceNumber = "CT", 1, i + 1
        ds.SeriesDescription = u"CT CAMINHO LONGO"
        ds.Rows = ds.Columns = 8
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
        ds.PixelRepresentation = 0
        ds.PixelSpacing, ds.SliceThickness = [1.0, 1.0], 3.0
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0.0, 0.0, 3.0 * i]
        ds.FrameOfReferenceUID = estudo
        ds.PixelData = b"\x00\x01" * 64
        ds.save_as(os.path.join(pasta, sop + ".dcm"), enforce_file_format=True)
    return serie_uid


def _maior_caminho(pasta):
    import radai_bridge_entrada as E
    maior = 0
    for r, _d, arqs in os.walk(E._com_prefixo(pasta)):
        for a in arqs:
            cheio = os.path.join(r, a)
            if cheio.startswith("\\\\?\\"):
                cheio = cheio[4:]
            maior = max(maior, len(cheio))
    return maior


def teste_o_caminho_longo_da_area_de_envio():
    secao(u"caminho longo: UIDs de 64 caracteres e pasta de paciente longa")
    import radai_bridge_entrada as E
    import radai_dicom
    origem = novo_temp()
    uid = _estudo_de_caminho_longo(origem)
    rels = []
    for raiz, _d, arqs in os.walk(origem):
        for a in arqs:
            rels.append(os.path.relpath(os.path.join(raiz, a),
                                        origem).replace(os.sep, "/"))
    base_sessao = os.path.join(E.raiz(), "0" * 32)
    velho = max(len(os.path.join(base_sessao, *E.partes_seguras(r)))
                for r in rels)
    checar(u"(isca) o fantoma reproduz o erro de campo: o nome cru passa de "
           u"260 caracteres", velho >= 260, str(velho))
    cli = cliente()
    sessao = ""
    for rel in rels:
        with open(os.path.join(origem, *rel.split("/")), "rb") as f:
            rr = _enviar(cli, sessao, rel, f.read())
        checar(u"o envio de %s… nao falha" % rel[:24], not rr.get("erro"),
               str(rr)[:120])
        sessao = rr.get("sessao") or sessao
    fim = cli.post("/api/bridge/receber/fim", json={"sessao": sessao}).json()
    pasta = fim.get("pasta") or ""
    m = _maior_caminho(pasta)
    checar(u"na area de envio todo arquivo fica abaixo de 260 caracteres",
           0 < m < 260, str(m))
    radai_dicom.esquecer_varredura()
    v = cli.post("/api/bridge/varrer", json={"pasta": pasta}).json()
    ss = v.get("series") or []
    checar(u"e a serie chega inteira, com o UID de 64 caracteres",
           len(ss) == 1 and ss[0]["cortes"] == 4
           and radai_dicom.varrer(pasta)["series"][0]["uid"] == uid,
           str(v)[:160])
    if ss:
        c = cli.post("/api/bridge/etapa/converter", json={
            "pasta": pasta, "series": [{"b": ss[0]["bilhete"]}]}).json()
        e = cli.post("/api/bridge/etapa/entregar", json={
            "conversao": c.get("conversao"), "destinos": [novo_temp()]}).json()
        checar(u"  e atravessa: converte e entrega com o UID preservado",
               [x["uid"] for x in e.get("series") or []] == [uid]
               and len(dcms(e["series"][0]["pasta"])) == 4, str(e)[:160])
    cli.post("/api/bridge/limpar", json={"sessao": sessao})

    zp = os.path.join(novo_temp(), "Exame.zip")
    with zipfile.ZipFile(zp, "w") as z:
        for rel in rels:
            z.write(os.path.join(origem, *rel.split("/")), rel)
    with open(zp, "rb") as f:
        rz = _enviar(cli, "", "Exame.zip", f.read())
    fz = cli.post("/api/bridge/receber/fim",
                  json={"sessao": rz.get("sessao")}).json()
    mz = _maior_caminho(fz.get("pasta") or "")
    checar(u"o .zip com a mesma arvore abre abaixo de 260 caracteres",
           0 < mz < 260, str(mz))
    radai_dicom.esquecer_varredura()
    vz = cli.post("/api/bridge/varrer", json={"pasta": fz.get("pasta")}).json()
    checar(u"  e a serie dele chega inteira",
           [s["cortes"] for s in vz.get("series") or []] == [4], str(vz)[:160])
    cli.post("/api/bridge/limpar", json={"sessao": rz.get("sessao")})

    checar(u"caminho curto nao ganha prefixo", E.no_disco("C:\\x\\y") == "C:\\x\\y")
    if os.name == "nt":
        checar(u"caminho de 240 caracteres ou mais ganha o prefixo",
               E.no_disco("C:\\" + "a" * 250).startswith("\\\\?\\C:\\"))
        checar(u"  e o de rede, a forma UNC",
               E.no_disco("\\\\srv\\share\\" + "b" * 240)
               .startswith("\\\\?\\UNC\\srv\\share\\"))
    funda = os.path.join(novo_temp(), *(["pasta_de_trabalho_funda"] * 8))
    original = E.raiz
    E.raiz = lambda criar=True: (os.makedirs(E._com_prefixo(funda),
                                             exist_ok=True) or funda)
    try:
        rr = _enviar(cli, "", rels[0], open(os.path.join(origem, *rels[0].split("/")),
                                            "rb").read())
        ff = cli.post("/api/bridge/receber/fim",
                      json={"sessao": rr.get("sessao")}).json()
        p = ff.get("pasta") or ""
        checar(u"com a pasta de trabalho funda, a leitura volta com o prefixo",
               os.name != "nt" or p.startswith("\\\\?\\"), p[:40])
        checar(u"  e o arquivo esta la, legivel",
               _maior_caminho(p) >= 260 if os.name == "nt" else True,
               str(_maior_caminho(p)))
        radai_dicom.esquecer_varredura()
        checar(u"  e a varredura o acha",
               len(radai_dicom.varrer(p)["series"]) == 1)
        cli.post("/api/bridge/limpar", json={"sessao": rr.get("sessao")})
        checar(u"  e limpar apaga a sessao funda",
               not os.path.exists(E._com_prefixo(p)))
    finally:
        E.raiz = original


def teste_o_envio_nao_sobra_no_temporario():
    secao(u"o conteudo enviado nao sobra no temporario (saida e arranque)")
    import time
    import radai_bridge_entrada as E
    r = E.receber("", "a/IM1.dcm", 0, b"DICM")
    pasta = os.path.join(E.raiz(), r["sessao"])
    checar(u"a sessao existe enquanto o app roda", os.path.isdir(pasta))
    E._ao_sair()
    checar(u"ao sair do app, a sessao e apagada", not os.path.exists(pasta),
           pasta)
    velha = os.path.join(E.raiz(), "0" * 32)
    os.makedirs(velha, exist_ok=True)
    antes = time.time() - E.VALIDADE_S - 60
    os.utime(velha, (antes, antes))
    cliente()
    checar(u"no arranque da tela, a sobra de uma queda e apagada",
           not os.path.exists(velha), velha)


def main():
    print(u"=" * 70)
    print(u"  test_bridge_motor — o motor do DicomBridge")
    print(u"=" * 70)
    try:
        import pydicom
        import fastapi
    except Exception as e:
        print(u"  pydicom/fastapi ausente (%s)" % type(e).__name__)
        print(u"OK: 0 checagens (runtime sem pydicom)")
        return 0
    testes = [teste_miniatura_de_rm_usa_a_janela_da_propria_imagem,
              teste_colorida_e_captura_identificadas,
              teste_a_miniatura_le_um_arquivo_so,
              teste_o_cache_sai_da_pasta_do_exame,
              teste_a_varredura_pula_o_que_e_nosso,
              teste_a_exportacao_devolve_a_lista,
              teste_descomprimir_preserva_os_uids,
              teste_a_colorida_vira_escala_de_cinza,
              teste_a_sintaxe_e_a_mesma_nos_dois_tps,
              teste_subpastas_nao_colidem_pelo_uid8,
              teste_a_conversao_forcada_sem_geometria,
              teste_posicao_parcial_preserva_a_medida,
              teste_ipp_sem_iop_preserva_a_posicao,
              teste_for_ausente_nao_funde_referenciais_diferentes,
              teste_o_que_nao_se_corrige_vira_alerta_e_nao_trava,
              teste_o_conteudo_enviado_vira_pasta_local,
              teste_o_zip_digitado_e_o_enviado_abrem,
              teste_a_entrega_e_uma_pasta_nova_sem_zip,
              teste_a_entrega_recusa_destino_dentro_do_root_do_vigia,
              teste_a_entrega_que_falha_no_meio,
              teste_a_origem_com_prefixo_de_caminho_longo,
              teste_o_texto_declarado_no_dicom,
              teste_o_corte_truncado_nao_chega_ao_tps,
              teste_a_guarda_da_fila,
              teste_o_caminho_longo_da_area_de_envio,
              teste_o_envio_nao_sobra_no_temporario]
    todos = set(k for k, v in globals().items()
                if k.startswith("teste_") and callable(v))
    fora = sorted(todos - set(f.__name__ for f in testes))
    checar(u"todo teste do arquivo esta na lista do main()", not fora,
           u", ".join(fora))
    for t in testes:
        try:
            t()
        except Exception as e:
            import traceback
            checar(u"%s (excecao inesperada)" % t.__name__, False,
                   u"%s: %s" % (type(e).__name__, e))
            traceback.print_exc()
    falhas = [(n, d) for n, ok, d in _RESULTADOS if not ok]
    print(u"\n" + u"=" * 70)
    if falhas:
        print(u"FALHOU: %d de %d checagens" % (len(falhas), len(_RESULTADOS)))
        for n, d in falhas:
            print(u"  - %s%s" % (n, ("  [%s]" % d) if d else ""))
    else:
        print(u"OK: %d checagens, todas passaram" % len(_RESULTADOS))
    print(u"=" * 70)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
