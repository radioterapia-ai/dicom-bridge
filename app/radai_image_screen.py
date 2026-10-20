# -*- coding: utf-8 -*-
import json
import os
import threading

import radai_image
import radai_web

POSICOES = (u"HFS", u"HFP", u"FFS", u"FFP")
TETO_PREVIA = 768
TETO_DE_PASTAS = 400
TETO_VOLUMES = 2
PASTA_DA_SERIE = u"IMAGEM"
INTERVALO_DO_MPR_MS = 450
SELO = u"JPEG/PNG"

_VOLUMES = {}
_TRAVA = threading.Lock()


def _esc(t):
    return (str(t if t is not None else u"").replace(u"&", u"&amp;")
            .replace(u"<", u"&lt;").replace(u">", u"&gt;")
            .replace(u'"', u"&quot;"))


def serie_do_bilhete(b):
    import radai_thumbnail
    pasta, chave = radai_thumbnail.resolver(b)
    if not pasta:
        return None, u""
    r = radai_image.varrer(pasta)
    for s in r["series"]:
        if s["chave"] == chave:
            return s, pasta
    return None, pasta


def ficha(pasta, s, b):
    desc = radai_image.descricao_sugerida(pasta, s["chave"])
    return {"bilhete": b, "chave": s["chave"], "descricao": desc, "n": s["n"],
            "matriz": u" / ".join(u"%dx%d" % d for d in s["dimensoes"]),
            "uniforme": s["uniforme"], "como_ordenou": s["como_ordenou"],
            "sugestoes": radai_image.sugestoes(s, desc)}


def series_da_arvore(pasta, teto=TETO_DE_PASTAS):
    import radai_dicom
    import radai_thumbnail
    fora, vistas, ignorados = [], 0, 0
    for raiz, dirs, arqs in os.walk(pasta):
        dirs[:] = sorted(d for d in dirs if not radai_dicom.pasta_pulada(d))
        vistas += 1
        if vistas > teto:
            break
        if not any(a.lower().endswith(radai_image.EXTENSOES) for a in arqs):
            continue
        r = radai_image.varrer(raiz)
        ignorados += len([n for n, _m in r["ignorados"]
                          if str(n).lower().endswith(radai_image.EXTENSOES)])
        for s in r["series"]:
            fora.append(ficha(raiz, s, radai_thumbnail.bilhete(raiz, s["chave"])))
    return fora, ignorados


def para_a_grade(f):
    return {"imagem": True, "bilhete": f["bilhete"], "descricao": f["descricao"],
            "modalidade": SELO, "cortes": f["n"], "n": f["n"],
            "matriz": f["matriz"], "uniforme": f["uniforme"],
            "como_ordenou": f["como_ordenou"], "sugestoes": f["sugestoes"]}


def geometria_do_pedido(c):
    g = dict(c.get("geometria") or {})
    esp = g.get("espacamento_mm") or [0, 0]
    try:
        er, ec = float(esp[0] or 0), float(esp[1] or 0)
    except Exception:
        er = ec = 0.0

    def _f(nome):
        try:
            return float(g.get(nome) or 0)
        except Exception:
            return 0.0
    fora = {"espacamento_mm": (er, ec) if (er > 0 and ec > 0) else None,
            "espessura_mm": _f("espessura_mm") if _f("espessura_mm") > 0 else None,
            "orientacao": str(g.get("orientacao") or "") or None,
            "posicao_paciente": str(g.get("posicao_paciente") or "") or None,
            "primeiro_corte_mm": _f("primeiro_corte_mm")}
    entre = _f("entre_cortes_mm")
    if entre > 0:
        fora["entre_cortes_mm"] = entre
    return fora


def converter_do_pedido(s, destino, c):
    c = dict(c or {})
    return radai_image.converter(
        s, destino, geometria_do_pedido(c),
        modalidade=str(c.get("modalidade") or "MR"),
        como=str(c.get("como") or "sc"),
        descricao=str(c.get("descricao") or ""),
        aceitar=list(c.get("aceitar") or ()),
        quem=str(c.get("quem") or ""))


