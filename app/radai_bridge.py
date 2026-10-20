# -*- coding: utf-8 -*-
import json
import os
import secrets
import threading
import time

import radai_bridge_entrada as _E
import radai_image_screen
import radai_menu
import radai_viewer
import radai_web

ROTA_DA_FILA = u"/api/fila/enfileirar"
ROTA_DO_ESTADO_DA_FILA = u"/api/fila/estado"
ROTA_DAS_OPCOES = u"/api/lote/opcoes"
ROTA_DE_REPOR = u"/api/fila/repor"
ORIGEM_NA_FILA = u"dicombridge"


def _teto_da_fila(padrao=8):
    try:
        import radai_queue_state
        return int(getattr(radai_queue_state, "TETO_DE_COPIAS", padrao))
    except Exception:
        return padrao


TETO_DE_COPIAS_DO_RTSTRUCT = _teto_da_fila()
FRASE_DO_TETO = (u"A segmentação copia o RTSTRUCT para no máximo %d outros "
                 u"destinos: tire destinos, ou entregue sem segmentação."
                 % TETO_DE_COPIAS_DO_RTSTRUCT)
MODOS_DE_SEGMENTACAO = (("nenhuma", u"nenhuma"), ("fast", u"FAST"),
                        ("auto", u"AUTO"), ("personalizado", u"PERSONALIZADO"))
MODALIDADES_QUE_SEGMENTAM = ("CT", "MR")
INTERVALO_DA_FILA_MS = 5000
CHAVE_DA_SESSAO = u"radai_bridge_fila"

CSS_COMUM = u"""
.dc-wrap{max-width:1180px;margin:0 auto;padding:0 20px 40px;box-sizing:border-box}
.dc-wrap .ui-fn{--ui-fn-cor:var(--mod-bridge);--ui-fn-fraco:var(--mod-bridge-fraco)}
.pp-etapa{background:var(--panel);border:1px solid var(--line);
 border-radius:var(--r-2xl);padding:16px 18px;margin:14px 0 0;scroll-margin-top:72px}
.pp-etapa[hidden]{display:none}
.pp-cab{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px}
.pp-cab h2{font:600 11.5px/1 var(--font-mono);letter-spacing:.08em;
 text-transform:uppercase;color:var(--text-dim);margin:0;display:flex;
 align-items:center;gap:9px}
.pp-cab h2 .n{display:grid;place-items:center;width:22px;height:22px;
 border-radius:var(--r-md);background:var(--mod-bridge-fraco);color:var(--mod-bridge);
 font-size:11.5px;flex:0 0 auto}
.pp-dir{margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pp-acoes{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px;
 padding-top:14px;border-top:1px solid var(--line)}
.pp-acoes .ui-bt{padding:9px 16px}
.pp-sub{font-size:12px;color:var(--text-dim)}
.pp-vazio{font-size:12.5px;line-height:1.55;color:var(--text-dim);margin:6px 0 0}
.bg-carga{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);
 gap:16px;align-items:stretch}
.bg-carga .ui-envio{min-height:160px;height:100%;box-sizing:border-box}
.bg-carga-pasta{display:flex;flex-direction:column;justify-content:center;gap:10px}
.bg-carga-rot{font-size:12.5px;color:var(--text-muted);margin:0}
.bg-carga-linha{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.bg-carga-linha input[type=text]{flex:1 1 220px;min-width:0;height:36px;
 padding:0 11px;font-size:12.5px}
.bg-carga-linha .ui-bt{height:36px;box-sizing:border-box;white-space:nowrap}
@media (max-width:900px){.bg-carga{grid-template-columns:1fr}}
.ui-bt.bg-limpar{border-color:var(--mod-bridge);background:var(--mod-bridge-fraco);
 color:var(--text);font-weight:650}
.ui-bt.bg-limpar:hover:not(:disabled){background:var(--panel-2)}
.bg-msg{min-height:19px;font-size:12.5px;line-height:1.5;color:var(--text-muted);
 margin:10px 0 0}
.bg-msg b{color:var(--text)}
.bg-msg.erro{color:var(--perigo)}
.bg-msg.ok{color:var(--success)}
.bg-rot{font:600 11px/1 var(--font-mono);letter-spacing:.08em;text-transform:uppercase;
 color:var(--text-dim);margin:0 0 8px}
.bg-dest-lista{list-style:none;margin:0 0 8px;padding:0;display:flex;
 flex-direction:column;gap:6px}
.bg-dest{display:flex;align-items:center;gap:8px;padding:7px 9px;
 border:1px solid var(--line-strong);border-radius:var(--r-md);background:var(--panel-2);
 min-width:0}
.bg-dest .ui-ic{color:var(--mod-bridge);margin:0;flex:0 0 auto}
.bg-dest code{flex:1 1 auto;min-width:0;font:400 11.5px/1.3 var(--font-mono);
 color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
 direction:rtl;text-align:left}
.bg-dest-x{display:grid;place-items:center;width:24px;height:24px;padding:0;
 border-radius:var(--r-sm);border:1px solid transparent;background:transparent;
 color:var(--text-dim);cursor:pointer;flex:0 0 auto}
.bg-dest-x:hover{color:var(--perigo);border-color:var(--line-strong)}
.bg-dest-x .ui-ic{margin:0}
.bg-dest-bts{display:flex;gap:8px;flex-wrap:wrap}
.bg-dest-bts .ui-bt{padding:7px 11px}
.bg-dest-bts .ui-bt[hidden]{display:none}
.bg-saida{font-size:12.5px;line-height:1.6;color:var(--text-muted);margin:12px 0 0}
.bg-saida b{color:var(--text)}
.bg-saida code{font:400 11.5px/1.4 var(--font-mono);color:var(--text);
 overflow-wrap:anywhere;word-break:break-all}
.bg-saida ul{margin:4px 0 0;padding-left:18px}
.bg-nao{color:var(--perigo)}
"""

CSS = u"""
.dc-ferr{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dc-ferr .ui-bt{padding:7px 12px}
.dc-cont{font-size:12.5px;color:var(--text-muted);white-space:nowrap}
.dc-cont b{color:var(--text)}
.dc-grade{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.dc-cart{position:relative;padding:8px;border-radius:var(--r-lg);background:var(--panel-2);
 border:1px solid var(--line);cursor:pointer;min-width:0;
 transition:border-color .14s,background-color .14s,transform .12s}
.dc-cart:hover{border-color:var(--line-strong)}
.dc-cart:active{transform:translateY(1px)}
.dc-cart:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.dc-cart.marc{border-color:var(--mod-bridge);background:var(--mod-bridge-fraco)}
.dc-cart.fora{cursor:default;opacity:.7}
.dc-x{position:absolute;right:13px;top:13px;z-index:3;display:none;place-items:center;
 width:24px;height:24px;padding:0;border-radius:50%;border:0;cursor:pointer;
 background:rgba(0,0,0,.62);color:rgb(230,237,247);font-size:19px;line-height:1}
.dc-x:hover{background:rgba(0,0,0,.82)}
.dc-x .ui-ic{margin:0}
.dc-cart.marc .dc-x{display:grid}
.dc-mini{position:relative;width:100%;aspect-ratio:1/1;background:#000;
 border-radius:var(--r-md);overflow:hidden;display:flex;align-items:center;
 justify-content:center}
.dc-mini img{width:100%;height:100%;object-fit:contain;display:block;user-select:none}
.dc-mini.sem-img::after{content:attr(data-mod);color:var(--text-dim);
 font-family:var(--font-mono);font-size:13px;letter-spacing:.08em}
.dc-mini.sem-img{background:#0b0f18;border:1px dashed var(--line)}
.dc-mini.sem-img img{display:none}
.dc-grade > .pp-vazio{grid-column:1/-1}
.dc-selos{position:absolute;left:6px;bottom:6px;display:flex;gap:4px;flex-wrap:wrap;z-index:2}
.dc-selo{font:600 9.5px/1 var(--font-mono);letter-spacing:.06em;padding:3px 6px;
 border-radius:var(--r-pill);background:rgba(0,0,0,.7);color:rgb(230,237,247);
 border:1px solid rgba(255,255,255,.18)}
.dc-cart .tt{font-size:12px;font-weight:600;line-height:1.3;margin-top:8px;
 color:var(--text);overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;
 -webkit-box-orient:vertical;overflow-wrap:anywhere;min-height:2.6em}
.dc-cart .mm{font:400 11px/1.4 var(--font-mono);color:var(--text-dim);margin-top:2px;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dc-cd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 0 0;
 padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-lg);
 background:var(--panel-2);font-size:12.5px;color:var(--text-muted)}
.dc-cd[hidden]{display:none}
.dc-cd b{color:var(--text)}
.dc-cd .ui-bt{padding:7px 12px}
.dc-cd .ui-bt[hidden]{display:none}
.dc-cd-txt{flex:1 1 260px;min-width:0}
.dc-marcadas{margin:16px 0 0;display:flex;flex-direction:column;gap:8px}
.dc-mrow{border:1px solid var(--line);border-radius:var(--r-lg);background:var(--panel-2);
 padding:9px 12px}
.dc-mrow-cab{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.dc-mrow-nome{font-size:12.5px;color:var(--text);flex:1 1 220px;min-width:0;
 overflow-wrap:anywhere}
.dc-mrow-nome .mod{font-family:var(--font-mono);color:var(--text-muted);margin-right:6px}
.dc-seg{display:inline-flex;border:1px solid var(--line-strong);border-radius:var(--r-pill);
 overflow:hidden;flex:0 0 auto}
.dc-seg button{border:0;background:transparent;color:var(--text-muted);
 font:600 11.5px/1 var(--font-display);padding:7px 11px;cursor:pointer}
.dc-seg button + button{border-left:1px solid var(--line)}
.dc-seg button[aria-pressed="true"]{background:var(--mod-bridge-fraco);color:var(--text)}
.dc-seg button:disabled{opacity:.45;cursor:not-allowed}
.dc-seg-nao{font-size:11.5px;color:var(--text-dim)}
.dc-tasks{margin:10px 0 2px;display:grid;gap:6px 14px;
 grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
.dc-task{display:flex;gap:8px;align-items:flex-start;font-size:12px;color:var(--text);
 cursor:pointer}
.dc-task input{accent-color:var(--mod-bridge);margin:2px 0 0;flex:0 0 auto}
.dc-task small{color:var(--warn);font-family:var(--font-mono);font-size:10px;margin-left:4px}
.dc-tasks-nota{grid-column:1/-1;font-size:11.5px;color:var(--text-dim)}
.dc-diag{display:grid;grid-template-columns:minmax(220px,.8fr) minmax(0,1.4fr);gap:16px;
 align-items:start}
@media (max-width:900px){.dc-diag{grid-template-columns:1fr}}
.dc-diag-lista{display:flex;flex-direction:column;gap:6px}
.dc-diag-item{display:flex;align-items:center;gap:8px;text-align:left;width:100%;
 border:1px solid var(--line);border-radius:var(--r-md);background:var(--panel-2);
 padding:8px 10px;color:var(--text);font-size:12.5px;cursor:pointer}
.dc-diag-item[aria-current="true"]{border-color:var(--mod-bridge);background:var(--mod-bridge-fraco)}
.dc-diag-item .mod{font-family:var(--font-mono);color:var(--text-muted)}
.dc-diag-item .nome{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}
.dc-diag-item .al{font:600 11px/1 var(--font-mono);color:var(--warn);white-space:nowrap}
.dc-diag-item .al.zero{color:var(--success)}
.dc-titulo{font:650 16px/1.3 var(--font-display);margin:0 0 10px;color:var(--text);
 overflow-wrap:anywhere}
.dc-visor{max-width:520px}
.dc-visor .ue-visor.sem-img{background:#0b0f18;border-style:dashed}
.dc-visor .ue-visor.sem-img::after{content:attr(data-mod);position:absolute;
 left:0;right:0;top:0;bottom:0;display:flex;align-items:center;
 justify-content:center;color:var(--text-dim);pointer-events:none;
 font-family:var(--font-mono);font-size:13px;letter-spacing:.08em}
.dc-janelas{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:9px 0 4px}
.dc-jan{font-size:11.5px;padding:4px 9px;border-radius:var(--r-md);cursor:pointer;
 border:1px solid var(--line-strong);background:var(--panel-2);color:var(--text-muted)}
.dc-jan.sel{border-color:var(--accent);background:var(--accent-fraco);color:var(--text)}
.dc-jan[hidden]{display:none}
#dc_laudo{margin-top:12px}
.dc-falta{border-radius:var(--r-lg);padding:9px 12px;margin-bottom:7px;
 border:1px solid var(--line);background:var(--panel-2)}
.dc-falta.decide{border-color:var(--borda-aviso);background:var(--fundo-aviso)}
.dc-falta.ruim{border-color:var(--borda-perigo);background:var(--fundo-perigo)}
.dc-falta.bom{border-color:var(--borda-ok);background:var(--fundo-ok)}
.dc-falta .tt{display:block;font-size:12.5px;font-weight:600;color:var(--text)}
.dc-falta .dd{font-size:12px;color:var(--text-muted);margin-top:3px;line-height:1.55}
.dc-falta .faz{font-size:12px;margin-top:6px;padding-left:10px;color:var(--text-muted);
 border-left:2px solid var(--line-strong);line-height:1.55}
.dc-falta .marca{display:block;font:600 10px/1.2 var(--font-mono);letter-spacing:.08em;
 text-transform:uppercase;margin:0 0 4px}
.dc-falta.decide .marca{color:var(--warn)}
.dc-falta.ruim .marca{color:var(--perigo)}
.dc-tab{width:100%;border-collapse:collapse;font-size:12.5px}
.dc-tab td{padding:6px 8px;border-bottom:1px solid var(--line)}
.dc-tab td.mod{font-family:var(--font-mono);color:var(--text-muted)}
.dc-tab td.al{color:var(--warn);white-space:nowrap}
.dc-tab td.al .ui-ic{margin:0 4px 0 0}
.dc-filas{display:flex;flex-direction:column;gap:10px}
.dc-fila{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:14px 16px;
 border-radius:var(--r-lg);border:1px solid var(--mod-bridge);background:var(--mod-bridge-fraco)}
.dc-fila p{margin:0;flex:1 1 280px;font-size:13px;color:var(--text);line-height:1.5}
.dc-fila .det{display:block;font-size:12px;color:var(--text-muted);margin-top:3px}
.dc-fila .dc-fila-nome{display:block;font:400 11px/1.4 var(--font-mono);color:var(--text-dim);
 margin:0 0 2px;overflow-wrap:anywhere}
.dc-fila.falha{border-color:var(--borda-perigo);background:var(--fundo-perigo)}
.dc-fila.pronta{border-color:var(--borda-ok);background:var(--fundo-ok)}
.dc-fila.meia{border-color:var(--borda-aviso);background:var(--fundo-aviso)}
.dc-fila .ui-bt{padding:8px 14px}
.dc-fila-x{display:grid;place-items:center;width:26px;height:26px;padding:0;margin-left:auto;
 border-radius:var(--r-sm);border:1px solid transparent;background:transparent;
 color:var(--text-dim);cursor:pointer;flex:0 0 auto}
.dc-fila-x:hover{color:var(--text);border-color:var(--line-strong)}
.dc-fila-x .ui-ic{margin:0}
.dc-outras{margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}
.dc-outras[hidden]{display:none}
.dc-outra{font-size:12px;line-height:1.55;color:var(--text-muted);margin:0 0 6px}
.dc-outra-nome{border:0;background:transparent;padding:0;margin:0 8px 0 0;cursor:pointer;
 color:var(--text);font:600 12px/1.4 var(--font-display);text-decoration:underline;
 text-decoration-color:var(--line-strong);text-underline-offset:3px}
.dc-outra-nome .mod{font-family:var(--font-mono);color:var(--text-muted);margin-right:6px}
.dc-outra .ok{color:var(--success)}
@media (prefers-reduced-motion:reduce){.dc-cart{transition:none}}
"""

