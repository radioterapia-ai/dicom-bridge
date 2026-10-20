# -*- coding: utf-8 -*-
import atexit
import hashlib
import io
import os
import re
import shutil
import threading
import time
import uuid
import zipfile

PASTA = "radai_bridge_entrada"
VALIDADE_S = 12 * 3600.0
TETO_ZIP_BYTES = 40 * 1024 ** 3
TETO_MEMBROS = 200000
TETO_PASTA = 32
TETO_NOME = 40
TETO_RELATIVO = 100
LIMITE_SEM_PREFIXO = 240
PREFIXO_CONVERSAO = "conv_"
_SESSAO = re.compile(r"^[0-9a-f]{32}$")
_EXTENSAO = re.compile(r"^\.[A-Za-z][A-Za-z0-9]{0,5}$")
_TRAVA = threading.Lock()
_ZIPS = {}
_SESSOES = {}
_CONVERSOES = {}
_ANOTACOES = {}


class EntradaRecusada(Exception):
    pass


def _com_prefixo(caminho):
    p = str(caminho or "")
    if os.name != "nt" or p.startswith("\\\\?\\"):
        return p
    cheio = os.path.abspath(p)
    if cheio.startswith("\\\\"):
        return "\\\\?\\UNC" + cheio[1:]
    return "\\\\?\\" + cheio


def no_disco(caminho):
    # GUARDA: sem o prefixo, o Windows sem caminho longo não acha o arquivo a
    # partir de 260 caracteres.
    p = str(caminho or "")
    if p.startswith("\\\\?\\") or len(os.path.abspath(p)) < LIMITE_SEM_PREFIXO:
        return p
    return _com_prefixo(p)


def sem_prefixo(caminho):
    p = str(caminho or "")
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


def mesma_arvore(raiz_, caminho):
    try:
        a = os.path.normcase(os.path.abspath(sem_prefixo(raiz_)))
        b = os.path.normcase(os.path.abspath(sem_prefixo(caminho)))
        return os.path.commonpath([a, b]) == a
    except ValueError:
        return False


def apagar(pasta):
    shutil.rmtree(_com_prefixo(pasta), ignore_errors=True)
    return not os.path.exists(_com_prefixo(pasta))


def _impressao(texto, n=10):
    return hashlib.sha1(str(texto).encode("utf-8", "replace")).hexdigest()[:n]


def _pasta_curta(nome):
    return nome if len(nome) <= TETO_PASTA else u"d" + _impressao(nome)


def nome_curto(nome):
    # GUARDA: a extensão e o número final ficam; a extração reconhece o .zip
    # pela extensão, e a série de imagem se agrupa e se ordena pelo número.
    if len(nome) <= TETO_NOME:
        return nome
    base, ext = os.path.splitext(nome)
    if not _EXTENSAO.match(ext):
        base, ext = nome, u""
    m = re.search(r"\d{1,12}$", base)
    if m and m.start() > 0:
        return u"n%s_%s%s" % (_impressao(base[:m.start()]), m.group(0), ext)
    return u"n%s%s" % (_impressao(base, 16), ext)


def partes_curtas(relativo):
    partes = partes_seguras(relativo)
    pastas = [_pasta_curta(p) for p in partes[:-1]]
    nome = nome_curto(partes[-1])
    if len(u"/".join(pastas + [nome])) > TETO_RELATIVO:
        ultima = partes[-2] if len(partes) > 1 and len(partes[-2]) <= 20 else u""
        pastas = [u"d" + _impressao(u"/".join(partes[:-1]), 8)
                  + (u"_" + ultima if ultima else u"")]
    return pastas + [nome]


def pasta_de_leitura(base):
    if len(os.path.abspath(str(base))) + TETO_RELATIVO + 20 >= LIMITE_SEM_PREFIXO:
        return _com_prefixo(base)
    return base


def raiz(criar=True):
    import radai_archive
    base = os.path.join(radai_archive.pasta_temporaria_local(
        marcar_ambiente=False), PASTA)
    nuvem, motivo = radai_archive.em_pasta_sincronizada(base)
    if nuvem:
        raise EntradaRecusada(u"a pasta de trabalho sincroniza com a nuvem "
                              u"(%s)" % motivo)
    if criar:
        os.makedirs(base, exist_ok=True)
    return base


