import json
import urllib.request


def _ler_porta(caminho):
    try:
        with open(caminho, encoding='ascii') as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def pedir_para_mostrar(caminho_da_porta, espera=3.0):
    porta = _ler_porta(caminho_da_porta)
    if not porta:
        return False
    pedido = urllib.request.Request(
        'http://127.0.0.1:%d/api/janela/mostrar' % porta,
        data=b'',
        method='POST',
    )
    try:
        with urllib.request.urlopen(pedido, timeout=espera) as r:
            return r.status == 200 and json.loads(r.read() or b'{}').get('disponivel') is True
    except Exception:
        return False
