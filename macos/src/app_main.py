"""FM Season Hub main application entry point (macOS & multiplatform)."""

import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.stdout is None or sys.stderr is None:
    _null = open(os.devnull, 'w', encoding='utf-8')
    if sys.stdout is None:
        sys.stdout = _null
    if sys.stderr is None:
        sys.stderr = _null

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()

import db
import paths
import sistema

if __name__ != '__mp_main__':
    import uvicorn
    from server import app, _boot_graphics, H11_MAX_URL, UVICORN_HTTP

HOST = '127.0.0.1'
DEFAULT_PORT = 54321 if ('--server-only' in sys.argv or '--browser' in sys.argv) else 8000

LOG_PATH = paths.user_data_path('fmsh.log')


def log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def _free_port(host, preferred):
    try:
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, preferred))
            return preferred
    except OSError:
        pass
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _wait_until_up(url, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                pass
            return True
        except Exception:
            time.sleep(0.15)
    return False


NOME_DO_MUTEX = 'FMSH-instancia-unica'
ERRO_JA_EXISTE = 183
_mutex = None
_lock_file = None


def _segurar_mutex():
    global _mutex, _lock_file
    if sys.platform != 'win32':
        import fcntl
        lock_path = paths.user_data_path('fmsh.lock')
        try:
            _lock_file = open(lock_path, 'w')
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except (BlockingIOError, OSError):
            return True
        except Exception:
            return False
    try:
        import ctypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _mutex = k32.CreateMutexW(None, False, NOME_DO_MUTEX)
        return ctypes.get_last_error() == ERRO_JA_EXISTE
    except Exception:
        log('nao consegui criar o mutex:\n' + traceback.format_exc())
        return False


def _soltar_mutex():
    global _mutex, _lock_file
    if sys.platform != 'win32':
        if _lock_file is not None:
            try:
                import fcntl
                fcntl.flock(_lock_file, fcntl.LOCK_UN)
                _lock_file.close()
            except Exception:
                pass
            _lock_file = None
        return
    try:
        import ctypes
        if _mutex:
            ctypes.windll.kernel32.CloseHandle(_mutex)
        _mutex = None
    except Exception:
        log('nao consegui soltar o mutex:\n' + traceback.format_exc())


PLUGINS_NA_ABERTURA_MAX = 25


def _plugins_na_abertura():
    try:
        import atualizacao
        import legal
        import plugins_atualizador
        import settings

        s = settings.load()
        if not (plugins_atualizador.caminho_lista() and legal.aceito_plugins(s)):
            return

        atualizacao._estado(fase='plugins')
        t = threading.Thread(
            target=lambda: plugins_atualizador.ciclo(
                forcar=True,
                aceito=True,
                desligados=s.get('plugins_desligados') or [],
            ),
            name='plugins-abertura',
            daemon=True,
        )
        t.start()
        t.join(PLUGINS_NA_ABERTURA_MAX)
        if t.is_alive():
            log('plugins: a abertura passou de %d s; o ciclo segue em segundo plano' % PLUGINS_NA_ABERTURA_MAX)
    except Exception:
        log('plugins: falhou na abertura:\n' + traceback.format_exc())


def _iniciar_atualizador_de_plugins():
    def laco():
        import legal
        import plugins_atualizador
        import settings

        time.sleep(45)
        while True:
            try:
                s = settings.load()
                plugins_atualizador.ciclo(
                    aceito=legal.aceito_plugins(s),
                    desligados=s.get('plugins_desligados') or [],
                )
            except Exception:
                log('plugins: ciclo falhou:\n' + traceback.format_exc())
            time.sleep(600)

    threading.Thread(target=laco, name='plugins-atualizador', daemon=True).start()


ARQUIVO_DA_PORTA = 'porta_do_app'
ARGUMENTO_BANDEJA = '--bandeja'
INTERVALO_DA_BANDEJA = 10
INTERVALO_DA_VERSAO = 1800
DICA_DA_BANDEJA = 'FM Season Hub'


def _gravar_porta(port):
    try:
        with open(paths.user_data_path(ARQUIVO_DA_PORTA), 'w', encoding='ascii') as f:
            f.write(str(port))
    except OSError:
        log('nao consegui gravar a porta para o plugin:\n' + traceback.format_exc())


def _apagar_porta():
    try:
        os.remove(paths.user_data_path(ARQUIVO_DA_PORTA))
    except OSError:
        pass


def _perto_do_mouse(largura, altura):
    if sys.platform != 'win32':
        try:
            from AppKit import NSEvent, NSScreen
            loc = NSEvent.mouseLocation()
            screen_h = NSScreen.mainScreen().frame().size.height
            mx = int(loc.x)
            my = int(screen_h - loc.y)
            x = max(0, mx - 24)
            y = my + 22
            return (x, y)
        except Exception:
            return (100, 100)

    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    p = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(p))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('rcMonitor', wintypes.RECT),
            ('rcWork', wintypes.RECT),
            ('dwFlags', wintypes.DWORD),
        ]

    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    monitor = u.MonitorFromPoint(p, 2)
    u.GetMonitorInfoW(monitor, ctypes.byref(info))
    area = info.rcWork

    x = min(max(p.x - 24, area.left), area.right - largura)
    if p.y + 22 + altura <= area.bottom:
        y = p.y + 22
    else:
        y = p.y - 22 - altura
    return (x, max(y, area.top))


def _tela_do_ponto(x, y):
    if sys.platform != 'win32':
        try:
            from AppKit import NSScreen
            frame = NSScreen.mainScreen().frame()
            w, h = int(frame.size.width), int(frame.size.height)
            return ((0, 0, w, h), (0, 0, w, h), 1.0)
        except Exception:
            return ((0, 0, 1920, 1080), (0, 0, 1920, 1080), 1.0)

    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('rcMonitor', wintypes.RECT),
            ('rcWork', wintypes.RECT),
            ('dwFlags', wintypes.DWORD),
        ]

    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    monitor = u.MonitorFromPoint(wintypes.POINT(x, y), 2)
    u.GetMonitorInfoW(monitor, ctypes.byref(info))
    escala = 1.0
    try:
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        if ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            escala = (dpi_x.value or 96) / 96.0
    except Exception:
        pass
    w = info.rcWork
    m = info.rcMonitor
    return (
        (w.left, w.top, w.right, w.bottom),
        (m.left, m.top, m.right, m.bottom),
        escala,
    )


