# -*- coding: utf-8 -*-
import io
import json
import os
import re
import shutil
import sys
import tempfile

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

import tempfile as _tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cleanup
import _componentes
_cleanup.adotar_prefixo('radai_ac_bridge')
_cleanup.adotar_prefixo('radai_bridge_cd_')
os.environ["RADAI_CALIB_DIR"] = _tempfile.mkdtemp(prefix="radai_ac_bridge_")


VERBOSO = "-v" in sys.argv
_RESULTADOS = []
_TEMPS = []


def checar(nome, ok, detalhe=""):
    _RESULTADOS.append((nome, bool(ok), detalhe))
    if VERBOSO or not ok:
        print("  %s  %s%s" % ("OK   " if ok else "FALHA", nome,
                              ("  [%s]" % detalhe) if detalhe else ""))
    return bool(ok)


def secao(t):
    print(u"\n\u2500\u2500 %s %s" % (t, u"\u2500" * max(0, 62 - len(t))))


def novo_temp(prefixo="radai_bridge_"):
    d = tempfile.mkdtemp(prefix=prefixo)
    _TEMPS.append(d)
    return d


def fonte(nome):
    return io.open(_componentes.fonte("app/" + nome), encoding="utf-8",
                   errors="replace").read()


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

    def _chamar(self, alvo, *a, **k):
        import asyncio
        import inspect
        if inspect.iscoroutinefunction(alvo):
            return asyncio.run(alvo(*a, **k))
        return alvo(*a, **k)

    def post(self, caminho, json=None):
        alvo = self.rotas[("POST", caminho)]
        return Resposta(self._chamar(alvo, PedidoFalso(json or {})))

    def get(self, caminho, params=None, headers=None):
        alvo = self.rotas[("GET", caminho)]
        k = dict(params or {})
        import inspect
        if "request" in inspect.signature(alvo).parameters:
            k["request"] = PedidoFalso({}, headers or {})
        return Resposta(self._chamar(alvo, **k))


class PedidoFalso(object):

    def __init__(self, corpo, headers=None):
        self._corpo = corpo
        self.headers = dict((k.lower(), v)
                            for k, v in (headers or {}).items())

    async def json(self):
        return self._corpo


class Resposta(object):

    def __init__(self, bruto):
        self._bruto = bruto
        if hasattr(bruto, "status_code"):
            self.status_code = bruto.status_code
            self.headers = bruto.headers
            self.content = bruto.body or b""
        else:
            self.status_code = 200
            self.headers = {}
            self.content = b""

    def json(self):
        return self._bruto


def escrever_serie(pasta, n=8, modalidade="CT", uid_serie=None, numero=1,
                   descricao=u"CT FANTOMA", lado=16, passo=3.0,
                   passo_torto=None):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    os.makedirs(pasta, exist_ok=True)
    uid_serie = uid_serie or generate_uid()
    frame = generate_uid()
    _z = [0.0]
    for i in range(n):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.SeriesInstanceUID = uid_serie
        ds.StudyInstanceUID = "1.2.3.4.5"
        ds.Modality = modalidade
        ds.SeriesNumber = numero
        ds.SeriesDescription = descricao
        ds.InstanceNumber = i + 1
        ds.Rows, ds.Columns = lado, lado
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SliceThickness = passo
        ds.PixelSpacing = [1.0, 1.0]
        ds.RescaleSlope = 1
        ds.RescaleIntercept = -1024
        ds.PatientPosition = "HFS"
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0.0, 0.0, _z[0]]
        _z[0] += (passo_torto[1] if (passo_torto and i + 1 == passo_torto[0])
                  else passo)
        ds.FrameOfReferenceUID = frame
        ds.PixelData = (b"\x40\x01" * (lado * lado))
        ds.save_as(os.path.join(pasta, "IM%03d.dcm" % i),
                   enforce_file_format=True)
    return uid_serie


def escrever_rtstruct(pasta, uid_serie=None):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    os.makedirs(pasta, exist_ok=True)
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.481.3"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.481.3"
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = uid_serie or generate_uid()
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.Modality = "RTSTRUCT"
    ds.SeriesNumber = 9
    ds.SeriesDescription = u"ESTRUTURAS"
    ds.save_as(os.path.join(pasta, "RS.dcm"), enforce_file_format=True)
    return ds.SeriesInstanceUID


def _semear_phi(pasta, nome, ident, nascimento):
    import pydicom
    for n in sorted(os.listdir(pasta)):
        if not n.lower().endswith(".dcm"):
            continue
        c = os.path.join(pasta, n)
        ds = pydicom.dcmread(c)
        ds.PatientName = nome
        ds.PatientID = ident
        ds.PatientBirthDate = nascimento
        ds.save_as(c, enforce_file_format=True)



def teste_a_grade_nao_rola():
    secao(u"a grade nao rola; o visor da serie aberta rola")
    f = fonte("radai_bridge.py")

    p = radai_pagina()
    checar(u"a página tem exatamente um handler de `wheel`",
           p.count("addEventListener('wheel'") == 1,
           str(p.count("addEventListener('wheel'")))
    visor = _corpo_js(p, u"RadaiUmEixo")
    checar(u"e ele está dentro de `RadaiUmEixo`, o visor da série aberta",
           "addEventListener('wheel'" in visor)
    import radai_bridge
    checar(u"o JS desta tela não tem `wheel` nenhum",
           "wheel" not in radai_bridge.JS)
    checar(u"a funcao que pinta a grade nao tem `wheel`",
           "wheel" not in f[f.index("function dcPintarGrade"):
                            f.index("function dcLigarCartao")])
    checar(u"o handler pede {passive:false}", "{passive: false}" in visor)
    checar(u"e a grade nao tem seletor de janela",
           "dcj_" not in f[f.index("function dcPintarGrade"):
                           f.index("function dcAbrir")])


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


def teste_um_pedido_por_serie():
    secao(u"a grade faz UM pedido por serie")
    try:
        from fastapi import FastAPI
    except Exception as e:
        checar(u"fastapi disponivel", False, str(e)[:60])
        return

    import radai_bridge
    import radai_dicom
    import radai_thumbnail

    base = novo_temp()
    for k in range(3):
        escrever_serie(os.path.join(base, "s%d" % k), n=6, numero=k + 1,
                       descricao=u"CT %d" % k)
    escrever_rtstruct(os.path.join(base, "rs"))
    radai_dicom.esquecer_varredura()

    contador = {"n": 0, "por_bilhete": {}}
    original = radai_thumbnail.png_central

    def contando(b, lado=radai_thumbnail.LADO):
        contador["n"] += 1
        contador["por_bilhete"][b] = contador["por_bilhete"].get(b, 0) + 1
        return original(b, lado)

    radai_thumbnail.png_central = contando
    try:
        app = radai_bridge.montar(FastAPI())
        cli = Cliente(app)
        r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
        series = r.get("series") or []
        checar(u"a varredura achou as quatro series", len(series) == 4,
               str(len(series)))

        respostas = []
        for s in series:
            respostas.append(cli.get("/api/bridge/miniatura",
                                     params={"b": s["bilhete"]}))
        checar(u"um pedido por serie, e nenhum a mais",
               contador["n"] == len(series),
               u"%d pedidos para %d series" % (contador["n"], len(series)))
        checar(u"nenhuma serie pediu duas vezes",
               all(v == 1 for v in contador["por_bilhete"].values()),
               str(contador["por_bilhete"]))

        imagens = [x for x in respostas if x.status_code == 200]
        vazias = [x for x in respostas if x.status_code == 204]
        checar(u"as tres CT devolveram PNG", len(imagens) == 3,
               str([x.status_code for x in respostas]))
        checar(u"e o RTSTRUCT devolveu 204, nao 404", len(vazias) == 1,
               str([x.status_code for x in respostas]))
        checar(u"o 204 diz a modalidade",
               vazias and vazias[0].headers.get("X-RadAI-Modalidade") == "RTSTRUCT",
               vazias[0].headers.get("X-RadAI-Modalidade") if vazias else u"")
        checar(u"o PNG e PNG mesmo",
               imagens and imagens[0].content[:8] == b"\x89PNG\r\n\x1a\n")

        cc = imagens[0].headers.get("Cache-Control", "")
        checar(u"a miniatura pode ser guardada pelo navegador",
               "max-age" in cc and "no-store" not in cc, cc)
        checar(u"e so por ele: `private`, e nao `public`",
               "private" in cc, cc)
        etag = imagens[0].headers.get("ETag", "")
        checar(u"ela vem com ETag", bool(etag), etag)

        n_antes = contador["n"]
        r304 = cli.get("/api/bridge/miniatura",
                       params={"b": series[0]["bilhete"]},
                       headers={"If-None-Match": etag})
        checar(u"ETag igual devolve 304", r304.status_code == 304,
               str(r304.status_code))
        checar(u"e 304 nao manda corpo", not r304.content, str(len(r304.content)))
        checar(u"cada visita ainda passa pelo modulo (a validacao e do servidor)",
               contador["n"] == n_antes + 1)
    finally:
        radai_thumbnail.png_central = original


def teste_204_e_404_nao_viram_laco():
    secao(u"204 e 404 nao viram laco")
    f = fonte("radai_bridge.py")
    import radai_bridge
    ligar = _corpo_js(radai_bridge.JS, u"dcVisorLigar")
    checar(u"abrir a série liga o visor de um eixo",
           "RadaiUmEixo(" in ligar, ligar[:120])
    checar(u"  e o `aoParar` dele é o desta tela",
           "dcVisorParou(" in ligar)
    parou = _corpo_js(radai_bridge.JS, u"dcVisorParou")
    checar(u"o 204 e o 404 têm galhos separados",
           "st === 204" in parou and "st === 404" in parou, parou[:160])
    checar(u"abrir outra série fecha o visor da anterior",
           "dcVisorFechar()" in ligar)

    grade = f[f.index("function dcCarregarMini"):f.index("function dcSemPrevia")]
    corpo = grade[grade.index("{"):]
    checar(u"a grade nao se re-dispara", "dcCarregarMini(" not in corpo)
    checar(u"e o fim do pedido libera a vaga da fila",
           "DC.rodando--" in grade and "dcTocarMini()" in grade)
    checar(u"a miniatura acende o brilho da casca e o apaga ao chegar",
           "bgBrilho(cx, true" in grade and "bgBrilho(cx, false)" in grade)
    checar(u"  e o visor do diagnostico tambem",
           "dcBrilhoNoVisor(cx)" in ligar
           and "bgBrilho(ue, false)" in _corpo_js(radai_bridge.JS, u"dcVisorParou"))

    sem = f[f.index("function dcSemPrevia"):f.index("function dcAbrir")]
    checar(u"o 404 manda recarregar a pasta", "recarregue a pasta" in sem)
    checar(u"e a serie sem pixel mostra a sigla", "data-mod" in sem)


_DOM_JS = u"""
function El(id){ var s = this; this.id = id; this.style = {}; this.value = '';
 this.textContent = ''; this.hidden = false; this.disabled = false; this.src = '';
 this.href = ''; this._a = {}; this._h = '';
 this.classList = {add: function(){}, remove: function(){}, toggle: function(){},
                   contains: function(){ return false; }}; }
El.prototype.setAttribute = function(k, v){ this._a[k] = String(v); };
El.prototype.getAttribute = function(k){ return this._a[k] || null; };
El.prototype.addEventListener = function(){};
El.prototype.appendChild = function(){};
El.prototype.replaceChild = function(){};
El.prototype.click = function(){};
El.prototype.querySelector = function(){ return null; };
El.prototype.querySelectorAll = function(){ return []; };
Object.defineProperty(El.prototype, 'innerHTML', {get: function(){ return this._h; },
 set: function(v){ this._h = v; }});
var ELS = {};
var document = {getElementById: function(id){ return ELS[id] || (ELS[id] = new El(id)); },
 addEventListener: function(){}, querySelectorAll: function(){ return []; },
 createElement: function(){ return new El(''); },
 body: {appendChild: function(){}, removeChild: function(){}}};
var window = {};
var CORPOS = [];
var RESPOSTAS = {};
var ABRIU = 0;
var sessionStorage = {_d: {},
 getItem: function(k){ return (k in this._d) ? this._d[k] : null },
 setItem: function(k, v){ this._d[k] = String(v) },
 removeItem: function(k){ delete this._d[k] }};
function fetch(url, op){
 var corpo = JSON.parse((op && op.body) || '{}');
 CORPOS.push({url: url, corpo: corpo});
 var chave = String(url).split('?')[0];
 if(!(chave in RESPOSTAS)) return new Promise(function(){});
 var r = RESPOSTAS[chave];
 if(typeof r === 'function') r = r(corpo);
 if(r === 'pendente') return new Promise(function(){});
 if(r === 'rede') return Promise.reject(new Error('rede'));
 return Promise.resolve({ok: r.status < 300, status: r.status,
                         json: function(){ return Promise.resolve(r.json) }});
}
function esperar(){ return new Promise(function(ok){ setTimeout(ok, 0) }) }
"""

_ENTREGA_JS = u"""
DC.series = [{uid: 'x1', descricao: 'CT ABDOME', modalidade: 'CT', cortes: 12,
              central: 6, bilhete: 'bilhete_do_abdome'},
             {uid: 'x2', descricao: 'CT TORAX', modalidade: 'CT', cortes: 20,
              central: 10, bilhete: 'bilhete_do_torax'}];
DC.fonte = 'pasta';
BG.destinos = ['destino'];
DC.marcadas = {1: true};
dcConverter();
console.log('JSON:' + JSON.stringify({corpos: CORPOS}));
"""

