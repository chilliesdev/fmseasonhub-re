import sys

try:
    import winreg
except ImportError:
    winreg = None

import paths

CHAVE = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALOR = 'FMSH'
ARGUMENTO = '--bandeja'


def disponivel():
    if sys.platform != 'win32':
        return False
    return bool(paths.FROZEN)


def comando(exe=None):
    target = exe if exe else sys.executable
    return f'"{target}" {ARGUMENTO}'


def ligado(chave=CHAVE, valor=VALOR):
    if sys.platform != 'win32' or winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as k:
            atual, _ = winreg.QueryValueEx(k, valor)
            return bool(atual)
    except OSError:
        return False


def mudar(ligar, chave=CHAVE, valor=VALOR, exe=None, so_no_exe=True):
    if so_no_exe and not disponivel():
        return False
    if sys.platform != 'win32' or winreg is None:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chave) as k:
            if ligar:
                winreg.SetValueEx(k, valor, 0, winreg.REG_SZ, comando(exe))
            else:
                try:
                    winreg.DeleteValue(k, valor)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
