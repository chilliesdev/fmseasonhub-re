import sys

LARGURA = 1161
ALTURA = 595
PROPORCAO = LARGURA / ALTURA
FOLGA_DO_ICONE = 24
FOLGA_DA_BORDA = 8
LARGURA_MINIMA = 640
MAXIMO_DA_LARGURA = 0.9


def tela_principal():
    try:
        if sys.platform == 'darwin':
            try:
                from AppKit import NSScreen
                frame = NSScreen.mainScreen().frame()
                return (0, 0, int(frame.size.width), int(frame.size.height))
            except Exception:
                return (0, 0, 1920, 1080)
        import ctypes
        u = ctypes.windll.user32
        return (0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1))
    except (AttributeError, OSError, ImportError):
        return None


def geometria(icone, jogo):
    gx, gy, gw, gh = jogo
    if gw <= 0 or gh <= 0:
        return None
    largura = min(LARGURA, int(gw * MAXIMO_DA_LARGURA))
    altura = round(largura / PROPORCAO)
    ax, ay, aw, ah = icone
    if aw > 0 and ah > 0:
        topo = ay + ah + FOLGA_DO_ICONE
    else:
        topo = gy + (gh - altura) // 2
    limite = gy + gh - FOLGA_DA_BORDA
    if topo + altura > limite:
        disponivel = limite - topo
        if disponivel >= round(LARGURA_MINIMA / PROPORCAO):
            largura = max(LARGURA_MINIMA, int(disponivel * PROPORCAO))
            altura = round(largura / PROPORCAO)
        if topo + altura > limite:
            topo = max(gy, limite - altura)
    return (
        gx + (gw - largura) // 2,
        max(topo, gy),
        largura,
        altura,
    )