def _volume(b):
    s, _pasta = serie_do_bilhete(b)
    if s is None:
        return None, None, None
    arqs = s.get("arquivos") or []
    try:
        assinatura = (len(arqs), os.path.getmtime(arqs[0]["caminho"]),
                      os.path.getmtime(arqs[-1]["caminho"]))
    except Exception:
        assinatura = (len(arqs),)
    with _TRAVA:
        guardado = _VOLUMES.get(b)
    if guardado and guardado[0] == assinatura:
        return s, guardado[1], guardado[2]
    vol, passo = radai_image.volume(s)
    with _TRAVA:
        _VOLUMES.pop(b, None)
        _VOLUMES[b] = (assinatura, vol, passo)
        while len(_VOLUMES) > TETO_VOLUMES:
            _VOLUMES.pop(next(iter(_VOLUMES)), None)
    return s, vol, passo


CSS = u"""
.im-ajuste{display:grid;grid-template-columns:minmax(260px,.9fr) minmax(0,1.3fr);gap:18px;
 align-items:start}
.dc-diag-serie .im-ajuste{grid-template-columns:1fr}
@media (max-width:960px){.im-ajuste{grid-template-columns:1fr}}
.im-campos{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
@media (max-width:620px){.im-campos{grid-template-columns:1fr}}
.im-campo.largo{grid-column:1/-1}
.im-campo label{display:block;font-size:11.5px;color:var(--text-dim);margin-bottom:3px}
.im-campo label b{color:var(--perigo);font-weight:700}
.im-campo input,.im-campo select{width:100%;box-sizing:border-box;
 padding:7px 9px;border-radius:var(--r-md);border:1px solid var(--line-strong);
 background:var(--panel-2);color:var(--text);font-size:12.5px}
.im-campo input:focus,.im-campo select:focus{outline:none;border-color:var(--accent)}
.im-campo input.vazio{border-color:var(--perigo)}
.im-nota{display:block;font-size:11px;line-height:1.45;color:var(--text-dim);margin-top:3px}
.im-mais{grid-column:1/-1;margin-top:2px}
.im-mais summary{cursor:pointer;font-size:12px;color:var(--text-muted)}
.im-mais .im-campos{margin-top:9px}
.im-visor{max-width:440px}
.im-mpr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:12px 0 0}
.im-mpr figure{margin:0}
.im-mpr-q{position:relative;background:#000;border-radius:var(--r-md);min-height:140px;
 display:flex;align-items:center;justify-content:center;overflow:hidden}
.im-mpr-q img{max-width:100%;max-height:300px;display:block;image-rendering:auto}
.im-mpr figcaption{font:600 10.5px/1.3 var(--font-mono);letter-spacing:.06em;
 text-transform:uppercase;color:var(--text-dim);margin-top:5px}
.im-conf{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0 0}
.im-conf .ui-bt[aria-pressed="true"]{border-color:var(--success);color:var(--success)}
.im-conf .ui-bt[hidden]{display:none}
#im_laudo{margin-top:14px}
.im-frame{margin:10px 0 0}
"""

