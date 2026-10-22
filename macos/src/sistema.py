import sys

_CACHE = None

_CHAVES_LAYERS = (
    ('HKCU', r'Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'),
    ('HKLM', r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'),
)


def _registro():
    try:
        import winreg
        chave = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, chave) as k:
            def ler(nome):
                try:
                    return winreg.QueryValueEx(k, nome)[0]
                except OSError:
                    return None
            return {
                'produto': ler('ProductName'),
                'versao': ler('DisplayVersion'),
                'build': ler('CurrentBuildNumber'),
                'ubr': ler('UBR'),
            }
    except Exception:
        return {}


def processo_elevado(pid):
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        PROCESS_QUERY_LIMITED = 4096
        TOKEN_QUERY = 8
        TokenElevation = 20
        k32 = ctypes.windll.kernel32
        adv = ctypes.windll.advapi32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, int(pid))
        if not h:
            return None
        try:
            tok = ctypes.c_void_p()
            if not adv.OpenProcessToken(ctypes.c_void_p(h), TOKEN_QUERY, ctypes.byref(tok)):
                k32.CloseHandle(h)
                return True
            try:
                elev = ctypes.c_uint(0)
                devolvido = ctypes.c_uint(0)
                if not adv.GetTokenInformation(tok, TokenElevation, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(devolvido)):
                    return None
                return bool(elev.value)
            finally:
                k32.CloseHandle(tok)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def marcas_compatibilidade(pedacos):
    if sys.platform != 'win32':
        return []
    try:
        import winreg
    except ImportError:
        return []
    pedacos = tuple(p.lower() for p in pedacos if p)
    achados = []
    for origem, caminho in _CHAVES_LAYERS:
        raiz = winreg.HKEY_CURRENT_USER if origem == 'HKCU' else winreg.HKEY_LOCAL_MACHINE
        try:
            with winreg.OpenKey(raiz, caminho) as k:
                i = 0
                while True:
                    try:
                        nome_, valor, _ = winreg.EnumValue(k, i)
                        i += 1
                        if any(p in nome_.lower() for p in pedacos):
                            achados.append((origem, nome_, str(valor)))
                    except OSError:
                        break
        except OSError:
            pass
    return achados


def nome():
    global _CACHE
    if _CACHE:
        return _CACHE
    if sys.platform != 'win32':
        import platform
        _CACHE = f'{platform.system()} {platform.release()}'
        return _CACHE
    r = _registro()
    try:
        build = int(r.get('build') or sys.getwindowsversion().build)
    except (TypeError, ValueError):
        build = sys.getwindowsversion().build
    produto = r.get('produto') or 'Windows'
    edicao = ''
    for palavra in ('Pro for Workstations', 'Enterprise', 'Education', 'Pro', 'Home', 'Server'):
        if palavra in produto:
            edicao = ' ' + palavra
            break
    if build >= 22000:
        familia = 'Windows 11'
    else:
        familia = 'Windows 10'
    if 'Server' in produto:
        familia = produto.split(',')[0].strip()
        edicao = ''
    partes = [familia + edicao]
    if r.get('versao'):
        partes.append(str(r['versao']))
    completa = str(build) + (('.' + str(r['ubr'])) if r.get('ubr') is not None else '')
    partes.append('(build %s)' % completa)
    partes.append('- %d bits' % (64 if sys.maxsize > 4294967296 else 32))
    _CACHE = ' '.join(partes)
    return _CACHE