_FILA_JS = u"""
window.radaiFilaAbrir = function(){ ABRIU++ };
DC.series = [{uid: 'x1', descricao: 'CT ABDOME', modalidade: 'CT', cortes: 12,
              bilhete: 'b_abd'},
             {uid: 'x2', descricao: 'RM T2', modalidade: 'MR', cortes: 20,
              bilhete: 'b_rm'},
             {uid: 'x3', descricao: 'CT SEM', modalidade: 'CT', cortes: 8,
              bilhete: 'b_sem'}];
DC.seg = {b_abd: {modo: 'fast', chaves: {}},
          b_rm: {modo: 'personalizado', chaves: {total_mr: 1, vertebrae_mr: 0}},
          b_sem: {modo: 'nenhuma', chaves: {}}};
var entrega = {nome: 'DICOM_BRIDGE_X', series: [
  {b: 'b_abd', uid: '1.2.3.1', pasta: 'D1/DICOM_BRIDGE_X/s1', copias: ['D2/DICOM_BRIDGE_X/s1']},
  {b: 'b_rm', uid: '1.2.3.2', pasta: 'D1/DICOM_BRIDGE_X/s2', copias: ['D2/DICOM_BRIDGE_X/s2']},
  {b: 'b_sem', uid: '1.2.3.3', pasta: 'D1/DICOM_BRIDGE_X/s3', copias: ['D2/DICOM_BRIDGE_X/s3']}]};
var itens = dcItensDaFila(entrega);
var saida = {itens: itens};
function html(){ return ELS['dc_fila'].innerHTML }
function ultima(){ return DC.filas[DC.filas.length - 1] }
function zerar(){ dcFilaParar(); DC.filas = []; DC.filaHtml = null }
(async function(){
 RESPOSTAS[DC_ROTA_GUARDAR] = {status: 200, json: {guarda: 'g1'}};
 RESPOSTAS[DC_ROTA_FILA] = {status: 404, json: {detail: 'Not Found'}};
 await dcSegmentar(itens, 'DICOM_BRIDGE_X');
 saida.indisponivel = html();
 zerar();
 RESPOSTAS[DC_ROTA_FILA] = 'rede';
 await dcSegmentar(itens, 'DICOM_BRIDGE_X');
 saida.sem_rede = html();
 zerar();
 RESPOSTAS[DC_ROTA_FILA] = {status: 200, json: {ok: false, erro: 'item 1: são no máximo 8 pastas de cópia'}};
 await dcSegmentar(itens, 'DICOM_BRIDGE_X');
 saida.recusada = html();
 zerar();
 RESPOSTAS[DC_ROTA_FILA] = {status: 200, json: {ok: true, cartoes: [
   {id: 'c1', posicao: 3}, {id: 'c2', posicao: 4}]}};
 var antes = CORPOS.length;
 await dcSegmentar(itens, 'DICOM_BRIDGE_X');
 await esperar();
 saida.pedido = CORPOS.slice(antes).filter(function(c){ return c.url === DC_ROTA_FILA })[0];
 saida.guardar = CORPOS.slice(antes).filter(function(c){ return c.url === DC_ROTA_GUARDAR })[0];
 saida.guarda = ultima().guarda;
 saida.na_fila = html();
 saida.abriu = ABRIU;
 saida.vigiando = !!DC.filaTimer;
 saida.sessao = sessionStorage.getItem(DC_SESSAO) || '';
 dcFilaParar();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: [
   {id: 'c1', estado: 'rodando', posicao: 0}, {id: 'c2', estado: 'esperando', posicao: 1}]}};
 await dcFilaConsultar();
 saida.rodando = html();
 saida.estado_pedido = CORPOS.filter(function(c){ return c.url === DC_ROTA_ESTADO }).pop();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {rodando: false, cartoes: [
   {id: 'c1', estado: 'esperando', posicao: 1}, {id: 'c2', estado: 'esperando', posicao: 2}]}};
 await dcFilaConsultar();
 saida.parada = html();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {rodando: true, cartoes: [
   {id: 'c1', estado: 'esperando', posicao: 1}, {id: 'c2', estado: 'esperando', posicao: 2}]}};
 await dcFilaConsultar();
 saida.andando = html();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: [
   {id: 'c1', estado: 'esperando', posicao: 1}, {id: 'c2', estado: 'esperando', posicao: 2}]}};
 await dcFilaConsultar();
 saida.sem_campo = html();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {rodando: true, cartoes: [
   {id: 'c1', estado: 'pronto', rotulo: 'CT · CT ABDOME',
    mensagem: 'RTSTRUCT copiado para 0 pasta(s); a pasta de cópia não existe mais'},
   {id: 'c2', estado: 'pronto', rotulo: 'MR · RM T2', mensagem: 'RTSTRUCT copiado para 1 pasta(s)'}]}};
 RESPOSTAS[DC_ROTA_CONFERIR] = {status: 200, json: {ok: true, series: [
   {i: 0, rs: true, copias: 0, de: 1}, {i: 1, rs: true, copias: 1, de: 1}]}};
 await dcFilaConsultar();
 saida.pronto_logo = html();
 for(var k = 0; k < 3; k++){ await dcFilaConsultar(); await esperar() }
 await esperar(); await esperar();
 saida.pronto = html();
 saida.concluida = !!ultima().concluida;
 saida.conferiu = CORPOS.filter(function(c){ return c.url === DC_ROTA_CONFERIR }).length;
 saida.sessao_fim = sessionStorage.getItem(DC_SESSAO) || '';
 zerar();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: [
   {id: 'c1', estado: 'pronto'}, {id: 'c2', estado: 'pronto'}]}};
 RESPOSTAS[DC_ROTA_CONFERIR] = {status: 200, json: {ok: true, series: [
   {i: 0, rs: true, copias: 1, de: 1}, {i: 1, rs: true, copias: 1, de: 1}]}};
 RESPOSTAS[DC_ROTA_FILA] = {status: 200, json: {ok: true, cartoes: [
   {id: 'c1', posicao: 3}, {id: 'c2', posicao: 4}]}};
 await dcSegmentar(itens, 'DICOM_BRIDGE_X');
 for(var k2 = 0; k2 < 4; k2++){ await dcFilaConsultar(); await esperar() }
 saida.pronto_inteiro = html();
 zerar();
 RESPOSTAS[DC_ROTA_FILA] = {status: 200, json: {ok: true, cartoes: [{id: 'c7', posicao: 2}]}};
 await dcSegmentar(itens.slice(0, 1), 'DICOM_BRIDGE_X');
 dcFilaParar();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: [
   {id: 'c7', estado: 'falhou', mensagem: 'o app fechou no meio'}]}};
 await dcFilaConsultar();
 saida.falhou = html();
 RESPOSTAS[DC_ROTA_REPOR] = function(c){ return {status: 200, json: {ok: c.id === 'c7', id: 'c8'}} };
 var a2 = CORPOS.length;
 await dcFilaDeNovo(ultima().chave);
 saida.repor = CORPOS.slice(a2).map(function(c){ return c.url + ' ' + JSON.stringify(c.corpo) });
 saida.repor_ids = ultima().cartoes.map(function(c){ return c.id + ':' + c.estado });
 zerar();
 console.log('JSON:' + JSON.stringify(saida));
})();
"""


_FILAS_JS = u"""
window.radaiFilaAbrir = function(){ ABRIU++ };
function html(){ return ELS['dc_fila'].innerHTML }
var itA = [{pasta: 'D1/A/a', uid: '1.1', modo: 'fast', chaves: {}, copiar_rs_para: [],
            origem: 'dicombridge', rotulo: 'CT · A'}];
var itB = [{pasta: 'D1/B/b', uid: '2.2', modo: 'auto', chaves: {}, copiar_rs_para: [],
            origem: 'dicombridge', rotulo: 'CT · B'},
           {pasta: 'D1/B/c', uid: '3.3', modo: 'auto', chaves: {}, copiar_rs_para: [],
            origem: 'dicombridge', rotulo: 'CT · C'}];
var saida = {};
(async function(){
 try{
 RESPOSTAS[DC_ROTA_GUARDAR] = function(c){
  return {status: 200, json: {guarda: c.itens[0].uid === '1.1' ? 'gA' : 'gB'}} };
 RESPOSTAS[DC_ROTA_FILA] = function(c){
  return {status: 200, json: {ok: true, cartoes: c.itens[0].uid === '1.1'
    ? [{id: 'a1', posicao: 1}] : [{id: 'b1', posicao: 2}, {id: 'b2', posicao: 3}]}} };
 await dcSegmentar(itA, 'DICOM_BRIDGE_A');
 await dcSegmentar(itB, 'DICOM_BRIDGE_B');
 await esperar();
 saida.duas = DC.filas.length;
 saida.html_duas = html();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: [
   {id: 'a1', estado: 'esperando', posicao: 1}, {id: 'b1', estado: 'esperando', posicao: 2},
   {id: 'b2', estado: 'esperando', posicao: 3}]}};
 await dcFilaConsultar();
 saida.ids = CORPOS.filter(function(c){ return c.url === DC_ROTA_ESTADO }).pop().corpo.ids;
 saida.sessao = JSON.parse(sessionStorage.getItem(DC_SESSAO) || 'null');
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: [
   {id: 'a1', estado: 'pronto', posicao: 1}, {id: 'b1', estado: 'esperando', posicao: 2},
   {id: 'b2', estado: 'esperando', posicao: 3}]}};
 await dcFilaConsultar();
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: []}};
 RESPOSTAS[DC_ROTA_CONFERIR] = function(c){
  return {status: 200, json: {ok: true, series: c.guarda === 'gA'
    ? [{i: 0, rs: false, copias: 0, de: 0}]
    : [{i: 0, rs: true, copias: 0, de: 0}, {i: 1, rs: false, copias: 0, de: 0}]}} };
 await dcFilaConsultar(); await esperar(); await esperar();
 saida.a_estado = ((DC.filas[0] || {cartoes: []}).cartoes[0] || {}).estado;
 saida.b_estados = (DC.filas[1] || {cartoes: []}).cartoes.map(function(c){ return c.estado });
 saida.html_saiu = html();
 saida.conferir_gA = CORPOS.filter(function(c){
  return c.url === DC_ROTA_CONFERIR && c.corpo.guarda === 'gA' }).length;
 saida.conferir_gB = CORPOS.filter(function(c){
  return c.url === DC_ROTA_CONFERIR && c.corpo.guarda === 'gB' }).pop();
 dcFilaParar();
 var guardado = sessionStorage.getItem(DC_SESSAO) || '';
 saida.guardado_sem_caminho = guardado.indexOf('D1/') < 0 && guardado.indexOf('CT · ') < 0;
 DC.filas = []; DC.filaHtml = null;
 dcRetomarFila();
 await esperar(); await esperar();
 saida.retomadas = DC.filas.map(function(e){ return e.nome });
 saida.retomada_itens = DC.filas.map(function(e){ return e.itens });
 saida.html_retomada = html();
 RESPOSTAS[DC_ROTA_REPOR] = {status: 200, json: {ok: false}};
 RESPOSTAS[DC_ROTA_DE_NOVO] = {status: 200, json: {ok: true, cartoes: [{id: 'b9', posicao: 1}]}};
 var eB = DC.filas.filter(function(e){ return e.nome === 'DICOM_BRIDGE_B' })[0];
 var antes = CORPOS.length;
 if(eB) await dcFilaDeNovo(eB.chave);
 var depois = CORPOS.slice(antes);
 saida.repor_pedidos = depois.filter(function(c){ return c.url === DC_ROTA_REPOR }).length;
 saida.de_novo = depois.filter(function(c){ return c.url === DC_ROTA_DE_NOVO })[0] || null;
 saida.b_depois = eB ? eB.cartoes.map(function(c){ return c.id + ':' + c.estado }) : [];
 dcFilaParar();
 sessionStorage.setItem(DC_SESSAO, JSON.stringify({ids: ['v1'], nome: 'DICOM_BRIDGE_V'}));
 DC.filas = []; DC.filaHtml = null;
 RESPOSTAS[DC_ROTA_ESTADO] = {status: 200, json: {cartoes: [{id: 'v1', estado: 'esperando', posicao: 4}]}};
 dcRetomarFila();
 await esperar(); await esperar();
 saida.formato_antigo = DC.filas.map(function(e){ return e.nome + ':' + e.estado + ':' + e.cartoes.length });
 dcFilaParar();
 DC.filas = []; DC.filaHtml = null;
 DC.series = [{uid: 'x1', descricao: 'CT', modalidade: 'CT', cortes: 3, bilhete: 'b1'}];
 DC.marcadas = {0: true};
 DC.seg = {b1: {modo: 'fast', chaves: {}}};
 DC.conversao = 'tok';
 var muitos = [];
 for(var k = 0; k <= DC_TETO_COPIAS + 1; k++) muitos.push('D' + k);
 BG.destinos = muitos;
 var nEnt = CORPOS.length;
 dcEntregar();
 saida.teto = ELS['dc_ent'].innerHTML;
 saida.teto_pedidos = CORPOS.slice(nEnt).filter(function(c){
  return c.url === '/api/bridge/etapa/entregar' }).length;
 BG.destinos = muitos.slice(0, DC_TETO_COPIAS + 1);
 document.getElementById('dc_ent').innerHTML = '';
 dcEntregar();
 saida.teto_no_limite = CORPOS.slice(nEnt).filter(function(c){
  return c.url === '/api/bridge/etapa/entregar' }).length;
 DC.seg = {b1: {modo: 'nenhuma', chaves: {}}};
 DC.conversao = 'tok2';
 BG.destinos = muitos;
 dcEntregar();
 saida.sem_segmentacao = CORPOS.slice(nEnt).filter(function(c){
  return c.url === '/api/bridge/etapa/entregar' }).length;
 }catch(x){ saida.erro = String(x) }
 dcFilaParar();
 console.log('JSON:' + JSON.stringify(saida));
})();
"""


