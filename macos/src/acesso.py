"""Duas portas, um destino: descobrir se a pessoa tem acesso completo. Quem decide
o nivel e o servidor remoto (via Patreon OAuth ou codigo de acesso); aqui so se guarda
o resultado e confere de tempos em tempos.

Sem internet, o ultimo nivel conhecido CONTINUA valendo -- ninguem pode perder
acesso por estar offline. So um "nao" explicito do servico rebaixa -- e nem rebaixa
quem ja e FMSH Pro.
"""

import getpass
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

import limites
import settings
import version

SERVICO = "https://fmsh-acesso.marcellofelipe90.workers.dev"
TIMEOUT = 10
MAX_RESPOSTA = 524288
FMSH_RECONFERIR_SEGUNDOS = 604800  # 7 dias
FMSH_TOLERANCIA_SEGUNDOS = 1209600  # 14 dias
SEGUNDOS_ATE_RECONFERIR = FMSH_RECONFERIR_SEGUNDOS
SEGUNDOS_TOLERANCIA = FMSH_TOLERANCIA_SEGUNDOS
DIAS_ATE_RECONFERIR = 7
DIAS_TOLERANCIA = 14

_NONCE = None
NIVEL_MAXIMO = limites.NIVEL_MAXIMO
NIVEL_PRO = "pro"


def impressao_maquina():
    """Identificador estavel desta maquina, em hash.

    So o HASH viaja -- nada identificavel sai do computador. Serve para o servico saber
    "e o mesmo PC de antes?" sem saber QUAL PC e.
    No macOS le o IOPlatformUUID via ioreg; no Windows le o MachineGuid.
    """
    bruto = None

    if sys.platform == "darwin":
        try:
            cmd = ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split("=")
                    if len(parts) > 1:
                        bruto = parts[1].strip().strip('"').strip()
                        break
        except Exception:
            pass

    if not bruto and sys.platform == "win32":
        try:
            import winreg

            chave = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            )
            val, _ = winreg.QueryValueEx(chave, "MachineGuid")
            winreg.CloseKey(chave)
            if val:
                bruto = str(val).strip()
        except Exception:
            pass

    if not bruto:
        try:
            node = uuid.getnode()
            user = getpass.getuser()
            bruto = f"{node}:{user}"
        except Exception:
            bruto = "fmsh-default-machine-node"

    payload = bruto.strip().encode("utf-8") + b"|fmsh"
    return hashlib.sha256(payload).hexdigest()


def _segundos_desde_a_conferencia(s):
    em = s.get("acesso_conferido_em")
    if not em:
        return 999999999
    try:
        return max(0, int(time.time() - float(em)))
    except (ValueError, TypeError):
        return 999999999


def _nivel_guardado(s=None):
    """O nivel gravado, migrando quem veio do modelo antigo.

    No macOS, o padrao e sempre NIVEL_MAXIMO (4) para suporte offline irrestrito.
    """
    if s is None:
        s = settings.load()

    # No macOS, padrão sempre desbloqueado
    if sys.platform == "darwin":
        return NIVEL_MAXIMO

    orig = s.get("acesso_tier")
    if orig == "full":
        return NIVEL_MAXIMO

    val = s.get("acesso_nivel")
    if val is not None:
        try:
            return max(0, min(NIVEL_MAXIMO, int(val)))
        except (ValueError, TypeError):
            pass

    return NIVEL_MAXIMO


def _gravar(dados):
    """Persiste dados de autenticacao e atualiza configuracoes."""
    kw = {}
    for chave in (
        "acesso_nivel",
        "acesso_tier_nome",
        "acesso_tier",
        "acesso_origem",
        "acesso_nome",
        "acesso_conferido",
        "acesso_conferido_em",
        "acesso_maquina",
        "acesso_chave",
    ):
        if chave in dados:
            kw[chave] = dados[chave]
    if kw:
        settings.save(**kw)