JS = u"""
var IM = {estado: {}, atual: null, visor: null, mprTimer: null};
var IM_INTERVALO = __INTERVALO__;
var IM_PLANOS = __PLANOS__;
var IM_CAMPOS = ['im_desc', 'im_mod', 'im_ori', 'im_esp', 'im_esc', 'im_pos', 'im_entre', 'im_z0', 'im_como'];
var IM_COBRANCA = {esp: ['im_esp', 'informe a espessura do corte'],
                   esc: ['im_esc', 'informe a escala'],
                   escala: ['im_conf_escala', 'confirme a escala ao lado do MPR'],
                   ordem: ['im_conf_ordem', 'confirme a ordem dos cortes ao lado do MPR'],
                   ori: ['im_ori', 'escolha a orientação']};

function imVal(id){ return String(((bgEl(id) || {}).value || '')).trim() }
function imNumDe(t){
 var v = parseFloat(String(t == null ? '' : t).trim().replace(',', '.'));
 return (isNaN(v) || v <= 0) ? 0 : v;
}
function imNum(id){ return imNumDe(imVal(id)) }
function imPor(t){ return String(t).replace('.', ',') }
function imNovoEstado(s){
 var g = s.sugestoes || {};
 return {im_desc: s.descricao || '', im_mod: g.modalidade || 'MR', im_ori: g.orientacao || '',
         im_esp: g.espessura_mm ? imPor(g.espessura_mm) : '',
         im_esc: g.espacamento_mm ? imPor(g.espacamento_mm) : '',
         im_pos: 'HFS', im_entre: '', im_z0: '0', im_como: 'sc',
         escala: false, ordem: false, oriManual: false, decidiveis: []};
}
function imEstado(s){
 if(!s || !s.bilhete) return null;
 return IM.estado[s.bilhete] || (IM.estado[s.bilhete] = imNovoEstado(s));
}
function imFecharVisor(){
 if(IM.visor){ try{ IM.visor.fechar() }catch(e){} }
 IM.visor = null;
 if(IM.mprTimer){ clearTimeout(IM.mprTimer); IM.mprTimer = null }
}
function imEsquecer(){ imFecharVisor(); IM.estado = {}; IM.atual = null }
function imAbrir(s){
 imFecharVisor();
 IM.atual = s;
 var e = imEstado(s); if(!e) return;
 IM_CAMPOS.forEach(function(id){ var el = bgEl(id); if(el) el.value = e[id] });
 var esp = bgEl('im_esp'); if(esp) esp.classList.toggle('vazio', !imNumDe(e.im_esp));
 bgMsg('im_aviso', '', '');
 imNotaOrientacao();
 imNotaEscala();
 imPintarConfirmacoes();
 imVisor(s);
 imMpr();
 imLaudo();
}
function imGuardar(){
 var e = imEstado(IM.atual); if(!e) return null;
 IM_CAMPOS.forEach(function(id){ var el = bgEl(id); if(el) e[id] = String(el.value == null ? '' : el.value) });
 return e;
}
function imNotaEscala(){
 var s = IM.atual, g = (s && s.sugestoes) || {};
 bgTexto(bgEl('im_esc_nota'), g.espacamento_mm
   ? ('sugerida para um campo de ' + imPor(g.fov_mm) + ' mm em ' + s.matriz + ' pixels: confira no MPR')
   : 'informe a escala');
}
function imNotaOrientacao(){
 var n = bgEl('im_ori_nota'), e = imEstado(IM.atual); if(!n || !e) return;
 var v = imVal('im_ori');
 bgTexto(n, e.oriManual ? '' : (v ? 'tirada da descrição da série: confira'
   : 'a descrição não diz a orientação: escolha'));
}
function imDescricaoMudou(){
 var e = imEstado(IM.atual); if(!e) return;
 if(!e.oriManual){
  var o = imOrientacaoDe(imVal('im_desc'));
  if(o) bgEl('im_ori').value = o;
 }
 imMudou(true);
 imNotaOrientacao();
}
function imOrientacaoDe(t){
 var p = String(t || '').toLowerCase().normalize('NFD').replace(/[^a-z0-9]+/g, ' ').split(' ');
 var achadas = {};
 p.forEach(function(x){
  if(['axial','ax','axi','tra','trans','transversal','transverse','transverso'].indexOf(x) >= 0) achadas.axial = 1;
  if(['coronal','cor','coro'].indexOf(x) >= 0) achadas.coronal = 1;
  if(['sagital','sagittal','sag'].indexOf(x) >= 0) achadas.sagital = 1;
 });
 var k = Object.keys(achadas);
 return k.length === 1 ? k[0] : '';
}
function imOrientacaoMudou(){
 var e = imEstado(IM.atual); if(e) e.oriManual = true;
 imMudou(true);
 imNotaOrientacao();
}
function imEscalaMudou(){
 var e = imEstado(IM.atual); if(e) e.escala = false;
 imMudou(true);
 imPintarConfirmacoes();
}
function imMudou(mpr){
 var e = imGuardar(); if(!e) return;
 var esp = bgEl('im_esp'); if(esp) esp.classList.toggle('vazio', !imNumDe(e.im_esp));
 bgMsg('im_aviso', '', '');
 if(typeof dcImagemMudou === 'function') dcImagemMudou(IM.atual);
 if(mpr){
  if(IM.mprTimer) clearTimeout(IM.mprTimer);
  IM.mprTimer = setTimeout(imMpr, IM_INTERVALO);
 }
 imLaudo();
}
function imGeometriaDe(e){
 var esc = imNumDe(e.im_esc);
 return {espacamento_mm: [esc, esc], espessura_mm: imNumDe(e.im_esp),
         entre_cortes_mm: imNumDe(e.im_entre),
         primeiro_corte_mm: parseFloat(String(e.im_z0 || '').replace(',', '.')) || 0,
         orientacao: e.im_ori || '', posicao_paciente: e.im_pos || ''};
}
function imAceitosDe(e){ return e.ordem ? (e.decidiveis || []).slice() : [] }
function imPedido(s){
 var e = imEstado(s); if(!e) return null;
 return {geometria: imGeometriaDe(e), descricao: e.im_desc || '', modalidade: e.im_mod || 'MR',
         como: e.im_como || 'sc', aceitar: imAceitosDe(e)};
}
function imFalta(s){
 var e = imEstado(s); if(!e) return 'esp';
 if(!imNumDe(e.im_esp)) return 'esp';
 if(!imNumDe(e.im_esc)) return 'esc';
 if(!e.escala) return 'escala';
 if((e.decidiveis || []).length && !e.ordem) return 'ordem';
 if(!e.im_ori) return 'ori';
 return '';
}
function imCobrar(falta){
 var c = IM_COBRANCA[falta]; if(!c) return;
 if(falta === 'esp'){ var esp = bgEl('im_esp'); if(esp) esp.classList.add('vazio') }
 bgMsg('im_aviso', c[1], 'erro');
 bgTremer(bgEl(c[0]));
}
function imVisor(s){
 var cx = bgEl('im_visor'); if(!cx || !window.RadaiUmEixo) return;
 var b = s.bilhete;
 bgMsg('im_visor_msg', '', '');
 var url = function(k){ return '/api/imagem/previa?b=' + encodeURIComponent(b) + '&k=' + k };
 IM.visor = RadaiUmEixo(cx, {n: s.n, emVoo: 3, inicio: Math.floor(s.n / 2), url: url,
  aoParar: function(st){
   try{ bgBrilho(cx.querySelector('.ue-visor'), false) }catch(e){}
   imVisorFalhou(s, url, st);
  }});
 bgVigiarVisor(cx, IM.visor, function(){ imVisorFalhou(s, url, 0) });
}
function imVisorFalhou(s, url, st){
 if(IM.atual !== s) return;
 if(st === 404){ bgMsg('im_visor_msg', 'recarregue a pasta', 'erro'); return }
 fetch(url(Math.floor(s.n / 2))).then(function(r){
  if(IM.atual !== s || r.status === 200) return;
  var m = '';
  try{ m = decodeURIComponent(r.headers.get('X-RadAI-Motivo') || '') }catch(e){ m = '' }
  bgErro('im_visor_msg', 'não consegui abrir as imagens', m || ('HTTP ' + r.status));
 }).catch(function(e){ if(IM.atual === s) bgErro('im_visor_msg', 'não consegui abrir as imagens', e) });
}
function imMpr(){
 var s = IM.atual, e = imEstado(s); if(!s || !e) return;
 var g = imGeometriaDe(e), ori = g.orientacao || 'axial';
 var planos = IM_PLANOS[ori] || IM_PLANOS.axial;
 ['linha', 'coluna'].forEach(function(corte){
  var q = bgEl('im_mpr_' + corte), rot = bgEl('im_mpr_' + corte + '_rot');
  if(!q) return;
  bgTexto(rot, planos[corte]);
  var esc = g.espacamento_mm[0], entre = g.entre_cortes_mm || g.espessura_mm;
  if(!esc || !entre || s.n < 2){
   q.innerHTML = '<span class="pp-sub">' + bgF(s.n < 2 ? 'uma imagem só: sem MPR'
     : 'informe a escala e a espessura para ver o MPR') + '</span>';
   bgTrad();
   return;
  }
  var img = document.createElement('img');
  img.alt = '';
  bgBrilho(q, true, 'reconstruindo');
  img.onload = function(){ bgBrilho(q, false) };
  img.onerror = function(){ bgBrilho(q, false); q.innerHTML = '<span class="pp-sub">'
    + bgF('não consegui reconstruir o MPR') + '</span>'; bgTrad() };
  var antigo = q.querySelector('img');
  if(antigo) q.replaceChild(img, antigo); else { q.innerHTML = ''; q.appendChild(img) }
  img.src = '/api/imagem/mpr?b=' + encodeURIComponent(s.bilhete) + '&corte=' + corte
    + '&er=' + esc + '&ec=' + esc + '&entre=' + entre + '&ori=' + encodeURIComponent(ori);
 });
}
function imConfirmarEscala(){
 var e = imEstado(IM.atual); if(!e) return;
 if(!imNum('im_esc')){ bgTremer(bgEl('im_esc')); return }
 e.escala = !e.escala;
 bgMsg('im_aviso', '', '');
 imPintarConfirmacoes();
 if(typeof dcImagemLaudo === 'function') dcImagemLaudo(IM.atual, null);
}
function imConfirmarOrdem(){
 var e = imEstado(IM.atual); if(!e) return;
 e.ordem = !e.ordem;
 bgMsg('im_aviso', '', '');
 imPintarConfirmacoes();
 imLaudo();
}
function imPintarConfirmacoes(){
 var st = imEstado(IM.atual) || {};
 var e = bgEl('im_conf_escala'), o = bgEl('im_conf_ordem');
 if(e) e.setAttribute('aria-pressed', st.escala ? 'true' : 'false');
 if(o){
  o.hidden = !(st.decidiveis || []).length;
  o.setAttribute('aria-pressed', st.ordem ? 'true' : 'false');
 }
}
function imLerLaudo(s){
 var e = imEstado(s); if(!e) return Promise.resolve(null);
 return bgPost('/api/imagem/laudo', {b: s.bilhete, geometria: imGeometriaDe(e), aceitar: imAceitosDe(e)})
  .then(function(d){
   if(d && !d.erro) e.decidiveis = d.decidiveis || [];
   return d;
  });
}
function imLaudo(){
 var s = IM.atual; if(!s) return;
 imLerLaudo(s).then(function(d){
  if(!d) return;
  if(typeof dcImagemLaudo === 'function') dcImagemLaudo(s, d);
  if(IM.atual !== s) return;
  if(d.erro){ bgHTML(bgEl('im_laudo'), '<p class="bg-nao">' + bgEsc(d.erro) + '</p>'); return }
  imPintarConfirmacoes();
  imPintarLaudo(d);
 }).catch(function(){});
}
function imPintarLaudo(d){
 var st = imEstado(IM.atual) || {};
 var h = '', todos = d.achados || [], dec = d.decidiveis || [];
 todos.forEach(function(a){
  if(a.ok) return;
  if(a.alerta){
   h += '<div class="dc-falta decide"><span class="marca">' + bgF('alerta') + '</span>'
     + '<span class="tt">' + bgEsc(a.titulo) + '</span>'
     + (a.detalhe ? '<div class="dd">' + bgEsc(a.detalhe) + '</div>' : '') + '</div>';
  } else if(a.resolve === false && dec.indexOf(a.titulo) >= 0){
   h += '<div class="dc-falta ' + (st.ordem ? 'bom' : 'decide') + '"><span class="marca">'
     + bgF(st.ordem ? 'confirmada' : 'confirme') + '</span>'
     + '<span class="tt">' + bgEsc(a.titulo) + '</span>'
     + (a.detalhe ? '<div class="dd">' + bgEsc(a.detalhe) + '</div>' : '')
     + (a.o_que_faz ? '<div class="faz">' + bgEsc(a.o_que_faz) + '</div>' : '') + '</div>';
  } else if(a.resolve === false){
   h += '<div class="dc-falta ruim"><span class="marca">' + bgF('falta informar') + '</span>'
     + '<span class="tt">' + bgEsc(a.titulo) + '</span>'
     + (a.detalhe ? '<div class="dd">' + bgEsc(a.detalhe) + '</div>' : '')
     + (a.o_que_faz ? '<div class="faz">' + bgEsc(a.o_que_faz) + '</div>' : '') + '</div>';
  }
 });
 bgHTML(bgEl('im_laudo'), h);
}
"""