_DIAG_JS = u"""
function RadaiUmEixo(){ return {fechar: function(){}, carga: {}, n: 0} }
DC.series = [{uid: 'x1', descricao: 'CT A', modalidade: 'CT', cortes: 4, bilhete: 'b1', central: 2},
             {uid: 'x2', descricao: 'RM B', modalidade: 'MR', cortes: 4, bilhete: 'b2', central: 2},
             {uid: 'x3', descricao: 'CT C', modalidade: 'CT', cortes: 4, bilhete: 'b3', central: 2}];
DC.fonte = 'pasta';
DC.marcadas = {0: true, 1: true, 2: true};
var LAUDOS = {b1: {achados: [{ok: false, alerta: true, titulo: 'Alerta da A'}]},
              b2: {achados: [{ok: false, alerta: true, impede: true, titulo: 'Decodificador da B'}]},
              b3: 'pendente'};
RESPOSTAS['/api/bridge/laudo'] = function(c){
 var l = LAUDOS[c.b]; return l === 'pendente' ? l : {status: 200, json: l} };
var saida = {};
(async function(){
 dcAvancar();
 for(var k = 0; k < 6; k++) await esperar();
 saida.pendente_bloqueia = ELS['dc_converter'].disabled;
 saida.outras_pendente = ELS['dc_outras'].innerHTML;
 DC.laudos.b3 = {achados: []}; delete DC.lendo.b3;
 dcPintarOutras(); dcPintarBarra(); dcPintarDiagLista();
 saida.depois_libera = !ELS['dc_converter'].disabled;
 saida.lista = ELS['dc_diag_lista'].innerHTML;
 saida.outras = ELS['dc_outras'].innerHTML;
 saida.pedidos = CORPOS.filter(function(c){ return c.url === '/api/bridge/laudo' })
  .map(function(c){ return c.corpo.b });
 DC.etapa = 5; DC.conversao = 'tok'; DC.seg = {b1: {modo: 'fast', chaves: {}}};
 var n0 = CORPOS.length;
 dcModo('b1', 'auto');
 saida.modo_descartou = CORPOS.slice(n0).filter(function(c){
  return c.url === '/api/bridge/etapa/descartar' }).length;
 saida.modo_conversao = DC.conversao;
 saida.modo_etapa = DC.etapa;
 DC.entregue = {nome: 'X'};
 document.getElementById('dc_ent').innerHTML = 'DICOM entregue em X';
 document.getElementById('dc_conv').innerHTML = '3 séries convertidas';
 dcMarcar(1);
 saida.marcar_limpa = [document.getElementById('dc_ent').innerHTML,
                       document.getElementById('dc_conv').innerHTML, DC.conversao];
 console.log('JSON:' + JSON.stringify(saida));
})();
"""


_VIGIA_JS = u"""
var BRILHO = [];
window.uiCarregando = function(alvo, ligado){ BRILHO.push(ligado ? 1 : 0) };
function caixa(){
 var ue = new El('ue'), im = new El('im');
 return {querySelector: function(s){ return s === '.ue-visor' ? ue : (s === '.ue-img' ? im : null) }};
}
function pausa(ms){ return new Promise(function(ok){ setTimeout(ok, ms) }) }
var saida = {};
(async function(){
 var falhou = 0;
 var v1 = {n: 10, fechado: false, carga: {nProntos: 0, nFalhos: 0, parado: 0}};
 bgVigiarVisor(caixa(), v1, function(){ falhou++ });
 await pausa(400);
 saida.esperando = [BRILHO.slice(), falhou];
 v1.carga.nFalhos = 3;
 await pausa(450);
 saida.tres_falhas = [BRILHO.slice(), falhou];
 BRILHO = []; falhou = 0;
 var v2 = {n: 10, fechado: false, carga: {nProntos: 1, nFalhos: 5, parado: 0}};
 bgVigiarVisor(caixa(), v2, function(){ falhou++ });
 await pausa(450);
 saida.chegou_um = [BRILHO.slice(), falhou];
 BRILHO = []; falhou = 0;
 var v3 = {n: 10, fechado: false, carga: {nProntos: 0, nFalhos: 0, parado: 404}};
 bgVigiarVisor(caixa(), v3, function(){ falhou++ });
 await pausa(450);
 saida.parado = [BRILHO.slice(), falhou];
 console.log('JSON:' + JSON.stringify(saida));
})();
"""


_TASKS_JS = u"""
RESPOSTAS[DC_ROTA_OPCOES] = {status: 200, json: {
  ligadas_de_fabrica: ['lung_nodules', 'body'],
  tasks: [{task: 'lung_nodules', rotulo: 'Nodulos', achado: true, permitida: true},
          {task: 'body', rotulo: 'Corpo', achado: false},
          {task: 'proibida', rotulo: 'X', permitida: false}]}};
DC.series = [{bilhete: 'b1', modalidade: 'CT', descricao: 'CT'}];
DC.seg = {b1: {modo: 'personalizado', chaves: {}}};
dcPintarTasks('b1');
(async function(){
 await esperar(); await esperar(); await esperar();
 var url = (CORPOS.filter(function(c){ return c.url.indexOf(DC_ROTA_OPCOES) === 0 })[0] || {}).url;
 console.log('JSON:' + JSON.stringify({chaves: DC.seg.b1.chaves, url: url}));
})();
"""


def _rodar_tela(js_extra, prefixo="radai_ac_bridge_js_"):
    import shutil as _sh
    import subprocess
    node = _sh.which("node")
    if not node:
        return None, u"PULADO -- sem node"
    import radai_bridge
    d = novo_temp(prefixo)
    alvo = os.path.join(d, "e.js")
    io.open(alvo, "w", encoding="utf-8").write(
        _DOM_JS + radai_bridge.JS_COMUM + radai_bridge.JS + js_extra)
    r = subprocess.run([node, alvo], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    linha = [l for l in (r.stdout or "").splitlines() if l.startswith("JSON:")]
    if not linha:
        return None, ((r.stderr or "") + (r.stdout or ""))[-400:]
    return json.loads(linha[-1][5:]), u""


_IMAGEM_JS = u"""
var TREMEU = [];
window.uiTremer = function(el){ TREMEU.push(el.id) };
DC.series = [{uid: 'x1', descricao: 'CT TORAX', modalidade: 'CT', cortes: 20,
              central: 10, bilhete: 'b_tc'},
             {imagem: true, bilhete: 'b_img', descricao: 'RM T2 AXIAL',
              modalidade: 'JPEG/PNG', cortes: 6, n: 6, matriz: '64x64',
              sugestoes: {modalidade: 'MR', orientacao: 'axial', espessura_mm: 5,
                          espacamento_mm: 0.8, fov_mm: 240}}];
DC.fonte = 'pasta';
BG.destinos = ['destino'];
DC.marcadas = {0: true, 1: true};
function pedidos(){ return CORPOS.filter(function(c){ return c.url === '/api/bridge/etapa/converter' }) }
var saida = {};
dcConverter();
saida.sem_confirmar = pedidos().length;
saida.tremeu = TREMEU.slice();
saida.aviso = (ELS['im_aviso'] || {}).textContent || '';
saida.aberta = IM.atual ? IM.atual.bilhete : '';
imEstado(DC.series[1]).im_esp = '';
TREMEU.length = 0;
dcConverter();
saida.sem_esp = pedidos().length;
saida.tremeu_esp = TREMEU.slice();
imEstado(DC.series[1]).im_esp = '5';
imEstado(DC.series[1]).escala = true;
dcConverter();
var p = pedidos();
saida.pedido = p.length ? p[0].corpo : null;
console.log('JSON:' + JSON.stringify(saida));
"""


def teste_a_imagem_no_pipeline_so_converte_ajustada():
    secao(u"a serie de imagem no pipeline: «Converter» cobra o ajuste dela")
    import radai_bridge as B
    res, erro = _rodar_tela(_IMAGEM_JS)
    checar(u"a tela executa com o DOM dublado", res is not None, erro)
    if res is None:
        return
    checar(u"escala nao confirmada: nao pede a conversao, abre a serie e treme o botao",
           res["sem_confirmar"] == 0 and res["tremeu"] == [u"im_conf_escala"]
           and res["aberta"] == u"b_img"
           and u"confirme a escala" in res["aviso"], str(res)[:240])
    checar(u"espessura vazia: nao pede a conversao e o campo treme",
           res["sem_esp"] == 0 and res["tremeu_esp"] == [u"im_esp"],
           str(res.get("tremeu_esp")))
    series = (res.get("pedido") or {}).get("series") or []
    img = series[1].get("imagem") if len(series) == 2 else None
    checar(u"ajustada: o pedido leva a DICOM pelo bilhete e a imagem com a geometria",
           series and series[0] == {u"b": u"b_tc"} and img
           and img["geometria"]["espessura_mm"] == 5
           and img["geometria"]["espacamento_mm"] == [0.8, 0.8]
           and img["geometria"]["orientacao"] == u"axial"
           and img["modalidade"] == u"MR" and img["descricao"] == u"RM T2 AXIAL",
           str(res.get("pedido"))[:300])
    original = B.JS
    try:
        B.JS = original.replace(
            u"falta = (si && si.imagem) ? imFalta(si) : ''", u"falta = ''")
        isca, _e = _rodar_tela(_IMAGEM_JS)
    finally:
        B.JS = original
    checar(u"  (isca) sem a cobranca, a imagem sem escala confirmada seria convertida",
           isca is not None and isca["sem_confirmar"] == 1, str(isca)[:160])


def _versao_errada(modulo, funcao, de, para):
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(getattr(modulo, funcao)))
    if de not in src:
        return None
    ns = dict(vars(modulo))
    exec(compile(src.replace(de, para), "<isca>", "exec"), ns)
    return ns[funcao]


def _retrato(raiz):
    fora = []
    for atual, _d, arqs in os.walk(raiz):
        for a in arqs:
            c = os.path.join(atual, a)
            fora.append((os.path.relpath(c, raiz), os.path.getsize(c),
                         os.path.getmtime(c)))
    return sorted(fora)