def _posicionar(hwnd, x, y, largura, altura, mostrar=False):
    if sys.platform != 'win32' or not hasattr(ctypes, 'WinDLL'):
        return False
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    u.SetWindowPos.restype = wintypes.BOOL
    sinalizadores = 16 | (64 if mostrar else 0)
    return bool(u.SetWindowPos(
        hwnd,
        wintypes.HWND(-1),
        x, y, largura, altura,
        sinalizadores,
    ))


def _janela_de_ferramenta(hwnd):
    if sys.platform != 'win32' or not hasattr(ctypes, 'windll'):
        return
    import ctypes
    u = ctypes.windll.user32
    u.GetWindowLongW.restype = ctypes.c_long
    estilo = u.GetWindowLongW(hwnd, -20)
    novo = (estilo | 128) & -262145
    if novo != estilo:
        u.SetWindowLongW(hwnd, -20, novo)


def _cantos_arredondados(hwnd):
    if sys.platform != 'win32' or not hasattr(ctypes, 'windll'):
        return
    import ctypes
    try:
        preferencia = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(preferencia), 4)
    except Exception:
        pass


def _janelas_deste_processo(titulo, escondidas=False):
    if sys.platform != 'win32' or not hasattr(ctypes, 'windll'):
        return []
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    meu_pid = os.getpid()
    achadas = []

    def cada(hwnd, _lparam):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == meu_pid and (escondidas or u.IsWindowVisible(hwnd) or u.IsIconic(hwnd)):
            texto = ctypes.create_unicode_buffer(128)
            u.GetWindowTextW(hwnd, texto, 128)
            if texto.value == titulo:
                achadas.append(hwnd)
        return True

    fn = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cada)
    u.EnumWindows(fn, 0)
    return achadas


def _forcar_frente(hwnd):
    if sys.platform != 'win32' or not hasattr(ctypes, 'windll'):
        return
    import ctypes
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    frente = u.GetForegroundWindow()
    if frente == hwnd:
        return
    minha = k.GetCurrentThreadId()
    dela = u.GetWindowThreadProcessId(frente, None) if frente else 0
    ligou = bool(dela) and dela != minha and u.AttachThreadInput(minha, dela, True)
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if ligou:
            u.AttachThreadInput(minha, dela, False)


def _dar_foco(titulo):
    if sys.platform == 'darwin':
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass
        return
    for hwnd in _janelas_deste_processo(titulo):
        _forcar_frente(hwnd)


def _trazer_para_frente():
    if sys.platform == 'darwin':
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass
        return
    import ctypes
    u = ctypes.windll.user32
    for hwnd in _janelas_deste_processo('FM Season Hub'):
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)
        _forcar_frente(hwnd)