def _raizes_de_entrada():
    import radai_archive
    saida = []
    for r in radai_archive.raizes_temporarias():
        p = os.path.join(r, PASTA)
        if os.path.isdir(p) and p not in saida:
            saida.append(p)
    return saida


def _pasta_da_sessao(sessao, criar=True):
    if not _SESSAO.match(str(sessao or "")):
        raise EntradaRecusada(u"sessão de envio inválida")
    # GUARDA: a sessão fica na base em que nasceu; as partes seguintes, o
    # `concluir` e o `limpar` não seguem uma escolha de disco nova.
    with _TRAVA:
        base = _SESSOES.get(str(sessao))
    if not base:
        base = raiz(criar=criar)
    return os.path.join(base, str(sessao))


def partes_seguras(relativo):
    # GUARDA: caminho absoluto, unidade, `..` ou nome vazio levantam; o que
    # chega do navegador nunca escreve fora da pasta da sessão.
    t = str(relativo or "").replace("\\", "/")
    if not t or t.startswith("/") or re.match(r"^[A-Za-z]:", t):
        raise EntradaRecusada(u"caminho do arquivo enviado inválido")
    partes = [p for p in t.split("/") if p not in ("", ".")]
    if not partes or any(p == ".." or ":" in p or "\x00" in p
                         for p in partes):
        raise EntradaRecusada(u"caminho do arquivo enviado inválido")
    return partes


def receber(sessao, relativo, offset, dados):
    partes = partes_curtas(relativo)
    if not sessao:
        sessao = uuid.uuid4().hex
        faxina()
    base = _pasta_da_sessao(sessao)
    with _TRAVA:
        _SESSOES.setdefault(str(sessao), os.path.dirname(base))
    alvo = os.path.join(base, *partes)
    if not os.path.abspath(alvo).startswith(os.path.abspath(base) + os.sep):
        raise EntradaRecusada(u"caminho do arquivo enviado inválido")
    os.makedirs(no_disco(os.path.dirname(alvo)), exist_ok=True)
    pos = max(0, int(offset or 0))
    modo = "wb" if pos == 0 or not os.path.exists(no_disco(alvo)) else "r+b"
    with open(no_disco(alvo), modo) as f:
        f.seek(pos)
        f.write(dados or b"")
    return {"sessao": sessao, "bytes": pos + len(dados or b"")}


def concluir(sessao):
    base = _pasta_da_sessao(sessao, criar=False)
    if not os.path.isdir(no_disco(base)):
        raise EntradaRecusada(u"nada foi recebido nesta sessão")
    abertos = 0
    zips = []
    for r, _d, arqs in os.walk(no_disco(base)):
        zips += [os.path.join(r, a) for a in arqs if a.lower().endswith(".zip")]
    for z in zips:
        extrair(z, os.path.join(base, u"z" + _impressao(z, 8)))
        try:
            os.remove(z)
        except Exception:
            pass
        abertos += 1
    return {"pasta": pasta_de_leitura(base), "zips": abertos}


def limpar(sessao):
    base = _pasta_da_sessao(sessao, criar=False)
    if not os.path.isdir(base):
        return False
    if not apagar(base):
        return False
    with _TRAVA:
        _SESSOES.pop(str(sessao), None)
    return True


def nova_conversao():
    token = uuid.uuid4().hex
    pasta = os.path.join(raiz(), PREFIXO_CONVERSAO + token)
    os.makedirs(pasta)
    with _TRAVA:
        _CONVERSOES[token] = pasta
    return token, pasta


def pasta_da_conversao(token):
    if not _SESSAO.match(str(token or "")):
        return None
    with _TRAVA:
        p = _CONVERSOES.get(str(token))
    return p if p and os.path.isdir(p) else None


def anotar_conversao(token, dados):
    with _TRAVA:
        if str(token or "") in _CONVERSOES:
            _ANOTACOES[str(token)] = dados


def anotacao_da_conversao(token):
    with _TRAVA:
        return _ANOTACOES.get(str(token or ""))


def esquecer_conversao(token):
    with _TRAVA:
        p = _CONVERSOES.pop(str(token or ""), None)
        _ANOTACOES.pop(str(token or ""), None)
    if p:
        apagar(p)
    return bool(p)