def teste_o_cd_le_so_o_drive_de_cd():
    secao(u"«Carregar um CD»: só o drive de CD com disco, lido inteiro, sem gravar")
    import time as _t
    import radai_bridge_entrada as E
    import radai_dicom
    cd = novo_temp("radai_bridge_cd_")
    escrever_serie(os.path.join(cd, u"DICOM", u"PAC1", u"EST1", u"SER1"), n=5)
    escrever_serie(os.path.join(cd, u"DICOM", u"PAC1", u"EST1", u"SER2"), n=4,
                   modalidade="MR", numero=2, descricao=u"RM FANTOMA")
    io.open(os.path.join(cd, u"AUTORUN.INF"), "w").write(u"[autorun]\n")
    antes = _retrato(cd)
    tipos = {u"C:\\": 3, u"D:\\": E.DRIVE_CDROM, u"E:\\": E.DRIVE_CDROM,
             u"F:\\": 2, cd: E.DRIVE_CDROM}
    midia = {u"D:\\": True, u"E:\\": False, cd: True}
    orig = (E._letras, E._tipo_do_drive, E._tem_midia)
    orig_arvore = radai_dicom.varrer_arvore
    try:
        E._letras = lambda: [u"C:\\", u"D:\\", u"E:\\", u"F:\\"]
        E._tipo_do_drive = lambda r: tipos.get(r, 0)
        E._tem_midia = lambda r: midia.get(r, True)
        achados = E.drives_de_cd()
        checar(u"só o drive de CD COM disco (GetDriveTypeW == DRIVE_CDROM)",
               achados == [u"D:\\"], str(achados))
        sem_tipo = _versao_errada(E, "drives_de_cd",
                                  u"_tipo_do_drive(r) == DRIVE_CDROM and ", u"")
        checar(u"  (isca) sem conferir o tipo, o disco fixo e o pendrive entrariam",
               sem_tipo is not None and sem_tipo() != [u"D:\\"]
               and u"C:\\" in sem_tipo(), str(sem_tipo and sem_tipo()))
        sem_midia = _versao_errada(E, "drives_de_cd", u" and _tem_midia(r)", u"")
        checar(u"  (isca) sem conferir o disco, o drive vazio entraria",
               sem_midia is not None and u"E:\\" in sem_midia())
        try:
            E.ler_cd(u"C:\\")
            recusou = False
        except E.EntradaRecusada:
            recusou = True
        checar(u"ler um drive que não é CD é recusado (a rota não lê caminho qualquer)",
               recusou)

        from fastapi import FastAPI
        from starlette.testclient import TestClient
        import radai_bridge as B
        cli = TestClient(B.montar(FastAPI()))
        E._letras = lambda: [u"C:\\", cd]
        checar(u"a rota lista o drive de CD, e só ele",
               cli.post(u"/api/bridge/cd/drives", json={}).json().get(u"drives") == [cd])
        checar(u"  e recusa o que não é CD",
               u"CD" in str(cli.post(u"/api/bridge/cd/ler",
                                     json={u"drive": u"C:\\"}).json().get(u"erro")))
        lei = cli.post(u"/api/bridge/cd/ler", json={u"drive": cd}).json().get(u"leitura")
        est = {}
        for _ in range(200):
            est = cli.post(u"/api/bridge/cd/estado", json={u"leitura": lei}).json()
            if est.get(u"fim"):
                break
            _t.sleep(0.05)
        checar(u"o disco é lido inteiro, pastas e subpastas, com o progresso",
               est.get(u"fim") and not est.get(u"parado") and est.get(u"series") == 2
               and est.get(u"pastas", 0) >= 5 and est.get(u"arquivos", 0) >= 10,
               str(est))
        checar(u"  e o estado não leva caminho de série nem identificação",
               set(est) == {u"raiz", u"pastas", u"arquivos", u"series", u"fim",
                            u"parado", u"erro"}, str(sorted(est)))
        orig_nomes = radai_dicom._ler_nomes
        lidos = []

        def _contar(pasta, nomes, *a, **k):
            lidos.extend(nomes)
            return orig_nomes(pasta, nomes, *a, **k)
        radai_dicom._ler_nomes = _contar
        try:
            v = cli.post(u"/api/bridge/varrer",
                         json={u"pasta": cd, u"leitura": lei}).json()
            n_carga = len(lidos)
            del lidos[:]
            radai_dicom.varrer(cd)
            n_depois = len(lidos)
            del lidos[:]
            ref = radai_dicom.varrer(cd, relembrar=False)
            n_ref = len(lidos)
            del lidos[:]
            v_sem = cli.post(u"/api/bridge/varrer", json={u"pasta": cd}).json()
            n_sem = len(lidos)
            del lidos[:]
            lei_r = cli.post(u"/api/bridge/cd/ler", json={u"drive": cd}).json().get(u"leitura")
            for _ in range(200):
                if cli.post(u"/api/bridge/cd/estado",
                            json={u"leitura": lei_r}).json().get(u"fim"):
                    break
                _t.sleep(0.05)
            intacto = _retrato(cd) == antes
            escrever_serie(os.path.join(cd, u"DICOM", u"PAC1", u"EST1", u"SER3"), n=3,
                           modalidade="CT", numero=3, descricao=u"TC TROCADA")
            del lidos[:]
            v_troca = cli.post(u"/api/bridge/varrer",
                               json={u"pasta": cd, u"leitura": lei_r}).json()
            n_troca = len(lidos)
        finally:
            radai_dicom._ler_nomes = orig_nomes
        checar(u"depois da leitura, o pipeline carrega as duas séries do CD",
               sorted(s[u"modalidade"] for s in v.get(u"series") or []) == [u"CT", u"MR"],
               str(v)[:160])
        checar(u"  sem ler o disco de novo: a carga usa o que a leitura com "
               u"progresso achou", n_carga == 0, str(n_carga))
        checar(u"  e o que ela achou é o que a varredura do pipeline leria "
               u"(séries, cortes e a ordem dos arquivos)",
               [(s[u"uid"][-12:], s[u"cortes"]) for s in v.get(u"series") or []]
               == [(s[u"uid"][-12:], s[u"cortes"]) for s in ref[u"series"]],
               str(v.get(u"series"))[:160])
        checar(u"  e fica guardado: o diagnóstico e a conversão (radai_dicom.varrer) "
               u"não leem o disco outra vez", n_depois == 0, str(n_depois))
        checar(u"  (isca) sem a leitura no pedido, a carga lê o disco inteiro de "
               u"novo -- a contagem discrimina",
               n_sem >= n_ref > 0 and len(v_sem.get(u"series") or []) == 2,
               u"sem=%d ref=%d" % (n_sem, n_ref))
        checar(u"  e o disco que mudou entre a leitura e a carga é lido de novo, "
               u"com a série nova", n_troca > 0
               and len(v_troca.get(u"series") or []) == 3,
               u"lidos=%d series=%d" % (n_troca, len(v_troca.get(u"series") or [])))
        checar(u"a leitura e as cargas não gravaram nada no disco lido", intacto)
        antes = _retrato(cd)
        tipos[u"C:\\"] = E.DRIVE_CDROM
        tipos[os.path.splitdrive(cd)[0].upper() + u"\\"] = E.DRIVE_CDROM
        v2 = cli.post(u"/api/bridge/varrer", json={u"pasta": cd}).json()
        checar(u"  e o CD não é oferecido como destino da entrega",
               v2.get(u"origem") == u"", str(v2.get(u"origem")))
        tipos[u"C:\\"] = 3
        tipos.pop(os.path.splitdrive(cd)[0].upper() + u"\\", None)
        checar(u"nada foi gravado no disco lido", _retrato(cd) == antes)

        def _devagar(raiz, parar=None, ao_ler=None, pular=None):
            for x in orig_arvore(raiz, parar=parar, ao_ler=ao_ler):
                _t.sleep(0.2)
                yield x
        radai_dicom.varrer_arvore = _devagar
        lei2 = cli.post(u"/api/bridge/cd/ler", json={u"drive": cd}).json().get(u"leitura")
        _t.sleep(0.05)
        cli.post(u"/api/bridge/cd/parar", json={u"leitura": lei2})
        for _ in range(200):
            est2 = cli.post(u"/api/bridge/cd/estado", json={u"leitura": lei2}).json()
            if est2.get(u"fim"):
                break
            _t.sleep(0.05)
        checar(u"«Cancelar» para a leitura no meio", est2.get(u"fim")
               and est2.get(u"parado") and est2.get(u"pastas", 99) < 5, str(est2))
        checar(u"leitura que não existe diz que não existe",
               u"não existe" in str(cli.post(u"/api/bridge/cd/estado",
                                             json={u"leitura": u"x"}).json().get(u"erro")))
    finally:
        E._letras, E._tipo_do_drive, E._tem_midia = orig
        radai_dicom.varrer_arvore = orig_arvore
    import radai_bridge as B
    import radai_menu
    import radai_ui
    p = radai_menu.aplicar(B.pagina(), "bridge_laudo")
    m = re.search(r'<span class="ui-envio-bts">(.*?)</span><span class="ui-envio-barra">',
                  p, re.S)
    bts = m.group(1) if m else u""
    checar(u"o botão «Carregar um CD» é a terceira opção do quadro de carregar",
           bts.find(u"Escolher arquivos") < bts.find(u"Escolher pasta")
           < bts.find(u"Carregar um CD") and bts.count(u"<button") == 3, bts[:200])
    checar(u"  com o ícone de disco em SVG, e o clique não abre o seletor de arquivos",
           radai_ui.icone(u"disco") and radai_ui.icone(u"disco") in bts
           and u"event.stopPropagation();dcCd()" in bts)
    checar(u"sem CD, a tela diz; com dois, pergunta qual",
           u"nenhum CD na unidade" in _corpo_js(B.JS, u"dcCd")
           and u"há mais de um CD: escolha qual ler" in _corpo_js(B.JS, u"dcCd")
           and u"if(ds.length === 1){ dcCdLer(0); return }" in _corpo_js(B.JS, u"dcCd"))


FRASES_DA_PERGUNTA_DO_PIXEL = (u"seguir assim", u"recortar as faixas",
                               u"recortar o texto", u"não mudam entre cortes",
                               u"nao mudam entre cortes")


def _perguntas_do_pixel(fonte_py):
    import ast
    achadas = []
    for n in ast.walk(ast.parse(fonte_py)):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            t = n.value.lower()
            achadas += [f for f in FRASES_DA_PERGUNTA_DO_PIXEL if f in t]
    return achadas


def teste_nenhuma_tela_pergunta_sobre_o_texto_no_pixel():
    secao(u"texto no pixel: só o alerta de uma linha, nenhuma pergunta em tela nenhuma")
    vistos, achadas = 0, []
    for nome in _componentes.nomes("app"):
        if not nome.endswith(".py"):
            continue
        vistos += 1
        fonte_py = io.open(_componentes.fonte("app/" + nome), encoding="utf-8",
                           errors="replace").read()
        achadas += [(nome, f) for f in _perguntas_do_pixel(fonte_py)]
    checar(u"a varredura passou pelo app/ das sete pastas (%d módulos)" % vistos,
           vistos >= 60, str(vistos))
    checar(u"nenhum texto de tela pergunta «Seguir assim» ou «Recortar as faixas»",
           not achadas, str(achadas[:5]))
    checar(u"  (isca) a pergunta antiga seria achada",
           _perguntas_do_pixel(u"x = u'80 das 512 linhas n\u00e3o mudam entre cortes. "
                               u"Seguir assim ou Recortar as faixas?'")
           == [u"seguir assim", u"recortar as faixas", u"não mudam entre cortes"])
    import radai_bridge as B
    import radai_image as RI
    p = B.pagina()
    checar(u"a tela do pipeline não tem caixa de escolha para o pixel",
           u'type="radio"' not in p and u"im_carimbo" not in p)
    checar(u"os títulos do texto no pixel são alerta de uma linha",
           all(u"\n" not in t and u"?" not in t for t in (
               B.TITULO_DO_TEXTO_DECLARADO, B.TITULO_DA_CAPTURA, RI.TITULO_DO_CARIMBO,
               RI.TITULO_SEM_CONFERIR_O_CARIMBO, RI.TITULO_DO_CARIMBO_NAO_CONFERIDO)))


def teste_a_entrega_vai_pelo_bilhete():
    secao(u"a conversao vai pelo bilhete")
    res, erro = _rodar_tela(_ENTREGA_JS)
    checar(u"a tela executa com o DOM dublado", res is not None, erro)
    if res is None:
        return
    conv = [c for c in res["corpos"] if c["url"] == "/api/bridge/etapa/converter"]
    checar(u"«Converter» manda o bilhete DA série marcada, e só ele",
           conv and [x.get("b") for x in conv[0]["corpo"].get("series") or []]
           == [u"bilhete_do_torax"], str(conv)[:200])
    checar(u"  sem índice e sem pedir .zip",
           conv and "indice" not in json.dumps(conv[0]["corpo"])
           and "zip" not in conv[0]["corpo"], str(conv)[:200])

    try:
        from fastapi import FastAPI
    except Exception as e:
        checar(u"fastapi disponivel", False, str(e)[:60])
        return
    import radai_bridge
    import radai_dicom
    base = novo_temp()
    escrever_serie(os.path.join(base, "s0"), n=6)
    radai_dicom.esquecer_varredura()
    cli = Cliente(radai_bridge.montar(FastAPI()))
    s = (cli.post("/api/bridge/varrer", json={"pasta": base}).json()
         .get("series") or [{}])[0]
    m = cli.get("/api/bridge/miniatura", params={"b": s.get("bilhete", "")})
    checar(u"  e a miniatura pedida por ela sai em PNG",
           m.status_code == 200 and m.content[:8] == b"\x89PNG\r\n\x1a\n",
           str(m.status_code))
    velho = cli.get("/api/bridge/corte", params={"b": ""})
    checar(u"  (o pedido antigo, com o bilhete vazio, dava 404)",
           velho.status_code == 404, str(velho.status_code))