JS_COMUM = u"""
var BG = {destinos: [], origem: ''};
function bgEsc(t){
 return String(t == null ? '' : t).replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function bgEl(id){ return document.getElementById(id) }
function bgTrad(){ try{ if(window.radaiRetraduzir) window.radaiRetraduzir() }catch(e){} }
function bgIco(nome){ var t = bgEl('ui-ico-' + nome); return (t && t.innerHTML) || '' }
function bgF(t){ return '<span data-radai-frase>' + bgEsc(t) + '</span>' }
function bgTexto(el, t){
 if(!el) return;
 if(window.uiTexto) window.uiTexto(el, t); else el.textContent = t;
 bgTrad();
}
function bgHTML(el, h){
 if(!el) return;
 if(window.uiHTML) window.uiHTML(el, h); else el.innerHTML = h;
 bgTrad();
}
function bgMsg(id, t, cls){
 var e = bgEl(id); if(!e) return;
 bgTexto(e, t); e.className = 'bg-msg' + (cls ? ' ' + cls : '');
}
function bgMsgHTML(id, h, cls){
 var e = bgEl(id); if(!e) return;
 bgHTML(e, h); e.className = 'bg-msg' + (cls ? ' ' + cls : '');
}
function bgErro(id, frase, det){
 bgMsgHTML(id, bgF(frase) + (det ? ' <code>' + bgEsc(det) + '</code>' : ''), 'erro');
}
function bgPost(url, corpo){
 return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify(corpo || {})})
  .then(function(r){ return r.json() });
}
function bgMovimento(){
 try{ return !window.matchMedia('(prefers-reduced-motion: reduce)').matches }
 catch(e){ return true }
}
function bgRolar(el){
 if(!el) return;
 try{ el.scrollIntoView({block:'start', behavior: bgMovimento() ? 'smooth' : 'auto'}) }
 catch(e){}
}
function bgTremer(el){
 if(!el) return;
 if(typeof window.uiTremer === 'function'){ try{ window.uiTremer(el); return }catch(e){} }
 try{ el.scrollIntoView({block:'center', behavior: bgMovimento() ? 'smooth' : 'auto'}) }
 catch(e){}
 try{ el.focus({preventScroll: true}) }catch(e){ try{ el.focus() }catch(x){} }
}
function bgBrilho(alvo, ligado, texto){
 try{ if(alvo && window.uiCarregando) window.uiCarregando(alvo, ligado, texto || '') }
 catch(e){}
}
function bgPintarDestinos(){
 var ul = bgEl('bg_dest_lista');
 if(ul){
  ul.innerHTML = BG.destinos.map(function(c, k){
   return '<li class="bg-dest">' + bgIco('pasta') + '<code title="' + bgEsc(c) + '">'
    + bgEsc(c) + '</code>'
    + (BG.destinos.length > 1 ? '<button type="button" class="bg-dest-x" title="tirar este destino"'
       + ' aria-label="tirar este destino" onclick="bgTirarDestino(' + k + ')">'
       + bgIco('fechar') + '</button>' : '')
    + '</li>';
  }).join('');
 }
 var o = bgEl('bg_dest_origem');
 if(o) o.hidden = !BG.origem || BG.destinos.indexOf(BG.origem) >= 0;
 bgTrad();
 if(typeof window.bgAoMudarDestinos === 'function') window.bgAoMudarDestinos();
}
function bgAdicionarDestino(bt){
 if(!window.uiExplorador) return;
 window.uiExplorador({origem: bt, titulo: 'Escolher a pasta', inicial: BG.destinos[0] || '',
  aoUsar: function(c){
   c = String(c || '').trim();
   if(c && BG.destinos.indexOf(c) < 0){ BG.destinos.push(c); bgPintarDestinos() }
  }});
}
function bgAdicionarOrigem(){
 if(BG.origem && BG.destinos.indexOf(BG.origem) < 0){ BG.destinos.push(BG.origem); bgPintarDestinos() }
}
function bgTirarDestino(k){
 if(BG.destinos.length > 1){ BG.destinos.splice(k, 1); bgPintarDestinos() }
}
function bgDestinosIniciais(){
 fetch('/api/bridge/destinos').then(function(r){ return r.json() }).then(function(d){
  if(d && d.downloads && !BG.destinos.length){ BG.destinos = [d.downloads]; bgPintarDestinos() }
 }).catch(function(){});
}
function bgLigarEnvio(id, aoPasta, aoErro){
 var z = bgEl(id);
 if(!z || !window.uiEnvio) return;
 window.uiEnvio(z, {url: '/api/bridge/receber', fim: '/api/bridge/receber/fim',
  pedacos: true, pagina: true, sessao: '',
  aoTerminar: function(resps){
   var d = resps[resps.length - 1] || {};
   if(d.pasta) aoPasta(d.pasta);
  },
  aoErro: aoErro});
}
function bgEsquecerEnvio(id){
 var z = bgEl(id);
 var ses = z && z._uiEnvio ? z._uiEnvio.sessao : '';
 if(ses){
  bgPost('/api/bridge/limpar', {sessao: ses}).catch(function(){});
  z._uiEnvio.sessao = '';
 }
 if(z){
  var st = z.querySelector ? z.querySelector('.ui-envio-est') : null;
  if(st) st.textContent = '';
  z.classList.remove('erro');
 }
}
function bgSaida(d){
 var h = '';
 (d.saidas || []).forEach(function(o){ h += '<li><code>' + bgEsc(o.pasta) + '</code></li>' });
 return h ? '<ul>' + h + '</ul>' : '';
}
function bgFalhas(d){
 var f = (d && d.falhas) || [];
 if(!f.length) return '';
 return '<div class="bg-saida bg-nao" id="bg_falhas">' + bgF('não chegou a estes destinos:')
  + '<ul>' + f.map(function(x){
     return '<li><code>' + bgEsc(x.destino) + '</code> &mdash; ' + bgEsc(x.motivo) + '</li>';
    }).join('') + '</ul></div>';
}
function bgVigiarVisor(cx, visor, aoFalhar){
 var ue = (cx && cx.querySelector) ? cx.querySelector('.ue-visor') : null;
 var im = (cx && cx.querySelector) ? cx.querySelector('.ue-img') : null;
 if(!ue || !visor) return;
 bgBrilho(ue, true, 'abrindo a série');
 var t = null;
 var parar = function(){
  if(t){ clearInterval(t); t = null }
  bgBrilho(ue, false);
  try{ if(im && im.removeEventListener) im.removeEventListener('load', parar) }catch(e){}
 };
 try{ if(im && im.addEventListener) im.addEventListener('load', parar) }catch(e){}
 // GUARDA: o visor só avisa 204 e 404; com 500 em todo corte, o brilho ficaria para sempre.
 t = setInterval(function(){
  var c = visor.carga || {};
  if(visor.fechado || c.parado){ parar(); return }
  if((c.nProntos | 0) > 0){ clearInterval(t); t = null; return }
  if((c.nFalhos | 0) >= Math.min(Math.max(visor.n | 0, 1), 3)){
   parar();
   if(aoFalhar) aoFalhar();
  }
 }, 300);
}
"""