def extrair(caminho_zip, destino):
    # GUARDA: membro com caminho inseguro é pulado, nunca escrito fora do
    # destino; há teto de tamanho e de número de membros.
    os.makedirs(no_disco(destino), exist_ok=True)
    base = os.path.abspath(destino)
    n, total = 0, 0
    with zipfile.ZipFile(no_disco(caminho_zip)) as z:
        membros = z.infolist()
        if len(membros) > TETO_MEMBROS:
            raise EntradaRecusada(u"o .zip tem arquivos demais")
        for m in membros:
            if m.is_dir():
                continue
            try:
                partes = partes_curtas(m.filename)
            except EntradaRecusada:
                continue
            alvo = os.path.abspath(os.path.join(base, *partes))
            if not alvo.startswith(base + os.sep):
                continue
            total += int(m.file_size or 0)
            if total > TETO_ZIP_BYTES:
                raise EntradaRecusada(u"o .zip é grande demais para abrir")
            os.makedirs(no_disco(os.path.dirname(alvo)), exist_ok=True)
            with z.open(m) as fo, open(no_disco(alvo), "wb") as fd:
                shutil.copyfileobj(fo, fd, 1024 * 1024)
            n += 1
    return n


def abrir_zip(caminho):
    c = os.path.abspath(str(caminho))
    st = os.stat(c)
    chave = u"%s|%d|%d" % (c.lower(), st.st_size, int(st.st_mtime))
    with _TRAVA:
        pronto = _ZIPS.get(chave)
    if pronto and os.path.isdir(pronto):
        return pasta_de_leitura(pronto)
    nome = "zip_" + hashlib.sha256(chave.encode("utf-8")).hexdigest()[:24]
    destino = os.path.join(raiz(), nome)
    if os.path.isdir(destino):
        apagar(destino)
    extrair(c, destino)
    with _TRAVA:
        _ZIPS[chave] = destino
    return pasta_de_leitura(destino)


def pasta_real(pasta):
    p = str(pasta or "")
    if p.lower().endswith(".zip") and os.path.isfile(p):
        return abrir_zip(p)
    return p


def faxina(agora=None):
    agora = time.time() if agora is None else agora
    n = 0
    try:
        bases = _raizes_de_entrada()
    except Exception:
        bases = []
    for base in bases:
        try:
            for nome in os.listdir(base):
                cheio = os.path.join(base, nome)
                try:
                    if agora - os.path.getmtime(cheio) > VALIDADE_S:
                        apagar(cheio)
                        n += 1
                except Exception:
                    pass
        except Exception:
            pass
    return n


def _apagar_aberturas():
    with _TRAVA:
        pastas = list(_ZIPS.values()) + list(_CONVERSOES.values())
        _ZIPS.clear()
        _CONVERSOES.clear()
        _ANOTACOES.clear()
    for p in pastas:
        apagar(p)


def _ao_sair():
    _apagar_aberturas()
    with _TRAVA:
        sessoes = list(_SESSOES.items())
        _SESSOES.clear()
    for sessao, base in sessoes:
        try:
            p = os.path.join(base, str(sessao))
            if _SESSAO.match(str(sessao)) and os.path.isdir(p):
                apagar(p)
        except Exception:
            pass


atexit.register(_ao_sair)


def pasta_downloads():
    if os.name == "nt":
        try:
            import ctypes
            import uuid as _u

            class _GUID(ctypes.Structure):
                _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort),
                            ("d3", ctypes.c_ushort),
                            ("d4", ctypes.c_ubyte * 8)]
            g = _u.UUID("374DE290-123F-4565-9164-39C4925E467B")
            guid = _GUID(g.fields[0], g.fields[1], g.fields[2],
                         (ctypes.c_ubyte * 8)(*g.bytes[8:]))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(guid), 0, None, ctypes.byref(p)) == 0:
                valor = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                if valor:
                    return valor
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


DRIVE_CDROM = 5
_SEM_DIALOGO_DE_DISCO = 0x0001 | 0x8000
TETO_DE_LEITURAS_DE_CD = 4
INTERVALO_DO_CD_MS = 700
_LEITURAS_DE_CD = {}


def _kernel32():
    import ctypes
    return ctypes.windll.kernel32


def _letras():
    try:
        mascara = int(_kernel32().GetLogicalDrives())
    except Exception:
        return []
    return [u"%s:\\" % chr(65 + i) for i in range(26) if mascara & (1 << i)]