JS = (JS.replace(u"__INTERVALO__", str(int(INTERVALO_DO_MPR_MS)))
      .replace(u"__PLANOS__", json.dumps(radai_image.PLANOS_DO_MPR,
                                         ensure_ascii=False)))


def _opcoes(valores, rotulos=None):
    return u"".join(u'<option value="%s">%s</option>'
                    % (_esc(v), _esc((rotulos or {}).get(v, v))) for v in valores)


def _campo(ident, rotulo, controle, nota=u"", largo=False, obrigatorio=False):
    return (u'<div class="im-campo%s"><label for="%s"><span data-radai-frase>%s'
            u'</span>%s</label>%s%s</div>'
            % (u" largo" if largo else u"", ident, rotulo,
               u" <b>*</b>" if obrigatorio else u"", controle,
               (u'<span class="im-nota" id="%s_nota">%s</span>' % (ident, nota))
               if nota is not None else u""))


NOTA_DO_FRAME = (u"A série que nasce de JPEG ou PNG tem Frame of Reference "
                 u"próprio e não carrega Hounsfield")

AJUDA_NO_PIPELINE = (
    u"Um JPEG não guarda milímetro por pixel, espessura nem orientação. A "
    u"escala e a espessura vêm sugeridas, e a orientação sai da descrição da "
    u"série («RM t2 axial» é axial): confira. A espessura é obrigatória, e a "
    u"escala se confirma num clique, olhando o MPR — escala errada põe na "
    u"fusão uma imagem do tamanho errado, e o registro rígido não corrige "
    u"tamanho.",
    u"A imagem não diz de quem é: a série sai como paciente DESCONHECIDO, com "
    u"um ID gerado (EXTERNO com a data, a hora e um sufixo aleatório curto), "
    u"e a pasta de entrega leva um LEIA-ME.txt. Atribua ao paciente certo no "
    u"TPS: ele pode criar paciente novo ou associar à pessoa errada.",
    u"Texto do visualizador gravado na imagem não é recortado: recortar "
    u"mudaria a geometria da fusão. Fica um alerta. Com uma imagem só não dá "
    u"para conferir, e o alerta diz isso.")