def teste_o_contrato_da_fila():
    secao(u"C1: a fila unica, com a rota dublada")
    import radai_bridge as B
    res, erro = _rodar_tela(_FILA_JS)
    checar(u"a tela executa com a fila dublada", res is not None, erro)
    if res is None:
        return
    itens = res["itens"]
    checar(u"so as series com segmentacao vao para a fila",
           [x["uid"] for x in itens] == [u"1.2.3.1", u"1.2.3.2"], str(itens)[:200])
    a, b = itens[0], itens[1]
    checar(u"cada item tem pasta, uid, modo, chaves, copiar_rs_para, origem e rotulo",
           all(sorted(x) == sorted(["pasta", "uid", "modo", "chaves",
                                    "copiar_rs_para", "origem", "rotulo"])
               for x in itens), str(sorted(a)))
    checar(u"  a pasta e a da serie ENTREGUE no primeiro destino",
           a["pasta"] == u"D1/DICOM_BRIDGE_X/s1")
    checar(u"  e copiar_rs_para sao as copias nos outros destinos",
           a["copiar_rs_para"] == [u"D2/DICOM_BRIDGE_X/s1"])
    checar(u"  o modo vai no vocabulario do contrato",
           a["modo"] == u"fast" and b["modo"] == u"personalizado")
    checar(u"  FAST vai sem chaves; PERSONALIZADO leva as tasks 0|1",
           a["chaves"] == {} and b["chaves"] == {u"total_mr": 1, u"vertebrae_mr": 0},
           str(b["chaves"]))
    checar(u"  a origem e o DicomBridge", a["origem"] == B.ORIGEM_NA_FILA
           == u"dicombridge")
    checar(u"  e o rotulo diz modalidade e serie, sem caminho",
           a["rotulo"] == u"CT · CT ABDOME" and u"/" not in a["rotulo"],
           a["rotulo"])
    checar(u"rota ausente (404): a tela diz «fila indisponivel», sem quebrar",
           u"fila indisponível" in res["indisponivel"]
           and u"dc-fila falha" in res["indisponivel"]
           and u"Tentar de novo" in res["indisponivel"], res["indisponivel"][:160])
    checar(u"  e sem rede tambem", u"fila indisponível" in res["sem_rede"])
    checar(u"a fila que RECUSA diz o motivo dela, e nao «indisponivel» (teto e outros)",
           u"a fila recusou a segmentação" in res["recusada"]
           and u"no máximo 8 pastas" in res["recusada"]
           and u"fila indisponível" not in res["recusada"]
           and u"Tentar de novo" not in res["recusada"], res["recusada"][:200])
    ped = res.get("pedido") or {}
    checar(u"com a fila no ar, o POST vai a /api/fila/enfileirar com {itens}",
           ped.get("url") == B.ROTA_DA_FILA == u"/api/fila/enfileirar"
           and (ped.get("corpo") or {}).get("itens") == itens, str(ped)[:160])
    gd = res.get("guardar") or {}
    checar(u"  e os itens ficam guardados no servidor; a tela so guarda o bilhete",
           (gd.get("corpo") or {}).get("itens") == itens and res.get("guarda") == u"g1"
           and u"D1/" not in res.get("sessao", u"") and u"g1" in res.get("sessao", u"")
           and u"CT ABDOME" not in res.get("sessao", u""), res.get("sessao", u"")[:200])
    checar(u"  e o cartao diz «DICOM entregue · segmentacao na fila (posicao N)»",
           u"DICOM entregue · segmentação na fila" in res["na_fila"]
           and u">3<" in res["na_fila"] and u"DICOM_BRIDGE_X" in res["na_fila"],
           res["na_fila"][:200])
    checar(u"  e a barra da fila abre (window.radaiFilaAbrir)", res["abriu"] == 1)
    checar(u"  e o cartao passa a consultar o estado", res["vigiando"])
    est = res.get("estado_pedido") or {}
    checar(u"o estado e pedido a /api/fila/estado pelos ids",
           est.get("url") == B.ROTA_DO_ESTADO_DA_FILA
           and (est.get("corpo") or {}).get("ids") == [u"c1", u"c2"], str(est)[:120])
    checar(u"  rodando: «segmentando»", u"segmentando" in res["rodando"])
    checar(u"fila parada (rodando: false): «clique Iniciar na barra», com o botao "
           u"que abre a barra",
           u"a fila está parada: clique Iniciar na barra" in res["parada"]
           and u"Abrir a fila" in res["parada"], res["parada"][:200])
    checar(u"  rodando: true nao avisa nada", u"parada" not in res["andando"])
    checar(u"  e sem o campo (desconhecido) tambem nao", u"parada" not in res["sem_campo"]
           and u"segmentação na fila" in res["sem_campo"])
    checar(u"pronto: a mensagem do cartao aparece (a copia que falhou)",
           u"a pasta de cópia não existe mais" in res["pronto_logo"]
           and u"CT · CT ABDOME" in res["pronto_logo"], res["pronto_logo"][:240])
    checar(u"  e, antes de conferir as copias no disco, nao afirma «RTSTRUCT entregue»",
           u"conferindo o RTSTRUCT nos destinos" in res["pronto_logo"]
           and u"RTSTRUCT entregue" not in res["pronto_logo"], res["pronto_logo"][:240])
    checar(u"  e, conferido no disco, a copia que faltou muda o titulo: nao diz "
           u"«RTSTRUCT entregue» a quem nao recebeu",
           u"o RTSTRUCT não chegou a todos os destinos" in res["pronto"]
           and u"dc-fila meia" in res["pronto"]
           and u"a pasta de cópia não existe mais" in res["pronto"]
           and res["conferiu"] >= 1, res["pronto"][:240])
    checar(u"  e a entrega fecha (sai da sessao)", res["concluida"]
           and u"DICOM_BRIDGE_X" not in res["sessao_fim"], res["sessao_fim"][:120])
    checar(u"com as copias todas no disco: «RTSTRUCT entregue»",
           u"DICOM entregue · RTSTRUCT entregue" in res["pronto_inteiro"]
           and u"dc-fila pronta" in res["pronto_inteiro"]
           and u"não chegou" not in res["pronto_inteiro"], res["pronto_inteiro"][:200])
    checar(u"falha da fila mostra a mensagem e oferece a fila de novo",
           u"o app fechou no meio" in res["falhou"]
           and u"Pôr na fila de novo" in res["falhou"]
           and u"dc-fila falha" in res["falhou"], res["falhou"][:200])
    checar(u"  e «Por na fila de novo» usa o /api/fila/repor pelo id, sem reenviar "
           u"os itens",
           res["repor"] == [u"%s {\"id\":\"c7\"}" % B.ROTA_DE_REPOR]
           and res["repor_ids"] == [u"c8:esperando"], str(res["repor"]))
    js = B.JS
    checar(u"a etapa 6 nao some com escolha nova enquanto ha fila",
           u"!(k === 6 && DC.filas.length)" in _corpo_js(js, u"dcEtapa"))
    checar(u"a tela nao chama mais o Rodar agora",
           u"/api/lote/selecao" not in js and u"/lote?ficha=" not in js)


def teste_varias_entregas_e_a_volta_a_tela():
    secao(u"varias entregas, o cartao que sai da fila e a volta a tela")
    import radai_bridge as B
    res, erro = _rodar_tela(_FILAS_JS)
    checar(u"a tela executa com duas entregas", res is not None, erro)
    if res is None:
        return
    checar(u"a segunda entrega NAO apaga a primeira: dois cartoes na tela",
           res["duas"] == 2 and u"DICOM_BRIDGE_A" in res["html_duas"]
           and u"DICOM_BRIDGE_B" in res["html_duas"], res["html_duas"][:200])
    checar(u"  e as duas sao acompanhadas num pedido so",
           res["ids"] == [u"a1", u"b1", u"b2"], str(res["ids"]))
    checar(u"  e as duas vao para a sessao, com o bilhete de cada uma",
           [e.get("guarda") for e in (res["sessao"] or {}).get("entregas") or []]
           == [u"gA", u"gB"], str(res["sessao"])[:200])
    checar(u"cartao que saiu da fila DEPOIS de pronto continua pronto (o «Limpar»)",
           res["a_estado"] == u"pronto" and res["conferir_gA"] == 0,
           u"%s, conferiu %s" % (res["a_estado"], res["conferir_gA"]))
    checar(u"cartao que saiu sem ser visto pronto e conferido no disco pela guarda",
           res["b_estados"] == [u"pronto", u"falhou"]
           and (res["conferir_gB"] or {}).get("corpo") == {u"guarda": u"gB", u"quais": [0, 1]},
           str(res["b_estados"]) + str(res["conferir_gB"]))
    checar(u"  com a frase que diz o que se achou",
           u"o RTSTRUCT está ao lado da série" in res["html_saiu"]
           and u"o cartão saiu da fila sem o RTSTRUCT" in res["html_saiu"],
           res["html_saiu"][-300:])
    checar(u"a sessao guarda so nome, bilhete, ids e estados: nem caminho nem rotulo",
           res["guardado_sem_caminho"])
    checar(u"ao voltar a tela, as duas entregas voltam",
           res["retomadas"] == [u"DICOM_BRIDGE_A", u"DICOM_BRIDGE_B"]
           and res["retomada_itens"] == [None, None], str(res["retomadas"]))
    checar(u"  a pronta continua pronta, e a que falhou oferece a fila de novo",
           u"dc-fila pronta" in res["html_retomada"]
           and u"Pôr na fila de novo" in res["html_retomada"], res["html_retomada"][:300])
    checar(u"«Por na fila de novo» depois de voltar: o cartao que saiu vai pela guarda",
           res["repor_pedidos"] == 0
           and (res["de_novo"] or {}).get("url") == u"/api/bridge/fila/de_novo"
           and (res["de_novo"] or {}).get("corpo") == {u"guarda": u"gB", u"quais": [1]}
           and res["b_depois"] == [u"b1:pronto", u"b9:esperando"],
           str(res["de_novo"]) + str(res["b_depois"]))
    checar(u"a sessao do formato antigo ({ids, nome}) ainda volta",
           res["formato_antigo"] == [u"DICOM_BRIDGE_V:na_fila:1"], str(res["formato_antigo"]))
    checar(u"teto: com segmentacao e destinos demais, nao entrega e diz por que",
           res["teto_pedidos"] == 0 and B.FRASE_DO_TETO in res["teto"]
           and (u"%d outros destinos" % B.TETO_DE_COPIAS_DO_RTSTRUCT) in res["teto"],
           res["teto"][:200])
    checar(u"  no limite (1 + teto) entrega; sem segmentacao nao ha teto",
           res["teto_no_limite"] == 1 and res["sem_segmentacao"] == 2,
           u"%s %s" % (res["teto_no_limite"], res["sem_segmentacao"]))
    try:
        import radai_queue_state as Q
        teto_fila = getattr(Q, "TETO_DE_COPIAS", None)
    except Exception:
        teto_fila = None
    checar(u"  e o teto e o da fila (radai_queue_state.TETO_DE_COPIAS), quando ela o diz",
           teto_fila is None or teto_fila == B.TETO_DE_COPIAS_DO_RTSTRUCT,
           u"%s contra %s" % (teto_fila, B.TETO_DE_COPIAS_DO_RTSTRUCT))
    original = B.JS
    try:
        B.JS = original.replace(u"DC.filas.push(e);", u"DC.filas = [e];", 1)
        isca1, _e = _rodar_tela(_FILAS_JS)
        B.JS = original.replace(
            u"if(DC_TERMINA.indexOf(c.estado) >= 0) return;", u"", 1)
        isca3, _e = _rodar_tela(_FILAS_JS)
    finally:
        B.JS = original
    checar(u"  (isca) com uma entrega so na memoria, a segunda apagaria a primeira",
           isca1 is not None and isca1["duas"] == 1, str((isca1 or {}).get("duas")))
    checar(u"  (isca) sem o ultimo estado conhecido, o pronto que saiu viraria falha",
           isca3 is not None and isca3["a_estado"] != u"pronto",
           str((isca3 or {}).get("a_estado")))


def teste_o_diagnostico_le_todas_as_series():
    secao(u"o diagnostico mostra os alertas de TODAS as series antes de converter")
    import radai_bridge as B
    res, erro = _rodar_tela(_DIAG_JS)
    checar(u"a tela executa com o laudo dublado", res is not None, erro)
    if res is None:
        return
    checar(u"«Avancar» le o laudo de cada serie escolhida, uma vez cada",
           sorted(res["pedidos"]) == [u"b1", u"b2", u"b3"], str(res["pedidos"]))
    checar(u"«Converter» espera os alertas de todas chegarem",
           res["pendente_bloqueia"] is True and res["depois_libera"] is True,
           u"%s %s" % (res["pendente_bloqueia"], res["depois_libera"]))
    checar(u"  e, enquanto isso, diz que esta lendo",
           u"lendo o cabeçalho…" in res["outras_pendente"], res["outras_pendente"][:200])
    checar(u"a lista conta os alertas de todas, sem «…»",
           res["lista"].count(u"1 alerta") == 2 and u"0 alertas" in res["lista"]
           and u"…" not in res["lista"], res["lista"][:300])
    checar(u"os alertas das outras series aparecem ao lado da aberta",
           u"Alertas das outras séries escolhidas" in res["outras"]
           and u"Decodificador da B" in res["outras"] and u"não converte" in res["outras"]
           and u"Nenhum alerta." in res["outras"] and u"Alerta da A" not in res["outras"],
           res["outras"][:300])
    checar(u"trocar o modo depois de converter NAO descarta a conversao",
           res["modo_descartou"] == 0 and res["modo_conversao"] == u"tok"
           and res["modo_etapa"] == 5, str(res)[:120])
    checar(u"trocar as series descarta, e limpa o que dizia «convertidas» e «entregue»",
           res["marcar_limpa"] == [u"", u"", u""], str(res["marcar_limpa"]))
    original = B.JS
    try:
        B.JS = original.replace(
            u"// GUARDA: a segmentação não muda o DICOM; trocar o modo não descarta a conversão.",
            u"if(DC.etapa > 4) dcVoltarA(4);", 1)
        isca, _e = _rodar_tela(_DIAG_JS)
    finally:
        B.JS = original
    checar(u"  (isca) com o retorno a etapa 4, trocar o modo descartaria",
           isca is not None and isca["modo_descartou"] == 1, str((isca or {}).get("modo_descartou")))


def teste_o_brilho_do_visor_para_no_erro():
    secao(u"o brilho do visor para quando nenhum corte chega")
    import radai_bridge as B
    res, erro = _rodar_tela(_VIGIA_JS)
    checar(u"o vigia do visor roda com o visor dublado", res is not None, erro)
    if res is None:
        return
    checar(u"esperando o primeiro corte, o brilho fica aceso",
           res["esperando"] == [[1], 0], str(res["esperando"]))
    checar(u"tres falhas sem nenhum corte: apaga o brilho e avisa quem chamou",
           res["tres_falhas"] == [[1, 0], 1], str(res["tres_falhas"]))
    checar(u"  com um corte chegando, nao avisa falha (o load apaga o brilho)",
           res["chegou_um"] == [[1], 0], str(res["chegou_um"]))
    checar(u"  e o 404 do visor apaga sem chamar o aviso de falha (o aoParar diz)",
           res["parado"] == [[1, 0], 0], str(res["parado"]))
    checar(u"o visor do diagnostico usa o vigia",
           u"bgVigiarVisor(cx, DC.visor" in _corpo_js(B.JS, u"dcBrilhoNoVisor"))