JS = u"""
var DC = {series: [], imagens: [], marcadas: {}, seg: {}, fonte: '', laudos: {},
          lendo: {}, laudoErro: {},
          sel: null, nav: [], janela: 'mediastino', visor: null, visorSerie: null,
          cliqueTimer: null, filaMini: [], rodando: 0, etapa: 1, conversao: '',
          exportadas: [], entregue: null, filas: [], filaTimer: null, filaTique: 0,
          filaRodando: null, filaHtml: null, opcoes: {}, cd: null, cdDrives: [], cdTimer: null};
var DC_CONCORRENCIA = 2;
var DC_INTERVALO_CD = __INTERVALO_CD__;
var DC_MODOS = __MODOS__;
var DC_SEGMENTAM = __SEGMENTAM__;
var DC_ROTA_FILA = '__ROTA_FILA__';
var DC_ROTA_ESTADO = '__ROTA_ESTADO__';
var DC_ROTA_OPCOES = '__ROTA_OPCOES__';
var DC_ROTA_REPOR = '__ROTA_REPOR__';
var DC_ROTA_GUARDAR = '/api/bridge/fila/guardar';
var DC_ROTA_CONFERIR = '/api/bridge/fila/conferir';
var DC_ROTA_DE_NOVO = '/api/bridge/fila/de_novo';
var DC_ORIGEM = '__ORIGEM__';
var DC_INTERVALO = __INTERVALO__;
var DC_SESSAO = '__SESSAO__';
var DC_TETO_COPIAS = __TETO_COPIAS__;
var DC_FRASE_DO_TETO = __FRASE_DO_TETO__;
var DC_LENTO = 12;
var DC_ASSENTAR = 2;
var DC_ESPERA = ['esperando', 'pulado', 'rodando', 'conferindo'];
var DC_TERMINA = ['pronto', 'parcial', 'falhou', 'cancelado', 'incerto'];
var DC_SAIU_PRONTO = 'o cartão saiu da fila; o RTSTRUCT está ao lado da série';
var DC_SAIU_SEM_RS = 'o cartão saiu da fila sem o RTSTRUCT';
var DC_SEM_GUARDA = 'esta estação não guarda mais esta entrega: refaça a entrega para segmentar';

function dcNome(s){ return (s && s.descricao) || ('série ' + ((s && s.numero) || '?')) }
function dcMm(v){ return Number(v).toFixed(2).replace('.', ',') + ' mm' }
function dcMeta(s){
 return bgEsc(s.modalidade) + ' &middot; ' + s.cortes
   + (s.espessura_mm ? ' &middot; ' + bgEsc(dcMm(s.espessura_mm)) : '');
}
function dcSelos(s){
 var h = '';
 if(s.colorida) h += '<span class="dc-selo" data-radai-frase>COLORIDA</span>';
 if(s.captura) h += '<span class="dc-selo" data-radai-frase>CAPTURA</span>';
 return h ? '<span class="dc-selos">' + h + '</span>' : '';
}
function dcMiniUrl(s){
 if(!s || !s.bilhete) return '';
 return s.imagem ? '/api/imagem/previa?b=' + encodeURIComponent(s.bilhete) + '&k=-1'
   : '/api/bridge/miniatura?b=' + encodeURIComponent(s.bilhete);
}
function dcPorBilhete(b){
 for(var i = 0; i < DC.series.length; i++) if(DC.series[i].bilhete === b) return i;
 return -1;
}

function dcEtapa(n, rolar){
 DC.etapa = n;
 for(var k = 2; k <= 6; k++){
  var e = bgEl('dc_e' + k);
  // GUARDA: o cartão da fila fica à vista até o RTSTRUCT chegar, mesmo com escolha nova.
  if(e) e.hidden = k > n && !(k === 6 && DC.filas.length);
 }
 if(rolar) bgRolar(bgEl('dc_e' + n));
 dcPintarBarra();
}
function dcVoltarA(n){
 if(DC.etapa <= n) return;
 if(DC.conversao){ bgPost('/api/bridge/etapa/descartar', {conversao: DC.conversao}).catch(function(){}) }
 DC.conversao = ''; DC.exportadas = []; DC.entregue = null;
 if(n < 4) bgHTML(bgEl('dc_conv'), '');
 if(n < 5) bgHTML(bgEl('dc_ent'), '');
 dcEtapa(n);
}

function dcVarrer(){
 var p = ((bgEl('dc_pasta') || {}).value || '').trim();
 if(!p){ bgMsg('dc_msg', 'informe a pasta do estudo', 'erro'); bgTremer(bgEl('dc_pasta')); return }
 dcCarregar(p);
}
function dcCarregar(pasta, leitura){
 DC.fonte = pasta;
 dcZerar();
 bgMsg('dc_msg', 'lendo os cabeçalhos…', '');
 var pedido = {pasta: pasta};
 if(leitura) pedido.leitura = leitura;
 bgPost('/api/bridge/varrer', pedido).then(function(d){
  if(d.erro){ DC.series = []; dcPintarGrade(); bgMsg('dc_msg', d.erro, 'erro'); return }
  DC.imagens = d.imagens || [];
  DC.series = (d.series || []).concat(DC.imagens);
  BG.origem = d.origem || '';
  dcPintarGrade();
  bgPintarDestinos();
  var ign = (d.ignorados || []).length, ni = DC.imagens.length;
  bgMsgHTML('dc_msg', '<b>' + (d.series || []).length + '</b> ' + bgF('série(s)')
    + (ni ? ' &middot; <b>' + ni + '</b> ' + bgF(ni === 1 ? 'série de imagem (JPEG ou PNG) nesta pasta'
       : 'séries de imagem (JPEG ou PNG) nesta pasta') : '')
    + (ign ? ' &middot; <b>' + ign + '</b> ' + bgF('arquivo(s) ignorado(s)') : ''), 'ok');
  dcEtapa(2, true);
 }).catch(function(e){ bgErro('dc_msg', 'não consegui varrer', e) });
}
function dcProcurar(bt){
 if(!window.uiExplorador) return;
 window.uiExplorador({origem: bt, titulo: 'Escolher a pasta',
  inicial: ((bgEl('dc_pasta') || {}).value || '').trim(),
  aoUsar: function(c){ if(!c) return; bgEl('dc_pasta').value = c; dcCarregar(c) }});
}

function dcCdMostrar(h, comParar){
 var c = bgEl('dc_cd'); if(!c) return;
 c.hidden = !h;
 bgHTML(bgEl('dc_cd_txt'), h || '');
 var pb = bgEl('dc_cd_parar');
 if(pb){ pb.hidden = !comParar; pb.disabled = false }
}
function dcCd(){
 if(DC.cd && !DC.cd.fim) return;
 dcCdMostrar('');
 bgMsg('dc_msg', 'procurando o CD…', '');
 bgPost('/api/bridge/cd/drives', {}).then(function(d){
  var ds = (d && d.drives) || [];
  DC.cdDrives = ds;
  if(d && d.erro){ bgErro('dc_msg', 'não consegui ler o CD', d.erro); return }
  if(!ds.length){ bgMsg('dc_msg', 'nenhum CD na unidade: ponha o disco e clique de novo', 'erro'); return }
  if(ds.length === 1){ dcCdLer(0); return }
  bgMsg('dc_msg', '', '');
  dcCdMostrar(bgF('há mais de um CD: escolha qual ler') + ' ' + ds.map(function(x, k){
   return '<button type="button" class="ui-bt dc-cd-op" onclick="dcCdLer(' + k + ')"><code>'
     + bgEsc(x) + '</code></button>';
  }).join(' '), false);
 }).catch(function(e){ bgErro('dc_msg', 'não consegui ler o CD', e) });
}
function dcCdLer(k){
 var drive = (DC.cdDrives || [])[k]; if(!drive) return;
 var cd = {drive: drive, leitura: '', fim: false};
 DC.cd = cd;
 bgMsg('dc_msg', '', '');
 dcCdMostrar(bgF('lendo o CD') + ' <code>' + bgEsc(drive) + '</code>', true);
 var cdb = bgEl('dc_cd_bt'); if(cdb) cdb.disabled = true;
 bgPost('/api/bridge/cd/ler', {drive: drive}).then(function(d){
  if(DC.cd !== cd) return;
  if(!d || d.erro || !d.leitura){ dcCdFim(); bgErro('dc_msg', 'não consegui ler o CD', (d && d.erro) || '?'); return }
  cd.leitura = d.leitura;
  if(cd.parar) dcCdParar();
  dcCdVigiar();
 }).catch(function(e){ if(DC.cd === cd){ dcCdFim(); bgErro('dc_msg', 'não consegui ler o CD', e) } });
}
function dcCdVigiar(){
 if(DC.cdTimer) clearTimeout(DC.cdTimer);
 DC.cdTimer = setTimeout(dcCdConsultar, DC_INTERVALO_CD);
}
function dcCdConsultar(){
 DC.cdTimer = null;
 var cd = DC.cd; if(!cd || !cd.leitura || cd.fim) return;
 bgPost('/api/bridge/cd/estado', {leitura: cd.leitura}).then(function(d){
  if(DC.cd !== cd) return;
  if(!d || !('fim' in d)){ dcCdFim(); bgErro('dc_msg', 'não consegui ler o CD', (d && d.erro) || '?'); return }
  dcCdMostrar(bgF('lendo o CD') + ' <code>' + bgEsc(cd.drive) + '</code> &middot; <b>' + (d.pastas | 0)
    + '</b> ' + bgF('pastas') + ' &middot; <b>' + (d.arquivos | 0) + '</b> ' + bgF('arquivos')
    + ' &middot; <b>' + (d.series | 0) + '</b> ' + bgF('série(s)'), true);
  if(cd.parar){ var pb = bgEl('dc_cd_parar'); if(pb) pb.disabled = true }
  if(!d.fim){ dcCdVigiar(); return }
  dcCdFim();
  if(d.parado){ bgMsg('dc_msg', 'leitura do CD cancelada', ''); return }
  if(d.erro){ bgErro('dc_msg', 'não consegui ler o CD', d.erro); return }
  var p = bgEl('dc_pasta'); if(p) p.value = cd.drive;
  dcCarregar(cd.drive, cd.leitura);
 }).catch(function(){ if(DC.cd === cd) dcCdVigiar() });
}
function dcCdFim(){
 if(DC.cdTimer){ clearTimeout(DC.cdTimer); DC.cdTimer = null }
 if(DC.cd) DC.cd.fim = true;
 dcCdMostrar('');
 var cdb = bgEl('dc_cd_bt'); if(cdb) cdb.disabled = false;
}
function dcCdParar(){
 var cd = DC.cd; if(!cd || cd.fim) return;
 cd.parar = true;
 var pb = bgEl('dc_cd_parar'); if(pb) pb.disabled = true;
 if(cd.leitura) bgPost('/api/bridge/cd/parar', {leitura: cd.leitura}).catch(function(){});
}
function dcCdEsquecer(){
 dcCdParar();
 DC.cd = null;
 dcCdFim();
}
function dcZerar(){
 dcVoltarA(1);
 DC.marcadas = {}; DC.seg = {}; DC.laudos = {}; DC.lendo = {}; DC.laudoErro = {};
 DC.sel = null; DC.nav = [];
 DC.filaMini = [];
 dcVisorFechar();
 imEsquecer();
 dcPintarMarcadas();
}
function dcLimparTudo(){
 bgEsquecerEnvio('dc_envio');
 dcCdEsquecer();
 var p = bgEl('dc_pasta'); if(p) p.value = '';
 DC.series = []; DC.imagens = []; DC.fonte = ''; BG.origem = '';
 dcZerar();
 dcPintarGrade();
 bgPintarDestinos();
 bgMsg('dc_msg', '', '');
 dcEtapa(1);
}

function dcMarcadas(){
 return Object.keys(DC.marcadas).map(function(k){ return k|0 })
        .sort(function(a,b){ return a-b });
}
function dcMarcavel(s){ return !!(s && s.bilhete && !s.sem_imagem) }
function dcPintarBarra(){
 var m = dcMarcadas();
 var cont = bgEl('dc_cont');
 if(cont){
  bgHTML(cont, m.length
    ? ('<b>' + m.length + '</b> ' + bgF(m.length === 1 ? 'série marcada' : 'séries marcadas'))
    : bgF('nenhuma série marcada'));
 }
 var n = DC.series.filter(dcMarcavel).length;
 var bt = bgEl('dc_marcar_todas'); if(bt) bt.disabled = !n || m.length >= n;
 bt = bgEl('dc_limpar_marc'); if(bt) bt.disabled = !m.length;
 bt = bgEl('dc_avancar'); if(bt) bt.disabled = !m.length;
 bt = bgEl('dc_converter'); if(bt) bt.disabled = !m.length || !!DC.conversao || dcLaudosPendentes();
 bt = bgEl('dc_entregar'); if(bt) bt.disabled = !DC.conversao || !BG.destinos.length || !!DC.entregue;
 var fr = bgEl('dc_fronteira'); if(fr) fr.hidden = !dcPedeSegmentacao();
}
window.bgAoMudarDestinos = dcPintarBarra;

function dcPintarGrade(){
 var alvo = bgEl('dc_grade');
 DC.filaMini = [];
 if(!alvo) return;
 if(!DC.series.length){
  alvo.innerHTML = '<p class="pp-vazio">' + bgF(DC.fonte ? 'nenhuma série DICOM nesta pasta'
    : 'as séries do estudo aparecem aqui') + '</p>';
  dcPintarBarra();
  bgTrad();
  return;
 }
 alvo.innerHTML = DC.series.map(function(s, i){
  var fora = !dcMarcavel(s);
  return '<div class="dc-cart' + (fora ? ' fora' : '') + '" id="dcs' + i + '" tabindex="0" role="button"'
   + ' aria-pressed="false" aria-label="' + bgEsc(dcNome(s)) + '">'
   + '<button type="button" class="dc-x" tabindex="-1" title="desmarcar"'
   + ' aria-label="desmarcar">' + bgIco('desmarcar') + '</button>'
   + '<div class="dc-mini" id="dcm' + i + '"><img id="dci' + i + '" alt="" draggable="false">'
   + dcSelos(s) + '</div>'
   + '<div class="tt">' + bgEsc(dcNome(s)) + '</div>'
   + '<div class="mm" id="dcmm' + i + '">' + dcMeta(s) + '</div></div>';
 }).join('');
 DC.series.forEach(function(s, i){
  var c = bgEl('dcs' + i);
  if(c) dcLigarCartao(c, i);
  if(s.bilhete && !s.sem_imagem) dcEnfileirarMini(i, s);
  else dcSemPrevia(i, s.modalidade || '');
 });
 dcPintarBarra();
 bgTrad();
}
function dcLigarCartao(c, i){
 c.addEventListener('click', function(){
  if(DC.cliqueTimer){ clearTimeout(DC.cliqueTimer); DC.cliqueTimer = null }
  DC.cliqueTimer = setTimeout(function(){
   DC.cliqueTimer = null; dcMarcar(i);
  }, 250);
 });
 c.addEventListener('dblclick', function(){
  if(DC.cliqueTimer){ clearTimeout(DC.cliqueTimer); DC.cliqueTimer = null }
  dcVisorModal(i);
 });
 c.addEventListener('keydown', function(ev){
  if(ev.target !== c) return;
  if(ev.key === 'Enter'){ ev.preventDefault(); dcVisorModal(i) }
  else if(ev.key === ' ' || ev.key === 'Spacebar'){ ev.preventDefault(); dcMarcar(i) }
 });
 var x = c.querySelector ? c.querySelector('.dc-x') : null;
 if(x) x.addEventListener('click', function(ev){
  ev.stopPropagation();
  if(DC.marcadas[i]) dcMarcar(i);
 });
}
function dcPintarMarca(i){
 var on = !!DC.marcadas[i];
 var c = bgEl('dcs' + i);
 if(c){ c.classList.toggle('marc', on); c.setAttribute('aria-pressed', on ? 'true' : 'false') }
}
function dcMarcar(i){
 var s = DC.series[i]; if(!dcMarcavel(s)) return;
 if(DC.marcadas[i]) delete DC.marcadas[i];
 else{
  DC.marcadas[i] = true;
  if(!DC.seg[s.bilhete]) DC.seg[s.bilhete] = {modo: 'nenhuma', chaves: {}};
 }
 dcPintarMarca(i);
 dcMudouEscolha();
}
function dcMarcarTodas(){
 DC.series.forEach(function(s, i){
  if(dcMarcavel(s) && !DC.marcadas[i]){
   DC.marcadas[i] = true;
   if(!DC.seg[s.bilhete]) DC.seg[s.bilhete] = {modo: 'nenhuma', chaves: {}};
   dcPintarMarca(i);
  }
 });
 dcMudouEscolha();
}
function dcLimparMarcacao(){
 Object.keys(DC.marcadas).forEach(function(k){ delete DC.marcadas[k]; dcPintarMarca(k|0) });
 dcMudouEscolha();
}
function dcMudouEscolha(){
 dcVoltarA(2);
 dcPintarMarcadas();
 dcPintarBarra();
}

function dcPintarMarcadas(){
 var el = bgEl('dc_marcadas'); if(!el) return;
 var m = dcMarcadas();
 if(!m.length){ el.innerHTML = ''; return }
 el.innerHTML = m.map(function(i){
  var s = DC.series[i], b = s.bilhete, seg = DC.seg[b] || {modo: 'nenhuma', chaves: {}};
  var pode = DC_SEGMENTAM.indexOf(String(s.modalidade || '').toUpperCase()) >= 0;
  var bts = pode ? '<span class="dc-seg" role="group" aria-label="segmentação">'
    + DC_MODOS.map(function(m2){
       return '<button type="button" data-modo="' + m2[0] + '" aria-pressed="'
        + (seg.modo === m2[0] ? 'true' : 'false') + '" onclick="dcModo(\\'' + bgEsc(b)
        + '\\', \\'' + m2[0] + '\\')" data-radai-frase>' + bgEsc(m2[1]) + '</button>';
      }).join('') + '</span>'
    : '<span class="dc-seg-nao" data-radai-frase>esta modalidade não se segmenta</span>';
  return '<div class="dc-mrow" id="dcr_' + bgEsc(b) + '"><div class="dc-mrow-cab">'
   + '<span class="dc-mrow-nome"><span class="mod">' + bgEsc(s.modalidade) + '</span>'
   + bgEsc(dcNome(s)) + '</span>'
   + '<span class="pp-sub" data-radai-frase>segmentação</span>' + bts + '</div>'
   + '<div class="dc-tasks" id="dct_' + bgEsc(b) + '"' + (seg.modo === 'personalizado' ? '' : ' hidden')
   + '></div></div>';
 }).join('');
 m.forEach(function(i){
  var s = DC.series[i];
  if((DC.seg[s.bilhete] || {}).modo === 'personalizado') dcPintarTasks(s.bilhete);
 });
 bgTrad();
}
function dcModo(b, modo){
 var seg = DC.seg[b] || (DC.seg[b] = {modo: 'nenhuma', chaves: {}});
 seg.modo = modo;
 if(modo !== 'personalizado') seg.chaves = {};
 var row = bgEl('dcr_' + b);
 if(row) Array.prototype.forEach.call(row.querySelectorAll('.dc-seg button'), function(x){
  x.setAttribute('aria-pressed', x.getAttribute('data-modo') === modo ? 'true' : 'false');
 });
 var t = bgEl('dct_' + b);
 if(t){ t.hidden = modo !== 'personalizado'; if(!t.hidden) dcPintarTasks(b) }
 // GUARDA: a segmentação não muda o DICOM; trocar o modo não descarta a conversão.
 dcPintarBarra();
}
function dcOpcoes(mod){
 if(!DC.opcoes[mod]){
  DC.opcoes[mod] = fetch(DC_ROTA_OPCOES + '?modalidade=' + encodeURIComponent(mod))
   .then(function(r){ if(!r.ok) throw new Error('HTTP ' + r.status); return r.json() })
   .then(function(d){ if(!d || !d.tasks) throw new Error((d && d.erro) || 'sem tasks'); return d })
   .catch(function(e){ DC.opcoes[mod] = null; throw e });
 }
 return DC.opcoes[mod];
}
function dcPintarTasks(b){
 var el = bgEl('dct_' + b), i = dcPorBilhete(b);
 if(!el || i < 0) return;
 var s = DC.series[i], seg = DC.seg[b];
 var mod = String(s.modalidade || 'CT').toUpperCase();
 el.innerHTML = '<span class="dc-tasks-nota" data-radai-frase>lendo as tasks…</span>';
 bgTrad();
 dcOpcoes(mod).then(function(d){
  var de_fabrica = d.ligadas_de_fabrica || [];
  var lista = (d.tasks || []).filter(function(t){
   return t && t.task && t.permitida !== false && t.disponivel !== false && !t.travada;
  });
  lista.forEach(function(t){
   if(!(t.task in seg.chaves)) seg.chaves[t.task] = (de_fabrica.indexOf(t.task) >= 0 && !t.achado) ? 1 : 0;
  });
  el.innerHTML = '<span class="dc-tasks-nota" data-radai-frase>a base roda sempre; marque as tasks desta série</span>'
   + lista.map(function(t){
      return '<label class="dc-task"><input type="checkbox" data-task="' + bgEsc(t.task) + '"'
       + (seg.chaves[t.task] ? ' checked' : '') + '><span>' + bgEsc(t.caixa || t.rotulo || t.task)
       + (t.achado ? '<small data-radai-frase>achado</small>' : '') + '</span></label>';
     }).join('');
  Array.prototype.forEach.call(el.querySelectorAll('input[data-task]'), function(cx){
   cx.addEventListener('change', function(){
    seg.chaves[cx.getAttribute('data-task')] = cx.checked ? 1 : 0;
   });
  });
  bgTrad();
 }).catch(function(e){
  el.innerHTML = '<span class="dc-tasks-nota bg-nao" data-radai-frase>as opções do PERSONALIZADO não vieram do ContourLab</span>';
  bgTrad();
 });
}
function dcPedeSegmentacao(){
 return dcMarcadas().some(function(i){
  var s = DC.series[i];
  return s && (DC.seg[s.bilhete] || {}).modo && DC.seg[s.bilhete].modo !== 'nenhuma';
 });
}

function dcEnfileirarMini(i, s){ DC.filaMini.push({i: i, b: s.bilhete}); dcTocarMini() }
function dcTocarMini(){
 while(DC.rodando < DC_CONCORRENCIA && DC.filaMini.length){
  var t = DC.filaMini.shift();
  DC.rodando++;
  dcCarregarMini(t.i, t.b);
 }
}
function dcCarregarMini(i, b){
 var cx = bgEl('dcm' + i), img = bgEl('dci' + i);
 if(!img){ DC.rodando--; dcTocarMini(); return }
 bgBrilho(cx, true, '');
 var s = DC.series[i] || {};
 var url = dcMiniUrl(s) || ('/api/bridge/miniatura?b=' + encodeURIComponent(b));
 var pronto = function(){ bgBrilho(cx, false); DC.rodando--; dcTocarMini() };
 img.onload = pronto;
 img.onerror = function(){
  if(s.imagem){ dcSemPrevia(i, s.modalidade); pronto(); return }
  fetch(url, {method:'HEAD'})
   .then(function(r){ dcSemPrevia(i, r.headers.get('X-RadAI-Modalidade') || '', r.status) })
   .catch(function(){ dcSemPrevia(i, '') })
   .then(pronto);
 };
 img.src = url;
}
function dcSemPrevia(i, mod, status){
 var cx = bgEl('dcm' + i);
 if(cx){ cx.classList.add('sem-img'); cx.setAttribute('data-mod', mod || '—') }
 var m = bgEl('dcmm' + i);
 if(m && status === 404) bgTexto(m, 'recarregue a pasta');
}

function dcAvancar(){
 var m = dcMarcadas();
 if(!m.length){ bgMsg('dc_msg', 'marque uma série antes de avançar', 'erro'); return }
 DC.nav = m;
 dcEtapa(3, true);
 dcPintarDiagLista();
 dcAbrir(m[0]);
 dcLerLaudos(m);
}
function dcLerLaudo(b){
 if(DC.laudos[b]) return Promise.resolve(DC.laudos[b]);
 if(DC.lendo[b]) return DC.lendo[b];
 var fonte = DC.fonte, si = DC.series[dcPorBilhete(b)];
 var pedido = (si && si.imagem) ? imLerLaudo(si) : bgPost('/api/bridge/laudo', {pasta: fonte, b: b});
 var p = pedido.then(function(d){
  delete DC.lendo[b];
  if(fonte !== DC.fonte) return null;
  if(!d || d.erro){ DC.laudoErro[b] = (d && d.erro) || '?'; return d || null }
  DC.laudos[b] = d;
  delete DC.laudoErro[b];
  return d;
 }, function(e){
  delete DC.lendo[b];
  if(fonte === DC.fonte) DC.laudoErro[b] = String((e && e.message) || e || '?');
  throw e;
 });
 DC.lendo[b] = p;
 return p;
}
function dcLerLaudos(m){
 var cadeia = Promise.resolve();
 m.forEach(function(i){
  var s = DC.series[i];
  if(!s || !s.bilhete) return;
  cadeia = cadeia.then(function(){ return dcLerLaudo(s.bilhete).catch(function(){}) })
   .then(function(){ dcPintarDiagLista(); dcPintarOutras(); dcPintarBarra() });
 });
 return cadeia;
}
function dcLaudosPendentes(){
 return DC.etapa >= 3 && DC.nav.some(function(i){
  var s = DC.series[i];
  return !!(s && s.bilhete && !DC.laudos[s.bilhete] && !DC.laudoErro[s.bilhete]);
 });
}
function dcPintarOutras(){
 var el = bgEl('dc_outras'); if(!el) return;
 var outras = DC.nav.filter(function(i){ return i !== DC.sel && DC.series[i] });
 if(!outras.length){ el.hidden = true; el.innerHTML = ''; return }
 el.hidden = false;
 bgHTML(el, '<div class="bg-rot">' + bgF('Alertas das outras séries escolhidas') + '</div>'
  + outras.map(function(i){
     var s = DC.series[i], d = DC.laudos[s.bilhete], er = DC.laudoErro[s.bilhete], corpo;
     var falta = (s.imagem && imFalta(s)) ? '<b class="bg-nao">' + bgF('falta informar') + '</b> ' : '';
     if(d){
      var al = dcAlertas(d);
      corpo = falta + (al.length ? al.map(function(a){
        return (a.impede ? '<b class="bg-nao">' + bgF('não converte') + '</b> ' : '') + bgEsc(a.titulo);
       }).join(' &middot; ')
       : '<span class="ok">' + bgF('Nenhum alerta. A série está pronta para converter.') + '</span>');
     } else {
      corpo = er ? '<span class="bg-nao">' + bgEsc(er) + '</span>' : bgF('lendo o cabeçalho…');
     }
     return '<div class="dc-outra"><button type="button" class="dc-outra-nome" onclick="dcAbrir('
      + i + ')"><span class="mod">' + bgEsc(s.modalidade) + '</span>' + bgEsc(dcNome(s))
      + '</button><span class="dc-outra-al">' + corpo + '</span></div>';
    }).join(''));
}
function dcPintarDiagLista(){
 var el = bgEl('dc_diag_lista'); if(!el) return;
 el.innerHTML = DC.nav.map(function(i){
  var s = DC.series[i], d = DC.laudos[s.bilhete];
  var n = d ? dcAlertas(d).length : -1;
  return '<button type="button" class="dc-diag-item" id="dcd' + i + '" aria-current="'
   + (DC.sel === i ? 'true' : 'false') + '" onclick="dcAbrir(' + i + ')">'
   + '<span class="mod">' + bgEsc(s.modalidade) + '</span><span class="nome">' + bgEsc(dcNome(s))
   + '</span><span class="al' + (n === 0 ? ' zero' : '') + '">'
   + (n < 0 ? '…' : (n + ' ' + (n === 1 ? 'alerta' : 'alertas'))) + '</span></button>';
 }).join('');
 bgTrad();
}
function dcAlertas(d){ return (d.achados || []).filter(function(a){ return !a.ok && (a.alerta || a.impede) }) }
function dcImagemLaudo(s, d){
 if(!s || !s.bilhete) return;
 if(d && d.erro) DC.laudoErro[s.bilhete] = d.erro;
 else if(d){ DC.laudos[s.bilhete] = d; delete DC.laudoErro[s.bilhete] }
 dcPintarDiagLista(); dcPintarOutras(); dcPintarBarra();
}
function dcImagemMudou(s){
 // GUARDA: a geometria da imagem muda o DICOM; a conversão feita com a antiga é descartada.
 if(DC.etapa > 3) dcVoltarA(3);
}
function dcAbrir(i){
 var s = DC.series[i]; if(!s) return;
 DC.sel = i;
 dcPintarNav();
 bgTexto(bgEl('dc_titulo'), dcNome(s));
 var bi = bgEl('dc_bloco_imagem'), bd = bgEl('dc_bloco_dicom');
 if(bi) bi.hidden = !s.imagem;
 if(bd) bd.hidden = !!s.imagem;
 if(s.imagem){
  dcVisorFechar();
  dcPintarOutras();
  imAbrir(s);
  dcPintarDiagLista();
  return;
 }
 imFecharVisor();
 IM.atual = null;
 DC.janela = s.janela || 'mediastino';
 ['auto','pulmao','mediastino','osso'].forEach(function(k){
  var bj = bgEl('dcj_' + k); if(!bj) return;
  bj.className = 'dc-jan' + (k === DC.janela ? ' sel' : '');
  bj.hidden = (k === 'auto' && s.modalidade === 'CT');
 });
 dcVisorLigar(s);
 var b = s.bilhete || '';
 dcPintarOutras();
 if(DC.laudos[b]){ dcPintarLaudo(DC.laudos[b]); dcPintarDiagLista(); return }
 bgHTML(bgEl('dc_laudo'), '<p class="pp-vazio">' + bgF('lendo o cabeçalho…') + '</p>');
 dcLerLaudo(b).then(function(d){
  if(!d) return;
  if(DC.sel === i){
   if(d.erro) bgHTML(bgEl('dc_laudo'), '<p class="pp-vazio">' + bgEsc(d.erro) + '</p>');
   else dcPintarLaudo(d);
  }
  dcPintarDiagLista(); dcPintarOutras(); dcPintarBarra();
 }).catch(function(e){
  if(DC.sel === i)
   bgHTML(bgEl('dc_laudo'), '<p class="pp-vazio">' + bgF('não consegui ler o cabeçalho')
     + ' <code>' + bgEsc(e) + '</code></p>');
  dcPintarBarra();
 });
}
function dcPintarNav(){
 var pos = DC.nav.indexOf(DC.sel);
 var ant = bgEl('dc_ant'), prox = bgEl('dc_prox'), lb = bgEl('dc_nav_pos');
 if(ant) ant.hidden = pos <= 0;
 if(prox) prox.hidden = pos < 0 || pos >= DC.nav.length - 1;
 if(lb) lb.textContent = pos < 0 ? '' : ((pos + 1) + ' / ' + DC.nav.length);
 Array.prototype.forEach.call(document.querySelectorAll('.dc-diag-item'), function(x){
  x.setAttribute('aria-current', x.id === 'dcd' + DC.sel ? 'true' : 'false');
 });
}
function dcAnterior(){ var p = DC.nav.indexOf(DC.sel); if(p > 0) dcAbrir(DC.nav[p - 1]) }
function dcProxima(){ var p = DC.nav.indexOf(DC.sel); if(p >= 0 && p < DC.nav.length - 1) dcAbrir(DC.nav[p + 1]) }
function dcPintarLaudo(d){
 // GUARDA: alerta nao bloqueia; o servidor converte e grava cada alerta dentro do DICOM.
 var al = dcAlertas(d), h = '';
 if(!al.length){
  h = '<div class="dc-falta bom"><span class="tt">' + bgF('Nenhum alerta. A série está pronta para converter.')
    + '</span></div>';
 }
 al.forEach(function(a){
  h += '<div class="dc-falta ' + (a.impede ? 'ruim' : 'decide') + '"><span class="marca">'
    + bgF(a.impede ? 'não converte' : 'alerta') + '</span>'
    + '<span class="tt">' + bgEsc(a.titulo) + '</span>'
    + (a.detalhe ? '<div class="dd">' + bgEsc(a.detalhe) + '</div>' : '')
    + (a.o_que_faz ? '<div class="faz">' + bgEsc(a.o_que_faz) + '</div>' : '')
    + '</div>';
 });
 bgHTML(bgEl('dc_laudo'), h);
}

function dcVisorFechar(){
 if(DC.visor){ try{ DC.visor.fechar() }catch(e){} }
 DC.visor = null;
}
function dcVisorLigar(s, inicio){
 dcVisorFechar();
 DC.visorSerie = s || null;
 var cx = bgEl('dc_visor');
 if(!cx || !s || !s.bilhete){ return }
 var b = s.bilhete, jan = DC.janela;
 DC.visor = RadaiUmEixo(cx, {
  n: s.cortes, emVoo: 3, cranial: s.cranial,
  inicio: (inicio == null) ? (s.central|0) : inicio,
  url: function(k){
   return '/api/bridge/corte?b=' + encodeURIComponent(b)
        + '&corte=' + k + '&janela=' + encodeURIComponent(jan);
  },
  aoParar: function(st, e){ dcVisorParou(cx, st, e) }
 });
 dcBrilhoNoVisor(cx);
}
function dcBrilhoNoVisor(cx){
 bgVigiarVisor(cx, DC.visor, null);
}
function dcVisorParou(cx, st, e){
 var aviso = cx.querySelector('[data-ue="aviso"]');
 var ue = cx.querySelector('.ue-visor');
 bgBrilho(ue, false);
 if(st === 204){
  if(ue){
   ue.classList.add('sem-img');
   ue.setAttribute('data-mod', (e && e.modalidade) || '—');
  }
 } else if(st === 404){
  bgTexto(aviso, 'recarregue a pasta');
 }
}
function dcJanela(j){
 DC.janela = j;
 ['auto','pulmao','mediastino','osso'].forEach(function(k){
  var b = bgEl('dcj_' + k); if(b) b.className = 'dc-jan' + (k === j ? ' sel' : '');
 });
 var s = DC.visorSerie, v = DC.visor;
 if(!s || !v || !s.bilhete) return;
 dcVisorLigar(s, v.atual);
}
function dcVisorModal(i){
 var s = DC.series[i]; if(!s || !window.uiVisor) return;
 if(s.imagem){
  var n = Math.max(1, s.n | 0);
  window.uiVisor({titulo: dcNome(s), total: n, inicial: Math.floor(n / 2),
   janelas: [{chave: 'auto', rotulo: 'automática'}], janela: 'auto', origem: bgEl('dcs' + i),
   carregando: 'abrindo a série',
   src: function(k){ return '/api/imagem/previa?b=' + encodeURIComponent(s.bilhete) + '&k=' + k },
   cabecalho: function(){ return [['Descrição', dcNome(s)], ['Imagens', String(s.n || 0)]] }});
  return;
 }
 var tc = (s.modalidade === 'CT');
 var jans = [{chave:'mediastino', rotulo:'mediastino'}, {chave:'pulmao', rotulo:'pulmão'},
             {chave:'osso', rotulo:'osso'}];
 if(!tc) jans.unshift({chave:'auto', rotulo:'automática'});
 var cab = [['Modalidade', s.modalidade], ['Descrição', dcNome(s)], ['Imagens', String(s.cortes || 0)]];
 DC.cabModal = cab;
 var v = window.uiVisor({titulo: dcNome(s), total: s.cortes || 1, inicial: s.central,
  cranial: s.cranial, janelas: jans, janela: s.janela || jans[0].chave, origem: bgEl('dcs' + i),
  carregando: 'abrindo a série',
  src: function(k, j){
   return '/api/bridge/corte?b=' + encodeURIComponent(s.bilhete || '') + '&corte=' + k
        + '&janela=' + encodeURIComponent(j);
  },
  cabecalho: function(){ return DC.cabModal || cab }});
 dcLerLaudo(s.bilhete || '').then(function(d){
  if(!d || d.erro) return;
  var enc = d.encontrado || {};
  var pares = cab.filter(function(p){
   return !(p[0] in enc) && !(p[0] === 'Imagens' && ('Cortes' in enc));
  });
  Object.keys(enc).forEach(function(k){ pares.push([k, enc[k]]) });
  ((d.cabecalho && d.cabecalho.meta) || []).concat((d.cabecalho && d.cabecalho.tags) || [])
   .forEach(function(t){ pares.push([t.nome || (t.grupo + ',' + t.elemento), t.valor]) });
  DC.cabModal = pares;
  if(v && v.cabecalho) v.cabecalho();
  bgTrad();
 }).catch(function(){});
}

function dcConverter(){
 var m = dcMarcadas(); if(!m.length) return;
 for(var k = 0; k < m.length; k++){
  var si = DC.series[m[k]], falta = (si && si.imagem) ? imFalta(si) : '';
  if(falta){
   if(DC.sel !== m[k]) dcAbrir(m[k]);
   imCobrar(falta);
   return;
  }
 }
 var bt = bgEl('dc_converter'); if(bt) bt.disabled = true;
 bgTexto(bgEl('dc_conv_sub'), 'convertendo…');
 dcEtapa(4, true);
 bgHTML(bgEl('dc_conv'), '<p class="pp-vazio">' + bgF('convertendo as séries marcadas…') + '</p>');
 bgPost('/api/bridge/etapa/converter', {pasta: DC.fonte,
   series: m.map(function(i){
    var s = DC.series[i];
    return s.imagem ? {b: s.bilhete || '', imagem: imPedido(s)} : {b: s.bilhete || ''};
   })})
  .then(function(d){
   bgTexto(bgEl('dc_conv_sub'), '');
   if(d.erro && !(d.exportadas || []).length){
    bgHTML(bgEl('dc_conv'), '<p class="bg-nao">' + bgEsc(d.erro) + '</p>'
      + dcNaoForam(d));
    dcPintarBarra();
    return;
   }
   DC.conversao = d.conversao || '';
   DC.exportadas = d.exportadas || [];
   dcPintarConversao(d);
   dcEtapa(5, true);
  })
  .catch(function(e){
   bgTexto(bgEl('dc_conv_sub'), '');
   bgHTML(bgEl('dc_conv'), '<p class="bg-nao">' + bgF('não consegui converter') + ' <code>'
     + bgEsc(e) + '</code></p>');
   dcPintarBarra();
  });
}
function dcNaoForam(d){
 if(!(d.recusadas || []).length) return '';
 return '<p class="bg-nao">' + bgF('não foram:') + ' ' + bgEsc(d.recusadas.join(' · ')) + '</p>';
}
function dcPintarConversao(d){
 var ex = d.exportadas || [], n = ex.length;
 var h = '<p class="bg-saida"><b>' + n + '</b> ' + bgF(n === 1 ? 'série convertida' : 'séries convertidas')
   + '</p><table class="dc-tab">' + ex.map(function(x){
    return '<tr><td class="mod">' + bgEsc(x.modalidade) + '</td><td>' + bgEsc(x.descricao || x.uid8)
     + '</td><td class="mod">' + (x.cortes || '?') + '</td>'
     + '<td class="al">' + (x.alertas && x.alertas.length ? bgIco('alerta') + '<b>'
        + x.alertas.length + '</b> ' + bgF(x.alertas.length === 1 ? 'alerta' : 'alertas') : '')
     + '</td></tr>';
   }).join('') + '</table>' + dcNaoForam(d);
 bgHTML(bgEl('dc_conv'), h);
}

function dcEntregar(){
 if(!DC.conversao) return;
 if(!BG.destinos.length){ bgTremer(bgEl('bg_dest_lista')); return }
 if(dcPedeSegmentacao() && BG.destinos.length > DC_TETO_COPIAS + 1){
  bgHTML(bgEl('dc_ent'), '<p class="bg-nao" id="dc_teto">' + bgF(DC_FRASE_DO_TETO) + '</p>');
  bgTremer(bgEl('bg_dest_lista'));
  return;
 }
 var bt = bgEl('dc_entregar'); if(bt) bt.disabled = true;
 bgTexto(bgEl('dc_ent_sub'), 'entregando…');
 bgPost('/api/bridge/etapa/entregar', {conversao: DC.conversao, destinos: BG.destinos.slice()})
  .then(function(d){
   bgTexto(bgEl('dc_ent_sub'), '');
   if(d.erro){
    bgHTML(bgEl('dc_ent'), '<p class="bg-nao">' + bgEsc(d.erro) + '</p>');
    dcPintarBarra();
    return;
   }
   DC.entregue = d;
   DC.conversao = '';
   var ids = d.ids_externos || [];
   bgHTML(bgEl('dc_ent'), '<p class="bg-saida">' + bgF('DICOM entregue em') + ' <code>'
     + bgEsc(d.nome) + '</code>' + bgSaida(d) + '</p>'
     + (ids.length ? '<p class="bg-saida" id="dc_sem_dono">' + bgF('Paciente DESCONHECIDO, ID') + ' <code>'
        + bgEsc(ids.join(', ')) + '</code>: ' + bgF('atribua ao paciente certo no TPS') + '</p>' : '')
     + bgFalhas(d));
   var itens = dcItensDaFila(d);
   if(itens.length){ dcEtapa(6, true); dcSegmentar(itens, d.nome) }
   else dcPintarBarra();
  })
  .catch(function(e){
   bgTexto(bgEl('dc_ent_sub'), '');
   bgHTML(bgEl('dc_ent'), '<p class="bg-nao">' + bgF('não consegui entregar') + ' <code>'
     + bgEsc(e) + '</code></p>');
   dcPintarBarra();
  });
}
function dcItensDaFila(d){
 var fora = [];
 (d.series || []).forEach(function(x){
  var seg = DC.seg[x.b];
  if(!seg || !seg.modo || seg.modo === 'nenhuma') return;
  var i = dcPorBilhete(x.b), s = DC.series[i] || {};
  fora.push({pasta: x.pasta, uid: x.uid, modo: seg.modo,
             chaves: seg.modo === 'personalizado' ? JSON.parse(JSON.stringify(seg.chaves || {})) : {},
             copiar_rs_para: (x.copias || []).slice(), origem: DC_ORIGEM,
             rotulo: (s.modalidade ? s.modalidade + ' · ' : '') + dcNome(s)});
 });
 return fora;
}

function dcFilaChave(){ return 'e' + Date.now().toString(36) + Math.floor(Math.random() * 1e8).toString(36) }
function dcFilaPor(chave){
 for(var i = 0; i < DC.filas.length; i++) if(DC.filas[i].chave === chave) return DC.filas[i];
 return null;
}
function dcFilaAbrirBarra(){
 try{ if(typeof window.radaiFilaAbrir === 'function') window.radaiFilaAbrir() }catch(e){}
}
function dcSegmentar(itens, nome){
 var e = {chave: dcFilaChave(), nome: nome || (DC.entregue || {}).nome || '', itens: itens,
          n: itens.length, copias: ((itens[0] || {}).copiar_rs_para || []).length,
          cartoes: [], estado: 'pedindo', guarda: '', erro: ''};
 DC.filas.push(e);
 bgPost(DC_ROTA_GUARDAR, {itens: itens}).then(function(d){
  if(d && d.guarda){ e.guarda = d.guarda; dcFilaGuardar() }
 }).catch(function(){});
 return dcFilaPedir(e);
}
function dcFilaPost(url, corpo){
 return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
   body: JSON.stringify(corpo)})
  .then(function(r){
   return r.json().catch(function(){ return null }).then(function(d){
    if(r.ok && d && d.ok && (d.cartoes || []).length) return d;
    var x = new Error((d && d.erro) || (r.ok ? 'sem cartão' : 'HTTP ' + r.status));
    x.semGuarda = !!(d && d.sem_guarda);
    x.recusa = !!(r.ok && d && d.ok === false && d.erro && !d.indisponivel && !x.semGuarda);
    throw x;
   });
  });
}
function dcFilaEnfileirar(e, alvo){
 if(e.itens) return dcFilaPost(DC_ROTA_FILA, {itens: alvo.map(function(i){ return e.itens[i] })});
 if(e.guarda) return dcFilaPost(DC_ROTA_DE_NOVO, {guarda: e.guarda, quais: alvo});
 var x = new Error(''); x.semGuarda = true;
 return Promise.reject(x);
}
function dcFilaRecebeu(e, alvo, d){
 (d.cartoes || []).forEach(function(c, k){
  if(alvo[k] == null) return;
  e.cartoes[alvo[k]] = {id: c.id, posicao: c.posicao, estado: 'esperando', mensagem: '', rotulo: ''};
 });
 e.estado = 'na_fila'; e.erro = ''; e.semGuarda = false;
 e.assentar = null; e.copiasConferidas = false; e.copiasFaltam = 0; e.concluida = false;
}
function dcFilaPedir(e){
 var alvo = [];
 for(var i = 0; i < e.n; i++) alvo.push(i);
 e.estado = 'pedindo'; e.erro = '';
 dcPintarFila();
 return dcFilaEnfileirar(e, alvo).then(function(d){
  e.cartoes = [];
  dcFilaRecebeu(e, alvo, d);
  dcFilaGuardar();
  dcPintarFila();
  dcFilaAbrirBarra();
  dcFilaVigiar();
 }, function(x){
  e.estado = (x && x.recusa) ? 'recusada' : 'indisponivel';
  e.semGuarda = !!(x && x.semGuarda);
  e.erro = e.semGuarda ? '' : String((x && x.message) || x || '');
  dcFilaGuardar();
  dcPintarFila();
 });
}
function dcFilaDeNovo(chave){
 var e = dcFilaPor(chave); if(!e) return Promise.resolve();
 if(e.estado !== 'na_fila') return dcFilaPedir(e);
 var alvo = [];
 e.cartoes.forEach(function(c, i){ if(c.estado === 'falhou' || c.estado === 'cancelado') alvo.push(i) });
 if(!alvo.length) return Promise.resolve();
 e.repondo = true; e.erro = '';
 dcPintarFila();
 var resto = [], cadeia = Promise.resolve();
 alvo.forEach(function(i){
  cadeia = cadeia.then(function(){
   var c = e.cartoes[i];
   if(!c || !c.id || c.saiu){ resto.push(i); return }
   return bgPost(DC_ROTA_REPOR, {id: c.id}).then(function(d){
    if(d && d.ok && d.id) e.cartoes[i] = {id: d.id, posicao: null, estado: 'esperando',
                                          mensagem: '', rotulo: c.rotulo || ''};
    else resto.push(i);
   }, function(){ resto.push(i) });
  });
 });
 return cadeia.then(function(){
  return resto.length ? dcFilaEnfileirar(e, resto) : null;
 }).then(function(d){
  if(d) dcFilaRecebeu(e, resto, d);
  else { e.assentar = null; e.copiasConferidas = false; e.concluida = false }
  e.repondo = false;
  dcFilaGuardar();
  dcPintarFila();
  dcFilaAbrirBarra();
  dcFilaVigiar();
 }, function(x){
  e.repondo = false;
  e.semGuarda = !!(x && x.semGuarda);
  e.erro = e.semGuarda ? '' : String((x && x.message) || x || '');
  dcFilaGuardar();
  dcPintarFila();
  dcFilaVigiar();
 });
}
function dcFilaDispensar(chave){
 DC.filas = DC.filas.filter(function(e){ return e.chave !== chave });
 dcFilaGuardar();
 dcPintarFila();
 if(!DC.filas.length) dcEtapa(DC.etapa);
}
function dcFilaGuardar(){
 try{
  var lista = DC.filas.filter(function(e){ return !e.concluida && e.estado !== 'pedindo' })
   .map(function(e){
    return {nome: e.nome, guarda: e.guarda || '', n: e.n, copias: e.copias || 0, estado: e.estado,
            ids: e.cartoes.map(function(c){ return (c && c.id) || '' }),
            estados: e.cartoes.map(function(c){
             return (!c || c.estado === 'conferindo') ? 'esperando' : (c.estado || '') }),
            saiu: e.cartoes.map(function(c){ return (c && c.saiu) ? 1 : 0 })};
   });
  if(lista.length) sessionStorage.setItem(DC_SESSAO, JSON.stringify({v: 2, entregas: lista}));
  else sessionStorage.removeItem(DC_SESSAO);
 }catch(e){}
}
function dcFilaAtiva(e){
 if(e.estado !== 'na_fila' || e.concluida) return false;
 if(e.assentar != null && e.assentar > 0) return true;
 return e.cartoes.some(function(c){
  return c && (DC_ESPERA.indexOf(c.estado) >= 0 || (c.estado === 'parcial' && !c.saiu));
 });
}
function dcFilaLenta(e){
 if(e.assentar != null && e.assentar > 0) return false;
 return !e.cartoes.some(function(c){ return c && DC_ESPERA.indexOf(c.estado) >= 0 });
}
function dcFilaParar(){ if(DC.filaTimer){ clearInterval(DC.filaTimer); DC.filaTimer = null } }
function dcFilaVigiar(){
 if(DC.filaTimer) return;
 DC.filaTimer = setInterval(dcFilaTique, DC_INTERVALO);
}
function dcFilaTique(){
 DC.filaTique++;
 var ativas = DC.filas.filter(dcFilaAtiva);
 if(!ativas.length){ dcFilaParar(); return }
 if(!ativas.some(function(e){ return !dcFilaLenta(e) }) && DC.filaTique % DC_LENTO) return;
 dcFilaConsultar();
}
function dcFilaConferirSaida(e, idx){
 var marcar = function(){
  idx.forEach(function(i){
   var c = e.cartoes[i];
   if(c && c.estado === 'conferindo'){ c.estado = 'incerto'; c.mensagem = ''; c.frase = false }
  });
 };
 if(!e.guarda){ marcar(); return Promise.resolve() }
 return bgPost(DC_ROTA_CONFERIR, {guarda: e.guarda, quais: idx}).then(function(d){
  (d && d.ok ? d.series || [] : []).forEach(function(s){
   var c = e.cartoes[s.i]; if(!c || c.estado !== 'conferindo') return;
   c.estado = s.rs ? 'pronto' : 'falhou';
   c.mensagem = s.rs ? DC_SAIU_PRONTO : DC_SAIU_SEM_RS;
   c.frase = true;
  });
  marcar();
 }, marcar);
}
function dcFilaFechar(e){
 var tudo = e.cartoes.length && e.cartoes.every(function(c){ return c && c.estado === 'pronto' });
 e.concluida = !!tudo && (!e.copias || !e.guarda || !!e.copiasConferidas);
}
function dcFilaAssentar(e){
 if(e.estado !== 'na_fila') return;
 var est = e.cartoes.map(function(c){ return c ? c.estado : '' });
 var fim = est.length && est.every(function(s){ return DC_TERMINA.indexOf(s) >= 0 });
 if(!fim){ e.assentar = null; e.copiasConferidas = false; e.copiasFaltam = 0; return }
 if(e.assentar == null) e.assentar = DC_ASSENTAR;
 else if(e.assentar > 0) e.assentar--;
 if(e.assentar > 0) return;
 var bons = est.every(function(s){ return s === 'pronto' || s === 'parcial' });
 if(bons && e.copias && e.guarda && !e.copiasConferidas){
  if(e.conferindoCopias) return;
  e.conferindoCopias = true;
  bgPost(DC_ROTA_CONFERIR, {guarda: e.guarda, quais: e.cartoes.map(function(_c, i){ return i })})
   .then(function(d){
    e.conferindoCopias = false;
    e.copiasConferidas = true;
    e.copiasFaltam = (d && d.ok ? d.series || [] : []).reduce(function(t, s){
     return t + Math.max(0, (s.de | 0) - (s.copias | 0)) }, 0);
    dcFilaFechar(e); dcFilaGuardar(); dcPintarFila();
   }, function(){ e.conferindoCopias = false; e.copiasConferidas = true; dcFilaFechar(e); dcPintarFila() });
  return;
 }
 dcFilaFechar(e);
}
function dcFilaConsultar(){
 var ativas = DC.filas.filter(dcFilaAtiva);
 if(!ativas.length){ dcFilaParar(); return Promise.resolve() }
 var ids = [];
 ativas.forEach(function(e){ e.cartoes.forEach(function(c){ if(c && c.id && !c.saiu) ids.push(c.id) }) });
 if(!ids.length){
  ativas.forEach(dcFilaAssentar); dcFilaGuardar(); dcPintarFila();
  return Promise.resolve();
 }
 return fetch(DC_ROTA_ESTADO, {method:'POST', headers:{'Content-Type':'application/json'},
   body: JSON.stringify({ids: ids})})
  .then(function(r){ if(!r.ok) throw new Error('HTTP ' + r.status); return r.json() })
  .then(function(d){
   var por = {};
   (d.cartoes || []).forEach(function(c){ por[c.id] = c });
   DC.filaRodando = (d && typeof d.rodando === 'boolean') ? d.rodando : null;
   var esperas = [];
   ativas.forEach(function(e){
    e.semResposta = false;
    var sumiram = [];
    e.cartoes.forEach(function(c, i){
     if(!c || !c.id || c.saiu) return;
     var x = por[c.id];
     if(x){
      c.estado = x.estado || c.estado; c.posicao = x.posicao;
      c.mensagem = x.mensagem || ''; c.frase = false; c.rotulo = x.rotulo || c.rotulo || '';
      return;
     }
     c.saiu = true;
     // GUARDA: o Limpar da barra tira o pronto; o último estado conhecido vale.
     if(DC_TERMINA.indexOf(c.estado) >= 0) return;
     c.estado = 'conferindo';
     sumiram.push(i);
    });
    if(sumiram.length) esperas.push(dcFilaConferirSaida(e, sumiram));
   });
   return Promise.all(esperas).then(function(){
    ativas.forEach(dcFilaAssentar);
    dcFilaGuardar();
    dcPintarFila();
   });
  })
  .catch(function(){ ativas.forEach(function(e){ e.semResposta = true }); dcPintarFila() });
}
function dcFilaMensagens(e, filtro){
 var varios = e.cartoes.length > 1;
 return e.cartoes.filter(function(c){ return c && c.mensagem && filtro(c) }).map(function(c){
  return (varios && c.rotulo ? bgEsc(c.rotulo) + ': ' : '')
   + (c.frase ? bgF(c.mensagem) : bgEsc(c.mensagem));
 }).join(' &middot; ');
}
function dcFilaBotao(e, frase){
 return '<button type="button" class="ui-bt dc-fila-de-novo" onclick="dcFilaDeNovo(\\''
  + e.chave + '\\')">' + bgF(frase) + '</button>';
}
function dcFilaResumo(e){
 if(e.estado === 'pedindo' || e.repondo) return {cls: '', h: bgF('DICOM entregue · pondo na fila…')};
 var semGuarda = e.semGuarda ? bgF(DC_SEM_GUARDA) : '';
 var erro = e.erro ? ' <code>' + bgEsc(e.erro) + '</code>' : '';
 if(e.estado === 'indisponivel' || e.estado === 'recusada'){
  return {cls: 'falha', fim: true,
   h: bgF(e.estado === 'recusada' ? 'DICOM entregue · a fila recusou a segmentação'
                                  : 'DICOM entregue · fila indisponível'),
   det: (semGuarda || bgF('a segmentação não foi pedida; o DICOM está entregue.')) + erro,
   bt: (e.semGuarda || e.estado === 'recusada') ? '' : dcFilaBotao(e, 'Tentar de novo')};
 }
 var est = e.cartoes.map(function(c){ return c ? c.estado : '' });
 var esperando = est.some(function(s){ return DC_ESPERA.indexOf(s) >= 0 });
 var falhou = function(c){ return c.estado === 'falhou' || c.estado === 'cancelado' };
 var falhos = e.cartoes.filter(function(c){ return c && falhou(c) });
 var btFalhos = (falhos.length && !e.semGuarda) ? dcFilaBotao(e, 'Pôr na fila de novo') : '';
 if(falhos.length && !esperando){
  return {cls: 'falha', fim: true, h: bgF('DICOM entregue · a segmentação não terminou'),
   det: [dcFilaMensagens(e, function(){ return true }), semGuarda].filter(Boolean).join(' ') + erro,
   bt: btFalhos};
 }
 if(!esperando && est.indexOf('incerto') >= 0){
  return {cls: 'meia', fim: true, h: bgF('DICOM entregue · o cartão saiu da fila'),
   det: bgF('não sei se o RTSTRUCT chegou: confira a pasta entregue')};
 }
 if(est.length && est.every(function(s){ return s === 'pronto' || s === 'parcial' })){
  var msgs = dcFilaMensagens(e, function(){ return true });
  if(e.copias && e.guarda && !e.copiasConferidas)
   return {cls: '', h: bgF('DICOM entregue · conferindo o RTSTRUCT nos destinos…'), det: msgs};
  if(e.copiasFaltam > 0)
   return {cls: 'meia', fim: true, h: bgF('DICOM entregue · o RTSTRUCT não chegou a todos os destinos'),
           det: msgs};
  return {cls: 'pronta', fim: true, det: msgs,
   h: bgF(est.indexOf('parcial') >= 0 ? 'DICOM entregue · RTSTRUCT entregue em parte'
                                      : 'DICOM entregue · RTSTRUCT entregue')};
 }
 var det = falhos.length ? dcFilaMensagens(e, falhou) : '', bt = btFalhos;
 if(est.indexOf('rodando') >= 0) return {cls: '', h: bgF('DICOM entregue · segmentando'), det: det, bt: bt};
 var pos = e.cartoes.filter(function(c){
  return c && (c.estado === 'esperando' || c.estado === 'pulado') && c.posicao != null && c.posicao !== '' })
  .map(function(c){ return Number(c.posicao) });
 var h = bgF('DICOM entregue · segmentação na fila') + (pos.length
   ? ' (' + bgF('posição') + ' <b class="dc-fila-pos">' + bgEsc(Math.min.apply(null, pos)) + '</b>)' : '');
 if(DC.filaRodando === false){
  det = bgF('a fila está parada: clique Iniciar na barra') + (det ? ' &middot; ' + det : '');
  if(typeof window.radaiFilaAbrir === 'function')
   bt = '<button type="button" class="ui-bt dc-fila-abrir" onclick="dcFilaAbrirBarra()">'
     + bgF('Abrir a fila') + '</button>' + bt;
 }
 return {cls: '', h: h, det: det, bt: bt};
}
function dcPintarFila(){
 var el = bgEl('dc_fila'); if(!el) return;
 var h = DC.filas.map(function(e){
  var r = dcFilaResumo(e);
  var sr = (e.semResposta && !r.fim)
    ? '<span class="det">' + bgF('a fila não respondeu agora; tento de novo') + '</span>' : '';
  var x = r.fim ? '<button type="button" class="dc-fila-x" title="dispensar" aria-label="dispensar"'
    + ' onclick="dcFilaDispensar(\\'' + e.chave + '\\')">' + bgIco('fechar') + '</button>' : '';
  return '<div class="dc-fila' + (r.cls ? ' ' + r.cls : '') + '" data-entrega="' + bgEsc(e.chave) + '">'
   + '<p>' + (e.nome ? '<code class="dc-fila-nome">' + bgEsc(e.nome) + '</code>' : '') + r.h
   + (r.det ? '<span class="det">' + r.det + '</span>' : '') + sr + '</p>' + (r.bt || '') + x + '</div>';
 }).join('');
 if(h === DC.filaHtml) return;
 DC.filaHtml = h;
 bgHTML(el, h);
}
function dcRetomarFila(){
 var g = null;
 try{ g = JSON.parse(sessionStorage.getItem(DC_SESSAO) || 'null') }catch(e){ g = null }
 if(!g) return;
 var lista = g.entregas || ((g.ids || []).length ? [{nome: g.nome, ids: g.ids, estado: 'na_fila'}] : []);
 lista.forEach(function(s){
  var ids = s.ids || [], est = s.estados || [], saiu = s.saiu || [];
  DC.filas.push({chave: dcFilaChave(), nome: s.nome || '', itens: null, guarda: s.guarda || '',
   n: s.n || ids.length, copias: s.copias || 0, estado: s.estado || 'na_fila', erro: '',
   cartoes: ids.map(function(id, i){
    return {id: id, estado: est[i] || 'esperando', posicao: null, mensagem: '', rotulo: '',
            saiu: !!saiu[i]} })});
 });
 if(!DC.filas.length) return;
 var e6 = bgEl('dc_e6'); if(e6) e6.hidden = false;
 dcPintarFila();
 dcFilaConsultar();
 dcFilaVigiar();
}

document.addEventListener('DOMContentLoaded', function(){
 try{ bgLigarEnvio('dc_envio', function(p){ bgEl('dc_pasta').value = ''; dcCarregar(p) },
                   function(e){ bgErro('dc_msg', 'o envio falhou', e && e.message) }) }catch(e){}
 try{ dcPintarGrade(); dcEtapa(1) }catch(e){}
 try{ bgDestinosIniciais() }catch(e){}
 try{ dcRetomarFila() }catch(e){}
});
"""
JS = (JS.replace(u"__MODOS__", json.dumps([list(m) for m in MODOS_DE_SEGMENTACAO],
                                          ensure_ascii=False))
      .replace(u"__SEGMENTAM__", json.dumps(list(MODALIDADES_QUE_SEGMENTAM)))
      .replace(u"__ROTA_FILA__", ROTA_DA_FILA)
      .replace(u"__ROTA_ESTADO__", ROTA_DO_ESTADO_DA_FILA)
      .replace(u"__ROTA_OPCOES__", ROTA_DAS_OPCOES)
      .replace(u"__ROTA_REPOR__", ROTA_DE_REPOR)
      .replace(u"__ORIGEM__", ORIGEM_NA_FILA)
      .replace(u"__INTERVALO_CD__", str(int(_E.INTERVALO_DO_CD_MS)))
      .replace(u"__INTERVALO__", str(int(INTERVALO_DA_FILA_MS)))
      .replace(u"__SESSAO__", CHAVE_DA_SESSAO)
      .replace(u"__TETO_COPIAS__", str(int(TETO_DE_COPIAS_DO_RTSTRUCT)))
      .replace(u"__FRASE_DO_TETO__", json.dumps(FRASE_DO_TETO,
                                                ensure_ascii=False))
      + radai_image_screen.JS)


