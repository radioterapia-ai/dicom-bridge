# -*- coding: utf-8 -*-
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
APP = os.path.join(RAIZ, "app")
sys.path.insert(0, AQUI)
sys.path.insert(0, APP)

import _cleanup
import _componentes
_cleanup.adotar_prefixo("radai_bdgt_")

PORTA = 8861
BASE = "http://127.0.0.1:%d" % PORTA
_R = []


def checar(nome, ok, detalhe=u""):
    _R.append((nome, bool(ok), detalhe))
    print(u"  %-6s %s%s" % (u"ok" if ok else u"FALHA", nome,
                            (u"  [%s]" % detalhe) if detalhe and not ok else u""))
    return bool(ok)


def secao(t):
    print(u"\n── %s %s" % (t, u"─" * max(0, 64 - len(t))))


def _ds_base(uid_serie, estudo, modalidade, numero, descricao, i, lin, col):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ("1.2.840.10008.5.1.4.1.1.2"
                                            if modalidade == "CT"
                                            else "1.2.840.10008.5.1.4.1.1.4")
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = uid_serie
    ds.StudyInstanceUID = estudo
    ds.PatientName = u"FANTOMA^BRIDGE"
    ds.PatientID = u"FANTOMA0001"
    ds.Modality = modalidade
    ds.SeriesNumber = numero
    ds.SeriesDescription = descricao
    ds.InstanceNumber = i + 1
    ds.Rows, ds.Columns = lin, col
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [2.0, 2.0]
    ds.PatientPosition = "HFS"
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    return ds


def escrever_tc(pasta, n=24, numero=2, descricao=u"TC TORAX FANTOMA",
                estudo="1.2.826.0.1.3680043.8.498.77"):
    import numpy as np
    from pydicom.uid import generate_uid
    os.makedirs(pasta, exist_ok=True)
    uid, frame = generate_uid(), generate_uid()
    yy, xx = np.mgrid[0:128, 0:128]
    for i in range(n):
        hu = np.full((128, 128), -1000, dtype=np.int32)
        corpo = ((xx - 64) / 54.0) ** 2 + ((yy - 66) / 40.0) ** 2 <= 1
        hu[corpo] = 40
        r = 13 + 6 * np.sin(np.pi * i / max(1, n - 1))
        for cx in (42, 86):
            hu[((xx - cx) / r) ** 2 + ((yy - 62) / (r * 1.4)) ** 2 <= 1] = -820
        hu[((xx - 64) ** 2 + (yy - 92) ** 2) <= 64] = 700
        hu[((xx - 64) ** 2 + (yy - 60) ** 2) <= 70] = 60
        ds = _ds_base(uid, estudo, "CT", numero, descricao, i, 128, 128)
        ds.SliceThickness = 3.0
        ds.RescaleSlope = 1
        ds.RescaleIntercept = -1024
        ds.ImagePositionPatient = [-128.0, -128.0, 3.0 * i]
        ds.FrameOfReferenceUID = frame
        ds.PixelData = (hu + 1024).astype(np.uint16).tobytes()
        ds.save_as(os.path.join(pasta, "CT%03d.dcm" % i), enforce_file_format=True)
    return uid


def escrever_rm(pasta, n=20, numero=5, descricao=u"RM T1 CRANIO FANTOMA",
                estudo="1.2.826.0.1.3680043.8.498.77", com_frame=False):
    import numpy as np
    from pydicom.uid import generate_uid
    os.makedirs(pasta, exist_ok=True)
    uid = generate_uid()
    yy, xx = np.mgrid[0:128, 0:128]
    for i in range(n):
        v = np.full((128, 128), 20, dtype=np.int32)
        cab = ((xx - 64) / 50.0) ** 2 + ((yy - 64) / 58.0) ** 2 <= 1
        v[cab] = 1300
        cer = ((xx - 64) / 42.0) ** 2 + ((yy - 64) / 50.0) ** 2 <= 1
        v[cer] = 820 + (i * 7)
        v[((xx - 56) / 6.0) ** 2 + ((yy - 62) / 14.0) ** 2 <= 1] = 300
        v[((xx - 72) / 6.0) ** 2 + ((yy - 62) / 14.0) ** 2 <= 1] = 300
        ds = _ds_base(uid, estudo, "MR", numero, descricao, i, 128, 128)
        ds.SliceThickness = 5.0
        ds.ImagePositionPatient = [-128.0, -128.0, 5.0 * i]
        if com_frame:
            ds.FrameOfReferenceUID = generate_uid()
        ds.PixelData = v.astype(np.uint16).tobytes()
        ds.save_as(os.path.join(pasta, "MR%03d.dcm" % i), enforce_file_format=True)
    return uid


def escrever_rtstruct(pasta, estudo="1.2.826.0.1.3680043.8.498.77"):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    os.makedirs(pasta, exist_ok=True)
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.481.3"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = estudo
    ds.Modality = "RTSTRUCT"
    ds.SeriesNumber = 9
    ds.SeriesDescription = u"ESTRUTURAS"
    ds.save_as(os.path.join(pasta, "RS.dcm"), enforce_file_format=True)


def _png(caminho, linhas):
    import struct
    import zlib
    alt, larg = len(linhas), len(linhas[0])
    cru = b"".join(b"\x00" + bytes(l) for l in linhas)

    def bloco(tipo, dados):
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xffffffff))
    with open(caminho, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + bloco(b"IHDR", struct.pack(">IIBBBBB", larg, alt, 8, 0, 0, 0, 0))
                + bloco(b"IDAT", zlib.compress(cru))
                + bloco(b"IEND", b""))


def escrever_pngs(pasta, n=6, lado=96):
    os.makedirs(pasta, exist_ok=True)
    for k in range(1, n + 1):
        linhas = []
        for y in range(lado):
            if y < 6:
                linhas.append([210 if (x % 9 < 3) else 8 for x in range(lado)])
                continue
            l = []
            for x in range(lado):
                d = ((x - 48) / 40.0) ** 2 + ((y - 50) / 38.0) ** 2
                v = 0 if d > 1 else int(120 + 90 * (1 - d)) - (k * 3)
                l.append(max(0, min(255, v)))
            linhas.append(l)
        _png(os.path.join(pasta, "rm_t2_%04d.png" % k), linhas)


def montar_estudo(raiz):
    tc = escrever_tc(os.path.join(raiz, "TC"))
    rm = escrever_rm(os.path.join(raiz, "RM"))
    escrever_rtstruct(os.path.join(raiz, "RS"))
    escrever_pngs(os.path.join(raiz, "IMAGENS_RM"))
    return {"tc": tc, "rm": rm}


FRASE = (u"Carregue suas imagens que falharam na importação, receba o "
         u"diagnóstico e processe a conversão para TPS de aceitar na fusão")

TRADUZIDAS = (
    u"Limpar carregamentos", u"Marcar todas", u"série anterior",
    u"próxima série", u"Pasta de destino", u"Adicionar outro destino",
    u"Pasta de origem do estudo", u"Imagens", u"falta informar", u"alerta",
    u"ou aponte a pasta do estudo", u"Procurar…", u"COLORIDA",
    u"CAPTURA", u"não foram:", u"série(s)", u"arquivo(s) ignorado(s)",
    u"as séries do estudo aparecem aqui", u"nenhuma série DICOM nesta pasta",
    u"clique marca · duplo clique abre a série", u"abrindo a série",
    u"desmarcar", u"tirar este destino", u"lendo o cabeçalho…", u"alertas",
    FRASE,
    u"A série que nasce de JPEG ou PNG tem Frame of Reference próprio e não "
    u"carrega Hounsfield",
    u"A série exportada leva a identificação do paciente; o destino não pode "
    u"ser pasta que sincroniza com a nuvem",
    u"orientação", u"carregar o estudo",
    u"Escolher as séries", u"Diagnóstico", u"Converter", u"Entregar",
    u"Segmentar", u"segmentação", u"esta modalidade não se segmenta",
    u"a base roda sempre; marque as tasks desta série", u"achado",
    u"Nenhum alerta. A série está pronta para converter.", u"não converte",
    u"série convertida", u"séries convertidas", u"DICOM entregue em",
    u"DICOM entregue · segmentação na fila", u"posição",
    u"DICOM entregue · segmentando", u"DICOM entregue · RTSTRUCT entregue",
    u"DICOM entregue · RTSTRUCT entregue em parte",
    u"DICOM entregue · a segmentação não terminou",
    u"DICOM entregue · fila indisponível", u"Tentar de novo",
    u"Pôr na fila de novo", u"DICOM entregue · pondo na fila…",
    u"a segmentação não foi pedida; o DICOM está entregue.",
    u"a fila não respondeu agora; tento de novo",
    u"série de imagem (JPEG ou PNG) nesta pasta",
    u"séries de imagem (JPEG ou PNG) nesta pasta",
    u"as opções do PERSONALIZADO não vieram do ContourLab",
    u"descrição da série",
    u"espessura do corte (mm)", u"escala (mm por pixel)", u"mais ajustes",
    u"Confirmo a escala", u"Confirmo a ordem dos cortes",
    u"Paciente DESCONHECIDO, ID", u"atribua ao paciente certo no TPS",
    u"tirada da descrição da série: confira",
    u"a descrição não diz a orientação: escolha",
    u"informe a espessura do corte", u"confirme a escala ao lado do MPR",
    u"uma imagem só: sem MPR",
    u"Alertas das outras séries escolhidas",
    u"não chegou a estes destinos:",
    u"DICOM entregue · a fila recusou a segmentação",
    u"DICOM entregue · o cartão saiu da fila",
    u"não sei se o RTSTRUCT chegou: confira a pasta entregue",
    u"DICOM entregue · o RTSTRUCT não chegou a todos os destinos",
    u"DICOM entregue · conferindo o RTSTRUCT nos destinos…",
    u"a fila está parada: clique Iniciar na barra",
    u"Abrir a fila",
    u"dispensar",
    u"o cartão saiu da fila; o RTSTRUCT está ao lado da série",
    u"o cartão saiu da fila sem o RTSTRUCT",
    u"esta estação não guarda mais esta entrega: refaça a entrega para segmentar",
    u"não consegui abrir as imagens",
)