def teste_o_pipeline_abre_etapa_por_etapa():
    secao(u"um cartao, um pipeline vertical que abre etapa por etapa")
    import radai_bridge as B
    p = radai_pagina()
    ordem = [p.find(u'id="dc_e%d"' % k) for k in range(1, 7)]
    checar(u"seis etapas, na ordem", all(x > 0 for x in ordem)
           and ordem == sorted(ordem), str(ordem))
    for k, nome in ((1, u"Carregar"), (2, u"Escolher as séries"),
                    (3, u"Diagnóstico"), (4, u"Converter"), (5, u"Entregar"),
                    (6, u"Segmentar")):
        bloco = p[p.find(u'id="dc_e%d"' % k):]
        checar(u"  etapa %d: %s" % (k, nome),
               (u"<span data-radai-frase>%s</span>" % nome) in bloco[:400])
    oculto = [k for k in range(2, 7)
              if re.search(r'id="dc_e%d"[^>]*hidden' % k, p)]
    checar(u"so a primeira nasce aberta", oculto == [2, 3, 4, 5, 6], str(oculto))
    cab1 = p[p.find(u'id="dc_e1"'):p.find(u'id="dc_envio"')]
    checar(u"«Limpar carregamentos» com destaque, no cabecalho da etapa 1",
           u'class="ui-bt bg-limpar" id="dc_limpar"' in cab1)
    checar(u"a carga tem a area de envio, o campo e o Procurar",
           u'id="dc_envio"' in p and u'id="dc_pasta"' in p
           and u"dcProcurar(this)" in p and u'id="dc_carregar"' in p)
    checar(u"o .zip saiu da entrega",
           u'id="dc_zip"' not in p and u"converte e grava o .zip" not in p
           and u"zip:" not in B.JS)
    checar(u"so um cartao: /bridge/tps leva ao pipeline",
           u"RedirectResponse(url=\"/bridge/laudo\"" in fonte("radai_bridge.py"))
    checar(u"a segmentacao por serie: nenhuma, FAST, AUTO, PERSONALIZADO",
           [m[0] for m in B.MODOS_DE_SEGMENTACAO]
           == [u"nenhuma", u"fast", u"auto", u"personalizado"])
    checar(u"  so CT e RM se segmentam", tuple(B.MODALIDADES_QUE_SEGMENTAM)
           == ("CT", "MR"))
    checar(u"  o PERSONALIZADO le as tasks do Rodar agora por GET so com a "
           u"modalidade", u"DC_ROTA_OPCOES + '?modalidade='" in _corpo_js(B.JS, u"dcOpcoes")
           and B.ROTA_DAS_OPCOES == u"/api/lote/opcoes")
    res, erro = _rodar_tela(_TASKS_JS)
    ch = (res or {}).get("chaves") or {}
    checar(u"  task de ACHADO nunca nasce marcada, nem ligada de fabrica (regra 6)",
           res is not None and ch.get("lung_nodules") == 0 and ch.get("body") == 1
           and "proibida" not in ch, erro or str(ch))
    checar(u"  e o pedido de opcoes leva so a modalidade",
           res is not None and res.get("url") == u"/api/lote/opcoes?modalidade=CT",
           str((res or {}).get("url")))
    original = B.JS
    try:
        B.JS = original.replace(u"&& !t.achado", u"")
        isca, _e = _rodar_tela(_TASKS_JS)
    finally:
        B.JS = original
    checar(u"  (isca) sem a trava, o achado de fabrica nasceria marcado",
           isca is not None and (isca.get("chaves") or {}).get("lung_nodules") == 1,
           str(isca))
    checar(u"o diagnostico mostra so os alertas",
           u"a.alerta || a.impede" in _corpo_js(B.JS, u"dcAlertas")
           and u"A conversão resolve" not in B.JS and u"já conformes" not in B.JS)
    checar(u"a frase da fronteira mora no gesto que poe na fila",
           u'id="dc_fronteira"' in p
           and p.find(u'id="dc_fronteira"') < p.find(u'id="dc_entregar"')
           and u"UNAPPROVED" in p)
    checar(u"  e so aparece com segmentacao pedida",
           u"fr.hidden = !dcPedeSegmentacao()" in _corpo_js(B.JS, u"dcPintarBarra"))
    checar(u"a serie de imagem entra na MESMA grade do pipeline",
           u"DC.series = (d.series || []).concat(DC.imagens)"
           in _corpo_js(B.JS, u"dcCarregar"))
    checar(u"  e nenhum endereco leva mais a outra tela de imagem",
           u"/bridge/imagem" not in B.JS and u"dcPintarImagens" not in B.JS
           and u'id="dc_imagens"' not in p)
    checar(u"  (isca) o atalho antigo seria achado",
           u"/bridge/imagem" in u"'<a href=\"/bridge/imagem?b=' + b")


def teste_clique_marca_duplo_abre():
    secao(u"clique marca, duplo clique abre")
    f = fonte("radai_bridge.py")
    lig = f[f.index("function dcLigarCartao"):f.index("function dcMarcar(")]
    checar(u"o clique passa por um atraso", "setTimeout(function()" in lig)
    checar(u"e o duplo clique CANCELA o atraso",
           lig.count("clearTimeout(DC.cliqueTimer)") == 2,
           str(lig.count("clearTimeout(DC.cliqueTimer)")))
    checar(u"o duplo clique abre a serie no visor", "dcVisorModal(i)" in lig)
    checar(u"e o clique simples marca", "dcMarcar(i)" in lig)
    checar(u"Enter abre e Espaco marca",
           "'Enter'" in lig and "' '" in lig)

    p = radai_pagina()
    checar(u"o Avançar nasce desabilitado",
           'id="dc_avancar" disabled onclick="dcAvancar()"' in p)
    import radai_bridge as B
    checar(u"e so a serie marcada o habilita",
           u"bt = bgEl('dc_avancar'); if(bt) bt.disabled = !m.length;"
           in _corpo_js(B.JS, u"dcPintarBarra"))


def radai_pagina():
    import radai_bridge
    return radai_bridge.pagina()


def teste_cache_em_disco():
    secao(u"o cache em disco da miniatura")
    import radai_dicom
    import radai_thumbnail as M

    base = novo_temp()
    pasta = os.path.join(base, "s")
    escrever_serie(pasta, n=6)
    radai_dicom.esquecer_varredura()
    r = radai_dicom.varrer(base)
    s = r["series"][0]
    b = M.bilhete(base, s["uid"])

    dados1, info1 = M.png_central(b)
    checar(u"a primeira leitura veio do DICOM", info1.get("de") == "lido",
           str(info1.get("de")))
    guardado = M._pasta_cache(s)
    arqs = [a for a in (os.listdir(guardado) if os.path.isdir(guardado)
                        else []) if a.startswith(M._uid8(s["uid"]))]
    checar(u"e o PNG ficou no disco, no temporario local", len(arqs) == 1,
           str(arqs))
    checar(u"com a impressao do UID inteiro, o corte e a janela no nome",
           arqs and re.match(r"^[0-9a-f]{24}_c\d+_\w+_\d+\.png$", arqs[0]),
           arqs[0] if arqs else u"")
    checar(u"e nada dentro da pasta do exame",
           not os.path.exists(os.path.join(pasta, "_RadAI")))

    dados2, info2 = M.png_central(b)
    checar(u"a segunda leitura veio do disco", info2.get("de") == "disco",
           str(info2.get("de")))
    checar(u"e e o mesmo PNG", dados1 == dados2)

    import time
    alvo = os.path.join(guardado, arqs[0])
    velho = os.path.getmtime(alvo)
    os.utime(alvo, (velho - 100, velho - 100))
    _d3, info3 = M.png_central(b)
    checar(u"PNG mais velho que o DICOM e ignorado",
           info3.get("de") == "lido", str(info3.get("de")))

    sem_escrita = {"arquivos": [{"caminho": os.path.join(
        "\x00nao", "existe", "IM000.dcm")}], "uid": "1.2.3"}
    checar(u"o cache nao depende da pasta da serie, e nao levanta",
           "\x00nao" not in M._pasta_cache(sem_escrita))


def teste_cache_da_varredura():
    secao(u"o cache da varredura")
    import radai_dicom as D

    base = novo_temp()
    escrever_serie(os.path.join(base, "s1"), n=5, numero=1)
    D.esquecer_varredura()

    lidos = {"n": 0}
    import pydicom
    original = pydicom.dcmread

    def contando(*a, **k):
        lidos["n"] += 1
        return original(*a, **k)

    pydicom.dcmread = contando
    try:
        D.varrer(base)
        n1 = lidos["n"]
        checar(u"a primeira varredura leu os cabecalhos", n1 >= 5, str(n1))
        D.varrer(base)
        checar(u"a segunda nao releu nada", lidos["n"] == n1,
               u"%d -> %d" % (n1, lidos["n"]))

        escrever_serie(os.path.join(base, "s2"), n=4, numero=2)
        r = D.varrer(base)
        checar(u"serie nova na arvore e relida", lidos["n"] > n1,
               u"%d -> %d" % (n1, lidos["n"]))
        checar(u"e ela aparece", len(r["series"]) == 2, str(len(r["series"])))

        n2 = lidos["n"]
        D.esquecer_varredura(base)
        D.varrer(base)
        checar(u"esquecer_varredura forca a releitura", lidos["n"] > n2,
               u"%d -> %d" % (n2, lidos["n"]))
    finally:
        pydicom.dcmread = original


def teste_recibo_grava_o_que_se_decidiu():
    secao(u"o recibo da conversao")
    import radai_dicom as D

    base = novo_temp()
    pasta = os.path.join(base, "s")
    escrever_serie(pasta, n=6)
    destino = os.path.join(base, "saida")
    D.esquecer_varredura()
    s = D.varrer(base)["series"][0]

    r = D.converter(s, destino, quem=u"Operador de Teste")
    caminho = os.path.join(destino, "_RadAI", D.NOME_RECIBO)
    checar(u"o recibo foi escrito", os.path.exists(caminho), caminho)
    with io.open(caminho, encoding="utf-8") as f:
        d = json.load(f)
    checar(u"e ele e uma LISTA", isinstance(d, list), type(d).__name__)
    e = d[0]
    checar(u"tem versao", e.get("versao_recibo") == D.VERSAO_RECIBO)
    checar(u"tem quando, com fuso",
           bool(re.search(r"[+-]\d\d:\d\d$|Z$", e.get("quando") or "")),
           e.get("quando"))
    checar(u"tem quem", e.get("quem") == u"Operador de Teste")
    checar(u"tem a conferencia sobre o que foi GRAVADO",
           "gravados" in (e.get("conferido") or ""), e.get("conferido"))
    checar(u"e a sintaxe de destino",
           e["destino"]["sintaxe"] == D.SINTAXE_DESTINO)

    plano = json.dumps(d, ensure_ascii=False)
    checar(u"nao grava o UID inteiro", s["uid"] not in plano)
    checar(u"grava so os 8 ultimos digitos",
           e["serie"]["uid8"] == s["uid"][-8:], e["serie"]["uid8"])
    checar(u"nao grava o caminho de origem", pasta not in plano)
    checar(u"nem o caminho de destino", destino not in plano,
           u"o recibo mora DENTRO do destino: o campo era redundante")

    base2 = novo_temp()
    p2 = os.path.join(base2, "com_phi")
    escrever_serie(p2, n=4)
    _semear_phi(p2, nome=u"BELTRANO^ISCA^DE^TESTE", ident=u"FANTOMA-0001",
                nascimento=u"19510314")
    D.esquecer_varredura()
    s2 = D.varrer(base2)["series"][0]
    destino2 = os.path.join(novo_temp(), "saida")
    r2 = D.converter(s2, destino2, quem=u"bateria")
    texto = json.dumps(r2["recibo"], ensure_ascii=False)
    for rotulo, valor in ((u"o nome do paciente", u"BELTRANO"),
                          (u"a identificacao", u"FANTOMA-0001"),
                          (u"a data de nascimento", u"19510314")):
        checar(u"o recibo nao carrega %s" % rotulo, valor not in texto,
               texto[:80])
    import pydicom
    saiu = pydicom.dcmread(os.path.join(destino2, "IM00000.dcm"))
    checar(u"e a serie convertida CONTINUA identificada",
           str(getattr(saiu, "PatientName", "")).startswith(u"BELTRANO"),
           str(getattr(saiu, "PatientName", "")))

    D.converter(s, destino, quem=u"outro")
    with io.open(caminho, encoding="utf-8") as f:
        d2 = json.load(f)
    checar(u"a segunda conversao ACRESCENTA", len(d2) == 2, str(len(d2)))
    checar(u"e a primeira continua la", d2[0]["quem"] == u"Operador de Teste")


def teste_recibo_nao_leva_a_descricao_da_serie():
    secao(u"o recibo nao leva a descricao da serie")
    import radai_dicom
    fonte = io.open(_componentes.fonte("app/radai_dicom.py"), encoding="utf-8").read()
    i = fonte.find("def recibo(")
    corpo = fonte[i:fonte.find(chr(10) + "def ", i + 10)] if i >= 0 else ""
    checar(u"o recibo e montado numa funcao propria", bool(corpo))
    checar(u"e ele NAO grava a descricao da serie",
           '"descricao"' not in corpo,
           u"campo livre onde o servico digita nome e iniciais")
    checar(u"  e o que a serie era continua dito por campo tecnico",
           '"modalidade"' in corpo or '"cortes"' in corpo)


def teste_recibo_nao_derruba_conversao():
    secao(u"recibo que nao grava nao derruba a conversao")
    import radai_dicom as D
    ditos = []
    caminho = D.gravar_recibo({"quando": "x", "aceitos": []},
                              os.path.join("\x00", "impossivel"),
                              log=ditos.append)
    checar(u"nao levantou", True)
    checar(u"e disse no log", any("recibo" in t for t in ditos), str(ditos))
    checar(u"a conversao E dita como feita",
           any("ESTA feita" in t for t in ditos), str(ditos))
    checar(u"e o caminho devolvido nao mente", not os.path.exists(caminho or "x"))


def teste_recibo_ilegivel_nao_e_apagado():
    secao(u"recibo ilegivel e guardado, nao apagado")
    import radai_dicom as D
    base = novo_temp()
    destino = os.path.join(base, "d")
    os.makedirs(os.path.join(destino, "_RadAI"))
    alvo = os.path.join(destino, "_RadAI", D.NOME_RECIBO)
    io.open(alvo, "w", encoding="utf-8").write(u"{isto nao e json")
    D.gravar_recibo({"quando": "y", "aceitos": []}, destino)
    checar(u"o ilegivel foi guardado ao lado",
           os.path.exists(alvo + ".ilegivel"))
    with io.open(alvo, encoding="utf-8") as f:
        d = json.load(f)
    checar(u"e o novo abre", isinstance(d, list) and d[0]["quando"] == "y")