FRASE = (u"Carregue suas imagens que falharam na importação, receba o "
         u"diagnóstico e processe a conversão para TPS de aceitar na fusão")

AJUDA = (
    u"Arraste o exame para a área de envio, escolha arquivos (um .zip, vários "
    u"arquivos ou pastas) ou aponte a pasta. O que é enviado fica numa pasta de "
    u"trabalho desta estação, fora de pasta que sincroniza, e é apagado ao "
    u"limpar os carregamentos ou ao fechar o app.",
    u"Clique marca a série; duplo clique abre a série para conferir, com o "
    u"cabeçalho. Para cada série marcada, escolha a segmentação: nenhuma, "
    u"FAST, AUTO ou PERSONALIZADO, com as tasks.",
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
    u"A entrega é sempre uma pasta nova, DICOM_BRIDGE com a data e a hora, em "
    u"Downloads ou no destino escolhido, copiada para os outros destinos; se "
    u"um destino falha, a tela diz qual. A série com segmentação vai para o "
    u"fim da parte manual da fila da estação, e a fila parada só começa no "
    u"«Iniciar» da barra. O RTSTRUCT é gravado ao lado da série entregue, no "
    u"primeiro destino, e copiado para até %d outros." % TETO_DE_COPIAS_DO_RTSTRUCT,
    u"Imagem JPEG ou PNG entra no mesmo pipeline, sem segmentação: marque a "
    u"série, e o diagnóstico abre o ajuste dela ao lado do MPR. «Carregar um "
    u"CD» lê o "
    u"disco inteiro, pastas e subpastas, sem gravar nada nele.",
    ) + radai_image_screen.AJUDA_NO_PIPELINE

