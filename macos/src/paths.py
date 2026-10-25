import os
import sys
from pathlib import Path

FROZEN = getattr(sys, 'frozen', False)
APP_FOLDER_NAME = 'FM Season Hub'

if getattr(sys, '_MEIPASS', None):
    _RES_ROOT = os.path.join(sys._MEIPASS, 'fmsh')
elif FROZEN:
    cand = os.path.join(os.path.dirname(sys.executable), '_internal', 'fmsh')
    if os.path.exists(cand):
        _RES_ROOT = cand
    else:
        _RES_ROOT = os.path.abspath(os.path.join(os.path.dirname(sys.executable), '..', 'Resources', 'fmsh'))
else:
    _src_parent = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    cand = os.path.join(_src_parent, 'fmsh')
    if os.path.exists(cand):
        _RES_ROOT = cand
    else:
        _RES_ROOT = _src_parent


def app_dir():
    if FROZEN:
        return os.path.dirname(sys.executable)
    return _src_parent


def documents_dir():
    if sys.platform != 'win32':
        return os.path.join(os.path.expanduser('~'), 'Documents')
    try:
        import ctypes
        import ctypes.wintypes
        from ctypes import wintypes

        class _Guid(ctypes.Structure):
            _fields_ = [
                ('Data1', wintypes.DWORD),
                ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD),
                ('Data4', wintypes.BYTE * 8),
            ]

        guid = _Guid()
        ctypes.windll.ole32.CLSIDFromString('{FDD39AD0-238F-46AF-ADB4-6C85480369C7}', ctypes.byref(guid))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
            if out.value:
                return out.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


ALPHA_FOLDER_NAME = 'alpha'


def _escolher_raiz_dos_dados():
    forcada = os.environ.get('FMSH_PASTA_DADOS')
    if forcada:
        return forcada
    base = os.path.join(documents_dir(), APP_FOLDER_NAME)
    if FROZEN:
        return base
    return os.path.join(base, ALPHA_FOLDER_NAME)


_DATA_ROOT = _escolher_raiz_dos_dados()

INSTALADO = FROZEN and os.path.isfile(os.path.join(os.path.dirname(sys.executable), 'unins000.exe'))


def _escolher_raiz_local():
    forcada = os.environ.get('FMSH_PASTA_LOCAL')
    if forcada:
        return forcada
    if sys.platform == 'darwin':
        return str(Path.home() / 'Library' / 'Application Support' / 'FMSeasonHub')
    if INSTALADO and not os.environ.get('FMSH_PASTA_DADOS'):
        return os.path.join(os.path.dirname(sys.executable), 'dados')
    return _DATA_ROOT


_LOCAL_ROOT = _escolher_raiz_local()


def local_root():
    try:
        os.makedirs(_LOCAL_ROOT, exist_ok=True)
    except OSError:
        pass
    return _LOCAL_ROOT


def local_data_path(*parts):
    return os.path.join(local_root(), *parts)


_PARA_A_PASTA_LOCAL = ('webview', 'fmsh_avisos.json', 'fmsh_versao.json', 'fmsh_apoiadores.json')
BANCO = 'fm26_snapshots.db'


def banco_padrao(create_parent=True):
    local = os.path.join(_LOCAL_ROOT, BANCO)
    antigo = os.path.join(_DATA_ROOT, BANCO)
    if not os.path.exists(local) and os.path.exists(antigo):
        return antigo
    return local_data_path(BANCO) if create_parent else local


def migrar_para_pasta_local(mover_banco=True, log=None):
    import shutil
    if os.path.normcase(os.path.abspath(_LOCAL_ROOT)) == os.path.normcase(os.path.abspath(_DATA_ROOT)):
        return []

    feitos = []

    def avisar(msg):
        if log:
            log(msg)

    origem = os.path.join(_DATA_ROOT, BANCO)
    destino = os.path.join(local_root(), BANCO)
    if mover_banco and os.path.exists(origem):
        if os.path.exists(destino):
            avisar('banco existe em Documentos e na pasta local: o de Documentos ficou intocado')
        else:
            try:
                import sqlite3
                con = sqlite3.connect(origem)
                con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                con.close()
                shutil.copy2(origem, destino + '.movendo')
                os.replace(destino + '.movendo', destino)
                os.remove(origem)
                for resto in ('-wal', '-shm'):
                    if os.path.exists(origem + resto):
                        os.remove(origem + resto)
                feitos.append(BANCO)
            except Exception as e:
                avisar('nao consegui mudar o banco de lugar (segue em Documentos): %s' % e)

    for nome in _PARA_A_PASTA_LOCAL:
        de = os.path.join(_DATA_ROOT, nome)
        para = os.path.join(local_root(), nome)
        if os.path.exists(de) and not os.path.exists(para):
            shutil.move(de, para)
            feitos.append(nome)

    cache_de = os.path.join(_DATA_ROOT, 'cache')
    cache_para = os.path.join(local_root(), 'cache')
    if os.path.isdir(cache_de) and not os.path.exists(origem) and not os.path.exists(cache_para):
        shutil.move(cache_de, cache_para)
        feitos.append('cache')

    if feitos:
        avisar(f'de Documentos para {_LOCAL_ROOT}: ' + ', '.join(feitos))
    return feitos


def data_root():
    try:
        os.makedirs(_DATA_ROOT, exist_ok=True)
    except OSError:
        pass
    return _DATA_ROOT


def resource_path(*parts):
    return os.path.join(_RES_ROOT, *parts)


def user_data_path(*parts):
    return os.path.join(data_root(), *parts)


def biblioteca_dir():
    destino = user_data_path('Biblioteca')
    try:
        os.makedirs(destino, exist_ok=True)
    except OSError:
        pass
    return destino


def idiomas_dir():
    if FROZEN:
        destino = user_data_path('Idiomas')
    else:
        destino = os.path.join(_RES_ROOT, 'idiomas_do_usuario')
    try:
        os.makedirs(destino, exist_ok=True)
    except OSError:
        pass
    return destino


def idiomas_embarcados():
    return resource_path('idiomas')


def migrate_legacy_files(names, log=None):
    if not FROZEN:
        return []
    import shutil
    old_dir = os.path.dirname(sys.executable)
    if os.path.normcase(old_dir) == os.path.normcase(_DATA_ROOT):
        return []
    moved = []
    for name in names:
        src = os.path.join(old_dir, name)
        dst = os.path.join(data_root(), name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.move(src, dst)
                moved.append(name)
            except OSError as e:
                if log:
                    log(f'nao consegui mover {name}: {e}')
    if moved and log:
        log(f'migrados de {old_dir}: ' + ', '.join(moved))
    return moved


def sports_interactive_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Sports Interactive'
    return Path(documents_dir()) / 'Sports Interactive'


def steam_fm26_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Steam' / 'steamapps' / 'common' / 'Football Manager 26'
    return Path(r'C:\Program Files (x86)\Steam\steamapps\common\Football Manager 26')