def ajuste():
    texto = (u'<input type="text" id="%s" %s>')
    campos = (
        _campo(u"im_desc", u"descrição da série",
               texto % (u"im_desc", u'spellcheck="false" '
                        u'oninput="imDescricaoMudou()"'), nota=None, largo=True)
        + _campo(u"im_mod", u"modalidade",
                 u'<select id="im_mod" onchange="imMudou()">%s</select>'
                 % _opcoes((u"MR", u"CT")), nota=None)
        + _campo(u"im_ori", u"orientação",
                 u'<select id="im_ori" onchange="imOrientacaoMudou()">'
                 u'<option value=""></option>%s</select>'
                 % _opcoes(sorted(radai_image.ORIENTACOES)), nota=u"")
        + _campo(u"im_esp", u"espessura do corte (mm)",
                 texto % (u"im_esp", u'inputmode="decimal" required '
                          u'aria-required="true" oninput="imEscalaMudou()"'),
                 nota=None, obrigatorio=True)
        + _campo(u"im_esc", u"escala (mm por pixel)",
                 texto % (u"im_esc", u'inputmode="decimal" '
                          u'oninput="imEscalaMudou()"'), nota=u"")
        + _campo(u"im_pos", u"posição do paciente",
                 u'<select id="im_pos" onchange="imMudou()">%s</select>'
                 % _opcoes(POSICOES), nota=None)
        + u'<details class="im-mais"><summary data-radai-frase>mais ajustes'
          u'</summary><div class="im-campos">'
        + _campo(u"im_entre", u"distância entre cortes (mm)",
                 texto % (u"im_entre", u'inputmode="decimal" '
                          u'placeholder="igual à espessura" '
                          u'oninput="imEscalaMudou()"'), nota=None)
        + _campo(u"im_z0", u"posição do primeiro corte (mm)",
                 texto % (u"im_z0", u'inputmode="decimal" value="0" '
                          u'oninput="imMudou()"'), nota=None)
        + _campo(u"im_como", u"como gravar",
                 u'<select id="im_como" onchange="imMudou()">%s</select>'
                 % _opcoes((u"sc", u"modalidade"),
                           {u"sc": u"Secondary Capture",
                            u"modalidade": u"Série da modalidade"}), nota=None)
        + u'</div></details>')
    ver = (
        u'<div class="im-ver">'
        u'<div class="im-visor dc-visor" id="im_visor"></div>'
        u'<div id="im_visor_msg" class="bg-msg" role="status" '
        u'aria-live="polite"></div>'
        u'<div class="im-mpr">'
        u'<figure><div class="im-mpr-q" id="im_mpr_linha"></div>'
        u'<figcaption id="im_mpr_linha_rot"></figcaption></figure>'
        u'<figure><div class="im-mpr-q" id="im_mpr_coluna"></div>'
        u'<figcaption id="im_mpr_coluna_rot"></figcaption></figure></div>'
        u'<p class="pp-sub" data-radai-frase>O MPR mostra se a escala e a '
        u'espessura deformam a anatomia: com a escala errada, o que é redondo '
        u'sai achatado ou esticado.</p>'
        u'<div class="im-conf">'
        u'<button type="button" class="ui-bt" id="im_conf_escala" '
        u'aria-pressed="false" onclick="imConfirmarEscala()"><span '
        u'data-radai-frase>Confirmo a escala</span></button>'
        u'<button type="button" class="ui-bt" id="im_conf_ordem" hidden '
        u'aria-pressed="false" onclick="imConfirmarOrdem()"><span '
        u'data-radai-frase>Confirmo a ordem dos cortes</span></button>'
        u'</div></div>')
    return (u'<div class="im-ajuste"><div class="im-campos">%s</div>%s</div>'
            u'<div id="im_aviso" class="bg-msg" role="status" aria-live="polite">'
            u'</div><div id="im_laudo"></div>'
            u'<p class="pp-sub im-frame" data-radai-frase>%s</p>'
            % (campos, ver, NOTA_DO_FRAME))