ALERTA = (u"A série exportada leva a identificação do paciente; o destino "
          u"não pode ser pasta que sincroniza com a nuvem")


BOTAO_DO_CD = (u'<button type="button" class="ui-bt" data-cd id="dc_cd_bt" '
               u'onclick="event.stopPropagation();dcCd()">@ICO_DISCO@'
               u'<span data-radai-frase>Carregar um CD</span></button>')
QUADRO_DO_CD = (u'<div class="dc-cd" id="dc_cd" hidden>'
                u'<span class="dc-cd-txt" id="dc_cd_txt" role="status" '
                u'aria-live="polite"></span>'
                u'<button type="button" class="ui-bt" id="dc_cd_parar" hidden '
                u'onclick="dcCdParar()"><span data-radai-frase>Cancelar</span>'
                u'</button></div>')


def carga(p, ao_carregar, ao_procurar, ao_limpar, rotulo):
    import radai_ui
    return (
        u'<section class="bg-carga" aria-label="carregar o estudo">'
        + radai_ui.area_de_envio(p + u"_envio", extra=BOTAO_DO_CD)
        + u'<div class="bg-carga-pasta">'
        u'<label class="bg-carga-rot" for="%(p)s_pasta" data-radai-frase>%(rot)s'
        u'</label>'
        u'<div class="bg-carga-linha">'
        u'<input type="text" id="%(p)s_pasta" spellcheck="false" '
        u'placeholder="C:\\... ou \\\\servidor\\share\\... ou '
        u'C:\\...\\EXAME.zip" '
        u'onkeydown="if(event.key===\'Enter\'){event.preventDefault();%(car)s()}">'
        u'<button type="button" class="ui-bt" onclick="%(pro)s(this)">'
        u'@ICO_PASTA@<span data-radai-frase>Procurar…</span></button></div>'
        u'<div class="bg-carga-linha">'
        u'<button type="button" class="ui-bt pri" id="%(p)s_carregar" '
        u'onclick="%(car)s()"><span data-radai-frase>Carregar pasta</span>'
        u'</button></div></div></section>'
        u'<div id="%(p)s_msg" class="bg-msg" role="status" aria-live="polite"></div>'
        % {"p": p, "car": ao_carregar, "pro": ao_procurar, "rot": rotulo}
        + QUADRO_DO_CD)