NOVAS_V85 = (
    u"O diagnóstico mostra só os alertas, de todas as séries escolhidas, antes "
    u"de converter. Duas coisas impedem a conversão («não converte»): a "
    u"compressão que este pacote não sabe abrir e o corte com a imagem "
    u"incompleta no arquivo, que chegaria ao TPS corrompido. O resto converte, "
    u"e o que a conversão não corrige vai gravado dentro do próprio DICOM: a "
    u"contagem na descrição da série e o texto nos comentários da imagem. Toda "
    u"série sai descomprimida, na sintaxe que o TPS desta estação importa, com "
    u"os UIDs que trouxe — menos a colorida, que vira escala de cinza, e a "
    u"série sem a posição ou a orientação dos cortes, cuja geometria a "
    u"conversão assume: essas saem com UID novo, para nunca se misturarem com a "
    u"original. A série sem Frame of Reference ganha um novo.",
)

NOVAS_V86 = (
    u"Carregar um CD", u"procurando o CD…",
    u"nenhum CD na unidade: ponha o disco e clique de novo",
    u"há mais de um CD: escolha qual ler", u"lendo o CD", u"arquivos",
    u"leitura do CD cancelada", u"não consegui ler o CD",
)

SAIRAM_V86 = (
    u"converta uma por vez em «Conversão de imagens»", u"Ajustar e finalizar",
    u"Baixar de novo", u"ou aponte a pasta das imagens", u"cortes entregues em",
)

ACHADOS_SEM_TRADUCAO = ()


def novas_dos_modulos():
    import radai_bridge as B
    import radai_image as RI
    import radai_image_screen as IS
    return (B.FRASE_DO_TETO, B.AJUDA[3], IS.AJUDA_NO_PIPELINE[1],
            IS.AJUDA_NO_PIPELINE[2], IS.NOTA_DO_FRAME,
            B.TITULO_DO_TEXTO_DECLARADO, B.TITULO_DA_CAPTURA,
            RI.TITULO_SEM_CONFERIR_O_CARIMBO, RI.TITULO_DO_CARIMBO_NAO_CONFERIDO)


def novas_dos_modulos_v86():
    import radai_bridge as B
    return (B.AJUDA[4],)


def rotulos_do_laudo():
    import radai_dicom as D
    with open(D.__file__, encoding="utf-8") as fh:
        return sorted(set(re.findall(r'enc\[u?"([^"]+)"\]', fh.read())))


def _formatos(no):
    import ast
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return [no.value]
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Mod):
        return _formatos(no.left)
    if isinstance(no, ast.IfExp):
        return _formatos(no.body) + _formatos(no.orelse)
    return []


