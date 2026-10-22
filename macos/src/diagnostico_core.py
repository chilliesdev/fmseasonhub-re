"""Gerador de relatorios de diagnostico do FM Season Hub.

Inspeciona o ambiente do sistema (macOS / Windows), status de permissao e elevacao,
processos do jogo em execucao, conexao com o servico Cloudflare Worker e logs recentes.
"""

from datetime import datetime
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
import paths
import settings
import version

CLUB_ROOT_RVA = 0x0
COMP_ROOT_RVA = 0x0
PERSON_ROOT_RVA = 0x0
GAME_DATE_RVA = 0x0
GAME_MODULE = "game_plugin.dll" if sys.platform != "darwin" else "fm"
HEAP_LO = 0x0000000000000000
HEAP_HI = 0x7FFFFFFFFFFFFFFF
PROCESS_QUERY_LIMITED = 0x1000

ERRO = "ERRO"
ATENCAO = "ATENÇÃO"


def _tipo_js(val):
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    return f'"{val}"'


def _fixo(val):
    return str(val).strip()


def _elevado():
    """Verifica se o processo roda com privilegios de administrador/root."""
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _antivirus():
    """Detecta ferramentas de protecao do sistema (Gatekeeper / SIP no Mac; Defender no Win)."""
    if sys.platform == "darwin":
        itens = []
        try:
            sp = subprocess.check_output(["spctl", "--status"], text=True, stderr=subprocess.DEVNULL)
            itens.append(f"Gatekeeper: {sp.strip()}")
        except Exception:
            pass
        try:
            csr = subprocess.check_output(["csrutil", "status"], text=True, stderr=subprocess.DEVNULL)
            itens.append(f"SIP: {csr.strip()}")
        except Exception:
            pass
        return "; ".join(itens) if itens else "Segurança padrão macOS ativa"

    return "Windows Defender ou Antivírus de terceiros"


def _webview2():
    """No macOS PyWebView utiliza WebKit nativo do sistema."""
    if sys.platform == "darwin":
        return "macOS WKWebView (Nativo)"
    return "WebView2 Runtime / Evergreen"


def versao_arquivo(caminho):
    if not os.path.isfile(caminho):
        return None
    return getattr(version, "VERSION", "0.8.2.1")


def idioma_gravado():
    s = settings.load()
    return s.get("idioma", "pt")


def veio_da_internet(caminho):
    """Verifica flag de quarentena de download."""
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["xattr", "-p", "com.apple.quarantine", caminho], stderr=subprocess.DEVNULL)
            return bool(out)
        except Exception:
            return False
    return False


def estado_de(servico_url):
    try:
        req = urllib.request.Request(
            servico_url,
            headers={"User-Agent": f"FMSH/{getattr(version, 'VERSION', '0.8.2.1')}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return f"OK ({resp.status})"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return f"Falha ({e})"


def bloco_ambiente():
    itens = []
    agora = datetime.now().isoformat(timespec="seconds")
    itens.append(("Data e hora", agora))
    itens.append(("FMSH Diagnostico", getattr(version, "VERSION", "0.8.2.1")))
    itens.append(("Sistema", f"{platform.system()} {platform.release()} ({platform.machine()})"))
    itens.append(("Arquitetura do Python", f"{platform.architecture()[0]} (Python {platform.python_version()})"))
    itens.append(("Rodando como admin", "SIM" if _elevado() else "NÃO"))
    itens.append(("Executavel", sys.executable))
    itens.append(("Motor Webview", _webview2()))
    itens.append(("Protecoes do SO", _antivirus()))
    itens.append(("Pasta de Dados", paths.user_data_path()))
    return {"titulo": "1. AMBIENTE", "itens": itens}


def bloco_processos():
    itens = []
    nomes_alvo = ("fm", "fm.exe", "Football Manager", "FMSH", "FMSH.exe")
    encontrados = []

    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["ps", "-A", "-o", "pid,comm"], text=True)
            for line in out.splitlines():
                for alvo in nomes_alvo:
                    if alvo.lower() in line.lower():
                        encontrados.append(line.strip())
                        break
        elif sys.platform == "win32":
            out = subprocess.check_output(["tasklist"], text=True)
            for line in out.splitlines():
                for alvo in nomes_alvo:
                    if alvo.lower() in line.lower():
                        encontrados.append(line.strip())
                        break
    except Exception:
        pass

    if encontrados:
        for p in encontrados:
            itens.append(("Processo", p))
    else:
        itens.append(("Status", "Nenhum processo do FM ou FMSH detectado em execucao"))

    return {"titulo": "2. PROCESSOS", "itens": itens}


def bloco_rede():
    itens = []
    itens.append(("Servico Principal", estado_de("https://fmsh-acesso.marcellofelipe90.workers.dev/avisos")))
    itens.append(("Painel Web", estado_de("https://painel.fmseasonhub.com")))
    return {"titulo": "3. REDE", "itens": itens}


def bloco_leitura():
    itens = []
    itens.append(("Plataforma", sys.platform))
    itens.append(("Modo de Leitura", "macOS Mach Kernel Task Port / Native Dyld"))
    return {"titulo": "4. LEITURA DE MEMORIA", "itens": itens}


def bloco_log():
    itens = []
    caminho_log = paths.local_data_path("fmsh.log")
    if os.path.isfile(caminho_log):
        try:
            with open(caminho_log, "r", encoding="utf-8", errors="ignore") as f:
                linhas = f.readlines()
                ultimas = [l.strip() for l in linhas[-20:] if l.strip()]
                for l in ultimas:
                    itens.append(("Log", l))
        except Exception:
            itens.append(("Log", "Erro ao ler arquivo de log"))
    else:
        itens.append(("Log", "Arquivo de log ainda nao gerado"))
    return {"titulo": "5. LOG DO APP", "itens": itens}


def bloco_valores():
    itens = []
    try:
        import db

        p_banco = db.db_file()
        if os.path.isfile(p_banco):
            tamanho = os.path.getsize(p_banco)
            itens.append(("Banco de Dados", f"{p_banco} ({tamanho / 1024 / 1024:.2f} MB)"))
            conn = db.connect()
            try:
                row = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()
                itens.append(("Snapshots Gravados", row[0] if row else 0))
            finally:
                conn.close()
        else:
            itens.append(("Banco de Dados", "Ainda nao criado no disco"))
    except Exception as e:
        itens.append(("Banco de Dados", f"Erro: {e}"))
    return {"titulo": "6. VALORES DO BANCO", "itens": itens}


def rodar():
    """Gera o relatorio completo de diagnostico."""
    return {
        "ambiente": bloco_ambiente(),
        "processos": bloco_processos(),
        "rede": bloco_rede(),
        "leitura": bloco_leitura(),
        "log": bloco_log(),
        "valores": bloco_valores(),
    }


def salvar(relatorio, caminho=None):
    """Grava o relatorio em formato texto legivel."""
    if not caminho:
        caminho = paths.local_data_path("diagnostico.txt")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)

    linhas = []
    linhas.append("=" * 60)
    linhas.append("          FM SEASON HUB - RELATORIO DE DIAGNOSTICO")
    linhas.append("=" * 60)
    linhas.append("")

    for chave, bloco in relatorio.items():
        linhas.append(f"--- {bloco.get('titulo', chave.upper())} ---")
        for rotulo, val in bloco.get("itens", []):
            linhas.append(f"{rotulo:25}: {val}")
        linhas.append("")

    texto = "\n".join(linhas)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)

    return caminho
