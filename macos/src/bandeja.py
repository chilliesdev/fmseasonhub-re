import sys
import threading
import subprocess

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes, WinDLL, c_ssize_t, WINFUNCTYPE

    user32 = WinDLL('user32', use_last_error=True)
    shell32 = WinDLL('shell32', use_last_error=True)
    kernel32 = WinDLL('kernel32', use_last_error=True)

    LRESULT = c_ssize_t
    HWND = wintypes.HWND
    UINT = wintypes.UINT
    WPARAM = wintypes.WPARAM
    LPARAM = wintypes.LPARAM
    WNDPROC = WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

    WM_NULL = 0
    WM_DESTROY = 2
    WM_CLOSE = 16
    WM_QUERYENDSESSION = 17
    WM_ENDSESSION = 22
    SM_SHUTTINGDOWN = 8192
    WM_TIMER = 275
    WM_CONTEXTMENU = 123
    WM_LBUTTONDBLCLK = 515
    WM_USER = 1024
    WM_APP = 32768
    NIN_SELECT = WM_USER + 0
    NIN_KEYSELECT = WM_USER + 1
    NIN_BALLOONUSERCLICK = WM_USER + 5
    NIM_ADD = 0
    NIM_MODIFY = 1
    NIM_DELETE = 2
    NIM_SETVERSION = 4
    NOTIFYICON_VERSION_4 = 4
    NIF_MESSAGE = 1
    NIF_ICON = 2
    NIF_TIP = 4
    NIF_INFO = 16
    NIF_GUID = 32
    NIIF_INFO = 1
    NIIF_LARGE_ICON = 32


class Bandeja:
    def __init__(
        self,
        icones,
        estado_inicial,
        dica='',
        montar_menu=None,
        ao_clicar=None,
        ao_escolher=None,
        icone_da_notificacao=None,
        nome_da_classe='FMSHBandeja',
        ao_aparecer=None,
        intervalo_de_nova_tentativa_ms=1000,
        abrir_menu=None,
    ):
        self._caminhos = dict(icones) if icones else {}
        self._estado = estado_inicial
        self._dica = dica
        self._montar_menu = montar_menu
        self._ao_clicar = ao_clicar
        self._ao_escolher = ao_escolher
        self._caminho_notificacao = icone_da_notificacao
        self._nome_da_classe = nome_da_classe
        self._ao_aparecer = ao_aparecer
        self._intervalo = intervalo_de_nova_tentativa_ms
        self._abrir_menu = abrir_menu
        self._hwnd = None
        self._icones = {}
        self._icone_notificacao = None
        self._pronto = threading.Event()
        self._criado = False
        self._trava = threading.Lock()
        self._sessao_terminando = False
        self._ponto_nativo = None

    def iniciar(self, espera=None):
        self._criado = True
        self._pronto.set()
        if self._ao_aparecer:
            try:
                self._ao_aparecer(True)
            except Exception:
                pass

    def mudar_estado(self, estado, dica=None):
        with self._trava:
            self._estado = estado
            if dica is not None:
                self._dica = dica

    def notificar(self, titulo, texto, dados=None):
        if sys.platform == 'darwin':
            try:
                t_esc = (titulo or 'FM Season Hub').replace('"', '\\"')
                m_esc = (texto or '').replace('"', '\\"')
                subprocess.run(['osascript', '-e', f'display notification "{m_esc}" with title "{t_esc}"'], check=False)
            except Exception:
                pass

    def mostrar_menu_nativo(self, x=None, y=None):
        self._ponto_nativo = (x, y)

    def sessao_terminando(self):
        return self._sessao_terminando

    def remover(self):
        with self._trava:
            self._criado = False