def main():
    em_bandeja = ARGUMENTO_BANDEJA in sys.argv[1:]
    server_only = ('--server-only' in sys.argv[1:]) or ('-s' in sys.argv[1:])
    browser_mode = ('--browser' in sys.argv[1:]) or ('-b' in sys.argv[1:])

    if _segurar_mutex():
        import instancia_unica
        if em_bandeja:
            log('ja existe outra copia aberta: o inicio com o Windows nao abre a segunda')
            return
        if instancia_unica.pedir_para_mostrar(paths.user_data_path(ARQUIVO_DA_PORTA)):
            log('ja existe outra copia aberta: ela mostrou a janela; esta sai')
            return
        log('ja existe outra copia, mas ela nao respondeu: abrindo mesmo assim')

    log(f"=== iniciando (frozen={paths.FROZEN}, exe={sys.executable})")

    threading.excepthook = lambda a: log(
        'excecao na thread '
        + str(getattr(a.thread, 'name', '?'))
        + ':\n'
        + ''.join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))
    )

    log(f"dados em {paths.data_root()} | banco e cache em {paths.local_root()}")

    paths.migrate_legacy_files(['fm26_snapshots.db', 'fmsh_settings.json'], log=log)

    import settings
    paths.migrar_para_pasta_local(mover_banco=not bool(settings.load().get('db_dir')), log=log)
    _db_conn = db.init_db()
    if _db_conn is not None and hasattr(_db_conn, 'close'):
        _db_conn.close()

    import legal
    legal.importar_aceite_do_instalador(log=log)

    threading.Thread(target=_boot_graphics, daemon=True).start()

    preferred_port = 54321 if (server_only or browser_mode) else DEFAULT_PORT
    port = _free_port(HOST, preferred_port)
    base = f"http://{HOST}:{port}"
    log('porta %d' % port)

    os.environ['FMSH_PORTA'] = str(port)

    def serve():
        try:
            uvicorn.run(
                app,
                host=HOST,
                port=port,
                log_level='warning',
                http=UVICORN_HTTP,
                h11_max_incomplete_event_size=H11_MAX_URL,
            )
        except Exception:
            log('FALHA NO SERVIDOR:\n' + traceback.format_exc())

    threading.Thread(target=serve, daemon=True).start()

    if not _wait_until_up(base + '/api/live'):
        log('ERRO: servidor interno nao subiu a tempo')
        raise SystemExit('o servidor interno nao subiu a tempo')

    log('servidor no ar')
    _gravar_porta(port)

    # Server-only or Browser-only headless mode
    if server_only or browser_mode:
        if browser_mode:
            import webbrowser
            webbrowser.open(base)
        mode_str = 'browser' if browser_mode else 'server-only'
        log(f"servidor em execucao em {base} ({mode_str})")
        print(f"FM Season Hub running on {base} ({mode_str})")
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            try:
                import server
                server.parar_leitura_viva()
            except Exception:
                pass
            _apagar_porta()
            try:
                import navegador_do_jogo
                navegador_do_jogo.fechar()
            except Exception:
                pass
            log('servidor encerrado')
        return

    import webview
    log('webview %s' % getattr(webview, '__version__', '?'))
    webview.settings['ALLOW_DOWNLOADS'] = True

    def janela_principal(escondida=False):
        janela = webview.create_window(
            'FM Season Hub',
            base,
            width=1440,
            height=900,
            min_size=(960, 540),
            maximized=True,
            hidden=escondida,
        )
        janela.events.closing += ao_fechar_principal
        janela.events.closed += ao_principal_fechada
        return janela

    def ao_principal_fechada():
        if janelas.get('caixa') is None:
            fechar_janela_do_menu()

    def caixinha():
        return webview.create_window(
            'FM Season Hub',
            base + '/atualizando',
            width=380,
            height=230,
            resizable=False,
            frameless=True,
            easy_drag=True,
            background_color='#10202E',
            hidden=True,
        )

    CAIXA_MINIMO = 2.0

    def caixa_visivel():
        caixa = janelas['caixa']
        try:
            caixa.events.loaded.wait(6)
        except Exception:
            pass
        try:
            caixa.show()
        except Exception:
            log('nao consegui mostrar a caixinha:\n' + traceback.format_exc())
        return time.time()

    import atualizacao
    atualizacao.limpar_downloads()

    janelas = {'principal': None, 'caixa': None}

    def pedido_do_jogo():
        abrir_menu_do_jogo(None, None)
        abrir_dados_do_jogo(None, None, None, None)
        if janelas['principal'] is None:
            return
        mostrar()
        try:
            janelas['principal'].evaluate_js("window.dispatchEvent(new Event('fmsh-pedido-do-jogo'))")
        except Exception:
            log('nao consegui avisar a tela do pedido do jogo:\n' + traceback.format_exc())

    LARGURA_MENU = 300
    ALTURA_MENU = 440
    TITULO_MENU = 'FM Season Hub - comparar'
    trava_menu = threading.Lock()

    def abrir_menu_do_jogo(uid, sid):
        with trava_menu:
            if janelas.get('menu') is not None:
                try:
                    janelas['menu'].destroy()
                except Exception:
                    pass
                janelas['menu'] = None
            if uid is None or sid is None:
                return
            x, y = _perto_do_mouse(LARGURA_MENU, ALTURA_MENU)
            menu = webview.create_window(
                TITULO_MENU,
                f"{base}/janela/comparar?sid={sid}&uid={uid}",
                width=LARGURA_MENU,
                height=ALTURA_MENU,
                x=x,
                y=y,
                frameless=True,
                on_top=True,
                resizable=False,
                background_color='#10202E',
            )
            janelas['menu'] = menu
        menu.events.shown += lambda: _dar_foco(TITULO_MENU)
        menu.events.loaded += lambda: _dar_foco(TITULO_MENU)

    TITULO_DADOS = 'FM Season Hub - player data'
    trava_dados = threading.Lock()

    def guardar_no_topo(janela, chave='dados', titulo=TITULO_DADOS):
        import janela_topo

        def laco():
            pausas = (0.05, 0.1, 0.2, 0.4, 0.8)
            i = 0
            anotou = False
            while janelas.get(chave) is janela:
                for hwnd in _janelas_deste_processo(titulo):
                    try:
                        janela_topo.fixar_no_topo(hwnd)
                        if not anotou:
                            anotou = True
                            log(f"{titulo}: janela {hwnd} por cima (topmost={janela_topo.tem_topmost(hwnd)})")
                    except Exception:
                        log(f"{titulo}: nao consegui reafirmar o topo:\n{traceback.format_exc()}")
                time.sleep(pausas[i] if i < len(pausas) else 0.5)
                i += 1

        threading.Thread(target=laco, daemon=True).start()

    def abrir_dados_do_jogo(uid, sid, modo, geo):
        with trava_dados:
            atual = janelas.get('dados')
            if uid is not None and atual is not None and janelas.get('dados_uid') == uid:
                if modo == 'fixa':
                    _dar_foco(TITULO_DADOS)
                return
            if atual is not None:
                try:
                    atual.destroy()
                except Exception:
                    pass
                janelas['dados'] = None
                janelas['dados_uid'] = None
            if uid is None or sid is None or geo is None:
                return
            x, y, largura, altura = geo
            janela = webview.create_window(
                TITULO_DADOS,
                f"{base}/janela/dados?sid={sid}&uid={uid}",
                width=largura,
                height=altura,
                x=x,
                y=y,
                frameless=True,
                on_top=True,
                resizable=False,
                focus=(modo == 'fixa'),
                background_color='#10202E',
            )
            janelas['dados'] = janela
            janelas['dados_uid'] = uid
        log(f"hover Player Data: abrindo uid={uid} modo={modo} em ({x},{y}) {largura}x{altura}")
        guardar_no_topo(janela)
        if modo == 'fixa':
            janela.events.shown += lambda: _dar_foco(TITULO_DADOS)
            janela.events.loaded += lambda: _dar_foco(TITULO_DADOS)

    LARGURA_FAIXA = 620
    ALTURA_FAIXA = 96
    TOPO_FAIXA = 120
    LARGURA_PILULA = 440
    ALTURA_PILULA = 36

    def recortar_em_pilula(janela, titulo):
        if sys.platform != 'win32' or not hasattr(ctypes, 'windll'):
            return
        import ctypes
        import ctypes.wintypes
        u32 = ctypes.windll.user32
        gdi = ctypes.windll.gdi32

        feitos = 0
        for _ in range(80):
            for hwnd in _janelas_deste_processo(titulo):
                r = ctypes.wintypes.RECT()
                u32.GetWindowRect(hwnd, ctypes.byref(r))
                w = r.right - r.left
                h = r.bottom - r.top
                if not w or not h:
                    continue
                sem_cor = ctypes.c_uint(1)
                nao_arredondar = ctypes.c_uint(4294967294)
                dwm = ctypes.windll.dwmapi
                dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(sem_cor), 4)
                dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(nao_arredondar), 4)
                u32.SetWindowRgn(hwnd, gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, h, h), True)
                feitos += 1
            if feitos >= 20:
                log('faixa da captura: pilula recortada (%dx%d)' % (w, h))
                return
            time.sleep(0.1)
        log('faixa da captura: nao achei a janela da pilula para recortar')

    TITULO_FAIXA = 'FM Season Hub - captura'
    SOM_DA_FAIXA = {
        'inicio': 'captura-inicio',
        'concluida': 'captura-fim',
        'falhou': 'captura-alerta',
    }
    trava_faixa = threading.Lock()

    import queue
    fila_de_sons = queue.Queue()

    def laco_dos_sons():
        if sys.platform != 'win32':
            while True:
                nome, volume = fila_de_sons.get()
                try:
                    caminho = paths.resource_path('src', 'web', 'sons', nome + '.mp3')
                    if os.path.isfile(caminho):
                        subprocess.run(['afplay', '-v', str(max(0.0, min(1.0, volume / 100.0))), caminho], check=False)
                except Exception:
                    log(f"faixa da captura: nao consegui tocar {nome}:\n{traceback.format_exc()}")
            return

        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW
        while True:
            nome, volume = fila_de_sons.get()
            try:
                caminho = paths.resource_path('src', 'web', 'sons', nome + '.mp3')
                if not os.path.isfile(caminho):
                    continue
                mci('close fmsh_som', None, 0, None)
                erro = mci(f'open "{caminho}" type mpegvideo alias fmsh_som', None, 0, None)
                if erro == 0:
                    mci(f'setaudio fmsh_som volume to {volume * 10}', None, 0, None)
                    erro = mci('play fmsh_som', None, 0, None)
                if erro:
                    log(f"faixa da captura: o MCI recusou {nome} (erro {erro})")
            except Exception:
                log(f"faixa da captura: nao consegui tocar {nome}:\n{traceback.format_exc()}")

    threading.Thread(target=laco_dos_sons, name='sons', daemon=True).start()

    def tocar_som(nome, testar=False):
        s = settings.load()
        if not testar and s.get('captura_som_ligado', True) is False:
            return
        volume = max(0, min(100, int(s.get('captura_som_volume', 100))))
        fila_de_sons.put((nome, volume))

    def aviso_da_captura(momento):
        if server.SIMULACAO.get('estado'):
            tipo = server.SIMULACAO.get('tipo')
        else:
            tipo = server.CAPTURA_AUTO.get('tipo')
        pilula = (tipo == 'tracker')
        sem_som = (not server.SIMULACAO.get('estado')) and (server.CAPTURA_AUTO.get('estado') == 'ja_salva')
        if momento in SOM_DA_FAIXA and not pilula and not sem_som:
            tocar_som(SOM_DA_FAIXA[momento])
        largura, altura = (LARGURA_PILULA, ALTURA_PILULA) if pilula else (LARGURA_FAIXA, ALTURA_FAIXA)
        with trava_faixa:
            atual = janelas.get('faixa')
            if atual is not None and momento != 'fechar' and janelas.get('faixa_tamanho') != (largura, altura):
                janelas['faixa'] = None
                try:
                    atual.destroy()
                except Exception:
                    pass
                atual = None
            if momento == 'fechar':
                if atual is not None:
                    janelas['faixa'] = None
                    try:
                        atual.destroy()
                    except Exception:
                        pass
                return
            if atual is not None:
                return
            import janela_dados
            tela = janela_dados.tela_principal() or (0, 0, 1920, 1080)
            janela = webview.create_window(
                TITULO_FAIXA,
                f"{base}/janela/captura",
                width=largura,
                height=altura,
                x=tela[0] + (tela[2] - largura) // 2,
                min_size=(largura, altura),
                y=tela[1] + TOPO_FAIXA,
                frameless=True,
                on_top=True,
                resizable=False,
                easy_drag=False,
                focus=False,
                background_color='#10202E',
            )
            janelas['faixa'] = janela
            janelas['faixa_tamanho'] = (largura, altura)
        log(f"faixa da captura: aberta ({momento}, {'pilula' if pilula else 'faixa'})")
        if pilula:
            threading.Thread(target=recortar_em_pilula, args=(janela, TITULO_FAIXA), daemon=True).start()
        guardar_no_topo(janela, 'faixa', TITULO_FAIXA)

    TITULO_FAIXA_CONEXAO = 'FM Season Hub - conexao'

    def aviso_da_conexao(momento):
        if momento in SOM_DA_FAIXA:
            tocar_som(SOM_DA_FAIXA[momento])
        with trava_faixa:
            atual = janelas.get('faixa_conexao')
            if momento == 'fechar' or (momento == 'inicio' and atual is not None):
                janelas['faixa_conexao'] = None
                if atual is not None:
                    try:
                        atual.destroy()
                    except Exception:
                        pass
                if momento == 'fechar':
                    return
            elif atual is not None:
                return
            import janela_dados
            tela = janela_dados.tela_principal() or (0, 0, 1920, 1080)
            janela = webview.create_window(
                TITULO_FAIXA_CONEXAO,
                f"{base}/janela/captura?tipo=conexao",
                width=LARGURA_FAIXA,
                height=ALTURA_FAIXA,
                x=tela[0] + (tela[2] - LARGURA_FAIXA) // 2,
                min_size=(LARGURA_FAIXA, ALTURA_FAIXA),
                y=tela[1] + TOPO_FAIXA,
                frameless=True,
                on_top=True,
                resizable=False,
                easy_drag=False,
                focus=False,
                background_color='#10202E',
            )
            janelas['faixa_conexao'] = janela
        log('faixa da conexao: aberta')
        guardar_no_topo(janela, 'faixa_conexao', TITULO_FAIXA_CONEXAO)

    import server
    _iniciar_atualizador_de_plugins()
    server.AO_PEDIDO_DO_JOGO = pedido_do_jogo
    server.AO_MENU_DO_JOGO = abrir_menu_do_jogo
    server.AO_DADOS_DO_JOGO = abrir_dados_do_jogo
    server.AO_AVISO_DA_CAPTURA = aviso_da_captura
    server.AO_AVISO_DA_CONEXAO = aviso_da_conexao
    server.AO_TESTAR_SOM = lambda: tocar_som(SOM_DA_FAIXA['inicio'], testar=True)

    import json
    import bandeja
    import bandeja_estado
    import idiomas

    bandeja_viva = {'ok': False, 'estado': bandeja_estado.DESCONECTADO, 'clube': None}
    estado_janela = {'escondida': False}

    def txt(chave, **valores):
        texto = idiomas.texto(settings.load().get('idioma') or 'pt', chave)
        for nome, valor in valores.items():
            texto = texto.replace('{{%s}}' % nome, str(valor))
        return texto

    def rotulo(estado, clube):
        if estado == bandeja_estado.CONECTADO:
            return txt('bandeja.conectado', clube=clube or 'FM')
        if estado == bandeja_estado.PERDIDA:
            return txt('bandeja.perdida')
        return txt('bandeja.desconectado')

    def disparar_na_tela(evento, detalhe=None):
        janela = janelas['principal']
        if janela is None:
            return
        try:
            janela.evaluate_js(f"window.dispatchEvent(new CustomEvent({json.dumps(evento)}, {{detail: {json.dumps(detalhe)}}}))")
        except Exception:
            log(f"bandeja: a tela nao recebeu {evento}:\n{traceback.format_exc()}")

    def mostrar():
        janela = janelas['principal']
        if janela is None:
            return False
        estado_janela['escondida'] = False
        janela.show()
        _trazer_para_frente()
        return True

    def esconder():
        janela = janelas['principal']
        if janela is None:
            return
        janela.hide()
        estado_janela['escondida'] = True
        if not settings.load().get('bandeja_aviso_visto'):
            settings.save(bandeja_aviso_visto=True)
            icone.notificar(txt('bandeja.avisoContinuaTitulo'), txt('bandeja.avisoContinuaTexto'))

    def fechar_por_dentro(janela):
        if janela is None:
            return
        janela.fmsh_liberada = True
        janela.destroy()

    def sair():
        for janela in list(webview.windows):
            try:
                fechar_por_dentro(janela)
            except Exception:
                log('bandeja: falha ao fechar uma janela ao sair:\n' + traceback.format_exc())

    def perguntar():
        janela = janelas['principal']
        try:
            atendeu = janela.evaluate_js('window.__fmshPerguntarAoFechar ? (window.__fmshPerguntarAoFechar(), true) : false')
        except Exception:
            atendeu = False
        if not atendeu:
            log('bandeja: a tela nao atendeu a pergunta do X (ainda carregando?): fechando como antes')
            fechar_por_dentro(janela)

    def ao_fechar_principal(window):
        decisao = bandeja_estado.decidir_fechamento(
            getattr(window, 'fmsh_liberada', False),
            bandeja_viva['ok'],
            icone.sessao_terminando(),
            settings.load().get('ao_fechar'),
        )
        if decisao == bandeja_estado.FECHAR:
            return True
        threading.Thread(
            target=esconder if decisao == bandeja_estado.ESCONDER else perguntar,
            daemon=True,
        ).start()
        return False

    def resposta_ao_fechar(acao):
        if acao == 'bandeja':
            esconder()
        else:
            fechar_por_dentro(janelas['principal'])

    TITULO_MENU_BANDEJA = 'FM Season Hub - menu da bandeja'
    PRAZO_DO_MENU = 3.0
    menu_atual = bandeja_estado.MenuAtual()
    dados_do_menu = {}
    janela_do_menu = {'janela': None, 'pronta': threading.Event()}
    trava_da_janela_do_menu = threading.Lock()

    TITULO_PAINEL_BANDEJA = 'FM Season Hub - plugins da bandeja'
    FORA_DA_TELA = -32000
    FOLGA_DO_PAINEL = 4
    ESPERA_PARA_FECHAR_O_PAINEL = 0.3
    janela_do_painel = {'janela': None, 'pronta': threading.Event()}

    def _hwnd_do_menu():
        achadas = _janelas_deste_processo(TITULO_MENU_BANDEJA, escondidas=True)
        return achadas[0] if achadas else None

    def _menu_carregou():
        hwnd = _hwnd_do_menu()
        if hwnd:
            _janela_de_ferramenta(hwnd)
        janela_do_menu['pronta'].set()
        log('bandeja: janela do menu pronta (hwnd %s)' % hwnd)

    def _menu_morreu():
        janela_do_menu['janela'] = None
        janela_do_menu['pronta'].clear()

    def _hwnd_do_painel():
        achadas = _janelas_deste_processo(TITULO_PAINEL_BANDEJA, escondidas=True)
        return achadas[0] if achadas else None

    def _painel_carregou():
        hwnd = _hwnd_do_painel()
        if hwnd:
            _janela_de_ferramenta(hwnd)
            _cantos_arredondados(hwnd)
            _tirar_o_painel()
        janela_do_painel['pronta'].set()
        log('bandeja: janela do painel de plugins pronta (hwnd %s)' % hwnd)

    def _painel_morreu():
        janela_do_painel['janela'] = None
        janela_do_painel['pronta'].clear()

    def criar_janela_do_menu():
        with trava_da_janela_do_menu:
            if janela_do_menu['janela'] is not None:
                return
            try:
                janela = webview.create_window(
                    TITULO_MENU_BANDEJA,
                    base + '/janela/menu-bandeja',
                    width=276,
                    height=460,
                    x=-32000,
                    y=-32000,
                    frameless=True,
                    on_top=True,
                    resizable=False,
                    hidden=True,
                    background_color='#10202E',
                )
                janela.events.loaded += _menu_carregou
                janela.events.closed += _menu_morreu
                janela_do_menu['janela'] = janela
            except Exception:
                log('bandeja: a janela do menu nao foi criada:\n' + traceback.format_exc())
                return

            try:
                painel = webview.create_window(
                    TITULO_PAINEL_BANDEJA,
                    base + '/janela/menu-bandeja?painel=1',
                    width=230,
                    height=200,
                    x=FORA_DA_TELA,
                    y=FORA_DA_TELA,
                    frameless=True,
                    on_top=True,
                    resizable=False,
                    min_size=(1, 1),
                    focus=False,
                    easy_drag=False,
                    background_color='#10202E',
                )
                painel.events.loaded += _painel_carregou
                painel.events.closed += _painel_morreu
                janela_do_painel['janela'] = painel
            except Exception:
                log('bandeja: a janela do painel de plugins nao foi criada:\n' + traceback.format_exc())
                return

    def fechar_janela_do_menu():
        for janela in (janela_do_painel['janela'], janela_do_menu['janela']):
            if janela is not None:
                try:
                    fechar_por_dentro(janela)
                except Exception:
                    log('bandeja: falha ao fechar a janela do menu:\n' + traceback.format_exc())

    def preparar_menu_da_bandeja():
        limite = time.monotonic() + 180
        while not bandeja_viva['ok'] and time.monotonic() < limite:
            time.sleep(1)
        if bandeja_viva['ok']:
            time.sleep(3)
            server.plugins_do_menu()
            criar_janela_do_menu()

    def _esconder(janela):
        if janela is not None:
            try:
                janela.hide()
            except Exception:
                log('bandeja: falha ao esconder o menu:\n' + traceback.format_exc())

    def fechar_menu_bandeja(n=None):
        aceito, janela = menu_atual.tirar(n)
        if aceito:
            dados_do_menu.clear()
            _tirar_o_painel()
        _esconder(janela)

    def _usar_o_nativo(n, motivo):
        ganhou, janela = menu_atual.desistir(n)
        if not ganhou:
            return
        ponto = dados_do_menu.get(n, {}).get('ponto')
        log('bandeja: %s; usando o menu nativo' % motivo)
        _esconder(janela)
        if ponto:
            icone.mostrar_menu_nativo(*ponto)

    def abrir_menu_bandeja(x, y):
        janela = janela_do_menu['janela']
        if janela is None or not janela_do_menu['pronta'].is_set():
            log('bandeja: a janela do menu ainda nao esta pronta; usando o menu nativo')
            icone.mostrar_menu_nativo(x, y)
            if janela is None:
                threading.Thread(target=criar_janela_do_menu, daemon=True).start()
            return
        fechar_menu_bandeja()
        n = menu_atual.reservar()
        menu_atual.registrar(n, janela)
        apareceu = threading.Event()
        dados_do_menu.clear()
        dados_do_menu[n] = {'ponto': (x, y), 'geo': None, 'apareceu': apareceu}

        def _pedir_a_pagina():
            try:
                janela.evaluate_js('window.__fmshAbrirMenu && window.__fmshAbrirMenu(%d)' % n)
            except Exception:
                log('bandeja: a pagina do menu nao respondeu:\n' + traceback.format_exc())
                _usar_o_nativo(n, 'a pagina do menu nao respondeu')

        threading.Thread(target=_pedir_a_pagina, name='pedido-ao-menu', daemon=True).start()
        if not apareceu.wait(PRAZO_DO_MENU):
            _usar_o_nativo(n, 'a pagina do menu nao ficou pronta em %.0f s' % PRAZO_DO_MENU)

    def menu_pronto(n, largura, altura):
        if not menu_atual.pronto(n):
            return
        dados = dados_do_menu.get(n)
        try:
            _mostrar_o_menu(n, dados, largura, altura)
        except Exception:
            log('bandeja: falha ao mostrar o menu:\n' + traceback.format_exc())
            fechar_menu_bandeja(n)
            if dados:
                icone.mostrar_menu_nativo(*dados['ponto'])
        finally:
            if dados:
                dados['apareceu'].set()

    def _mostrar_o_menu(n, dados, largura, altura):
        hwnd = _hwnd_do_menu()
        janela = menu_atual.janela(n)
        if dados is None or (sys.platform == 'win32' and hwnd is None) or janela is None:
            log('bandeja: janela do menu nao encontrada para posicionar; usando o menu nativo')
            fechar_menu_bandeja(n)
            if dados:
                icone.mostrar_menu_nativo(*dados['ponto'])
            return
        ponto = dados['ponto']
        monitor, area, escala = _tela_do_ponto(*ponto)
        w = round(largura * escala)
        h = round(altura * escala)
        x, y = bandeja_estado.posicao_do_menu(ponto, area, monitor, w, h)
        dados['geo'] = (x, y, w, h, area, escala)
        if hwnd:
            _janela_de_ferramenta(hwnd)
            _cantos_arredondados(hwnd)
        janela.resize(round(w / escala), round(h / escala))
        janela.move(round(x / escala), round(y / escala))
        janela.show()

        if sys.platform == 'win32' and hwnd:
            import ctypes
            limite = time.monotonic() + 0.5
            while not ctypes.windll.user32.IsWindowVisible(hwnd) and time.monotonic() < limite:
                time.sleep(0.01)
            _posicionar(hwnd, x, y, w, h)
            _dar_foco(TITULO_MENU_BANDEJA)
            threading.Thread(target=_vigiar_o_foco, args=(n, hwnd), name='foco-do-menu', daemon=True).start()

        log('bandeja: menu em (%s,%s) %sx%s, escala %.2f' % (x, y, w, h, escala))

    def _vigiar_o_foco(n, hwnd):
        if sys.platform != 'win32':
            return
        import ctypes
        teve = False
        inicio = time.monotonic()
        insistiu = False
        while menu_atual.janela(n) is not None:
            if ctypes.windll.user32.GetForegroundWindow() == hwnd:
                teve = True
            elif teve:
                fechar_menu_bandeja(n)
                return
            elif not insistiu and (time.monotonic() - inicio) > 1.0:
                insistiu = True
                log('bandeja: o menu nao recebeu o foco; tentando de novo')
                _dar_foco(TITULO_MENU_BANDEJA)
            time.sleep(0.1)

    def _tirar_o_painel():
        hwnd = _hwnd_do_painel()
        if hwnd:
            import ctypes
            from ctypes import wintypes
            u = ctypes.WinDLL('user32', use_last_error=True)
            u.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            u.SetWindowPos(hwnd, None, FORA_DA_TELA, FORA_DA_TELA, 0, 0, 149)

    def fechar_painel(n):
        if not menu_atual.fechar_painel(n):
            return
        _tirar_o_painel()
        janela = menu_atual.janela(n)
        if janela is not None:
            try:
                janela.evaluate_js('window.__fmshPainelFechou && window.__fmshPainelFechou(%d)' % n)
            except Exception:
                log('bandeja: o menu nao recebeu o fechar do painel:\n' + traceback.format_exc())

    def _vigiar_o_painel(n, linha, painel):
        if sys.platform != 'win32':
            return
        import ctypes
        from ctypes import wintypes
        ponto = wintypes.POINT()
        dentro = lambda r: (r[0] <= ponto.x < r[2]) and (r[1] <= ponto.y < r[3])
        fora_desde = None
        while menu_atual.painel_aberto(n):
            ctypes.windll.user32.GetCursorPos(ctypes.byref(ponto))
            if dentro(linha) or dentro(painel):
                fora_desde = None
            elif fora_desde is None:
                fora_desde = time.monotonic()
            elif time.monotonic() - fora_desde >= ESPERA_PARA_FECHAR_O_PAINEL:
                fechar_painel(n)
                return
            time.sleep(0.05)

    def mostrar_painel(n, linha, largura, altura):
        dados = dados_do_menu.get(n)
        painel = janela_do_painel['janela']
        hwnd = _hwnd_do_painel()
        if dados is None or dados.get('geo') is None or painel is None or (sys.platform == 'win32' and hwnd is None) or not janela_do_painel['pronta'].is_set():
            return
        if not menu_atual.abrir_painel(n):
            return dados.get('lado_do_painel')

        x, y, w, h, area, escala = dados['geo']
        lx, ly, lw, lh = (round(v * escala) for v in linha)
        pw = round(largura * escala)
        ph = round(altura * escala)
        px, py, lado = bandeja_estado.posicao_do_painel((x, y, w, h), ly, pw, ph, round(FOLGA_DO_PAINEL * escala), area)
        dados['lado_do_painel'] = lado

        try:
            painel.evaluate_js('window.__fmshAbrirPainel && window.__fmshAbrirPainel(%d, %s)' % (n, json.dumps(server.plugins_do_menu())))
        except Exception:
            log('bandeja: o painel de plugins nao respondeu:\n' + traceback.format_exc())
            menu_atual.fechar_painel(n)
            return

        if hwnd:
            _posicionar(hwnd, px, py, pw, ph, mostrar=True)
            threading.Thread(
                target=_vigiar_o_painel,
                name='painel-da-bandeja',
                daemon=True,
                args=(
                    n,
                    (x + lx, y + ly, x + lx + lw, y + ly + lh),
                    (px, py, px + pw, py + ph),
                ),
            ).start()
        else:
            painel.resize(round(pw / escala), round(ph / escala))
            painel.move(round(px / escala), round(py / escala))
            painel.show()

        log(f"bandeja: painel de plugins em ({px},{py}) {pw}x{ph}, {lado}")
        return lado

    def montar_menu():
        estado = bandeja_viva['estado']
        clube = bandeja_viva['clube']
        marca = '●  ' if estado == bandeja_estado.CONECTADO else '○  '
        if estado == bandeja_estado.CONECTADO:
            conexao = {'id': 'desconectar', 'texto': txt('bandeja.desconectar')}
        else:
            conexao = {'id': 'conectar', 'texto': txt('bandeja.conectar')}

        return [
            {'id': 'status', 'texto': marca + rotulo(estado, clube), 'ativo': False},
            None,
            conexao,
            None,
            {'id': 'abrir', 'texto': txt('bandeja.abrir')},
            {'id': 'ir:/database', 'texto': txt('bandeja.base')},
            {'id': 'ir:/my-team', 'texto': txt('bandeja.meuTime')},
            {'id': 'ir:/seasons', 'texto': txt('bandeja.temporadas')},
            {'id': 'ir:/settings', 'texto': txt('bandeja.config')},
            None,
            {'id': 'sair', 'texto': txt('bandeja.sair')},
        ]

    def ao_escolher(item):
        if item == 'abrir':
            mostrar()
            return
        if item.startswith('ir:'):
            mostrar()
            disparar_na_tela('fmsh-ir', item[3:])
            return
        if item in ('conectar', 'desconectar'):
            if item == 'conectar':
                server.iniciar_faixa_da_conexao()
                threading.Thread(target=aviso_da_conexao, args=('inicio',), daemon=True).start()
            disparar_na_tela('fmsh-' + item)
            return
        if item == 'atualizar':
            mostrar()
            disparar_na_tela('fmsh-atualizar')
            return
        if item == 'sair':
            sair()
            return

    def vigiar_bandeja():
        avisador = bandeja_estado.Avisador(settings.load().get('bandeja_versao_avisada'))
        proxima_versao = time.monotonic() + 60
        while True:
            try:
                estado, clube = server.estado_da_conexao(avisador.anterior)
                aviso = avisador.mudou_estado(estado, estado_janela['escondida'])
                if (estado, clube) != (bandeja_viva['estado'], bandeja_viva['clube']):
                    bandeja_viva.update(estado=estado, clube=clube)
                    icone.mudar_estado(estado, DICA_DA_BANDEJA + ' · ' + rotulo(estado, clube))
                if aviso == bandeja_estado.AVISO_CONEXAO_PERDIDA:
                    icone.notificar(txt('bandeja.perdida'), txt('bandeja.avisoPerdidaTexto'))
                if time.monotonic() >= proxima_versao:
                    proxima_versao = time.monotonic() + INTERVALO_DA_VERSAO
                    v = atualizacao.verificar()
                    if v.get('tem_nova') and not v.get('dispensada'):
                        if avisador.versao_nova(v['versao'], estado_janela['escondida']):
                            icone.notificar(
                                txt('bandeja.avisoVersaoTitulo', versao=v['versao']),
                                txt('bandeja.avisoVersaoTexto'),
                            )
                        if avisador.versao_avisada != settings.load().get('bandeja_versao_avisada'):
                            settings.save(bandeja_versao_avisada=avisador.versao_avisada)
            except Exception:
                log('bandeja: falha ao conferir o estado:\n' + traceback.format_exc())
            time.sleep(INTERVALO_DA_BANDEJA)

    def bandeja_pronta():
        if bandeja_viva['ok']:
            return
        bandeja_viva['ok'] = True
        if isinstance(server.BANDEJA_ATIVA, dict):
            server.BANDEJA_ATIVA['ok'] = True
        else:
            server.BANDEJA_ATIVA = {'ok': True}
        threading.Thread(target=vigiar_bandeja, name='vigia-da-bandeja', daemon=True).start()

    def bandeja_apareceu_depois():
        log('bandeja: o icone apareceu depois da abertura (a bandeja do Windows ficou pronta)')
        bandeja_pronta()

    pasta_dos_icones = paths.resource_path('src', 'web', 'bandeja')
    icone = bandeja.Bandeja(
        {e: os.path.join(pasta_dos_icones, 'bandeja-%s.ico' % e) for e in bandeja_estado.ESTADOS},
        bandeja_estado.DESCONECTADO,
        DICA_DA_BANDEJA + ' · ' + txt('bandeja.desconectado'),
        montar_menu=montar_menu,
        ao_clicar=mostrar,
        ao_escolher=ao_escolher,
        icone_da_notificacao=os.path.join(pasta_dos_icones, 'bandeja-app.ico'),
        ao_aparecer=bandeja_apareceu_depois,
        abrir_menu=abrir_menu_bandeja,
    )

    if icone.iniciar():
        bandeja_pronta()
    else:
        log('bandeja: o icone nao foi criado (%s); o X fecha o app como antes' % getattr(icone, 'erro', 'desativado'))

    server.AO_MOSTRAR_JANELA = mostrar
    server.ESTADO_DA_BANDEJA = bandeja_viva
    server.AO_MENU_PRONTO = menu_pronto
    server.AO_MENU_PAINEL = mostrar_painel
    server.AO_FECHAR_MENU = fechar_menu_bandeja
    server.AO_ESCOLHER_NA_BANDEJA = ao_escolher
    server.AO_SAIR = sair
    server.AO_RESPOSTA_AO_FECHAR = resposta_ao_fechar

    def conectar_pela_tela():
        janela = janelas['principal']
        if janela is None:
            return False
        try:
            return bool(janela.evaluate_js('window.__fmshConectar ? (window.__fmshConectar(), true) : false'))
        except Exception:
            log('conectar pelo jogo: a tela nao atendeu:\n' + traceback.format_exc())
            return False

    server.AO_CONECTAR_PELA_TELA = conectar_pela_tela

    escondida_na_abertura = em_bandeja and bandeja_viva['ok']
    estado_janela['escondida'] = escondida_na_abertura

    if atualizacao.instalado() and not em_bandeja:
        janelas['caixa'] = caixinha()
        log('app instalado: conferindo atualizacao antes de abrir')
    else:
        janelas['principal'] = janela_principal(escondida=escondida_na_abertura)
        log('abrindo janela%s…' % (' escondida (bandeja)' if escondida_na_abertura else ''))

    def atualizar(man):
        if atualizacao.executar(man, soltar_trava=_soltar_mutex):
            time.sleep(1.5)
            janelas['caixa'].destroy()
            return True
        _segurar_mutex()
        time.sleep(2.5)
        return False

    def orquestrar():
        if janelas['caixa'] is not None:
            visivel_desde = caixa_visivel()
            try:
                with open(paths.local_data_path('caixinha_aberta'), 'w') as f:
                    f.write('1')
            except OSError:
                pass
            man = atualizacao.na_abertura()
            if man:
                log('versao %s disponivel: atualizando na abertura' % man['versao'])
                if atualizar(man):
                    return
            _plugins_na_abertura()
            resto = CAIXA_MINIMO - (time.time() - visivel_desde)
            if resto > 0:
                time.sleep(resto)
            atualizacao._estado(fase='abrindo')
            janelas['principal'] = janela_principal()
            janelas['caixa'].destroy()
            janelas['caixa'] = None

        while True:
            atualizacao.PEDIDO.wait()
            atualizacao.PEDIDO.clear()
            man = atualizacao.manifesto_pendente()
            if not man:
                continue
            log('versao %s: atualizacao pedida pela pessoa' % man['versao'])
            janelas['caixa'] = caixinha()
            caixa_visivel()
            fechar_por_dentro(janelas['principal'])
            if atualizar(man):
                return
            atualizacao._estado(fase='abrindo')
            janelas['principal'] = janela_principal()
            janelas['caixa'].destroy()
            janelas['caixa'] = None

    perfil = paths.local_data_path('webview')
    log('perfil do webview em %s' % perfil)

    def ao_iniciar_o_webview():
        if sys.platform == 'darwin':
            from PyObjCTools import AppHelper
            from window_macos import install_window_menu
            AppHelper.callAfter(install_window_menu)
        threading.Thread(target=orquestrar, daemon=True).start()
        threading.Thread(target=preparar_menu_da_bandeja, name='menu-da-bandeja', daemon=True).start()

    webview.start(ao_iniciar_o_webview, private_mode=False, storage_path=perfil)

    try:
        icone.remover()
    except Exception:
        log('bandeja: nao consegui remover o icone:\n' + traceback.format_exc())

    try:
        import server
        server.parar_leitura_viva()
    except Exception:
        pass

    _apagar_porta()

    try:
        import navegador_do_jogo
        navegador_do_jogo.fechar()
    except Exception:
        pass

    log('janela fechada — encerrando')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log('FALHA FATAL:\n' + traceback.format_exc())
        raise