def botao_limpar(p, ao_limpar):
    return (u'<button type="button" class="ui-bt bg-limpar" id="%s_limpar" '
            u'onclick="%s()">@ICO_FECHAR@<span data-radai-frase>Limpar '
            u'carregamentos</span></button>' % (p, ao_limpar))


def destinos(com_origem):
    return (
        u'<div class="bg-destinos">'
        u'<div class="bg-rot" data-radai-frase>Pasta de destino</div>'
        u'<ul class="bg-dest-lista" id="bg_dest_lista" tabindex="-1"></ul>'
        u'<div class="bg-dest-bts">'
        + (u'<button type="button" class="ui-bt" id="bg_dest_origem" hidden '
           u'onclick="bgAdicionarOrigem()">@ICO_MAIS@<span data-radai-frase>'
           u'Pasta de origem do estudo</span></button>' if com_origem else u"")
        + u'<button type="button" class="ui-bt" id="bg_dest_mais" '
        u'onclick="bgAdicionarDestino(this)">@ICO_MAIS@<span data-radai-frase>'
        u'Adicionar outro destino</span></button></div></div>')


def etapa(n, ident, titulo, corpo, direita=u"", oculta=True):
    return (u'<section class="pp-etapa" id="%s" data-etapa="%d"%s>'
            u'<div class="pp-cab"><h2><span class="n">%d</span>'
            u'<span data-radai-frase>%s</span></h2>%s</div>%s</section>'
            % (ident, n, u" hidden" if oculta else u"", n, titulo,
               (u'<div class="pp-dir">%s</div>' % direita) if direita else u"",
               corpo))


