CONECTADO = 'conectado'
DESCONECTADO = 'desconectado'
PERDIDA = 'perdida'
ESTADOS = (CONECTADO, DESCONECTADO, PERDIDA)
AVISO_CONEXAO_PERDIDA = 'conexao_perdida'
JOBS_DE_LEITURA = ('connect', 'refresh')


def estado_da_conexao(pronto, job_ocupado, job_tipo, fm_rodando, anterior):
    if job_ocupado and job_tipo in JOBS_DE_LEITURA:
        return CONECTADO
    if not pronto:
        return DESCONECTADO
    if job_ocupado:
        return anterior if anterior else CONECTADO
    if fm_rodando:
        return CONECTADO
    return PERDIDA


FECHAR, ESCONDER, PERGUNTAR = 'fechar', 'esconder', 'perguntar'


def decidir_fechamento(liberada, icone_ok, sessao_terminando, modo):
    if liberada or not icone_ok or sessao_terminando or modo == 'fechar':
        return FECHAR
    if modo == 'bandeja':
        return ESCONDER
    return PERGUNTAR


class Avisador:
    def __init__(self, versao_ja_avisada=None):
        self.anterior = None
        self.versao_avisada = versao_ja_avisada if versao_ja_avisada else None

    def mudou_estado(self, novo, janela_escondida):
        antes = self.anterior
        self.anterior = novo
        if novo == PERDIDA and antes == CONECTADO and janela_escondida:
            return AVISO_CONEXAO_PERDIDA
        return None

    def versao_nova(self, versao, janela_escondida):
        if not versao or versao == self.versao_avisada:
            return False
        self.versao_avisada = versao
        return bool(janela_escondida)


def posicao_do_menu(cursor, area, monitor, largura, altura):
    cx, cy = cursor
    esquerda, topo, direita, base = area
    x = cx if (cx + largura) <= direita else (cx - largura)
    y = cy if (topo > monitor[1]) else (cy - altura)
    x = min(max(x, esquerda), direita - largura)
    y = min(max(y, topo), base - altura)
    return (x, y)


def posicao_do_painel(menu, topo_da_linha, largura, altura, folga, area):
    x, y, largura_menu, _ = menu
    if x + largura_menu + folga + largura <= area[2]:
        px = x + largura_menu + folga
        lado = 'direita'
    else:
        px = x - folga - largura
        lado = 'esquerda'
    py = min(max(y + topo_da_linha, area[1]), area[3] - altura)
    return (px, py, lado)


def plugins_do_menu(tela):
    saida = []
    por_id = {}
    for jogo in (tela.get('jogos') or []):
        for p in (jogo.get('plugins') or []):
            if p.get('id') in por_id:
                if not por_id[p['id']]['reiniciar']:
                    por_id[p['id']]['reiniciar'] = bool(p.get('reiniciar'))
            else:
                item = {
                    'id': p.get('id'),
                    'nome': p.get('nome') or p.get('id'),
                    'versao': p.get('instalada'),
                    'reiniciar': bool(p.get('reiniciar')),
                }
                por_id[item['id']] = item
                saida.append(item)
    return saida


class MenuAtual:
    def __init__(self):
        import threading
        self._trava = threading.Lock()
        self._n = 0
        self._janela = None
        self._fechado = True
        self._decidido = False
        self._painel = False

    def _vale(self, n):
        return n == self._n and not self._fechado

    def reservar(self):
        with self._trava:
            self._n += 1
            self._janela, self._fechado, self._decidido, self._painel = None, False, False, False
            return self._n

    def registrar(self, n, janela):
        with self._trava:
            if not self._vale(n):
                return False
            self._janela = janela
            return True

    def pronto(self, n):
        with self._trava:
            if not self._vale(n) or self._decidido:
                return False
            self._decidido = True
            return True

    def janela(self, n):
        with self._trava:
            return self._janela if self._vale(n) else None

    def desistir(self, n):
        with self._trava:
            if not self._vale(n) or self._decidido:
                return False, None
            self._decidido = True
            self._fechado = True
            janela = self._janela
            self._janela = None
            return True, janela

    def abrir_painel(self, n):
        with self._trava:
            if not self._vale(n) or self._painel:
                return False
            self._painel = True
            return True

    def fechar_painel(self, n):
        with self._trava:
            if not self._vale(n) or not self._painel:
                return False
            self._painel = False
            return True

    def painel_aberto(self, n):
        with self._trava:
            return self._vale(n) and self._painel

    def tirar(self, n=None):
        with self._trava:
            if n is not None and n != self._n:
                return False, None
            self._fechado = True
            janela = self._janela
            self._janela = None
            return True, janela


ESPERA_PELA_CONEXAO_S = 15


def faixa_da_conexao(job, leitura_pronta, viu_rodando, esperando_s):
    if job.get('kind') == 'connect' and job.get('state') == 'running':
        return ('conectando', True)
    if viu_rodando:
        if leitura_pronta:
            return ('conectado', True)
        return ('falhou', True)
    if esperando_s > ESPERA_PELA_CONEXAO_S:
        return ('falhou', False)
    return ('conectando', False)