def _tipo_do_drive(raiz):
    try:
        return int(_kernel32().GetDriveTypeW(raiz))
    except Exception:
        return 0


def _tem_midia(raiz):
    import ctypes
    try:
        k = _kernel32()
    except Exception:
        return False
    antigo = ctypes.c_uint(0)
    try:
        # GUARDA: sem este modo de erro da thread, o drive de CD vazio abre uma caixa de dialogo modal do Windows e trava a leitura.
        trocou = bool(k.SetThreadErrorMode(_SEM_DIALOGO_DE_DISCO,
                                           ctypes.byref(antigo)))
    except Exception:
        trocou = False
    try:
        rotulo = ctypes.create_unicode_buffer(261)
        return bool(k.GetVolumeInformationW(ctypes.c_wchar_p(raiz), rotulo, 261,
                                            None, None, None, None, 0))
    except Exception:
        return False
    finally:
        if trocou:
            try:
                k.SetThreadErrorMode(antigo.value, None)
            except Exception:
                pass


def drives_de_cd():
    return [r for r in _letras()
            if _tipo_do_drive(r) == DRIVE_CDROM and _tem_midia(r)]


def e_cd(caminho):
    unidade = os.path.splitdrive(sem_prefixo(str(caminho or u"")))[0]
    if len(unidade) != 2 or unidade[1] != u":":
        return False
    return _tipo_do_drive(unidade.upper() + u"\\") == DRIVE_CDROM


def _ler_o_cd(v):
    import radai_dicom
    juncao = radai_dicom.nova_juncao()
    try:
        radai_dicom.buscar_series(v["raiz"], busca=v,
                                  pular=radai_dicom.pasta_pulada,
                                  juncao=juncao)
        if not (v.get("parado") or v.get("cortada")):
            v["varredura"] = (radai_dicom.carimbo_da_arvore(v["raiz"]),
                              radai_dicom.varredura_da_juncao(juncao))
    except Exception as e:
        v["erro"] = u"%s: %s" % (type(e).__name__, str(e)[:160])
    finally:
        v["fim"] = True


def _mesma_pasta(a, b):
    def n(p):
        return os.path.normcase(os.path.abspath(sem_prefixo(str(p or u""))))
    return bool(str(a or u"").strip()) and n(a) == n(b)


def varredura_do_cd(leitura, pasta):
    import radai_dicom
    with _TRAVA:
        v = _LEITURAS_DE_CD.get(str(leitura or u""))
        if v is None or not v.get("fim") or not _mesma_pasta(v.get("raiz"), pasta):
            return None
        par = v.pop("varredura", None)
    if par is None:
        return None
    carimbo, r = par
    # GUARDA: o disco trocado entre a leitura e a carga muda o carimbo das pastas, e a carga volta a ler o disco.
    if carimbo is None or radai_dicom.carimbo_da_arvore(pasta) != carimbo:
        return None
    radai_dicom.lembrar_varredura(pasta, carimbo, r)
    return r


def ler_cd(raiz, em_segundo_plano=True):
    import radai_dicom
    raiz = str(raiz or u"")
    if raiz not in drives_de_cd():
        raise EntradaRecusada(u"este drive não tem um CD")
    v = radai_dicom.nova_busca()
    v.update({"leitura": uuid.uuid4().hex, "raiz": raiz, "fim": False,
              "erro": None})
    with _TRAVA:
        prontas = [k for k, x in _LEITURAS_DE_CD.items() if x.get("fim")]
        while prontas and len(_LEITURAS_DE_CD) >= TETO_DE_LEITURAS_DE_CD:
            _LEITURAS_DE_CD.pop(prontas.pop(0), None)
        _LEITURAS_DE_CD[v["leitura"]] = v
    if em_segundo_plano:
        threading.Thread(target=_ler_o_cd, args=(v,), daemon=True,
                         name="radai_bridge_cd").start()
    else:
        _ler_o_cd(v)
    return v["leitura"]


def estado_do_cd(leitura):
    with _TRAVA:
        v = _LEITURAS_DE_CD.get(str(leitura or u""))
    if v is None:
        return None
    return {"raiz": v["raiz"], "pastas": int(v.get("pastas") or 0),
            "arquivos": int(v.get("arquivos") or 0),
            "series": len(v.get("series") or ()), "fim": bool(v.get("fim")),
            "parado": bool(v.get("parado")), "erro": v.get("erro")}