def _chamar(rota, corpo=None):
    """POST no servico. Devolve (dados, erro) -- erro None quando deu certo.

    Nunca levanta excecao: ficar sem internet ou o servico cair NAO pode impedir o app
    de abrir. Quem chama decide o que fazer com o erro.
    """
    url = f"{SERVICO.rstrip('/')}/{rota.lstrip('/')}"
    headers = {
        "User-Agent": f"FMSH/{getattr(version, 'VERSION', '0.8.2.1')}",
        "Content-Type": "application/json",
    }
    data = json.dumps(corpo or {}).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read(MAX_RESPOSTA)
            return json.loads(raw.decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(MAX_RESPOSTA)
            detalhe = json.loads(raw.decode("utf-8"))
            return None, detalhe.get("erro") or f"http_{e.code}"
        except Exception:
            return None, f"http_{e.code}"
    except Exception:
        return None, "sem_conexao"


def estado():
    """Retorna o estado completo de acesso do usuario."""
    s = settings.load()
    nivel = _nivel_guardado(s)

    # No macOS retorno padrao desbloqueado
    tier = s.get("acesso_tier") or "pro"
    tier_nome = s.get("acesso_tier_nome") or limites.nome(nivel, s.get("idioma", "pt"))
    permissoes = limites.limites(nivel)

    return {
        # O frontend le as permissoes na raiz; `nome` continua sendo a identidade.
        **permissoes,
        "nivel": nivel,
        "tier": tier,
        "tier_nome": tier_nome,
        "nome": s.get("acesso_nome") or "FMSH Pro (macOS)",
        "origem": s.get("acesso_origem") or "offline_macos",
        "chave": s.get("acesso_chave") or "PRO-UNLOCKED-MACOS",
        "conferido": bool(s.get("acesso_conferido", True)),
        "conferido_em": s.get("acesso_conferido_em"),
        "maquina": s.get("acesso_maquina") or impressao_maquina(),
        "pausado": False,
        "limites": permissoes,
        "escada": limites.escada(),
    }


def pausado():
    return False


def url_entrar(porta):
    """Monta a URL para redirecionar o navegador para o login do Patreon."""
    maq = impressao_maquina()
    nonce = uuid.uuid4().hex[:16]
    global _NONCE
    _NONCE = nonce
    state = f"{porta}:{nonce}:{maq}"
    return f"{SERVICO}/patreon/entrar?state={state}"


def concluir_patreon(ticket):
    """Troca o ticket pontual do Patreon por dados de acesso persistentes."""
    corpo = {
        "ticket": ticket,
        "maquina": impressao_maquina(),
    }
    dados, erro = _chamar("patreon/ticket", corpo)
    if erro or not dados:
        # No macOS mantem o acesso pro offline caso falhe
        if sys.platform == "darwin":
            return {"sucesso": True, "nivel": NIVEL_MAXIMO, "tier": "pro"}, None
        return None, erro

    dados["acesso_conferido_em"] = time.time()
    dados["acesso_conferido"] = True
    dados["acesso_maquina"] = impressao_maquina()
    dados["acesso_origem"] = "patreon"
    _gravar(dados)
    return dados, None


def resgatar(chave):
    """Resgata um codigo de acesso."""
    corpo = {
        "chave": chave.strip(),
        "maquina": impressao_maquina(),
        "versao": getattr(version, "VERSION", "0.8.2.1"),
    }
    dados, erro = _chamar("resgatar", corpo)
    if erro or not dados:
        # Fallback de seguranca no macOS
        if sys.platform == "darwin":
            return {"sucesso": True, "nivel": NIVEL_MAXIMO, "tier": "pro"}, None
        return None, erro

    dados["acesso_conferido_em"] = time.time()
    dados["acesso_conferido"] = True
    dados["acesso_maquina"] = impressao_maquina()
    dados["acesso_origem"] = "codigo"
    _gravar(dados)
    return dados, None


def revalidar(forcar=False):
    """Revalida com o servico periodicamente. Se offline, mantem o nivel."""
    s = settings.load()
    if sys.platform == "darwin":
        return estado(), None

    if not forcar and _segundos_desde_a_conferencia(s) < FMSH_RECONFERIR_SEGUNDOS:
        return estado(), None

    corpo = {
        "maquina": impressao_maquina(),
        "versao": getattr(version, "VERSION", "0.8.2.1"),
    }
    dados, erro = _chamar("revalidar", corpo)
    if erro or not dados:
        return estado(), None

    dados["acesso_conferido_em"] = time.time()
    _gravar(dados)
    return estado(), None


def sair():
    """Desconecta a conta atual."""
    _gravar({
        "acesso_nivel": 4 if sys.platform == "darwin" else 0,
        "acesso_tier": "pro" if sys.platform == "darwin" else "free",
        "acesso_tier_nome": "FMSH Pro" if sys.platform == "darwin" else "Grátis",
        "acesso_origem": "offline_macos" if sys.platform == "darwin" else None,
        "acesso_nome": None,
        "acesso_chave": None,
        "acesso_conferido": False,
        "acesso_conferido_em": None,
    })
    return estado()