def montar(app):
    from fastapi import Request
    from fastapi.responses import Response

    @app.post("/api/imagem/laudo")
    async def _laudo(request: Request):
        try:
            c = await request.json() or {}
            b = str(c.get("b") or "")
            s, _pasta = await radai_web.no_threadpool(serie_do_bilhete, b)
            if s is None:
                return {"erro": u"série não encontrada — carregue a pasta de novo"}
            laudo = await radai_web.no_threadpool(
                radai_image.conferir, s, geometria_do_pedido(c))
            return {"achados": laudo["achados"],
                    "pode_converter": laudo["pode_converter"],
                    "decidiveis": sorted(radai_image.decidiveis(s))}
        except Exception as e:
            return {"erro": u"%s: %s" % (type(e).__name__, str(e)[:200])}

    @app.get("/api/imagem/previa")
    def _previa(b: str = "", k: int = -1):
        try:
            s, _pasta = serie_do_bilhete(b)
            arqs = (s or {}).get("arquivos") or []
            if not arqs:
                return Response(status_code=404, content=b"")
            ki = int(k) if 0 <= int(k) < len(arqs) else len(arqs) // 2
            try:
                px = radai_image.ler_cinza(arqs[ki]["caminho"])
            except radai_image.Recusa as r:
                from urllib.parse import quote
                return Response(status_code=422, headers={
                    "X-RadAI-Erro": "Recusa",
                    "X-RadAI-Motivo": quote(str(r)[:300], safe="")})
            passo = max(1, int(max(px.shape) // TETO_PREVIA))
            if passo > 1:
                px = px[::passo, ::passo]
            import radai_recon3d
            return Response(content=radai_recon3d.para_png(px, 128, 256),
                            media_type="image/png",
                            headers={"Cache-Control": "no-store",
                                     "X-RadAI-Corte": str(ki),
                                     "X-RadAI-Cortes": str(len(arqs))})
        except Exception as e:
            return Response(status_code=500,
                            headers={"X-RadAI-Erro": type(e).__name__,
                                     "X-RadAI-Motivo": type(e).__name__})

    @app.get("/api/imagem/mpr")
    def _mpr(b: str = "", corte: str = "linha", er: float = 0.0,
             ec: float = 0.0, entre: float = 0.0, ori: str = "axial"):
        try:
            s, vol, passo = _volume(b)
            if s is None:
                return Response(status_code=404, content=b"")
            if vol.shape[0] < 2:
                return Response(status_code=422, content=b"")
            px = radai_image.mpr(vol, passo, "coluna" if corte == "coluna"
                                 else "linha", er, ec, entre, ori)
            import radai_recon3d
            return Response(content=radai_recon3d.para_png(px, 128, 256),
                            media_type="image/png",
                            headers={"Cache-Control": "no-store",
                                     "X-RadAI-Linhas": str(px.shape[0]),
                                     "X-RadAI-Colunas": str(px.shape[1])})
        except radai_image.Recusa:
            return Response(status_code=422, content=b"")
        except Exception as e:
            return Response(status_code=500,
                            headers={"X-RadAI-Erro": type(e).__name__})

    return app
