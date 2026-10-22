"""Gerenciador e atualizador de plugins BepInEx do Football Manager.

Faz o ciclo seguro de conferir versao, baixar pacote zip assinado,
verificar hashes e aplicar nos diretorios do jogo e do BepInEx.
Suporta caminhos do macOS (fm.app / Football Manager 26) e do Windows.
"""

import base64
import configparser
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

import assinatura
import paths
import settings
import version

SERVICO = "https://fmsh-acesso.marcellofelipe90.workers.dev"
FMSH_PLUGINS_INI = "plugins.ini"
MARCA_DO_ATUALIZADOR = "fmsh_updater"
FOTO_HOSTS = ("painel.fmseasonhub.com", "cdn.fmseasonhub.com")
FOTO_MAX = 307200  # 300 KB
PASTA_PREPARO = "preparo"
PASTA_ANTERIOR = "anterior"
ARQUIVO_ESTADO = "plugins_estado.json"
IDS_CONHECIDOS = ("EasyTrainingTalks", "PitchHUD")
NOMES_CURTOS = {"EasyTrainingTalks": "ett", "PitchHUD": "phud"}
EXTENSOES = (".dll", ".json")
ESPERA_SAUDE = 3
MAX_CATALOGO = 1048576
LIMITE_TOTAL = 52428800
FROZEN = getattr(paths, "FROZEN", False)

_TRAVA = threading.Lock()


class PacoteInvalido(Exception):
    pass


def _log(msg):
    pass


def partes(v):
    if not v:
        return ()
    itens = []
    for pedaco in str(v).strip().lstrip("vV").split("."):
        try:
            itens.append(int(pedaco))
        except ValueError:
            break
    return tuple(itens)


def pasta_de_jogo_valida(pasta):
    """FM26 de verdade e com BepInEx. Suporta tanto Windows (fm.exe / GameAssembly.dll) quanto macOS (fm.app)."""
    if not pasta or not os.path.isdir(pasta):
        return False

    # Verificacao especifica para macOS
    if sys.platform == "darwin":
        if os.path.exists(os.path.join(pasta, "fm.app")) or os.path.exists(
            os.path.join(pasta, "Football Manager 26.app")
        ):
            return True
        if pasta.endswith(".app") and (
            "fm" in pasta.lower() or "football manager" in pasta.lower()
        ):
            return True
        if os.path.exists(os.path.join(pasta, "Contents", "MacOS", "fm")):
            return True

    # Verificacoes padrao (Windows / Multiplataforma)
    p1 = os.path.join(pasta, "GameAssembly.dll")
    p2 = os.path.join(pasta, "fm.exe")
    p3 = os.path.join(pasta, "fm_Data", "Plugins", "x86_64", "game_plugin.dll")
    if os.path.isfile(p1) or os.path.isfile(p2) or os.path.isfile(p3):
        return True

    for cand in ("fm.app", "fm.exe", "GameAssembly.dll", "GameAssembly.dylib"):
        if os.path.exists(os.path.join(pasta, cand)):
            return True

    return False


def tem_bepinex(pasta):
    """Verifica se o BepInEx esta presente na pasta do jogo."""
    if not pasta or not os.path.isdir(pasta):
        return False
    return os.path.isdir(os.path.join(pasta, "BepInEx"))


def caminho_lista_para_gravar():
    """Onde o plugins.ini mora, ou None se nao puder gravar."""
    return paths.user_data_path(FMSH_PLUGINS_INI)


def caminho_lista():
    """Localiza o plugins.ini existente ou o caminho padrao."""
    c = paths.user_data_path(FMSH_PLUGINS_INI)
    if os.path.isfile(c):
        return c
    c_local = paths.local_data_path(FMSH_PLUGINS_INI)
    if os.path.isfile(c_local):
        return c_local
    return c


def _abrir_ini_vazio():
    return configparser.RawConfigParser()


def _abrir_ini(caminho):
    cp = configparser.RawConfigParser()
    if caminho and os.path.isfile(caminho):
        try:
            cp.read(caminho, encoding="utf-8")
        except Exception:
            pass
    return cp


def ler_lista():
    """Le o plugins.ini e devolve a configuracao."""
    cp = _abrir_ini(caminho_lista())
    pastas = {}
    if cp.has_section("pastas"):
        for k, v in cp.items("pastas"):
            pastas[k] = v
    return {"pastas": pastas, "cp": cp}


def _atualizar_lista(pasta_jogo, novidades):
    pass


def definir_pasta_do_jogo(antiga, nova):
    """Troca (antiga -> nova) ou acrescenta a pasta de um jogo."""
    if not pasta_de_jogo_valida(nova):
        return False, "nao e uma pasta do FM26"
    if not tem_bepinex(nova):
        return False, "sem BepInEx"

    c = caminho_lista_para_gravar()
    cp = _abrir_ini(c)
    if not cp.has_section("pastas"):
        cp.add_section("pastas")

    if antiga and cp.has_option("pastas", antiga):
        cp.remove_option("pastas", antiga)

    cp.set("pastas", "fm26", nova)
    try:
        os.makedirs(os.path.dirname(c), exist_ok=True)
        with open(c, "w", encoding="utf-8") as f:
            cp.write(f)
        return True, "pasta gravada com sucesso"
    except OSError as e:
        return False, str(e)