def teste_lote_separa_as_series_em_subpastas():
    secao(u"o lote separa as series em subpastas")
    try:
        from fastapi import FastAPI
    except Exception as e:
        checar(u"fastapi disponivel", False, str(e)[:60])
        return
    import radai_bridge
    import radai_dicom

    base = novo_temp()
    escrever_serie(os.path.join(base, "a"), n=6, numero=1, descricao=u"CT A")
    escrever_serie(os.path.join(base, "b"), n=9, numero=2, descricao=u"CT B")
    radai_dicom.esquecer_varredura()
    destino = os.path.join(novo_temp(), "saida")

    cli = Cliente(radai_bridge.montar(FastAPI()))
    r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    checar(u"duas series", len(r["series"]) == 2, str(len(r["series"])))
    d = cli.post("/api/bridge/etapa/converter", json={
        "pasta": base, "series": [{"b": s["bilhete"]} for s in r["series"]]}).json()
    checar(u"as duas converteram", len(d.get("exportadas") or []) == 2
           and not d.get("recusadas"), str(d)[:160])
    e = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": d.get("conversao"), "destinos": [destino]}).json()
    entrega = os.path.join(destino, e.get("nome") or "x")
    subs = sorted(n for n in os.listdir(entrega)
                  if os.path.isdir(os.path.join(entrega, n))) \
        if os.path.isdir(entrega) else []
    checar(u"cada uma foi para a sua subpasta, dentro da pasta nova", len(subs) == 2,
           str(subs))
    contagens = sorted(len([f for f in os.listdir(os.path.join(entrega, n))
                            if f.lower().endswith(".dcm")]) for n in subs)
    checar(u"e nenhuma perdeu corte", contagens == [6, 9], str(contagens))

    destino2 = os.path.join(novo_temp(), "saida_uma")
    d2 = cli.post("/api/bridge/etapa/converter", json={
        "pasta": base, "series": [{"b": r["series"][0]["bilhete"]}]}).json()
    e2 = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": d2.get("conversao"), "destinos": [destino2]}).json()
    checar(u"serie unica tambem vai numa subpasta da pasta nova",
           [len(x["pasta"]) > 0 and os.path.dirname(x["pasta"])
            == os.path.join(destino2, e2.get("nome") or "") for x in
            e2.get("series") or []] == [True], str(e2)[:160])


def teste_lote_nao_aceita_por_ninguem():
    secao(u"o lote nao aceita nada por ninguem")
    try:
        from fastapi import FastAPI
    except Exception as e:
        checar(u"fastapi disponivel", False, str(e)[:60])
        return
    import radai_bridge
    import radai_dicom

    base = novo_temp()
    sys.path.insert(0, AQUI)
    from test_dicom import escrever_serie as escrever_com_defeito
    escrever_com_defeito(os.path.join(base, "s"), n=8, passo=3.0, duplicar=4)
    radai_dicom.esquecer_varredura()

    cli = Cliente(radai_bridge.montar(FastAPI()))
    v = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    b = v["series"][0]["bilhete"]
    d = cli.post("/api/bridge/etapa/converter", json={
        "pasta": base, "series": [{"b": b, "aceitar": [u"qualquer coisa"]}]}).json()
    res = (d.get("exportadas") or [{}])[0]
    checar(u"o lote converte sem aceite, com o alerta (C1)",
           not d.get("erro") and res.get("alertas"), str(d)[:90])
    checar(u"e o alerta nomeia o corte duplicado",
           any(u"mesma posição" in t for t in res.get("alertas") or ()),
           str(res.get("alertas"))[:90])
    checar(u"a tela sabe de qual serie e", res.get("b") == b and "descricao" in res)
    destino = novo_temp()
    e = cli.post("/api/bridge/etapa/entregar", json={
        "conversao": d.get("conversao"), "destinos": [destino]}).json()
    rec = os.path.join(destino, e.get("nome") or "x", res.get("sub") or "x",
                       "_RadAI", "recibo_conversao.json")
    aceitos = json.load(io.open(rec, encoding="utf-8"))[0].get("aceitos") \
        if os.path.isfile(rec) else None
    checar(u"e o recibo registra que ninguem aceitou nada por ninguem",
           aceitos == [], str(aceitos))

    laudo = cli.post("/api/bridge/laudo", json={"pasta": base, "b": b}).json()
    checar(u"o laudo mostra o alerta, sem pedir decisao",
           any(a.get("alerta") for a in laudo["achados"]))


def teste_medida_da_grade():
    secao(u"a medida da grade: tempo, e requisicoes depois de pronta")
    try:
        from fastapi import FastAPI
    except Exception as e:
        checar(u"fastapi disponivel", False, str(e)[:60])
        return
    import time
    import radai_bridge
    import radai_dicom
    import radai_thumbnail

    N = 11
    base = novo_temp()
    for k in range(N):
        escrever_serie(os.path.join(base, "s%02d" % k), n=12, numero=k + 1,
                       descricao=u"CT %02d" % k, lado=256)
    radai_dicom.esquecer_varredura()

    cli = Cliente(radai_bridge.montar(FastAPI()))
    t0 = time.time()
    r = cli.post("/api/bridge/varrer", json={"pasta": base}).json()
    t_varrer = time.time() - t0
    series = r.get("series") or []
    checar(u"a varredura achou as %d series" % N, len(series) == N,
           str(len(series)))
    if len(series) != N:
        return

    t0 = time.time()
    primeira = None
    etags = []
    for i, ss in enumerate(series):
        resp = cli.get("/api/bridge/miniatura", params={"b": ss["bilhete"]})
        if i == 0:
            primeira = time.time() - t0
        etags.append(resp.headers.get("ETag"))
    t_grade = time.time() - t0

    print(u"         · varredura de %d series: %.2f s" % (N, t_varrer))
    print(u"         · primeira miniatura:     %.2f s  (alvo < 1,5)" % primeira)
    print(u"         · grade completa:         %.2f s  (alvo < 8)" % t_grade)

    checar(u"a primeira miniatura sai em menos de 5 s (%.2f s)" % primeira,
           primeira < 5.0, u"%.2f s" % primeira)
    checar(u"a grade de %d sai em menos de 30 s (%.2f s)" % (N, t_grade),
           t_grade < 30.0, u"%.2f s" % t_grade)

    contador = {"n": 0}
    original = radai_thumbnail.png_central

    def contando(b, lado=radai_thumbnail.LADO):
        contador["n"] += 1
        return original(b, lado)

    radai_thumbnail.png_central = contando
    try:
        time.sleep(0.4)
        checar(u"depois da grade pronta, ZERO requisicoes", contador["n"] == 0,
               str(contador["n"]))
    finally:
        radai_thumbnail.png_central = original

    t0 = time.time()
    origens = []
    for ss in series:
        rr = cli.get("/api/bridge/miniatura", params={"b": ss["bilhete"]})
        origens.append(rr.headers.get("X-RadAI-Origem"))
    t_reabrir = time.time() - t0
    print(u"         · grade reaberta:         %.2f s  (do cache)" % t_reabrir)
    checar(u"reabrir vem toda do cache em disco, sem decodificar DICOM",
           origens and all(o == "disco" for o in origens), str(origens[:3]))

    n304 = 0
    corpo = 0
    for ss, marca in zip(series, etags):
        resp = cli.get("/api/bridge/miniatura", params={"b": ss["bilhete"]},
                       headers={"If-None-Match": marca})
        if resp.status_code == 304:
            n304 += 1
        corpo += len(resp.content or b"")
    checar(u"as %d revalidacoes devolvem 304" % N, n304 == N, str(n304))
    checar(u"e nenhum byte de imagem viaja de novo", corpo == 0, str(corpo))