def parar_cd(leitura):
    with _TRAVA:
        v = _LEITURAS_DE_CD.get(str(leitura or u""))
    if v is None:
        return False
    v["parado"] = True
    return True


def _dentro_do_root_do_vigia(destino):
    try:
        import radai_config
        root = radai_config.chave_configurada("ROOT")
    except Exception:
        root = ""
    if not str(root or "").strip() or not str(destino or "").strip():
        return False
    try:
        a = os.path.normcase(os.path.abspath(root))
        b = os.path.normcase(os.path.abspath(destino))
        return os.path.commonpath([a, b]) == a
    except ValueError:
        return False


def conferir_destinos(destinos):
    import radai_archive
    fora = []
    for d in destinos or ():
        d = str(d or "").strip()
        if d and d not in fora:
            fora.append(d)
    if not fora:
        fora = [pasta_downloads()]
    for destino in fora:
        nuvem, motivo = radai_archive.em_pasta_sincronizada(destino)
        if nuvem:
            raise EntradaRecusada(
                u"o destino sincroniza com a nuvem (%s): escolha uma pasta "
                u"fora dessa raiz — %s" % (motivo, destino[-80:]))
        if _dentro_do_root_do_vigia(destino):
            raise EntradaRecusada(
                u"o destino fica dentro da pasta que o vigia processa: gravar "
                u"ali é escrever no share de produção. Escolha uma pasta fora "
                u"dela — %s" % destino[-80:])
    return fora


def _nome_livre(destinos, agora=None):
    nome = nome_saida(destinos[0], agora)
    base, k = nome, 1
    while any(os.path.exists(os.path.join(d, nome))
              or os.path.exists(os.path.join(d, nome + ".zip"))
              for d in destinos):
        k += 1
        nome = u"%s_%d" % (base, k)
    return nome


def _motivo(e):
    if isinstance(e, shutil.Error):
        n = len(e.args[0]) if e.args and isinstance(e.args[0], list) else 0
        return u"%d arquivo(s) não copiaram" % n if n else u"a cópia parou"
    t = getattr(e, "strerror", None)
    return (u"%s" % t) if t else type(e).__name__


def _por_no_primeiro(origem, alvo, mover):
    if mover:
        try:
            os.rename(no_disco(origem), no_disco(alvo))
            return
        except OSError:
            if os.path.exists(no_disco(alvo)):
                raise
    shutil.copytree(no_disco(origem), no_disco(alvo))
    if mover:
        apagar(origem)


def entregar(origem, destinos, linha_leia_me=u"", mover=False):
    destinos = conferir_destinos(destinos)
    falhas = []
    validos = []
    for d in destinos:
        try:
            os.makedirs(d, exist_ok=True)
            validos.append(d)
        except OSError as e:
            falhas.append((d, _motivo(e)))
    nome = _nome_livre(validos) if validos else u""
    pastas = []
    # GUARDA: com mover, a origem só sai depois de uma cópia inteira; o
    # destino que falha perde a pasta pela metade e o próximo vira o primeiro.
    for d in validos:
        p = os.path.join(d, nome)
        try:
            if not pastas:
                _por_no_primeiro(origem, p, mover)
            else:
                shutil.copytree(no_disco(pastas[0]), no_disco(p))
            pastas.append(p)
        except Exception as e:
            apagar(p)
            falhas.append((d, _motivo(e)))
    if not pastas:
        raise EntradaRecusada(
            u"não consegui gravar em nenhum destino: %s"
            % u"; ".join(u"%s (%s)" % (d[-60:], m) for d, m in falhas[:3]))
    if linha_leia_me:
        import radai_image
        for p in pastas:
            with io.open(os.path.join(p, radai_image.NOME_DO_LEIA_ME), "w",
                         encoding="ascii", errors="replace",
                         newline="\r\n") as f:
                f.write(linha_leia_me + u"\n")
    return nome, pastas, falhas


def nome_saida(destino, agora=None):
    base = time.strftime("DICOM_BRIDGE_%Y%m%d_%H%M%S",
                         time.localtime(agora if agora is not None
                                        else time.time()))
    nome, k = base, 1
    while (os.path.exists(os.path.join(destino, nome))
           or os.path.exists(os.path.join(destino, nome + ".zip"))):
        k += 1
        nome = u"%s_%d" % (base, k)
    return nome