def textos_dos_achados(fonte):
    import ast
    fora = []
    for n in ast.walk(ast.parse(fonte)):
        if not (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_achado"):
            continue
        args = list(n.args[1:3]) + [k.value for k in n.keywords
                                    if k.arg in ("detalhe", "o_que_faz")]
        for a in args:
            fora += [t for t in _formatos(a) if t.strip()]
    return fora


def teste_os_achados_do_diagnostico_tem_chave():
    secao(u"TEL-04: os achados do diagnóstico do DicomBridge têm chave nos doze idiomas")
    import radai_dicom as D
    import radai_phrases as F
    with open(D.__file__, encoding="utf-8") as fh:
        fonte = fh.read()
    textos = textos_dos_achados(fonte)
    checar(u"a busca acha os achados (título, detalhe, o que faz)", len(textos) >= 40,
           str(len(textos)))
    d = F.construir()

    def _traduzido(t):
        return all(d[c].get(F.normalizar(t)) for c in F.CODIGOS
                   if F.normalizar(t) not in (u"%s",))
    sem = [t for t in textos if t not in ACHADOS_SEM_TRADUCAO and not _traduzido(t)]
    checar(u"  cada um com as onze traduções", not sem, u" | ".join(s[:50] for s in sem[:5]))
    velhos = [t for t in ACHADOS_SEM_TRADUCAO if t not in textos or _traduzido(t)]
    checar(u"  a espera da tradução só tem achado vivo e ainda sem chave "
           u"(traduziu? tire de ACHADOS_SEM_TRADUCAO)", not velhos,
           u" | ".join(s[:50] for s in velhos[:5]))
    print(u"         · %d achado(s) novo(s) do laudo ainda sem tradução "
          u"(a tradução vem depois)" % len(ACHADOS_SEM_TRADUCAO))
    isca = textos_dos_achados(u"_achado(False, u'Achado novo sem chave %.2f.' % x)")
    checar(u"  (isca) achado novo é achado pela busca, e reprova",
           isca == [u"Achado novo sem chave %.2f."]
           and not d["en"].get(F.normalizar(isca[0])))


def _visivel(p):
    import html as _h
    p = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", u" ", p)
    return u" ".join(_h.unescape(re.sub(r"<[^>]+>", u" ", p)).split())


def teste_a_estrutura():
    secao(u"a estrutura: um cartão, um pipeline, cabeça, frase, alerta, ? e o que saiu")
    import radai_bridge as B
    import radai_image_screen as IS
    import radai_modules as M
    import radai_ui
    pip = B.pagina()
    checar(u"a cabeça do pipeline é a de função, com a frase do autor",
           u'class="ui-fn-tag"' in pip and u"Converter imagens para o TPS" in pip
           and FRASE in _visivel(pip))
    checar(u"  na cor do DicomBridge", u"--ui-fn-cor:var(--mod-bridge)" in pip)

    def _icone_da_cabeca(p):
        m = re.search(r'<span class="ui-fn-ic" aria-hidden="true">(.*?)</span>', p, re.S)
        return m.group(1) if m else u""
    checar(u"  com o ícone SVG por nome (TEL-19): exportar",
           _icone_da_cabeca(pip) == radai_ui.icone(u"exportar")
           and u"<svg" in _icone_da_cabeca(pip))
    checar(u"  (isca) o glifo de antes seria acusado",
           _icone_da_cabeca(radai_ui.cabeca_de_funcao(u"▣", u"x", u"y"))
           != radai_ui.icone(u"exportar"))
    cartoes = [f[0] for f in M.FERRAMENTAS[u"bridge"]]
    checar(u"a mini-página do DicomBridge tem UM cartão, o pipeline",
           cartoes == [u"bridge_laudo"], str(cartoes))
    mini = M.pagina(u"bridge")
    checar(u"  e a página da mini-página leva um link só, para /bridge/laudo",
           re.findall(r'<a class="md-fer[^"]*" href="([^"]+)"', mini) == [u"/bridge/laudo"],
           str(re.findall(r'<a class="md-fer[^"]*" href="([^"]+)"', mini)))
    al = re.findall(r'<div class="ui-alerta[^"]*">', pip)
    checar(u"UM alerta de rodapé", len(al) == 1, str(len(al)))
    checar(u"o texto longo mora no ?", u'class="ui-ajuda' in pip.split(u"</header>")[0])
    checar(u"  e o ? fala da imagem e do CD dentro do pipeline",
           all(t in pip for t in (B.AJUDA[4],) + IS.AJUDA_NO_PIPELINE))
    e3 = pip[pip.find(u'id="dc_e3"'):pip.find(u'id="dc_e4"')]
    checar(u"o ajuste da imagem mora na etapa 3 (Diagnóstico), escondido até abrir uma imagem",
           re.search(r'id="dc_bloco_imagem" hidden', e3) is not None
           and u'id="im_esp"' in e3 and u'id="dc_bloco_dicom"' in e3)
    checar(u"saiu a tela própria da conversão de imagens",
           not hasattr(IS, u"pagina") and u"dc_imagens" not in pip
           and u"/bridge/imagem" not in B.JS)
    def _sobras_da_barra(p):
        return [s for s in (u"data-dir-inicial", u"uiDireita('1')",
                            u"radai_dir_recolhido") if s in p]
    checar(u"a barra da direita nasce pela casca: a página não pede o "
           u"recolhimento por script nem por atributo do corpo",
           not _sobras_da_barra(B.PAGINA) and not _sobras_da_barra(B.JS),
           str(_sobras_da_barra(B.PAGINA) + _sobras_da_barra(B.JS)))
    checar(u"  (isca) a página com o atributo e o script antigos é acusada",
           len(_sobras_da_barra(B.PAGINA.replace(
               u"</head><body>",
               u"</head><body data-dir-inicial=\"recolhida\">\n<script>try{ "
               u"if(window.uiDireita) window.uiDireita('1') }catch(e){}"
               u"</" + u"script>", 1))) == 2)
    checar(u"saiu o «Escolha o que exportar» (um cartão só)",
           u"Escolha o que exportar" not in pip and u"dc_salvar_bt" not in pip)
    checar(u"saiu o «Segmentar séries do estudo» pelo Rodar agora",
           u"Segmentar séries do estudo" not in pip and u"/api/lote/selecao" not in B.JS)

    def _abre_corpo(js):
        return u"<body" in js.lower()
    checar(u"nenhum JS servido traz o texto da tag de abertura do corpo",
           not any(_abre_corpo(j) for j in (radai_ui.JS, radai_ui.COMPONENTES_JS,
                                              B.JS, B.JS_COMUM, IS.JS)))
    checar(u"  (isca) um comentário com a tag é acusado",
           _abre_corpo(u"// diz isso no `<body>`"))
    fecha = u"<" + u"/script"
    checar(u"nenhum JS servido traz a tag que fecha o script",
           not any(fecha in j.lower() for j in (B.JS, B.JS_COMUM, IS.JS)))
    checar(u"o glifo de alerta é SVG de radai_ui", bool(radai_ui.icone(u"alerta"))
           and u"alerta" in radai_ui.ICONES_DOS_COMPONENTES)
    import radai_release
    checar(u"o campo do DicomBridge não recebe o «soltar caminho»",
           u"'dc_pasta'" not in radai_release.JS)
    import radai_phrases as F
    tab = dict((F.normalizar(l[0]), l) for l in F.TABELA)
    faltam = [f for f in TRADUZIDAS if F.normalizar(f) not in tab]
    checar(u"as frases que ficaram continuam no dicionário", not faltam,
           u" | ".join(faltam[:5]))
    tela = _visivel(pip) + u" " + B.JS_COMUM + B.JS + IS.JS
    soltas = [f for f in NOVAS_V85 + NOVAS_V86 if f not in tela]
    checar(u"cada frase nova da v8.5 e da v8.6 está mesmo na tela (a lista não apodrece)",
           not soltas, u" | ".join(soltas[:5]))
    voltaram = [f for f in SAIRAM_V86 if f in tela]
    checar(u"as frases da tela de imagem que saiu não voltam", not voltaram,
           u" | ".join(voltaram))
    modulos = novas_dos_modulos()
    checar(u"  e as dos módulos (teto, ajuda, títulos do laudo) existem e são frases",
           all(isinstance(f, type(u"")) and len(f) > 8 for f in modulos))
    sem = [f for f in modulos if F.normalizar(f) not in tab
           or not all(tab[F.normalizar(f)][1:])]
    checar(u"  e as dos módulos têm chave nos doze idiomas (%d)" % len(modulos),
           not sem, u" | ".join(f[:50] for f in sem[:5]))
    pendentes = [f for f in NOVAS_V85 + NOVAS_V86 + novas_dos_modulos_v86()
                 if F.normalizar(f) not in tab]
    print(u"         · %d frase(s) nova(s) ainda sem tradução "
          u"(a tradução vem depois)" % len(pendentes))


def teste_as_rotas():
    secao(u"as rotas: carga, etapas, imagem e o que saiu")
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    import radai_bridge as B
    import radai_dicom
    radai_dicom.esquecer_varredura()
    app = B.montar(FastAPI())
    cli = TestClient(app)
    r = cli.get(u"/bridge/tps", follow_redirects=False)
    checar(u"/bridge/tps leva ao pipeline",
           r.status_code in (301, 302, 307, 308)
           and r.headers.get(u"location") == u"/bridge/laudo", str(r.status_code))
    ri = cli.get(u"/bridge/imagem", follow_redirects=False)
    checar(u"/bridge/imagem leva ao pipeline (a conversão de imagens mora nele)",
           ri.status_code == 307 and ri.headers.get(u"location") == u"/bridge/laudo",
           str(ri.status_code))
    for rota in (u"/api/imagem/carregar", u"/api/imagem/finalizar",
                 u"/api/imagem/de_novo", u"/api/imagem/descartar"):
        checar(u"POST %s saiu (sem tela)" % rota, cli.post(rota, json={}).status_code == 404)
    for rota in (u"/api/bridge/converter", u"/api/bridge/entregar",
                 u"/api/bridge/salvar", u"/api/imagem/converter",
                 u"/api/imagem/varrer", u"/api/imagem/identidade"):
        checar(u"POST %s saiu" % rota, cli.post(rota, json={}).status_code == 404)
    for rota in (u"/api/bridge/baixar", u"/api/bridge/corpus"):
        checar(u"GET %s saiu" % rota, cli.get(rota).status_code == 404)
    d = tempfile.mkdtemp(prefix=u"radai_bdgt_")
    uids = montar_estudo(os.path.join(d, u"estudo"))
    v = cli.post(u"/api/bridge/varrer", json={u"pasta": os.path.join(d, u"estudo")}).json()
    ss = v.get(u"series") or []
    mods = sorted(s[u"modalidade"] for s in ss)
    checar(u"a carga acha TC, RM e RTSTRUCT", mods == [u"CT", u"MR", u"RTSTRUCT"], str(mods))
    checar(u"  e traz a série de imagem para a mesma grade, sem caminho",
           [(x[u"n"], x[u"imagem"], x[u"modalidade"]) for x in v.get(u"imagens") or []]
           == [(6, True, u"JPEG/PNG")]
           and d not in json.dumps(v.get(u"imagens")), str(v.get(u"imagens"))[:120])
    checar(u"  e os PNG não contam como ignorados",
           not any(n.lower().endswith(u".png") for n in v.get(u"ignorados") or []))
    checar(u"  a origem é a pasta digitada", v.get(u"origem") == os.path.join(d, u"estudo"))
    zp = os.path.join(d, u"estudo_tc.zip")
    with zipfile.ZipFile(zp, "w") as z:
        for a in os.listdir(os.path.join(d, u"estudo", u"TC")):
            z.write(os.path.join(d, u"estudo", u"TC", a), os.path.join(u"TC", a))
    vz = cli.post(u"/api/bridge/varrer", json={u"pasta": zp}).json()
    checar(u"o .zip digitado no campo abre e vira série",
           [s[u"modalidade"] for s in vz.get(u"series") or []] == [u"CT"], str(vz)[:160])
    checar(u"  e a origem oferecida é a pasta onde o .zip está", vz.get(u"origem") == d)
    tc = [s for s in ss if s[u"modalidade"] == u"CT"][0]
    rm = [s for s in ss if s[u"modalidade"] == u"MR"][0]
    c = cli.post(u"/api/bridge/etapa/converter", json={
        u"pasta": os.path.join(d, u"estudo"),
        u"series": [{u"b": tc[u"bilhete"]}, {u"b": rm[u"bilhete"]}]}).json()
    checar(u"Converter converte as duas", len(c.get(u"exportadas") or []) == 2, str(c)[:200])
    d1, d2 = os.path.join(d, u"dest1"), os.path.join(d, u"dest2")
    e = cli.post(u"/api/bridge/etapa/entregar", json={
        u"conversao": c.get(u"conversao"), u"destinos": [d1, d2]}).json()
    checar(u"Entregar grava a pasta DICOM_BRIDGE_ em CADA destino, com o mesmo nome",
           len(e.get(u"saidas") or []) == 2
           and all(os.path.isdir(o[u"pasta"]) for o in e[u"saidas"])
           and len(set(os.path.basename(o[u"pasta"]) for o in e[u"saidas"])) == 1
           and os.path.basename(e[u"saidas"][0][u"pasta"]).startswith(u"DICOM_BRIDGE_"),
           str(e.get(u"saidas"))[:200])
    checar(u"  sem .zip", not any(n.endswith(u".zip") for n in os.listdir(d1) + os.listdir(d2)))
    sel = e.get(u"series") or []
    checar(u"para a fila: as séries ENTREGUES, com o UID e as cópias",
           sorted(x[u"uid"] for x in sel) == sorted([uids[u"tc"], uids[u"rm"]])
           and all(x[u"pasta"].startswith(e[u"saidas"][0][u"pasta"])
                   and x[u"copias"][0].startswith(e[u"saidas"][1][u"pasta"])
                   for x in sel), str(sel)[:200])
    img = (v.get(u"imagens") or [{}])[0]
    geo = {u"espacamento_mm": [2.5, 2.5], u"espessura_mm": 5.0,
           u"orientacao": u"axial", u"posicao_paciente": u"HFS"}
    cm = cli.post(u"/api/bridge/etapa/converter", json={
        u"pasta": os.path.join(d, u"estudo"),
        u"series": [{u"b": tc[u"bilhete"]},
                    {u"b": img.get(u"bilhete"), u"imagem": {
                        u"geometria": geo, u"descricao": u"RM T2 AXIAL",
                        u"modalidade": u"MR"}}]}).json()
    exm = cm.get(u"exportadas") or []
    checar(u"DICOM e imagem convertem no MESMO pedido do pipeline",
           [x.get(u"imagem") for x in exm] == [None, True]
           and exm[1].get(u"cortes") == 6, str(cm)[:200])
    d3 = os.path.join(d, u"dest3")
    em = cli.post(u"/api/bridge/etapa/entregar", json={
        u"conversao": cm.get(u"conversao"), u"destinos": [d3]}).json()
    pasta3 = (em.get(u"saidas") or [{}])[0].get(u"pasta") or u""
    dentro = sorted(os.listdir(pasta3)) if os.path.isdir(pasta3) else []
    checar(u"  e saem na mesma pasta: a série DICOM, a IMAGEM e o LEIA-ME.txt",
           len(dentro) == 3 and u"IMAGEM" in dentro and u"LEIA-ME.txt" in dentro,
           str(dentro))
    checar(u"  com o ID gerado da imagem na resposta, e a DICOM indo para a fila",
           len(em.get(u"ids_externos") or []) == 1
           and uids[u"tc"] in [x[u"uid"] for x in em.get(u"series") or []],
           str(em.get(u"ids_externos")))


def _chromium():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    if not os.path.isdir(base):
        return None
    for nome in sorted(os.listdir(base), reverse=True):
        if not nome.startswith("chromium-"):
            continue
        for sub in ("chrome-win64", "chrome-win"):
            exe = os.path.join(base, nome, sub, "chrome.exe")
            if os.path.isfile(exe):
                return exe
    return None


def _subir(base_tmp):
    share = os.path.join(base_tmp, "share")
    os.makedirs(share, exist_ok=True)
    cfg = os.path.join(base_tmp, "t.config")
    io.open(cfg, "w", encoding="utf-8").write(
        u"ROOT=%s\nDRY_RUN=1\nMIN_SLICES=5\nQUIET_MIN=0\nTPS_DESTINO=eclipse\n"
        u"PORT=%d\nLOG_DIR=%s\n" % (share, PORTA, os.path.join(base_tmp, "log")))
    env = dict(os.environ, RADAI_CONFIG=cfg, RADAI_MACHINE="BATERIA_BRIDGE",
               RADAI_CALIB_DIR=os.path.join(base_tmp, "calib"),
               RADAI_REGISTRO_DIR=os.path.join(base_tmp, "registro"),
               LOCALAPPDATA=os.path.join(base_tmp, "ad"),
               RADAI_TMP=os.path.join(base_tmp, "tmp"),
               RADAI_NOTIFICACAO="0", RADAI_URL_VERSOES="0",
               PYTHONIOENCODING="utf-8:replace")
    os.makedirs(env["RADAI_TMP"], exist_ok=True)
    saida = io.open(os.path.join(base_tmp, "vigia.log"), "wb")
    proc = subprocess.Popen(
        [sys.executable, _componentes.fonte("app/radai_watcher.py")],
        env=env, stdout=saida, stderr=subprocess.STDOUT)
    for _ in range(90):
        try:
            urllib.request.urlopen(BASE + "/aceite", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    return None


def _aceitar(pg):
    pg.goto(BASE + "/bridge/laudo", wait_until="networkidle")
    if "/aceite" in pg.url:
        pg.wait_for_timeout(500)
        pg.check("#ac_ok")
        pg.click("#ac_bt")
        pg.wait_for_timeout(1200)


def _abrir(pg, rota, idioma="pt-BR", tema=None):
    pg.evaluate("(function(a){ try{ localStorage.setItem('radai_idioma', a[0]);"
                " if(a[1]) localStorage.setItem('radai_tema', a[1]);"
                " else localStorage.removeItem('radai_tema') }catch(e){} })",
                [idioma, tema])
    pg.goto(BASE + rota, wait_until="networkidle")
    pg.wait_for_timeout(600)


def _carregar(pg, pasta):
    pg.fill("#dc_pasta", pasta)
    pg.click("#dc_carregar")
    pg.wait_for_function("DC.series.length > 0 && DC.rodando === 0"
                         " && DC.filaMini.length === 0", timeout=20000)
    pg.wait_for_timeout(300)


def _indice(pg, mod):
    return pg.evaluate("(function(m){ for(var i=0;i<DC.series.length;i++)"
                       " if(DC.series[i].modalidade===m) return i; return -1 })", mod)


def _clicar_e_esperar(pg, sel, ms=420):
    pg.click(sel)
    pg.wait_for_timeout(ms)


def _rect(pg, sel):
    return pg.evaluate("(function(s){ var e=document.querySelector(s); if(!e) return null;"
                       " var r=e.getBoundingClientRect();"
                       " return {x:r.left,y:r.top,w:r.width,h:r.height,b:r.bottom} })", sel)


def _destino_pelo_explorador(pg, botao, caminho):
    pg.click(botao)
    pg.wait_for_selector(".ui-fp-cam", timeout=8000)
    pg.wait_for_timeout(1200)
    pg.fill(".ui-fp-cam", caminho)
    pg.press(".ui-fp-cam", "Enter")
    alvo = os.path.normcase(caminho.rstrip("\\/"))
    for _ in range(40):
        pg.wait_for_timeout(150)
        v = pg.input_value(".ui-fp-cam")
        if os.path.normcase(v.rstrip("\\/")) == alvo:
            break
    pg.click('[data-fp="usar"]')
    pg.wait_for_timeout(500)


def _so_um_destino(pg, caminho):
    for _ in range(4):
        ds = pg.evaluate("BG.destinos.slice()")
        if len(ds) <= 1:
            break
        pg.click("#bg_dest_lista li:first-child .bg-dest-x")
        pg.wait_for_timeout(300)
    return pg.evaluate("BG.destinos.slice()") == [caminho]


def _print(pg, pasta, nome):
    if not pasta:
        return
    os.makedirs(pasta, exist_ok=True)
    pg.evaluate("window.scrollTo(0, 0)")
    pg.wait_for_timeout(150)
    pg.screenshot(path=os.path.join(pasta, nome + ".png"), full_page=True)


def _contar_brilho(pg):
    pg.evaluate("""(function(){ window.__brilho = 0;
      var o = window.uiCarregando;
      window.uiCarregando = function(a, l, t){ if(l !== false) window.__brilho++;
        return o ? o.apply(this, arguments) : null } })()""")


OPCOES_DUBLADAS = {
    "modalidade": "MR", "base": "total_mr",
    "ligadas_de_fabrica": ["vertebrae_mr", "achado_mr"],
    "tasks": [{"task": "vertebrae_mr", "rotulo": u"Vértebras", "achado": False},
              {"task": "achado_mr", "rotulo": u"Achado de teste", "achado": True},
              {"task": "proibida_mr", "rotulo": u"Proibida", "permitida": False}]}


def roteiro_pipeline(pg, estudo, uids, tmp, prints):
    secao(u"o pipeline: a tela renderizada, etapa por etapa")
    _abrir(pg, "/bridge/laudo")
    h1 = pg.evaluate("(document.querySelector('h1.ui-fn-tag')||{}).textContent||''")
    checar(u"a tag grande diz o nome da função", u"Converter imagens para o TPS" in h1, h1)
    checar(u"a casca chega à tela: o trilho e o cabeçalho, no corpo",
           pg.evaluate("!!document.querySelector('body > nav.radai-menu')"
                       " && !!document.querySelector('body header.rc-topo')"))
    checar(u"a barra da direita nasce recolhida",
           pg.evaluate("document.documentElement.classList.contains('dir-recolhida')"))
    vis = pg.evaluate("[1,2,3,4,5,6].map(function(k){ return !document.getElementById('dc_e'+k).hidden })")
    checar(u"só a etapa 1 aparece no começo", vis == [True] + [False] * 5, str(vis))
    lim, cab = _rect(pg, "#dc_limpar"), _rect(pg, "#dc_e1 .pp-cab")
    checar(u"«Limpar carregamentos» em destaque, no cabeçalho da etapa 1",
           lim and cab and lim["y"] >= cab["y"] - 1 and lim["b"] <= cab["b"] + 1
           and pg.evaluate("document.getElementById('dc_limpar').classList.contains('bg-limpar')"),
           str((lim, cab)))
    _print(pg, prints, "01_pipeline_vazio_1280_pt_escuro")

    _contar_brilho(pg)
    _carregar(pg, estudo)
    msg = pg.inner_text("#dc_msg")
    checar(u"a mensagem conta as séries DICOM", u"3" in msg and u"série" in msg, msg)
    checar(u"a etapa 2 abre", not pg.evaluate("document.getElementById('dc_e2').hidden"))
    checar(u"quatro cartões na MESMA grade (TC, RM, RTSTRUCT e a série de imagem)",
           pg.evaluate("DC.series.length") == 4
           and pg.evaluate("DC.series.filter(function(s){ return s.imagem }).length") == 1)
    checar(u"o brilho de processamento acende nas prévias",
           pg.evaluate("window.__brilho") >= 2, str(pg.evaluate("window.__brilho")))
    i_tc, i_rm, i_rs = _indice(pg, "CT"), _indice(pg, "MR"), _indice(pg, "RTSTRUCT")
    b_tc = pg.evaluate("DC.series[%d].bilhete" % i_tc)
    src = pg.evaluate("document.getElementById('dci%d').src" % i_tc)
    checar(u"cada miniatura pede a série DO cartão (pelo bilhete)", b_tc in src, src[-60:])
    checar(u"a série sem pixel mostra a sigla e não se marca",
           pg.evaluate("document.getElementById('dcm%d').getAttribute('data-mod')" % i_rs)
           == u"RTSTRUCT"
           and pg.evaluate("document.getElementById('dcs%d').classList.contains('fora')" % i_rs))
    i_img = _indice_da_imagem(pg)
    b_img = pg.evaluate("DC.series[%d].bilhete" % i_img)
    src_img = pg.evaluate("document.getElementById('dci%d').src" % i_img)
    checar(u"a série de imagem é um cartão da grade, com a prévia pelo bilhete",
           u"/api/imagem/previa?b=" + b_img in src_img
           and u"JPEG/PNG" in pg.inner_text("#dcmm%d" % i_img), src_img[-80:])
    checar(u"  e a mensagem conta a série de imagem",
           u"série de imagem (JPEG ou PNG)" in msg, msg)
    checar(u"  e nenhum link para outra tela de imagem",
           pg.evaluate("!document.querySelector('a[href^=\"/bridge/imagem\"]')"))

    secao(u"marcar e escolher a segmentação de cada série")
    x_vis = pg.evaluate("getComputedStyle(document.querySelector('#dcs%d .dc-x')).display" % i_tc)
    checar(u"o ⓧ não aparece na série desmarcada", x_vis == u"none", x_vis)
    _clicar_e_esperar(pg, "#dcs%d" % i_tc)
    checar(u"  marcada, o ⓧ aparece e a linha de segmentação também",
           pg.evaluate("getComputedStyle(document.querySelector('#dcs%d .dc-x')).display"
                       % i_tc) != u"none"
           and pg.evaluate("document.querySelectorAll('#dc_marcadas .dc-mrow').length") == 1)
    pg.click("#dcs%d .dc-x" % i_tc)
    pg.wait_for_timeout(350)
    checar(u"  e clicar no ⓧ desmarca", not pg.evaluate("!!DC.marcadas[%d]" % i_tc))
    pg.click("#dc_marcar_todas")
    pg.wait_for_timeout(300)
    m = pg.evaluate("dcMarcadas().map(function(i){return DC.series[i].modalidade})")
    checar(u"«Marcar todas» marca as séries com imagem (o RTSTRUCT não)",
           sorted(m) == [u"CT", u"JPEG/PNG", u"MR"], str(m))
    checar(u"  e a série de imagem não se segmenta",
           u"esta modalidade não se segmenta" in pg.inner_text("#dcr_%s" % b_img))
    pg.click("#dcs%d .dc-x" % i_img)
    pg.wait_for_timeout(350)
    checar(u"  (o roteiro segue com as duas DICOM; a imagem tem roteiro próprio)",
           not pg.evaluate("!!DC.marcadas[%d]" % i_img))
    pg.route("**/api/lote/opcoes*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(OPCOES_DUBLADAS)))
    b_rm = pg.evaluate("DC.series[%d].bilhete" % i_rm)
    pg.click("#dcr_%s .dc-seg button[data-modo=\"fast\"]" % b_tc)
    pg.click("#dcr_%s .dc-seg button[data-modo=\"personalizado\"]" % b_rm)
    pg.wait_for_function("document.querySelectorAll('#dct_%s input[data-task]').length === 2" % b_rm,
                         timeout=8000)
    ch = pg.evaluate("DC.seg['%s'].chaves" % b_rm)
    checar(u"o PERSONALIZADO lista as tasks permitidas, e a de achado nasce desmarcada",
           ch == {u"vertebrae_mr": 1, u"achado_mr": 0}, str(ch))
    _print(pg, prints, "02_pipeline_escolha_1280_pt_escuro")

    secao(u"diagnóstico: só alertas, com o visor")
    pg.click("#dc_avancar")
    pg.wait_for_function("!document.getElementById('dc_e3').hidden", timeout=8000)
    pg.wait_for_function("document.querySelector('#dc_laudo .dc-falta')", timeout=10000)
    pg.wait_for_timeout(900)
    checar(u"duas séries na lista do diagnóstico, «1 / 2»",
           pg.evaluate("document.querySelectorAll('.dc-diag-item').length") == 2
           and pg.inner_text("#dc_nav_pos") == u"1 / 2", pg.inner_text("#dc_nav_pos"))
    checar(u"  o visor da série abre", pg.evaluate("!!document.querySelector('#dc_visor .ue-visor')"))
    pg.wait_for_function("!document.getElementById('dc_converter').disabled", timeout=15000)
    outras = pg.evaluate("document.getElementById('dc_outras').textContent")
    checar(u"  os alertas da OUTRA série aparecem antes de converter",
           u"Alertas das outras séries escolhidas" in outras
           and pg.evaluate("Object.keys(DC.laudos).length") == 2
           and u"…" not in pg.inner_text("#dc_diag_lista"), outras[:200])
    pg.evaluate("dcAbrir(%d)" % i_rm)
    pg.wait_for_function("document.querySelector('#dc_laudo .dc-falta.decide')", timeout=10000)
    tts = pg.evaluate("Array.from(document.querySelectorAll('#dc_laudo .dc-falta .tt'))"
                      ".map(function(e){return e.textContent})")
    checar(u"a RM mostra o alerta (Frame of Reference ausente)",
           any(u"FrameOfReferenceUID" in t for t in tts), str(tts))
    checar(u"  e nada além de alertas (nem «a conversão resolve», nem «já conformes»)",
           pg.evaluate("document.querySelectorAll('#dc_laudo .dc-falta.resolve,"
                       " #dc_laudo .dc-falta.bom, #dc_laudo details').length") == 0)
    checar(u"  e não pede decisão: nenhuma caixa de aceite",
           pg.evaluate("document.querySelectorAll('#dc_e3 input[type=checkbox]').length") == 0)
    _print(pg, prints, "03_pipeline_diagnostico_1280_pt_escuro")

    secao(u"converter e entregar numa pasta nova, sem .zip")
    pg.click("#dc_converter")
    pg.wait_for_function("!document.getElementById('dc_e5').hidden", timeout=60000)
    pg.wait_for_timeout(500)
    checar(u"a conversão lista as duas séries",
           pg.evaluate("document.querySelectorAll('#dc_conv tr').length") == 2)
    padrao = pg.evaluate("BG.destinos.slice()")
    via = json.loads(urllib.request.urlopen(BASE + "/api/bridge/destinos").read().decode("utf-8"))
    checar(u"a pasta de destino nasce com Downloads", padrao == [via.get(u"downloads")],
           str(padrao))
    d1 = os.path.join(tmp, u"entrega_a")
    os.makedirs(d1, exist_ok=True)
    _destino_pelo_explorador(pg, "#dc_e5 #bg_dest_mais", d1)
    checar(u"«Adicionar outro destino» acrescenta a pasta escolhida, e o ✕ tira Downloads",
           _so_um_destino(pg, d1), str(pg.evaluate("BG.destinos")))
    checar(u"a frase da fronteira aparece no gesto que põe na fila",
           pg.evaluate("!document.getElementById('dc_fronteira').hidden")
           and u"UNAPPROVED" in pg.inner_text("#dc_fronteira"))
    pedidos = {}

    def _fila(rota):
        try:
            pedidos["fila"] = json.loads(rota.request.post_data or "{}")
        except Exception:
            pedidos["fila"] = {}
        rota.fulfill(status=200, content_type="application/json",
                     body=json.dumps({"ok": True, "cartoes": [
                         {"id": "c1", "posicao": 2}, {"id": "c2", "posicao": 3}]}))
    estado = {"e": "esperando", "rodando": False}

    def _estado(rota):
        pedidos["estado"] = json.loads(rota.request.post_data or "{}")
        rota.fulfill(status=200, content_type="application/json",
                     body=json.dumps({"rodando": estado["rodando"], "cartoes": [
                         {"id": "c1", "estado": estado["e"], "posicao": 2},
                         {"id": "c2", "estado": estado["e"], "posicao": 3}]}))
    pg.route("**/api/fila/enfileirar", _fila)
    pg.route("**/api/fila/estado", _estado)
    pg.evaluate("""(function(){ window.__abriu = 0;
      window.radaiFilaAbrir = function(){ window.__abriu++; return true } })()""")
    pg.click("#dc_entregar")
    pg.wait_for_function("!document.getElementById('dc_e6').hidden"
                         " && DC.filas.length === 1 && DC.filas[0].estado === 'na_fila'",
                         timeout=60000)
    pg.wait_for_timeout(400)
    feitos = os.listdir(d1)
    checar(u"a entrega é UMA pasta DICOM_BRIDGE_<data_hora>, sem .zip",
           len(feitos) == 1 and re.match(r"^DICOM_BRIDGE_\d{8}_\d{6}$", feitos[0]),
           str(feitos))
    if feitos:
        subs = os.listdir(os.path.join(d1, feitos[0]))
        checar(u"  com uma subpasta por série", len(subs) == 2, str(subs))
    itens = (pedidos.get("fila") or {}).get("itens") or []
    checar(u"(C1, rota dublada) a fila recebe as duas séries ENTREGUES",
           sorted(x.get("uid") for x in itens) == sorted([uids[u"tc"], uids[u"rm"]])
           and all(x.get("pasta", "").startswith(os.path.join(d1, feitos[0]))
                   for x in itens), str(itens)[:200])
    por = dict((x.get("uid"), x) for x in itens)
    checar(u"  (C1) com o modo e as tasks de cada série",
           por.get(uids[u"tc"], {}).get("modo") == u"fast"
           and por.get(uids[u"rm"], {}).get("modo") == u"personalizado"
           and por.get(uids[u"rm"], {}).get("chaves") == {u"vertebrae_mr": 1,
                                                         u"achado_mr": 0},
           str(itens)[:300])
    checar(u"  (C1) origem DicomBridge e nenhuma cópia (um destino só)",
           all(x.get("origem") == u"dicombridge" and x.get("copiar_rs_para") == []
               for x in itens))
    texto = pg.inner_text("#dc_fila")
    checar(u"o cartão diz «DICOM entregue · segmentação na fila (posição 2)»",
           u"DICOM entregue · segmentação na fila" in texto and u"2" in texto, texto)
    checar(u"  e a barra da fila abre (window.radaiFilaAbrir)",
           pg.evaluate("window.__abriu") >= 1, str(pg.evaluate("window.__abriu")))
    B_SESSAO = __import__("radai_bridge").CHAVE_DA_SESSAO
    checar(u"  e os itens ficam guardados no servidor (um bilhete opaco na tela)",
           bool(pg.evaluate("DC.filas[0].guarda"))
           and d1 not in (pg.evaluate("sessionStorage.getItem('%s') || ''"
                                      % B_SESSAO) or u""),
           str(pg.evaluate("sessionStorage.getItem('%s')" % B_SESSAO))[:160])
    pg.evaluate("dcFilaConsultar()")
    pg.wait_for_function("document.getElementById('dc_fila').textContent"
                         ".indexOf('Iniciar') >= 0", timeout=8000)
    checar(u"fila parada: o cartão manda clicar Iniciar na barra",
           u"a fila está parada: clique Iniciar na barra" in pg.inner_text("#dc_fila")
           and pg.evaluate("!!document.querySelector('#dc_fila .dc-fila-abrir')"),
           pg.inner_text("#dc_fila")[:200])
    _print(pg, prints, "04_pipeline_na_fila_1280_pt_escuro")
    estado["e"] = "pronto"
    estado["rodando"] = True
    pg.evaluate("dcFilaConsultar()")
    pg.wait_for_function("document.getElementById('dc_fila').textContent"
                         ".indexOf('RTSTRUCT entregue') >= 0", timeout=8000)
    checar(u"quando a fila termina: «RTSTRUCT entregue»",
           u"RTSTRUCT entregue" in pg.inner_text("#dc_fila")
           and u"Iniciar" not in pg.inner_text("#dc_fila"))
    checar(u"  e o estado foi pedido pelos ids", (pedidos.get("estado") or {}).get("ids")
           == [u"c1", u"c2"], str(pedidos.get("estado")))
    pg.unroute("**/api/fila/enfileirar")
    pg.route("**/api/fila/enfileirar", lambda r: r.fulfill(
        status=404, content_type="application/json", body='{"detail":"Not Found"}'))
    pg.evaluate("dcSegmentar(DC.filas[0].itens, 'DICOM_BRIDGE_SEGUNDA')")
    pg.wait_for_function("DC.filas.length === 2 && DC.filas[1].estado === 'indisponivel'",
                         timeout=8000)
    checar(u"sem a rota da fila, a tela diz «fila indisponível» e não quebra",
           u"fila indisponível" in pg.inner_text("#dc_fila"))
    checar(u"  e a segunda entrega não apaga a primeira: dois cartões à vista",
           pg.evaluate("document.querySelectorAll('#dc_fila .dc-fila').length") == 2
           and u"RTSTRUCT entregue" in pg.inner_text("#dc_fila"))
    _print(pg, prints, "05_pipeline_fila_indisponivel_1280_pt_escuro")
    pg.click("#dc_fila .dc-fila:first-child .dc-fila-x")
    pg.wait_for_timeout(300)
    checar(u"«dispensar» tira só aquele cartão",
           pg.evaluate("document.querySelectorAll('#dc_fila .dc-fila').length") == 1
           and u"fila indisponível" in pg.inner_text("#dc_fila"))
    pg.unroute("**/api/fila/enfileirar")
    pg.unroute("**/api/fila/estado")
    _clicar_e_esperar(pg, "#dcs%d" % i_tc)
    checar(u"mudar a escolha volta à etapa 2, e o cartão da fila continua à vista",
           pg.evaluate("document.getElementById('dc_e3').hidden"
                       " && !document.getElementById('dc_e6').hidden"))
    pg.click("#dc_limpar")
    pg.wait_for_timeout(500)
    checar(u"«Limpar carregamentos» zera a tela",
           pg.evaluate("DC.series.length") == 0 and pg.input_value("#dc_pasta") == u""
           and pg.evaluate("document.getElementById('dc_e2').hidden"))
    pg.unroute("**/api/lote/opcoes*")


def roteiro_envio(pg, estudo, tmp, prints):
    secao(u"a área de envio: o conteúdo vai ao servidor, e o caminho não")
    _abrir(pg, "/bridge/laudo")
    pedidos = []
    pg.on("request", lambda r: pedidos.append((r.url, r.headers)) if "/api/bridge/receber" in r.url else None)
    zp = os.path.join(tmp, u"estudo_enviado.zip")
    with zipfile.ZipFile(zp, "w") as z:
        for raiz, _d, arqs in os.walk(os.path.join(estudo, u"TC")):
            for a in arqs:
                z.write(os.path.join(raiz, a), os.path.join(u"TC", a))
    pg.set_input_files("#dc_envio .ui-envio-arq", zp)
    pg.wait_for_function("DC.series.length > 0", timeout=30000)
    pg.wait_for_timeout(600)
    checar(u"o .zip escolhido chega e vira série", pg.evaluate("DC.series.length") == 1,
           str(pg.evaluate("DC.series.length")))
    urls = [u for u, _h in pedidos]
    checar(u"o envio passou pela rota que recebe conteúdo", len(urls) >= 2, str(len(urls)))
    checar(u"  e nenhum endereço leva caminho ou nome de arquivo",
           not any(u"estudo_enviado" in u or u"\\" in u or u"%5C" in u for u in urls),
           str(urls[:2]))
    checar(u"  e o campo de caminho não ganhou a pasta de trabalho",
           pg.input_value("#dc_pasta") == u"")
    checar(u"  e a origem não é oferecida como destino (veio pelo navegador)",
           pg.evaluate("BG.origem") == u"")
    pg.set_input_files("#dc_envio .ui-envio-dir", os.path.join(estudo, u"RM"))
    pg.wait_for_function("DC.series.length === 2", timeout=30000)
    checar(u"a segunda pasta escolhida SOMA à primeira (várias pastas)",
           pg.evaluate("DC.series.length") == 2)
    navegou = pg.evaluate("""(function(){
      var dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array([1,2,3])], 'x.bin'));
      var ev = new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true});
      document.querySelector('#dc_e2').dispatchEvent(ev);
      return ev.defaultPrevented })()""")
    checar(u"soltar o arquivo FORA da área não tira o navegador da tela", navegou)
    pg.wait_for_timeout(1500)
    sobre = pg.evaluate("""(function(){
      var z=document.getElementById('dc_envio'), dt=new DataTransfer();
      dt.items.add(new File([new Uint8Array([1])], 'y.bin'));
      z.dispatchEvent(new DragEvent('dragenter', {dataTransfer: dt, bubbles: true, cancelable: true}));
      return z.classList.contains('sobre') })()""")
    checar(u"arrastando por cima, a área acende", sobre)
    _print(pg, prints, "06_pipeline_envio_1280_pt_escuro")
    pg.evaluate("document.getElementById('dc_envio').dispatchEvent(new DragEvent('dragleave'))")
    pg.click("#dc_limpar")
    pg.wait_for_timeout(600)
    checar(u"«Limpar carregamentos» esquece a sessão do envio",
           pg.evaluate("document.getElementById('dc_envio')._uiEnvio.sessao") == u"")


def _indice_da_imagem(pg):
    return pg.evaluate("(function(){ for(var i=0;i<DC.series.length;i++)"
                       " if(DC.series[i].imagem) return i; return -1 })()")


def roteiro_imagem(pg, estudo, tmp, prints):
    secao(u"a imagem JPEG ou PNG no MESMO pipeline: o ajuste mora no diagnóstico")
    _abrir(pg, "/bridge/laudo")
    _contar_brilho(pg)
    _carregar(pg, estudo)
    i_img, i_tc = _indice_da_imagem(pg), _indice(pg, "CT")
    b_img = pg.evaluate("DC.series[%d].bilhete" % i_img)
    _clicar_e_esperar(pg, "#dcs%d" % i_img)
    _clicar_e_esperar(pg, "#dcs%d" % i_tc)
    checar(u"a imagem se marca na grade e diz que não se segmenta",
           u"esta modalidade não se segmenta" in pg.inner_text("#dcr_%s" % b_img),
           pg.inner_text("#dcr_%s" % b_img)[:120])
    pg.click("#dc_avancar")
    pg.wait_for_function("!document.getElementById('dc_e3').hidden", timeout=8000)
    pg.evaluate("dcAbrir(%d)" % i_img)
    pg.wait_for_function("IM.atual && !document.getElementById('dc_bloco_imagem').hidden",
                         timeout=8000)
    pg.wait_for_function("document.querySelector('#im_mpr_linha img')", timeout=15000)
    pg.wait_for_timeout(1200)
    checar(u"abrir a imagem troca o visor DICOM pelo ajuste dela",
           pg.evaluate("document.getElementById('dc_bloco_dicom').hidden"))
    checar(u"a espessura e a escala vêm sugeridas",
           pg.input_value("#im_esp") == u"5" and pg.input_value("#im_esc") == u"2,5",
           u"%s · %s" % (pg.input_value("#im_esp"), pg.input_value("#im_esc")))
    checar(u"sem palavra de orientação na descrição, a tela pede a escolha",
           pg.input_value("#im_ori") == u""
           and u"escolha" in pg.inner_text("#im_ori_nota"), pg.inner_text("#im_ori_nota"))
    pg.fill("#im_desc", u"RM t2 axial")
    pg.wait_for_timeout(600)
    checar(u"«RM t2 axial» → axial, para a pessoa conferir",
           pg.input_value("#im_ori") == u"axial"
           and u"confira" in pg.inner_text("#im_ori_nota"), pg.inner_text("#im_ori_nota"))
    checar(u"o brilho acende no visor e no MPR", pg.evaluate("window.__brilho") >= 2,
           str(pg.evaluate("window.__brilho")))
    pg.wait_for_function("document.querySelectorAll('#im_laudo .dc-falta').length > 0",
                         timeout=8000)
    al = pg.evaluate("Array.from(document.querySelectorAll('#im_laudo .dc-falta'))"
                     ".map(function(e){return e.textContent})")
    carimbo = [t for t in al if u"texto do visualizador" in t]
    checar(u"o texto no pixel é um alerta de uma linha, sem pergunta",
           len(carimbo) == 1 and u"?" not in carimbo[0], str(al))
    checar(u"  e nenhuma escolha na tela (nem rádio, nem botão de recorte)",
           pg.evaluate("document.querySelectorAll('input[type=radio]').length") == 0
           and u"Recortar" not in pg.inner_text("#dc_e3")
           and u"Seguir assim" not in pg.inner_text("#dc_e3"))
    _print(pg, prints, "07_imagem_ajuste_no_pipeline_1280_pt_escuro")
    pg.wait_for_function("!document.getElementById('dc_converter').disabled", timeout=15000)
    pg.fill("#im_esp", u"")
    pg.evaluate("window.scrollTo(0, 0)")
    tem_casca = pg.evaluate("typeof window.uiTremer === 'function'")
    checar(u"a casca publica o ajudante de tremor (C3)", tem_casca)
    pg.evaluate("""(function(){ window.__tremeu = []; var e = document.getElementById('im_esp');
      new MutationObserver(function(){ if(e.classList.contains('ui-treme')) window.__tremeu.push('classe') })
        .observe(e, {attributes: true, attributeFilter: ['class']});
      var o = window.uiTremer;
      window.uiTremer = function(x){ window.__tremeu.push(x.id); return o ? o(x) : null } })()""")
    pg.click("#dc_converter")
    pg.wait_for_timeout(700)
    tremeu = pg.evaluate("window.__tremeu")
    checar(u"espessura vazia: «Converter» não converte, o campo treme pela casca e a "
           u"tela rola até ele",
           u"im_esp" in tremeu and (u"classe" in tremeu or not tem_casca)
           and pg.evaluate("!DC.conversao && document.getElementById('dc_e4').hidden")
           and pg.evaluate("Math.abs(document.getElementById('im_esp').getBoundingClientRect().top"
                           " - innerHeight/2) < innerHeight/2"),
           str(tremeu))
    checar(u"  e o foco vai para o campo",
           pg.evaluate("document.activeElement && document.activeElement.id") == u"im_esp")
    pg.fill("#im_esp", u"5")
    pg.wait_for_timeout(400)
    pg.click("#dc_converter")
    pg.wait_for_timeout(600)
    checar(u"sem confirmar a escala, não converte",
           pg.evaluate("!DC.conversao") and u"confirme a escala" in pg.inner_text("#im_aviso"),
           pg.inner_text("#im_aviso"))
    pg.click("#im_conf_escala")
    pg.click("#dc_converter")
    pg.wait_for_function("!document.getElementById('dc_e5').hidden", timeout=60000)
    pg.wait_for_timeout(400)
    checar(u"confirmada, a imagem converte junto com a TC (duas linhas)",
           pg.evaluate("document.querySelectorAll('#dc_conv tr').length") == 2)
    d1 = os.path.join(tmp, u"entrega_img")
    os.makedirs(d1, exist_ok=True)
    _destino_pelo_explorador(pg, "#dc_e5 #bg_dest_mais", d1)
    _so_um_destino(pg, d1)
    filas_antes = pg.evaluate("DC.filas.length")
    pg.click("#dc_entregar")
    pg.wait_for_function("DC.entregue", timeout=60000)
    pg.wait_for_timeout(400)
    feitos = os.listdir(d1)
    checar(u"«Entregar» grava UMA pasta DICOM_BRIDGE_ com as duas séries",
           len(feitos) == 1 and feitos[0].startswith(u"DICOM_BRIDGE_"), str(feitos))
    if feitos:
        p = os.path.join(d1, feitos[0])
        dentro = sorted(os.listdir(p))
        leia = io.open(os.path.join(p, u"LEIA-ME.txt"), encoding="ascii").read() \
            if os.path.isfile(os.path.join(p, u"LEIA-ME.txt")) else u""
        checar(u"  a IMAGEM, a TC e o LEIA-ME.txt de uma linha",
               u"IMAGEM" in dentro and len(dentro) == 3
               and u"paciente certo no TPS" in leia and leia.count(u"\n") == 1, str(dentro))
    res = pg.inner_text("#dc_ent")
    checar(u"a tela diz DESCONHECIDO e o ID gerado",
           u"DESCONHECIDO" in res and u"EXTERNO-" in res, res)
    checar(u"  e sem segmentação pedida, nada vai para a fila",
           pg.evaluate("DC.filas.length") == filas_antes,
           u"%s -> %s" % (filas_antes, pg.evaluate("DC.filas.length")))
    _print(pg, prints, "08_imagem_entregue_no_pipeline_1280_pt_escuro")
    pg.fill("#im_esc", u"2")
    pg.wait_for_timeout(500)
    checar(u"mudar a escala depois volta ao diagnóstico (a conversão antiga não vale)",
           pg.evaluate("document.getElementById('dc_e4').hidden"
                       " && document.getElementById('dc_e5').hidden && DC.etapa === 3")
           and pg.evaluate("IM.estado['%s'].escala === false" % b_img))
    pg.click("#dc_limpar")
    pg.wait_for_timeout(500)
    checar(u"«Limpar carregamentos» esquece o ajuste das imagens",
           pg.evaluate("DC.series.length") == 0
           and pg.evaluate("Object.keys(IM.estado).length") == 0)

    secao(u"a imagem no pipeline: a prévia que o servidor recusa")
    from urllib.parse import quote
    motivo = u"este runtime não tem Pillow"
    pg.route("**/api/imagem/previa*", lambda r: r.fulfill(
        status=422, headers={"X-RadAI-Motivo": quote(motivo, safe="")}, body=b""))
    _carregar(pg, estudo)
    i_img = _indice_da_imagem(pg)
    _clicar_e_esperar(pg, "#dcs%d" % i_img)
    pg.click("#dc_avancar")
    pg.wait_for_function("IM.atual && !document.getElementById('dc_bloco_imagem').hidden",
                         timeout=10000)
    pg.wait_for_timeout(3200)
    msg = pg.inner_text("#im_visor_msg")
    checar(u"o brilho do visor apaga e a tela diz o erro com o motivo",
           u"não consegui abrir as imagens" in msg and motivo in msg
           and pg.evaluate("(document.querySelector('#im_visor .ue-visor')||{})"
                           ".getAttribute ? document.querySelector('#im_visor .ue-visor')"
                           ".getAttribute('aria-busy') !== 'true' : false"), msg)
    checar(u"  e a miniatura da imagem mostra a sigla, sem quebrar a grade",
           pg.evaluate("document.getElementById('dcm%d').getAttribute('data-mod')" % i_img)
           == u"JPEG/PNG")
    pg.unroute("**/api/imagem/previa*")
    pg.click("#dc_limpar")
    pg.wait_for_timeout(400)


def roteiro_cd(pg, estudo, prints):
    secao(u"«Carregar um CD» na tela (os drives dublados)")
    _abrir(pg, "/bridge/laudo")
    bts = pg.evaluate("Array.from(document.querySelectorAll('#dc_envio .ui-envio-bts button'))"
                      ".map(function(b){ return b.textContent.trim() })")
    checar(u"três opções no quadro de carregar, a terceira é «Carregar um CD»",
           bts == [u"Escolher arquivos", u"Escolher pasta", u"Carregar um CD"], str(bts))
    checar(u"  com o ícone de disco em SVG",
           pg.evaluate("!!document.querySelector('#dc_cd_bt svg.ui-ic')"))
    escolhas = []
    pg.on("filechooser", lambda fc: escolhas.append(1))
    est = {"drives": [], "n": 0, "parado": False, "trava": False, "ler": []}

    def _json(r, corpo):
        r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    def _ler(r):
        est["ler"].append(json.loads(r.request.post_data or "{}"))
        _json(r, {"leitura": "L1"})

    def _estado(r):
        est["n"] += 1
        fim = est["parado"] or (est["n"] >= 3 and not est["trava"])
        _json(r, {"raiz": u"X", "pastas": 2 * est["n"], "arquivos": 5 * est["n"],
                  "series": 1, "fim": fim, "parado": est["parado"], "erro": None})

    def _parar(r):
        est["parado"] = True
        _json(r, {"ok": True})
    pg.route("**/api/bridge/cd/drives", lambda r: _json(r, {"drives": est["drives"]}))
    pg.route("**/api/bridge/cd/ler", _ler)
    pg.route("**/api/bridge/cd/estado", _estado)
    pg.route("**/api/bridge/cd/parar", _parar)
    try:
        pg.click("#dc_cd_bt")
        pg.wait_for_timeout(600)
        checar(u"sem CD, a tela diz", u"nenhum CD na unidade" in pg.inner_text("#dc_msg"),
               pg.inner_text("#dc_msg"))
        checar(u"  e o clique no botão não abre o seletor de arquivos", not escolhas)
        est["drives"] = [u"D:\\", u"E:\\"]
        pg.click("#dc_cd_bt")
        pg.wait_for_timeout(600)
        checar(u"com dois CDs, pergunta qual",
               not pg.evaluate("document.getElementById('dc_cd').hidden")
               and u"há mais de um CD" in pg.inner_text("#dc_cd")
               and pg.evaluate("document.querySelectorAll('#dc_cd .dc-cd-op').length") == 2,
               pg.inner_text("#dc_cd"))
        checar(u"  e sem leitura em curso, o «Cancelar» não aparece",
               pg.evaluate("getComputedStyle(document.getElementById('dc_cd_parar'))"
                           ".display") == u"none")
        _print(pg, prints, "11_cd_dois_discos_1280_pt_escuro")
        est["drives"] = [estudo]
        pg.click("#dc_cd_bt")
        pg.wait_for_function("document.getElementById('dc_cd_txt').textContent"
                             ".indexOf('lendo o CD') >= 0", timeout=8000)
        checar(u"com um CD, lê direto e mostra o progresso com «Cancelar»",
               pg.evaluate("getComputedStyle(document.getElementById('dc_cd_parar'))"
                           ".display") != u"none", pg.inner_text("#dc_cd"))
        pg.wait_for_function("DC.series.length === 4", timeout=30000)
        checar(u"  e, lido, o pipeline carrega o disco",
               est["ler"] and est["ler"][-1].get("drive") == estudo
               and pg.input_value("#dc_pasta") == estudo
               and pg.evaluate("document.getElementById('dc_cd').hidden"))
        pg.click("#dc_limpar")
        pg.wait_for_timeout(400)
        est.update(n=0, trava=True, parado=False)
        pg.click("#dc_cd_bt")
        pg.wait_for_function("!document.getElementById('dc_cd_parar').hidden", timeout=8000)
        pg.click("#dc_cd_parar")
        pg.wait_for_function("document.getElementById('dc_msg').textContent"
                             ".indexOf('cancelada') >= 0", timeout=8000)
        checar(u"«Cancelar» para a leitura e não carrega nada",
               est["parado"] and pg.evaluate("DC.series.length") == 0
               and u"leitura do CD cancelada" in pg.inner_text("#dc_msg"))
        checar(u"  e nenhum seletor de arquivos foi aberto em todo o roteiro", not escolhas)
    finally:
        for rota in ("drives", "ler", "estado", "parar"):
            pg.unroute("**/api/bridge/cd/%s" % rota)


def roteiro_endereco_antigo(pg):
    secao(u"o endereço antigo da conversão de imagens leva ao pipeline")
    pg.goto(BASE + "/bridge/imagem", wait_until="networkidle")
    pg.wait_for_timeout(400)
    h1 = pg.evaluate("(document.querySelector('h1.ui-fn-tag')||{}).textContent||''")
    checar(u"/bridge/imagem abre o pipeline", pg.url.endswith(u"/bridge/laudo")
           and u"Converter imagens para o TPS" in h1, pg.url)


def roteiro_idioma_e_tema(pg, estudo, prints):
    secao(u"em inglês e no tema claro")
    _abrir(pg, "/bridge/laudo", idioma="en", tema="claro")
    _carregar(pg, estudo)
    pg.wait_for_timeout(700)
    texto = pg.evaluate("document.querySelector('.dc-wrap').innerText")
    restos = [f for f in (u"Limpar carregamentos", u"Marcar todas",
                          u"ou aponte a pasta do estudo", FRASE) if f in texto]
    checar(u"as frases que já tinham tradução saem em inglês", not restos,
           u" | ".join(restos))
    _print(pg, prints, "09_pipeline_1280_en_claro")
    for rota in ("/bridge/laudo",):
        for largura in (1600, 1280):
            pg.set_viewport_size({"width": largura, "height": 900})
            _abrir(pg, rota, idioma="pt-BR", tema=None)
            larg = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            checar(u"%s a %d px não rola de lado" % (rota, largura),
                   larg[0] <= larg[1] + 1, str(larg))
    pg.set_viewport_size({"width": 1280, "height": 800})

    secao(u"o diagnóstico em alemão: os alertas traduzidos")
    import radai_dicom as _D
    import radai_phrases as F
    _abrir(pg, "/bridge/laudo", idioma="de", tema=None)
    _carregar(pg, estudo)
    _clicar_e_esperar(pg, "#dcs%d" % _indice(pg, "MR"))
    pg.click("#dc_avancar")
    pg.wait_for_function("document.querySelector('#dc_laudo .dc-falta')", timeout=15000)
    pg.wait_for_timeout(3200)
    with open(_D.__file__, encoding="utf-8") as fh:
        _pt = set(F.normalizar(t) for t in textos_dos_achados(fh.read()))
    achados = pg.evaluate("Array.from(document.querySelectorAll('.dc-falta .tt, .dc-falta .dd,"
                          " .dc-falta .faz')).map(function(e){return e.textContent.trim()})")
    _rx = [re.compile(u"^" + u"(.+?)".join(re.escape(p) for p in
                                            re.split(r"%s|%d", t)) + u"$") for t in _pt]
    em_pt = [a for a in achados if any(r.match(F.normalizar(a)) for r in _rx)]
    checar(u"TEL-04: os alertas do diagnóstico saem em alemão",
           achados and not em_pt, u" | ".join(em_pt[:4]) or str(len(achados)))
    _print(pg, prints, "10_pipeline_diagnostico_1280_de_escuro")


def teste_no_navegador(prints):
    secao(u"o navegador")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        checar(u"PULADO: Playwright ausente neste runtime", True)
        return
    exe = _chromium()
    if not exe:
        checar(u"PULADO: sem o Chromium do Playwright nesta máquina", True)
        return
    base_tmp = tempfile.mkdtemp(prefix=u"radai_bdgt_")
    estudo = os.path.join(base_tmp, u"ESTUDO_FANTOMA")
    uids = montar_estudo(estudo)
    proc = _subir(base_tmp)
    if not proc:
        checar(u"o vigia de teste subiu na porta %d" % PORTA, False)
        return
    erros = []
    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch(executable_path=exe, headless=True)
            ctx = nav.new_context(viewport={"width": 1280, "height": 800},
                                  accept_downloads=False)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: erros.append(str(e)[:200]))
            try:
                _aceitar(pg)
                for f in (lambda: roteiro_pipeline(pg, estudo, uids, base_tmp, prints),
                          lambda: roteiro_envio(pg, estudo, base_tmp, prints),
                          lambda: roteiro_imagem(pg, estudo, base_tmp, prints),
                          lambda: roteiro_cd(pg, estudo, prints),
                          lambda: roteiro_endereco_antigo(pg),
                          lambda: roteiro_idioma_e_tema(pg, estudo, prints)):
                    try:
                        f()
                    except Exception as e:
                        checar(u"o roteiro chegou ao fim sem parar no meio", False,
                               u"%s: %s" % (type(e).__name__, str(e).splitlines()[0][:200]
                                            if str(e) else u""))
            finally:
                nav.close()
    finally:
        try:
            proc.kill()
        except Exception:
            pass
    checar(u"nenhum erro de JavaScript nas telas", not erros, u"; ".join(erros[:3]))


def main():
    prints = None
    if "--prints" in sys.argv:
        prints = sys.argv[sys.argv.index("--prints") + 1]
    print(u"=" * 68)
    print(u"test_bridge_tela | o pipeline único do DicomBridge (DICOM, imagem e CD)")
    print(u"=" * 68)
    for t in (teste_a_estrutura, teste_os_achados_do_diagnostico_tem_chave,
              teste_as_rotas):
        try:
            t()
        except Exception:
            checar(u"%s rodou sem exceção" % t.__name__, False,
                   traceback.format_exc()[-700:])
    teste_no_navegador(prints)
    ok = sum(1 for _n, c, _d in _R if c)
    falhou = len(_R) - ok
    print(u"\n" + u"=" * 68)
    if falhou:
        print(u"FALHOU: %d de %d checagens" % (falhou, len(_R)))
        for n, c, d in _R:
            if not c:
                print(u"    - %s %s" % (n, (u"[%s]" % d) if d else u""))
        print(u"=" * 68)
        return 1
    print(u"OK: %d checagens, todas passaram" % ok)
    print(u"=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