def _fronteira():
    try:
        import radai_review
        return (radai_review.CSS_DA_FRONTEIRA,
                radai_review.tag_da_fronteira(u"dc_fronteira"))
    except Exception:
        return u"", u""


def _corpo(fronteira):
    e1 = etapa(1, u"dc_e1", u"Carregar",
               carga(u"dc", u"dcVarrer", u"dcProcurar", u"dcLimparTudo",
                     u"ou aponte a pasta do estudo"),
               direita=botao_limpar(u"dc", u"dcLimparTudo"), oculta=False)
    e2 = etapa(2, u"dc_e2", u"Escolher as séries", (
        u'<div class="dc-ferr">'
        u'<button type="button" class="ui-bt" id="dc_marcar_todas" disabled '
        u'onclick="dcMarcarTodas()"><span data-radai-frase>Marcar todas</span>'
        u'</button>'
        u'<button type="button" class="ui-bt" id="dc_limpar_marc" disabled '
        u'onclick="dcLimparMarcacao()"><span data-radai-frase>Limpar '
        u'marca&ccedil;&atilde;o</span></button>'
        u'<span class="pp-sub" data-radai-frase>clique marca &middot; duplo '
        u'clique abre a s&eacute;rie</span></div>'
        u'<div class="dc-grade" id="dc_grade" style="margin-top:12px"></div>'
        u'<div class="dc-marcadas" id="dc_marcadas"></div>'
        u'<div class="pp-acoes">'
        u'<button type="button" class="ui-bt pri" id="dc_avancar" disabled '
        u'onclick="dcAvancar()"><span data-radai-frase>Avan&ccedil;ar</span>'
        u'@ICO_DIREITA@</button></div>'),
        direita=u'<span class="dc-cont" id="dc_cont"></span>')
    e3 = etapa(3, u"dc_e3", u"Diagnóstico", (
        u'<div class="dc-diag">'
        u'<div class="dc-diag-lista" id="dc_diag_lista"></div>'
        u'<div class="dc-diag-serie">'
        u'<h3 class="dc-titulo" id="dc_titulo"></h3>'
        u'<div id="dc_bloco_imagem" hidden>' + radai_image_screen.ajuste()
        + u'</div><div id="dc_bloco_dicom">'
        u'<div class="dc-visor" id="dc_visor"></div>'
        u'<div class="dc-janelas" id="dc_janelas">'
        u'<button type="button" id="dcj_auto" class="dc-jan" '
        u'onclick="dcJanela(\'auto\')" data-radai-frase>autom&aacute;tica</button>'
        u'<button type="button" id="dcj_mediastino" class="dc-jan sel" '
        u'onclick="dcJanela(\'mediastino\')" data-radai-frase>mediastino</button>'
        u'<button type="button" id="dcj_pulmao" class="dc-jan" '
        u'onclick="dcJanela(\'pulmao\')" data-radai-frase>pulm&atilde;o</button>'
        u'<button type="button" id="dcj_osso" class="dc-jan" '
        u'onclick="dcJanela(\'osso\')" data-radai-frase>osso</button></div>'
        u'<div id="dc_laudo"></div></div>'
        u'<div class="dc-outras" id="dc_outras" hidden></div></div></div>'
        u'<div class="pp-acoes">'
        u'<button type="button" class="ui-bt pri" id="dc_converter" disabled '
        u'onclick="dcConverter()"><span data-radai-frase>Converter</span>'
        u'@ICO_DIREITA@</button><span class="pp-sub" id="dc_conv_sub"></span>'
        u'</div>'),
        direita=(u'<button type="button" class="ui-bt" id="dc_ant" '
                 u'onclick="dcAnterior()" hidden>@ICO_ESQUERDA@<span '
                 u'data-radai-frase>s&eacute;rie anterior</span></button>'
                 u'<span class="dc-cont" id="dc_nav_pos"></span>'
                 u'<button type="button" class="ui-bt" id="dc_prox" '
                 u'onclick="dcProxima()" hidden><span data-radai-frase>'
                 u'pr&oacute;xima s&eacute;rie</span>@ICO_DIREITA@</button>'))
    e4 = etapa(4, u"dc_e4", u"Converter", u'<div id="dc_conv"></div>')
    e5 = etapa(5, u"dc_e5", u"Entregar", (
        destinos(True)
        + fronteira
        + u'<div class="pp-acoes">'
        u'<button type="button" class="ui-bt pri" id="dc_entregar" disabled '
        u'onclick="dcEntregar()"><span data-radai-frase>Entregar</span>'
        u'@ICO_DIREITA@</button><span class="pp-sub" id="dc_ent_sub"></span>'
        u'</div><div id="dc_ent"></div>'))
    e6 = etapa(6, u"dc_e6", u"Segmentar",
               u'<div class="dc-filas" id="dc_fila" role="status" '
               u'aria-live="polite"></div>')
    return e1 + e2 + e3 + e4 + e5 + e6


def pagina():
    import radai_ui
    css_f, tag_f = _fronteira()
    cabeca = radai_ui.cabeca_de_funcao(
        u"exportar", u"Converter imagens para o TPS", FRASE,
        radai_ui.ajuda(*AJUDA), u"bridge")
    css = (radai_viewer.CSS_UM_EIXO + CSS_COMUM + CSS + radai_image_screen.CSS
           + css_f)
    js = radai_viewer.JS_UM_EIXO + JS_COMUM + JS
    return (PAGINA.replace(u"@CSS@", css)
            .replace(u"@CABECA@", cabeca)
            .replace(u"@CORPO@", _corpo(tag_f))
            .replace(u"@ALERTA@", radai_ui.alerta(ALERTA))
            .replace(u"@JS@", js))


PAGINA = u"""<!doctype html><html><head><meta charset="utf-8">
<title>DicomBridge &middot; Radioterapia.AI Local</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>@CSS@</style></head><body>
<div class="dc-wrap">
@CABECA@
@CORPO@
@ALERTA@
</div>
<script>@JS@</script>
</body></html>"""


def _cab(t):
    return (t or u"").encode("ascii", "replace").decode("ascii")[:200]


TITULO_DO_TEXTO_DECLARADO = (u"O cabeçalho declara texto gravado na imagem "
                             u"(pode conter identificação)")
TITULO_DA_CAPTURA = (u"Captura secundária: pode haver texto do visualizador "
                     u"gravado na imagem (pode conter identificação)")


def _anotacao_queimada(caminho):
    try:
        import pydicom
        ds = pydicom.dcmread(caminho, stop_before_pixels=True, force=True,
                             specific_tags=[(0x0028, 0x0301)])
        return str(getattr(ds, "BurnedInAnnotation", "") or "").strip().upper()
    except Exception:
        return u""


def texto_no_pixel(serie):
    arqs = serie.get("arquivos") or []
    if not arqs:
        return []
    # GUARDA: a varredura lê o BurnedInAnnotation de todo corte; só arquivo de fora dela é aberto aqui.
    valores = set(a["anotacao"] if "anotacao" in a
                  else _anotacao_queimada(a.get("caminho")) for a in arqs)
    if "YES" in valores:
        titulo = TITULO_DO_TEXTO_DECLARADO
    elif serie.get("captura") and "NO" not in valores:
        titulo = TITULO_DA_CAPTURA
    else:
        return []
    # GUARDA: só alerta; recortar mudaria a geometria da fusão.
    return [{"ok": False, "titulo": titulo, "detalhe": u"", "resolve": None,
             "o_que_faz": u"", "alerta": True, "impede": False}]


def laudo_da_serie(serie):
    import radai_dicom
    laudo = radai_dicom.conferir(serie)
    extra = texto_no_pixel(serie)
    if extra:
        laudo["achados"] = list(laudo.get("achados") or []) + extra
        laudo["alertas"] = [a["titulo"] for a in laudo["achados"]
                            if a.get("alerta")]
        laudo["n_alertas"] = len(laudo["alertas"])
    return laudo


TETO_DE_GUARDAS = 64
VALIDADE_DA_GUARDA_S = 24 * 3600.0
CAMPOS_DO_ITEM = ("pasta", "uid", "modo", "chaves", "copiar_rs_para",
                  "origem", "rotulo")
_TRAVA = threading.Lock()
_ENTREGUES = {}
_GUARDAS = {}


def _chave_da_pasta(p):
    import radai_bridge_entrada as E
    return os.path.normcase(os.path.abspath(E.sem_prefixo(str(p or u""))))


def _vencer(agora):
    for tabela in (_GUARDAS, _ENTREGUES):
        for k in [k for k, v in tabela.items()
                  if agora - (v[0] if isinstance(v, tuple) else v)
                  > VALIDADE_DA_GUARDA_S]:
            del tabela[k]
    while len(_GUARDAS) > TETO_DE_GUARDAS:
        del _GUARDAS[min(_GUARDAS, key=lambda k: _GUARDAS[k][0])]
    while len(_ENTREGUES) > 16 * TETO_DE_GUARDAS:
        del _ENTREGUES[min(_ENTREGUES, key=lambda k: _ENTREGUES[k])]


def anotar_entrega(series):
    agora = time.time()
    with _TRAVA:
        _vencer(agora)
        for s in series or ():
            for p in [s.get("pasta")] + list(s.get("copias") or ()):
                if p:
                    _ENTREGUES[_chave_da_pasta(p)] = agora


def guardar_itens(itens):
    if not isinstance(itens, (list, tuple)) or not itens:
        return u""
    limpos = []
    with _TRAVA:
        for it in itens:
            if not isinstance(it, dict):
                return u""
            pastas = [it.get("pasta")] + list(it.get("copiar_rs_para") or ())
            # GUARDA: só se guarda o que esta tela entregou; a conferência
            # lista estas pastas no disco.
            if not it.get("uid") or not all(
                    p and _chave_da_pasta(p) in _ENTREGUES for p in pastas):
                return u""
            limpos.append(dict((k, it[k]) for k in CAMPOS_DO_ITEM if k in it))
        guarda = secrets.token_hex(16)
        _GUARDAS[guarda] = (time.time(), limpos)
        _vencer(time.time())
    return guarda


def itens_da_guarda(guarda):
    with _TRAVA:
        v = _GUARDAS.get(str(guarda or u""))
    return [dict(x) for x in v[1]] if v else None


def _quais(quais, n):
    fora = []
    for i in quais or ():
        try:
            k = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= k < n and k not in fora:
            fora.append(k)
    return fora


def _rs_ao_lado(pasta, uid):
    import radai_bridge_entrada as E
    try:
        nomes = os.listdir(E.no_disco(pasta))
    except OSError:
        return 0
    try:
        import radai_sets
        return len(list(radai_sets.arquivos_da_serie(nomes, uid)))
    except Exception:
        cauda = u"_%s.dcm" % (u"%s" % uid)[-8:].lower()
        return len([n for n in nomes
                    if n.startswith(u"RS_RadAI_") and n.lower().endswith(cauda)])


def conferir_guarda(guarda, quais):
    itens = itens_da_guarda(guarda)
    if itens is None:
        return None
    fora = []
    for i in _quais(quais, len(itens)):
        it = itens[i]
        copias = [bool(_rs_ao_lado(p, it["uid"]))
                  for p in it.get("copiar_rs_para") or ()]
        fora.append({"i": i, "rs": bool(_rs_ao_lado(it["pasta"], it["uid"])),
                     "copias": sum(copias), "de": len(copias)})
    return fora


def de_novo(guarda, quais):
    itens = itens_da_guarda(guarda)
    if itens is None:
        return {"ok": False, "sem_guarda": True,
                "erro": u"a entrega não está mais guardada nesta estação"}
    alvo = _quais(quais, len(itens))
    if not alvo:
        return {"ok": False, "erro": u"nenhuma série para pôr de novo"}
    try:
        import radai_queue_state
    except Exception:
        return {"ok": False, "indisponivel": True, "erro": u"fila indisponível"}
    return radai_queue_state.enfileirar([itens[i] for i in alvo])


