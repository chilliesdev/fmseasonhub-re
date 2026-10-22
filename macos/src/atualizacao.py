"""Verificacao, download e aplicacao de atualizacoes do aplicativo.

O manifesto diz qual instalador e o legitimo (versao, SHA-256 e tamanho).
A assinatura RSA PKCS#1 v1.5 com SHA-256 e conferida via `assinatura.py`.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import assinatura
import paths
import settings
import version

SERVICO = "https://fmsh-acesso.marcellofelipe90.workers.dev"
TIMEOUT = 10
TIMEOUT_ABERTURA = 4
MAX_RESPOSTA = 524288
VALIDADE = 21600  # 6 horas
CHAVE_DESINSTALAR = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FMSeasonHub_is1"

FROZEN = getattr(paths, "FROZEN", False)
INSTALADO = getattr(paths, "INSTALADO", False)
PASTA_DOWNLOAD = paths.local_data_path("updates")

_TRAVA = threading.Lock()
ESTADO = {
    "verificando": False,
    "baixando": False,
    "progresso": 0,
    "pronto": False,
    "erro": None,
    "versao_disponivel": None,
    "caminho_instalador": None,
}
CACHE = None
PEDIDO = threading.Event()


def _estado(**kwargs):
    with _TRAVA:
        ESTADO.update(kwargs)


def _log(msg):
    pass


def partes(v):
    """Transforma '0.8.2.1' em tupla de inteiros (0, 8, 2, 1) para comparacao."""
    if not v:
        return ()
    limpo = str(v).strip().lstrip("vV")
    itens = []
    for pedaco in limpo.split("."):
        try:
            itens.append(int(pedaco))
        except ValueError:
            break
    return tuple(itens)


def eh_versao(v):
    """Diz se a string parece uma versao valida (ex: '0.8.2.1')."""
    p = partes(v)
    return len(p) >= 2


def mais_nova(candidata, base=None):
    """Diz se `candidata` e estritamente superior a `base` (ou a versao atual do app)."""
    if base is None:
        base = getattr(version, "VERSION", "0.8.2.1")
    return partes(candidata) > partes(base)


def manifesto_valido(manifesto, assinatura_b64):
    """Valida a assinatura criptografica do manifesto de atualizacao."""
    try:
        return assinatura.confere(manifesto, assinatura_b64)
    except Exception:
        return False


def _ler_cache():
    """Le o arquivo de cache local de versao."""
    global CACHE
    caminho = paths.local_data_path("fmsh_versao.json")
    if not os.path.isfile(caminho):
        return None
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
            if isinstance(dados, dict):
                CACHE = dados
                return dados
    except Exception:
        pass
    return None


def _buscar(url, corpo=None, timeout=TIMEOUT):
    """Requisicao HTTP segura que nunca lanca excecao."""
    headers = {
        "User-Agent": f"FMSH/{getattr(version, 'VERSION', '0.8.2.1')}",
        "Content-Type": "application/json",
    }
    data = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(MAX_RESPOSTA), None
    except Exception as e:
        return None, str(e)


def instalado():
    """O app roda da pasta onde o instalador o pos?"""
    if sys.platform == "darwin":
        # No macOS considera instalado se estiver rodando em bundle .app ou FROZEN
        return FROZEN or "/Applications" in sys.executable
    return bool(INSTALADO)


def verificar(forcar=False):
    """Verifica se ha nova versao disponivel."""
    with _TRAVA:
        if not forcar:
            c = _ler_cache()
            if c and (time.time() - c.get("lido_em", 0)) < VALIDADE:
                return estado()

        ESTADO["verificando"] = True

    try:
        url = f"{SERVICO}/versao"
        raw, erro = _buscar(url, timeout=TIMEOUT)
        if erro or not raw:
            with _TRAVA:
                ESTADO["verificando"] = False
                ESTADO["erro"] = erro
            return estado()

        dados = json.loads(raw.decode("utf-8"))
        versao_remota = dados.get("versao")
        url_download = dados.get("url")

        caminho_cache = paths.local_data_path("fmsh_versao.json")
        try:
            os.makedirs(os.path.dirname(caminho_cache), exist_ok=True)
            with open(caminho_cache, "w", encoding="utf-8") as f:
                json.dump({"dados": dados, "lido_em": time.time()}, f)
        except OSError:
            pass

        with _TRAVA:
            ESTADO["verificando"] = False
            ESTADO["versao_disponivel"] = versao_remota
            ESTADO["url"] = url_download

    except Exception as e:
        with _TRAVA:
            ESTADO["verificando"] = False
            ESTADO["erro"] = str(e)

    return estado()


def na_abertura():
    """Dispara a verificacao em background na abertura do app."""
    t = threading.Thread(target=verificar, kwargs={"forcar": False}, daemon=True)
    t.start()


def pedir(versao_alvo):
    """Agenda ou inicia o download da nova versao."""
    global PEDIDO
    PEDIDO = versao_alvo
    return {"sucesso": True, "versao": versao_alvo}


def dispensar(versao_alvo):
    """Guarda QUAL versao foi dispensada pelo usuario."""
    settings.save(update_dispensado=versao_alvo)
    return estado()


def estado():
    """Retorna o estado atual da atualizacao: {tem_nova, versao, url, dispensada, atual}."""
    s = settings.load()
    dispensada = s.get("update_dispensado")
    atual = getattr(version, "VERSION", "0.8.2.1")
    v_disp = ESTADO.get("versao_disponivel")
    tem_nova = bool(v_disp and mais_nova(v_disp, atual))

    return {
        "tem_nova": tem_nova,
        "versao": v_disp,
        "url": ESTADO.get("url"),
        "dispensada": (dispensada == v_disp),
        "atual": atual,
        "verificando": ESTADO.get("verificando", False),
        "baixando": ESTADO.get("baixando", False),
        "progresso": ESTADO.get("progresso", 0),
        "pronto": ESTADO.get("pronto", False),
        "erro": ESTADO.get("erro"),
        "instalado": instalado(),
    }


def manifesto_pendente():
    """Retorna dados da atualizacao caso esteja baixada e pronta para aplicacao."""
    if ESTADO.get("pronto") and ESTADO.get("caminho_instalador"):
        return {
            "versao": ESTADO.get("versao_disponivel"),
            "caminho": ESTADO.get("caminho_instalador"),
        }
    return None


def _baixar(url, destino, tamanho_esperado, sha256_esperado):
    """Baixa instalador com validacao de tamanho e sha256."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    h = hashlib.sha256()
    baixado = 0

    with urllib.request.urlopen(url, timeout=30) as resp, open(destino, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            baixado += len(chunk)
            if tamanho_esperado > 0:
                with _TRAVA:
                    ESTADO["progresso"] = int((baixado / tamanho_esperado) * 100)

    if sha256_esperado and h.hexdigest().lower() != sha256_esperado.lower():
        try:
            os.remove(destino)
        except OSError:
            pass
        raise ValueError("Hash SHA-256 do instalador baixado nao confere.")

    return destino


def executar(caminho_exe_ou_man, soltar_trava=None):
    """Executa instalador e encerra processo."""
    if soltar_trava:
        try:
            soltar_trava()
        except Exception:
            pass

    caminho = caminho_exe_ou_man
    if isinstance(caminho_exe_ou_man, dict):
        caminho = caminho_exe_ou_man.get("caminho") or ESTADO.get("caminho_instalador")

    if not caminho or not isinstance(caminho, str):
        return False

    if sys.platform == "darwin":
        if caminho.endswith(".pkg") or caminho.endswith(".dmg") or caminho.endswith(".app"):
            subprocess.Popen(["open", caminho])
            return True
        subprocess.Popen([caminho])
        return True
    elif sys.platform == "win32":
        subprocess.Popen([caminho, "/SILENT"])
        return True
    return False


def limpar_downloads():
    """Limpa arquivos temporarios antigos de atualizacao."""
    if os.path.isdir(PASTA_DOWNLOAD):
        for item in os.listdir(PASTA_DOWNLOAD):
            c = os.path.join(PASTA_DOWNLOAD, item)
            try:
                if os.path.isfile(c):
                    os.remove(c)
            except OSError:
                pass