def teste_a_varredura_nao_abre_o_que_nao_e_dicom():
    secao(u"a varredura nao abre o que nao e DICOM")
    import radai_dicom as D

    base = novo_temp()

    def escrever(nome, dados):
        c = os.path.join(base, nome)
        with open(c, "wb") as f:
            f.write(dados)
        return c

    recusar = [
        (u"executavel (.dll/.exe)", "x.dll", b"MZ\x90\x00" + b"\x00" * 5000),
        (u"zip (estudo compactado)", "x.zip", b"PK\x03\x04" + b"\x00" * 5000),
        (u"PNG", "x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 500),
        (u"JSON", "x.json", b'{"uid": "1.2.3", "n": 4}'),
        (u"texto", "x.log", b"20:34 vigia iniciado\n" * 40),
    ]
    for rotulo, nome, dados in recusar:
        c = escrever(nome, dados)
        vale, porque = D.vale_abrir(c)
        checar(u"recusa %s" % rotulo, not vale, porque[:60])
        checar(u"e diz por que", bool(porque))

    com = escrever("com_preambulo.dcm", b"\x00" * 128 + b"DICM" + b"\x00" * 40)
    checar(u"aceita o preambulo DICM", D.vale_abrir(com)[0])

    for grupo, rotulo in ((b"\x02\x00", u"meta (0002)"),
                          (b"\x08\x00", u"identificacao (0008)")):
        cru = escrever("cru_%s.dcm" % rotulo[:4],
                       grupo + b"\x00\x00UL\x04\x00" + b"\x00" * 200)
        checar(u"aceita dataset cru, grupo %s" % rotulo,
               D.vale_abrir(cru)[0])

    escrever_serie(os.path.join(base, "serie"), n=2)
    real = os.path.join(base, "serie", "IM000.dcm")
    checar(u"aceita o DICOM que o pydicom escreve", D.vale_abrir(real)[0])

    D.esquecer_varredura()
    r = D.varrer(base)
    checar(u"acha a serie no meio do lixo", len(r["series"]) == 1,
           str(len(r["series"])))
    checar(u"e conta os recusados em `ignorados`",
           len(r["ignorados"]) >= len(recusar), str(len(r["ignorados"])))

    sem_ext = escrever("IM000001", b"\x00" * 128 + b"DICM" + b"\x00" * 40)
    checar(u"e DICOM sem extensao continua passando",
           D.vale_abrir(sem_ext)[0],
           u"os de CD vem assim")


def fonte_de(nome):
    return io.open(_componentes.fonte("app/" + nome), encoding="utf-8",
                   errors="replace").read()


def teste_a_tela_nao_detecta_nada():
    secao(u"a tela mostra, e nao aponta")
    f = fonte("radai_bridge.py")
    js = f[f.index("JS = u"):f.index("def pagina(")]
    for proibido in ("canvas", "getContext", "drawImage", "ctx.", "roi",
                     "detect", "score", "probabil", "suspeit", "nodul"):
        checar(u"o JS nao tem `%s`" % proibido, proibido not in js.lower())
    checar(u"a miniatura nao e desenhavel por cima",
           "<canvas" not in f.lower())
    checar(u"a imagem viaja por bilhete", "?b=' + encodeURIComponent" in f)
    checar(u"e nao ha `pasta=` em nenhuma URL de imagem",
           "pasta=" not in f)
    checar(u"a grade nao exibe nome de arquivo",
           ".dcm" not in f[f.index("function dcPintarGrade"):
                           f.index("function dcLigarCartao")])


def teste_cabecalho_http_e_ascii():
    secao(u"cabecalho HTTP em ASCII")
    import radai_bridge
    f = fonte("radai_bridge.py")
    checar(u"ha uma funcao que limpa o cabecalho", "def _cab(" in f)
    checar(u"e ela codifica em ASCII",
           'encode("ascii", "replace")' in f)
    for rota in ("_miniatura", "_corte"):
        corpo = f[f.index("def %s(" % rota):]
        corpo = corpo[:corpo.index("@app.")] if "@app." in corpo else corpo
        checar(u"`%s` passa tudo por `_cab`" % rota,
               "X-RadAI-Erro" not in corpo or "_cab(" in corpo)
    checar(u"o modulo importa", hasattr(radai_bridge, "montar"))


def teste_duas_series_no_mesmo_destino():
    secao(u"duas series no MESMO destino: recusa, e nao apaga a primeira")
    import radai_dicom

    base = novo_temp()
    escrever_serie(os.path.join(base, "a"), n=5, numero=1, descricao=u"CT A")
    escrever_serie(os.path.join(base, "b"), n=8, numero=2, descricao=u"CT B")
    achadas = radai_dicom.varrer(base)["series"]
    checar(u"duas series no fantoma", len(achadas) == 2, str(len(achadas)))
    if len(achadas) != 2:
        return
    pequena = min(achadas, key=lambda s: s["cortes"])
    grande = max(achadas, key=lambda s: s["cortes"])

    def dcm(d):
        return sorted(f for f in os.listdir(d) if f.lower().endswith(".dcm"))

    def uids(d):
        import pydicom
        fora = set()
        for f in dcm(d):
            try:
                x = pydicom.dcmread(os.path.join(d, f),
                                    stop_before_pixels=True, force=True)
                fora.add(str(getattr(x, "SeriesInstanceUID", "")))
            except Exception:
                pass
        return fora

    dest = os.path.join(base, "saidaA")
    r1 = radai_dicom.converter(pequena, dest,
                               laudo=radai_dicom.conferir(pequena))
    checar(u"a primeira converte", r1["cortes"] == pequena["cortes"],
           str(r1["cortes"]))
    try:
        radai_dicom.converter(grande, dest, laudo=radai_dicom.conferir(grande))
        checar(u"a segunda (MAIOR) e RECUSADA", False, u"passou")
    except radai_dicom.Recusa as e:
        checar(u"a segunda (MAIOR) e RECUSADA", True)
        checar(u"e a recusa diz que a pasta ja tem OUTRA serie",
               u"OUTRA serie" in str(e), str(e)[:70])
        checar(u"e diz o que fazer",
               u"pasta vazia" in str(e) or u"subpasta" in str(e),
               str(e)[-70:])
    checar(u"a PRIMEIRA continua inteira no disco",
           len(dcm(dest)) == pequena["cortes"],
           u"%d de %d" % (len(dcm(dest)), pequena["cortes"]))
    checar(u"e a pasta tem UMA serie so",
           len(uids(dest)) == 1, str(sorted(uids(dest))[:1]))

    dest2 = os.path.join(base, "saidaB")
    radai_dicom.converter(grande, dest2, laudo=radai_dicom.conferir(grande))
    try:
        radai_dicom.converter(pequena, dest2,
                              laudo=radai_dicom.conferir(pequena))
        checar(u"a segunda (MENOR) e RECUSADA", False, u"passou")
    except radai_dicom.Recusa:
        checar(u"a segunda (MENOR) e RECUSADA", True)
    checar(u"e nao sobrou pasta misturada",
           len(uids(dest2)) == 1 and len(dcm(dest2)) == grande["cortes"],
           u"%d arquivo(s), %d serie(s)" % (len(dcm(dest2)), len(uids(dest2))))

    import json
    cam = os.path.join(dest, "_RadAI", radai_dicom.NOME_RECIBO)
    rec = json.load(io.open(cam, encoding="utf-8")) if os.path.isfile(cam) else {}
    n = len(rec if isinstance(rec, list) else ((rec or {}).get("conversoes") or []))
    checar(u"o recibo tem UMA entrada, e nao duas", n == 1,
           u"%d entradas" % n)

    r2 = radai_dicom.converter(pequena, dest,
                               laudo=radai_dicom.conferir(pequena))
    checar(u"reconverter a MESMA serie continua passando",
           r2["cortes"] == pequena["cortes"], str(r2["cortes"]))
    checar(u"e a pasta segue com os arquivos certos",
           len(dcm(dest)) == pequena["cortes"] and len(uids(dest)) == 1,
           u"%d arquivo(s)" % len(dcm(dest)))

    import shutil
    shutil.copy(os.path.join(dest, dcm(dest)[0]),
                os.path.join(dest, "IM00099.dcm"))
    r3 = radai_dicom.converter(pequena, dest,
                               laudo=radai_dicom.conferir(pequena))
    checar(u"remanescente de execucao anterior nao entra na contagem",
           r3["cortes"] == pequena["cortes"] and len(dcm(dest)) == pequena["cortes"],
           u"%d no disco" % len(dcm(dest)))


def teste_destino_dentro_da_origem_e_recusado():
    secao(u"destino dentro da origem: recusado antes de gravar")
    import radai_dicom

    base = novo_temp()
    pasta = os.path.join(base, "estudo", "CT")
    escrever_serie(pasta, n=6)
    s0 = radai_dicom.varrer(base)["series"][0]
    n_antes = len([f for f in os.listdir(pasta) if f.lower().endswith(".dcm")])

    for rotulo, dest in ((u"a propria pasta", pasta),
                         (u"uma subpasta dela",
                          os.path.join(pasta, "convertida")),
                         (u"por `..`",
                          os.path.join(pasta, "x", "..", "conv"))):
        try:
            radai_dicom.converter(s0, dest,
                                  laudo=radai_dicom.conferir(s0))
            checar(u"destino %s e RECUSADO" % rotulo, False, u"passou")
        except radai_dicom.Recusa as e:
            checar(u"destino %s e RECUSADO" % rotulo, True)
            checar(u"e a recusa explica o UID preservado",
                   u"SeriesInstanceUID" in str(e), str(e)[:60])

    n_depois = len([f for f in os.listdir(pasta) if f.lower().endswith(".dcm")])
    checar(u"e a serie de origem ficou intacta", n_antes == n_depois,
           u"%d -> %d" % (n_antes, n_depois))

    r = radai_dicom.converter(s0, os.path.join(base, "saida"),
                              laudo=radai_dicom.conferir(s0))
    checar(u"destino fora da arvore continua passando",
           r["cortes"] == s0["cortes"], str(r["cortes"]))


def teste_indice_deslocado_nao_converte_outra_serie():
    secao(u"indice deslocado: o bilhete segura a serie certa")
    import radai_dicom
    import radai_thumbnail

    base = novo_temp()
    escrever_serie(os.path.join(base, "a"), n=6, numero=2, descricao=u"CT ABDOME")
    achadas = radai_dicom.varrer(base)["series"]
    checar(u"uma serie no comeco", len(achadas) == 1, str(len(achadas)))
    if not achadas:
        return
    alvo = achadas[0]
    b = radai_thumbnail.bilhete(base, alvo["uid"])
    indice_na_hora = 0

    escrever_serie(os.path.join(base, "b"), n=9, numero=1, descricao=u"CT TORAX")
    depois = radai_dicom.varrer(base)["series"]
    checar(u"agora sao duas", len(depois) == 2, str(len(depois)))
    checar(u"e o indice 0 passou a ser OUTRA serie",
           depois[indice_na_hora]["uid"] != alvo["uid"],
           u"o indice andou, como se esperava")

    _p, uid = radai_thumbnail.resolver(b)
    checar(u"o bilhete resolve para a serie de origem", uid == alvo["uid"])
    achada = [x for x in depois if x["uid"] == uid]
    checar(u"e ela e encontravel na varredura nova", len(achada) == 1)
    checar(u"com os cortes dela, e nao os da intrusa",
           achada and achada[0]["cortes"] == alvo["cortes"],
           u"%s contra %s" % (achada[0]["cortes"] if achada else "-",
                              alvo["cortes"]))

    fonte = io.open(_componentes.fonte("app/radai_bridge.py"),
                    encoding="utf-8", errors="replace").read()
    checar(u"`_serie` acha a serie SO pelo bilhete", u"def _serie(pasta, b):" in fonte)
    import radai_bridge as B
    checar(u"e nenhum pedido da tela manda indice", u"indice" not in B.JS)
    checar(u"o laudo manda o bilhete",
           u"{pasta: fonte, b: b}" in _corpo_js(B.JS, u"dcLerLaudo"))
    checar(u"e o visor do modal tambem",
           u"dcLerLaudo(s.bilhete || '')" in _corpo_js(B.JS, u"dcVisorModal"))
    corpo = fonte[fonte.index(u"def _serie(pasta, b):"):]
    corpo = corpo[:corpo.index(u"\n    def ", 10)]
    checar(u"bilhete que nao resolve NAO cai em outra serie",
           corpo.rstrip().endswith(u"return None"), corpo[-60:])


def teste_a_espessura_aparece_no_cartao():
    secao(u"a espessura aparece no cartao, e ela e MEDIDA")
    import radai_dicom

    base = novo_temp()
    escrever_serie(os.path.join(base, "fina"), n=8, numero=1,
                   descricao=u"CT TORAX")
    escrever_serie(os.path.join(base, "grossa"), n=8, numero=2,
                   descricao=u"CT TORAX")
    achadas = radai_dicom.varrer(base, relembrar=False)["series"]
    checar(u"duas series", len(achadas) == 2, str(len(achadas)))
    for s in achadas:
        checar(u"a serie ...%s traz espessura" % s["uid"][-6:],
               s.get("espessura_mm") is not None, str(s.get("espessura_mm")))
        checar(u"e ela e positiva",
               (s.get("espessura_mm") or 0) > 0, str(s.get("espessura_mm")))
        checar(u"e o declarado vem separado",
               "espessura_declarada_mm" in s,
               u"medido e declarado sao duas coisas")

    torto = os.path.join(base, "torto")
    escrever_serie(torto, n=9, passo=3.0, passo_torto=(4, 9.0),
                   descricao=u"CT PASSO TORTO")
    s = radai_dicom.varrer(torto, relembrar=False)["series"][0]
    checar(u"com um passo torto, a MEDIANA ignora o degrau",
           abs((s.get("espessura_mm") or 0) - 3.0) < 0.01,
           u"medida %s contra declarada %s"
           % (s.get("espessura_mm"), s.get("espessura_declarada_mm")))

    fonte = io.open(_componentes.fonte("app/radai_bridge.py"),
                    encoding="utf-8", errors="replace").read()
    checar(u"o cartao da grade escreve a espessura",
           u"s.espessura_mm" in fonte,
           u"sem isso, duas reconstrucoes ficam identicas na tela")
    checar(u"e com virgula decimal, como o resto da suite",
           u"replace('.', ',')" in fonte)


_RODA_JS = u"""
var CFG = {um: 'nada', modal: 'nada'};
RadaiUmEixo = function(cx, cfg){
 CFG.um = cfg.cranial;
 return {atual: 0, fechado: false, carga: null, fechar: function(){}};
};
window.uiVisor = function(o){
 CFG.modal = o.cranial;
 return {cabecalho: function(){}, fechar: function(){}};
};
DC.series = [{uid: 'x1', descricao: 'CT', modalidade: 'CT', cortes: 12, central: 6,
              bilhete: 'b_pes', cranial: -1}];
try{ dcVisorLigar(DC.series[0]); }catch(e){ CFG.erro_um = String(e); }
try{ dcVisorModal(0); }catch(e){ CFG.erro_modal = String(e); }
console.log('JSON:' + JSON.stringify(CFG));
"""


def teste_a_roda_vai_para_caudal():
    secao(u"a roda do mouse vai para caudal no pipeline e no visor modal")
    try:
        from fastapi import FastAPI
    except Exception as e:
        checar(u"fastapi disponivel", False, str(e)[:60])
        return
    import pydicom
    import radai_bridge
    import radai_dicom
    base = novo_temp()
    escrever_serie(os.path.join(base, "cabeca"), n=6, numero=1,
                   descricao=u"CT CABECA PRIMEIRO")
    pes = os.path.join(base, "pes")
    escrever_serie(pes, n=6, numero=2, descricao=u"CT PES PRIMEIRO")
    for nome in os.listdir(pes):
        f = os.path.join(pes, nome)
        ds = pydicom.dcmread(f)
        ds.ImageOrientationPatient = [-1, 0, 0, 0, 1, 0]
        ds.PatientPosition = "FFS"
        ds.save_as(f)
    radai_dicom.esquecer_varredura()
    cli = Cliente(radai_bridge.montar(FastAPI()))
    ss = cli.post("/api/bridge/varrer", json={"pasta": base}).json().get(
        "series") or []
    por = dict((s.get("descricao"), s.get("cranial")) for s in ss)
    checar(u"a varredura diz o sentido de cada serie: cabeca primeiro 1, pes "
           u"primeiro -1", por == {u"CT CABECA PRIMEIRO": 1,
                                   u"CT PES PRIMEIRO": -1}, str(por))

    res, erro = _rodar_tela(_RODA_JS)
    checar(u"a tela executa com os visores dublados", res is not None, erro)
    if res is None:
        return
    checar(u"o visor do pipeline (RadaiUmEixo) e o modal (uiVisor) recebem o "
           u"sentido da serie", res.get("um") == -1 and res.get("modal") == -1,
           json.dumps(res))
    js = radai_bridge.JS
    for trecho in (u"n: s.cortes, emVoo: 3, cranial: s.cranial,",
                   u"  cranial: s.cranial, janelas: jans,"):
        checar(u"  (a isca acha o trecho) %s" % trecho.strip()[:40],
               trecho in js)
        radai_bridge.JS = js.replace(trecho, trecho.replace(
            u"cranial: s.cranial,", u""))
        try:
            isca, _e = _rodar_tela(_RODA_JS)
        finally:
            radai_bridge.JS = js
        checar(u"  (isca) sem passar o sentido, o visor fica sem ele",
               isca is not None and (isca.get("um") != -1
                                     or isca.get("modal") != -1), str(isca))


def main():
    print(u"=" * 70)
    print(u"  test_bridge — a grade, os caches, o lote e o recibo")
    print(u"=" * 70)
    try:
        import pydicom
    except Exception as e:
        print(u"  pydicom ausente neste runtime (%s) — a bateria nao roda aqui"
              % type(e).__name__)
        print(u"OK: 0 checagens (runtime sem pydicom)")
        return 0

    testes = [teste_a_grade_nao_rola,
              teste_um_pedido_por_serie,
              teste_204_e_404_nao_viram_laco,
              teste_a_entrega_vai_pelo_bilhete,
              teste_a_imagem_no_pipeline_so_converte_ajustada,
              teste_o_cd_le_so_o_drive_de_cd,
              teste_nenhuma_tela_pergunta_sobre_o_texto_no_pixel,
              teste_o_contrato_da_fila,
              teste_varias_entregas_e_a_volta_a_tela,
              teste_o_diagnostico_le_todas_as_series,
              teste_o_brilho_do_visor_para_no_erro,
              teste_o_pipeline_abre_etapa_por_etapa,
              teste_clique_marca_duplo_abre,
              teste_cache_em_disco,
              teste_cache_da_varredura,
              teste_recibo_grava_o_que_se_decidiu,
              teste_recibo_nao_leva_a_descricao_da_serie,
              teste_recibo_nao_derruba_conversao,
              teste_recibo_ilegivel_nao_e_apagado,
              teste_lote_separa_as_series_em_subpastas,
              teste_duas_series_no_mesmo_destino,
              teste_a_espessura_aparece_no_cartao,
              teste_destino_dentro_da_origem_e_recusado,
              teste_indice_deslocado_nao_converte_outra_serie,
              teste_lote_nao_aceita_por_ninguem,
              teste_medida_da_grade,
              teste_a_varredura_nao_abre_o_que_nao_e_dicom,
              teste_a_tela_nao_detecta_nada,
              teste_cabecalho_http_e_ascii,
              teste_a_roda_vai_para_caudal]
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

    for d in _TEMPS:
        shutil.rmtree(d, ignore_errors=True)

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