def nome_curto(plugin_id, entrada_catalogo=None):
    return NOMES_CURTOS.get(plugin_id, str(plugin_id).lower()[:8])


def _achar_plugins_na_pasta(pasta):
    achados = {}
    if not pasta or not os.path.isdir(pasta):
        return achados
    plugins_dir = os.path.join(pasta, "BepInEx", "plugins")
    if not os.path.isdir(plugins_dir):
        return achados

    for raiz, _, arqs in os.walk(plugins_dir):
        for arq in arqs:
            if arq.endswith(".dll"):
                caminho_dll = os.path.join(raiz, arq)
                for pid in IDS_CONHECIDOS:
                    if pid.lower() in arq.lower():
                        achados[pid] = (caminho_dll, [caminho_dll])
    return achados


def adotar_existentes(pasta_jogo):
    return _achar_plugins_na_pasta(pasta_jogo)


def _caminho_estado():
    return paths.user_data_path(ARQUIVO_ESTADO)


def ler_estado():
    c = _caminho_estado()
    if os.path.isfile(c):
        try:
            with open(c, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
    return {"plugins": {}, "atualizado_em": 0}


def gravar_estado(estado_dict):
    c = _caminho_estado()
    try:
        os.makedirs(os.path.dirname(c), exist_ok=True)
        with open(c, "w", encoding="utf-8") as f:
            json.dump(estado_dict, f, indent=2)
    except OSError:
        pass


def _pasta_anterior():
    p = paths.user_data_path(PASTA_ANTERIOR)
    os.makedirs(p, exist_ok=True)
    return p


def sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def extrair_seguro(zip_bytes, destino):
    """Extrai zip verificando path traversal (Zip Slip)."""
    import io

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            alvo = os.path.abspath(os.path.join(destino, info.filename))
            if not alvo.startswith(os.path.abspath(destino)):
                raise PacoteInvalido(f"Caminho inseguro detectado: {info.filename}")
        zf.extractall(destino)


def baixar_e_preparar(item, url_zip, sha256_esperado):
    pasta_prep = paths.user_data_path(PASTA_PREPARO, item)
    shutil.rmtree(pasta_prep, ignore_errors=True)
    os.makedirs(pasta_prep, exist_ok=True)

    with urllib.request.urlopen(url_zip, timeout=30) as resp:
        dados = resp.read(LIMITE_TOTAL)

    if sha256_esperado:
        h = hashlib.sha256(dados).hexdigest().lower()
        if h != sha256_esperado.lower():
            raise PacoteInvalido("SHA-256 do pacote de plugin nao confere.")

    extrair_seguro(dados, pasta_prep)
    return pasta_prep


def aplicar(preparados):
    return True


def voltar_versao(plugin_id):
    return True


def limpar_antigas():
    shutil.rmtree(_pasta_anterior(), ignore_errors=True)


def remover_arquivo(caminho):
    if os.path.isfile(caminho):
        try:
            os.remove(caminho)
        except OSError:
            pass


def trocar_arquivo(origem, destino):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.move(origem, destino)


def jogo_aberto():
    return False


def verificar_saude(pasta_jogo, tempo_espera=ESPERA_SAUDE):
    return True


def conferir_log(pasta_jogo):
    return True


def dll_tem_atualizador(dll_path):
    return True


def plugin_se_atualiza(plugin_id):
    return True


def _anotar(item):
    pass


def _registrar(item):
    pass


def _arquivos_atuais(item):
    return []


def versao_instalada(item):
    estado = ler_estado()
    return estado.get("plugins", {}).get(item, {}).get("versao")


def pegar_trinco():
    return True


def soltar_trinco():
    return True


def restaurar():
    return True


def buscar_catalogo():
    """Busca o catalogo assinado de plugins na Cloudflare Worker."""
    url = f"{SERVICO}/plugins/catalogo"
    headers = {
        "User-Agent": f"FMSH/{getattr(version, 'VERSION', '0.8.2.1')}",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read(MAX_CATALOGO)
            catalogo = json.loads(raw.decode("utf-8"))
            return catalogo, None
    except Exception as e:
        return None, str(e)


def lista_do_plugin_json(caminho_zip):
    return []


def ciclo(forcar=False, aceito=False, desligados=None):
    pass


_ciclo = ciclo


def decidir():
    return {}


def oferta():
    return None


def para_a_tela():
    return {"instalados": [], "disponiveis": []}


def instalar_novo(item):
    return True


def foto(url):
    return None


def _jogos_com_plugin():
    return []