def montar(app):
    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    try:
        import radai_bridge_entrada
        radai_bridge_entrada.faxina()
    except Exception:
        pass

    @app.get("/bridge/laudo", response_class=HTMLResponse)
    def _tela():
        return radai_menu.aplicar(pagina(), "bridge_laudo")

    # GUARDA: o endereço antigo continua valendo — favorito e histórico levam ao pipeline.
    @app.get("/bridge/tps")
    def _tela_tps():
        return RedirectResponse(url="/bridge/laudo", status_code=307)

    @app.get("/bridge/imagem")
    def _tela_imagem():
        return RedirectResponse(url="/bridge/laudo", status_code=307)

    try:
        radai_image_screen.montar(app)
    except Exception as e:
        import sys as _sys
        _sys.stderr.write(
            "[bridge] as rotas do ajuste de imagem nao subiram: %s: %s\n"
            % (type(e).__name__, str(e)[:160]))

    def _pasta_real(pasta):
        import radai_bridge_entrada as E
        return E.pasta_real(pasta)

    def _serie(pasta, b):
        import radai_dicom
        import radai_thumbnail
        r = radai_dicom.varrer(_pasta_real(pasta))
        try:
            _p, uid = radai_thumbnail.resolver(b)
        except Exception:
            uid = None
        if uid:
            for x in r["series"]:
                if str(x.get("uid") or "") == str(uid):
                    return x
        return None

    def _origem(digitada):
        import radai_bridge_entrada as E
        d = str(digitada or "").strip()
        if not d:
            return u""
        try:
            # GUARDA: a pasta da área de envio pode vir com o prefixo de
            # caminho longo; sem tirá-lo, a comparação falha e a temporária
            # vira pasta de origem.
            if E.mesma_arvore(E.raiz(), d):
                return u""
        except Exception:
            pass
        d = E.sem_prefixo(d)
        if E.e_cd(d):
            return u""
        if d.lower().endswith(".zip") and os.path.isfile(E.no_disco(d)):
            return os.path.dirname(os.path.abspath(d))
        return d if os.path.isdir(E.no_disco(d)) else u""

    @app.post("/api/bridge/varrer")
    async def _varrer(request: Request):
        try:
            c = await request.json() or {}
            digitada = str(c.get("pasta") or "")
            try:
                pasta = await radai_web.no_threadpool(_pasta_real, digitada)
            except Exception as e:
                return {"erro": u"não consegui abrir o .zip: %s" % str(e)[:160]}
            if not os.path.isdir(pasta):
                return {"erro": u"a pasta não existe: %s" % pasta[-120:]}
            import radai_bridge_entrada as E
            import radai_dicom
            import radai_image
            import radai_thumbnail
            r = None
            if c.get("leitura"):
                r = await radai_web.no_threadpool(
                    E.varredura_do_cd, str(c.get("leitura") or ""), pasta)
            if r is None:
                radai_dicom.esquecer_varredura(pasta)
                r = await radai_web.no_threadpool(radai_dicom.varrer, pasta)
            bilhetes = radai_thumbnail.registrar_series(pasta, r["series"])
            series = [{"uid": s["uid"][-12:], "descricao": s["descricao"],
                       "modalidade": s["modalidade"],
                       "numero": s["numero"], "cortes": s["cortes"],
                       "espessura_mm": s.get("espessura_mm"),
                       "colorida": bool(s.get("colorida")),
                       "captura": bool(s.get("captura")),
                       "sem_imagem": (str(s.get("modalidade") or "").upper()
                                      in radai_thumbnail.SEM_IMAGEM),
                       "janela": radai_thumbnail.janela_do_visor(
                           s["modalidade"]),
                       "central": radai_thumbnail.central(s["cortes"]),
                       "cranial": radai_thumbnail.sentido_cranial(s),
                       "bilhete": bilhetes.get(s["uid"])}
                      for s in r["series"]]
            imagens, _n = await radai_web.no_threadpool(
                radai_image_screen.series_da_arvore, pasta)
            ignorados = [n for n, _m in r["ignorados"]
                         if not str(n).lower().endswith(radai_image.EXTENSOES)]
            return {"series": series, "ignorados": ignorados,
                    "imagens": [radai_image_screen.para_a_grade(x)
                                for x in imagens],
                    "origem": _origem(digitada)}
        except Exception as e:
            return {"erro": u"%s: %s" % (type(e).__name__, str(e)[:200])}

    @app.api_route("/api/bridge/miniatura", methods=["GET", "HEAD"])
    def _miniatura(b: str = "", request: Request = None):
        from fastapi.responses import Response
        import radai_thumbnail

        try:
            dados, info = radai_thumbnail.png_central(b)
        except Exception as e:
            return Response(status_code=500,
                            headers={"X-RadAI-Erro": _cab(type(e).__name__)})
        if not dados:
            return Response(status_code=(204 if info.get("sem_imagem") else 404),
                            headers={"X-RadAI-Erro": _cab(info.get("erro")),
                                     "X-RadAI-Modalidade":
                                     _cab(info.get("modalidade"))[:16]})
        etag = info.get("etag") or ""
        anterior = ""
        try:
            anterior = (request.headers.get("if-none-match") or "") if request else ""
        except Exception:
            anterior = ""
        cabs = {"ETag": _cab(etag),
                "Cache-Control": "private, max-age=86400",
                "X-RadAI-Corte": str(info.get("corte", 0)),
                "X-RadAI-Cortes": str(info.get("cortes", 0)),
                "X-RadAI-Origem": _cab(info.get("de") or "")}
        if anterior and etag and anterior.strip() == etag:
            return Response(status_code=304, headers=cabs)
        return Response(content=dados, media_type="image/png", headers=cabs)

    @app.get("/api/bridge/corte")
    def _corte(b: str = "", corte: int = 0, janela: str = "mediastino"):
        from fastapi.responses import Response
        import radai_thumbnail
        try:
            dados, info = radai_thumbnail.png(
                b, corte, janela, lado=radai_thumbnail.LADO_VISOR)
        except Exception as e:
            radai_thumbnail.registrar_falha(u"DicomBridge, corte do visor", e,
                                            bilhete=b)
            return Response(status_code=500,
                            headers={"X-RadAI-Erro": _cab(type(e).__name__)})
        if not dados:
            if info.get("sem_imagem"):
                status = 204
            elif info.get("cortes") is None:
                status = 404
            else:
                status = 422
            return Response(status_code=status,
                            headers={"X-RadAI-Erro": _cab(info.get("erro")),
                                     "X-RadAI-Modalidade":
                                     _cab(info.get("modalidade"))[:16]})
        return Response(content=dados, media_type="image/png", headers={
            "X-RadAI-Corte": str(info.get("corte", 0)),
            "X-RadAI-Cortes": str(info.get("cortes", 0)),
            "Cache-Control": "no-store"})

    @app.post("/api/bridge/laudo")
    async def _laudo(request: Request):
        try:
            c = await request.json() or {}
            import radai_dicom
            s = await radai_web.no_threadpool(
                _serie, str(c.get("pasta") or ""), str(c.get("b") or ""))
            if s is None:
                return {"erro": u"série não encontrada — recarregue a pasta"}
            laudo = await radai_web.no_threadpool(laudo_da_serie, s)
            laudo["cabecalho"] = radai_dicom.ler_cabecalho(
                s["arquivos"][0]["caminho"])
            return laudo
        except Exception as e:
            return {"erro": u"%s: %s" % (type(e).__name__, str(e)[:200])}

    def _converter_lote(pasta, pedidos):
        import radai_bridge_entrada as E
        import radai_dicom
        achadas = []
        for p in pedidos:
            b = str(p.get("b") or "")
            if isinstance(p.get("imagem"), dict):
                achadas.append((b, radai_image_screen.serie_do_bilhete(b)[0],
                                p["imagem"]))
            else:
                achadas.append((b, _serie(pasta, b), None))
        validas = [s for _b, s, im in achadas if s is not None and im is None]
        subs = dict(zip([id(s) for s in validas], radai_dicom.nomes_de_subpasta(
            [str(s.get("uid") or "") for s in validas])))
        token, base = E.nova_conversao()
        exportadas, recusadas, ids = [], [], []
        for b, s, im in achadas:
            if s is None:
                recusadas.append(u"série não encontrada — recarregue a pasta")
                continue
            if im is not None:
                k = len(ids) + 1
                sub = (radai_image_screen.PASTA_DA_SERIE if k == 1 else
                       u"%s_%d" % (radai_image_screen.PASTA_DA_SERIE, k))
                try:
                    r = radai_image_screen.converter_do_pedido(
                        s, os.path.join(base, sub), im)
                except Exception as e:
                    recusadas.append(u"%s: %s" % (
                        str(im.get("descricao") or u"imagem")[:60], str(e)[:160]))
                    continue
                ids.append(r["id_externo"])
                exportadas.append({"b": b, "sub": sub, "imagem": True,
                                   "descricao": str(im.get("descricao") or u""),
                                   "modalidade": r.get("modalidade") or u"",
                                   "cortes": r.get("gravados"), "uid8": u"",
                                   "id_externo": r["id_externo"],
                                   "alertas": list(r.get("alertas") or ())})
                continue
            sub = subs[id(s)]
            try:
                r = radai_dicom.converter(s, os.path.join(base, sub),
                                          laudo=laudo_da_serie(s))
            except Exception as e:
                recusadas.append(u"%s: %s" % (s.get("descricao") or u"série",
                                              str(e)[:160]))
                continue
            exportadas.append({"b": b, "sub": sub,
                               "descricao": s.get("descricao") or u"",
                               "modalidade": s.get("modalidade") or u"",
                               "cortes": r.get("cortes") or s.get("cortes"),
                               "uid8": str(s.get("uid") or "")[-8:],
                               "alertas": list(r.get("alertas") or ())})
        if not exportadas:
            E.esquecer_conversao(token)
            return {"erro": (recusadas[0] if recusadas
                             else u"nenhuma série convertida"),
                    "recusadas": recusadas}
        E.anotar_conversao(token, {
            "series": [(x["b"], x["sub"]) for x in exportadas], "ids": ids})
        return {"conversao": token, "exportadas": exportadas,
                "recusadas": recusadas}

    def _entregar_lote(token, destinos_pedidos):
        import radai_bridge_entrada as E
        import radai_dicom
        import radai_image
        base = E.pasta_da_conversao(token)
        if not base:
            return {"erro": u"a conversão não está mais aqui — converta de novo"}
        nota = E.anotacao_da_conversao(token) or {}
        subs = list(nota.get("series") or ())
        ids = list(nota.get("ids") or ())
        try:
            nome, pastas, falhas = E.entregar(
                base, destinos_pedidos, mover=True,
                linha_leia_me=radai_image.linha_do_leia_me(ids) if ids else u"")
        except E.EntradaRecusada as e:
            return {"erro": str(e)}
        E.esquecer_conversao(token)
        series = []
        for b, sub in subs:
            alvo = os.path.join(pastas[0], sub)
            try:
                rr = radai_dicom.varrer(alvo, False)
            except Exception:
                continue
            for x in rr["series"]:
                series.append({"b": b, "uid": x["uid"], "pasta": alvo,
                               "copias": [os.path.join(p, sub)
                                          for p in pastas[1:]]})
        anotar_entrega(series)
        return {"nome": nome,
                "saidas": [{"destino": os.path.dirname(p), "pasta": p}
                           for p in pastas],
                "falhas": [{"destino": d, "motivo": m} for d, m in falhas],
                "series": series, "ids_externos": ids}

    @app.post("/api/bridge/etapa/converter")
    async def _etapa_converter(request: Request):
        try:
            c = await request.json() or {}
            pedidos = [p for p in list(c.get("series") or ())
                       if isinstance(p, dict)]
            if not pedidos:
                return {"erro": u"nenhuma série pedida"}
            return await radai_web.no_threadpool(
                _converter_lote, str(c.get("pasta") or ""), pedidos)
        except Exception as e:
            return {"erro": u"%s: %s" % (type(e).__name__, str(e)[:200])}

    @app.post("/api/bridge/etapa/entregar")
    async def _etapa_entregar(request: Request):
        try:
            c = await request.json() or {}
            return await radai_web.no_threadpool(
                _entregar_lote, str(c.get("conversao") or ""),
                list(c.get("destinos") or ()))
        except Exception as e:
            return {"erro": u"%s: %s" % (type(e).__name__, str(e)[:200])}

    @app.post("/api/bridge/fila/guardar")
    async def _fila_guardar(request: Request):
        try:
            c = await request.json() or {}
            return {"guarda": guardar_itens(c.get("itens"))}
        except Exception as e:
            return {"guarda": u"", "erro": u"%s" % str(e)[:200]}

    @app.post("/api/bridge/fila/conferir")
    async def _fila_conferir(request: Request):
        try:
            c = await request.json() or {}
            r = await radai_web.no_threadpool(
                conferir_guarda, str(c.get("guarda") or ""),
                list(c.get("quais") or ()))
            if r is None:
                return {"ok": False, "sem_guarda": True}
            return {"ok": True, "series": r}
        except Exception as e:
            return {"ok": False, "erro": u"%s" % str(e)[:200]}

    @app.post("/api/bridge/fila/de_novo")
    async def _fila_de_novo(request: Request):
        try:
            c = await request.json() or {}
            return await radai_web.no_threadpool(
                de_novo, str(c.get("guarda") or ""),
                list(c.get("quais") or ()))
        except Exception as e:
            return {"ok": False, "erro": u"%s: %s" % (type(e).__name__,
                                                      str(e)[:200])}

    @app.post("/api/bridge/etapa/descartar")
    async def _etapa_descartar(request: Request):
        try:
            import radai_bridge_entrada as E
            c = await request.json() or {}
            return {"ok": E.esquecer_conversao(str(c.get("conversao") or ""))}
        except Exception as e:
            return {"ok": False, "erro": u"%s" % str(e)[:200]}

    @app.post("/api/bridge/receber")
    async def _receber(request: Request):
        # GUARDA: o caminho vem no cabeçalho e o pedaço no corpo do POST, nunca
        # na URL (caminho de paciente fora do histórico); pedaço abaixo de 16 MB.
        try:
            from urllib.parse import unquote
            import radai_bridge_entrada as E
            h = request.headers
            rel = unquote(str(h.get("x-radai-arquivo") or ""))
            if not rel:
                return {"erro": u"nenhum arquivo no envio"}
            dados = await request.body()
            r = await radai_web.no_threadpool(
                E.receber, str(h.get("x-radai-sessao") or ""), rel,
                int(h.get("x-radai-offset") or 0), dados)
            return r
        except Exception as e:
            return {"erro": u"%s" % str(e)[:200]}

    @app.post("/api/bridge/receber/fim")
    async def _receber_fim(request: Request):
        try:
            import radai_bridge_entrada as E
            c = await request.json() or {}
            return await radai_web.no_threadpool(
                E.concluir, str(c.get("sessao") or ""))
        except Exception as e:
            return {"erro": u"%s" % str(e)[:200]}

    @app.post("/api/bridge/limpar")
    async def _limpar(request: Request):
        try:
            import radai_bridge_entrada as E
            c = await request.json() or {}
            ok = await radai_web.no_threadpool(
                E.limpar, str(c.get("sessao") or ""))
            return {"ok": bool(ok)}
        except Exception as e:
            return {"ok": False, "erro": u"%s" % str(e)[:200]}

    @app.get("/api/bridge/destinos")
    def _destinos():
        import radai_bridge_entrada as E
        return {"downloads": E.pasta_downloads()}

    @app.post("/api/bridge/cd/drives")
    async def _cd_drives():
        try:
            return {"drives": await radai_web.no_threadpool(_E.drives_de_cd)}
        except Exception as e:
            return {"drives": [], "erro": u"%s" % str(e)[:200]}

    @app.post("/api/bridge/cd/ler")
    async def _cd_ler(request: Request):
        try:
            c = await request.json() or {}
            leitura = await radai_web.no_threadpool(
                _E.ler_cd, str(c.get("drive") or ""))
            return {"leitura": leitura}
        except _E.EntradaRecusada as e:
            return {"erro": str(e)}
        except Exception as e:
            return {"erro": u"%s: %s" % (type(e).__name__, str(e)[:200])}

    @app.post("/api/bridge/cd/estado")
    async def _cd_estado(request: Request):
        try:
            c = await request.json() or {}
            r = _E.estado_do_cd(str(c.get("leitura") or ""))
            return r if r is not None else {"erro": u"esta leitura não existe mais"}
        except Exception as e:
            return {"erro": u"%s" % str(e)[:200]}

    @app.post("/api/bridge/cd/parar")
    async def _cd_parar(request: Request):
        try:
            c = await request.json() or {}
            return {"ok": _E.parar_cd(str(c.get("leitura") or ""))}
        except Exception as e:
            return {"ok": False, "erro": u"%s" % str(e)[:200]}

    return app
