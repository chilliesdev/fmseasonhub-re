import os

TAMANHO_DO_LOTE = 2000
MAXIMO_DE_PROCESSOS = 8
_leitor = None


def quantos_processos():
    return max(1, min(MAXIMO_DE_PROCESSOS, (os.cpu_count() or 2) - 2))


def _abrir_leitor(oficiais, comp_idx):
    global _leitor
    from fm_memory import FmMemory
    from fm_reader import FmReader
    _leitor = FmReader(FmMemory())
    _leitor._comps_edicao = oficiais
    _leitor._comp_idx = comp_idx


def linhas_do_lote(reader, lote, sid, ref_date):
    import arquivo_partidas
    from capture_all import build_player_rows, _person_base
    base_pessoa = _person_base()
    saida = []
    for pe, abias in lote:
        obj = pe - base_pessoa
        rows = build_player_rows(reader, obj, sid, ref_date, abias)
        if not rows:
            continue
        feminino = None
        if not abias:
            feminino = reader._memo_pessoa[obj][1]
        saida.append(rows + (arquivo_partidas.id_interno(reader, obj), obj, feminino))
    return saida


def _ler_lote(args):
    lote, sid, ref_date = args
    return linhas_do_lote(_leitor, lote, sid, ref_date)


def ler_jogadores(reader, jogadores, sid, ref_date, log=None):
    lotes = [jogadores[i:i + TAMANHO_DO_LOTE] for i in range(0, len(jogadores), TAMANHO_DO_LOTE)]
    feitos = 0
    n = quantos_processos()
    if n > 1 and len(lotes) > 1:
        import multiprocessing
        try:
            oficiais = reader.comps_com_edicao()
            comp_idx = reader.comp_uid_por_indice()
            ctx = multiprocessing.get_context('spawn')
            with ctx.Pool(n, initializer=_abrir_leitor, initargs=(oficiais, comp_idx)) as pool:
                for linhas in pool.imap(_ler_lote, [(l, sid, ref_date) for l in lotes]):
                    lido = min(len(jogadores), (feitos + 1) * TAMANHO_DO_LOTE)
                    feitos += 1
                    yield (lido, linhas)
            return
        except Exception as e:
            if log:
                log(f'leitura em {n} processos falhou no lote {feitos + 1} de {len(lotes)} ({type(e).__name__}: {e}); segue num processo so')
    for i in range(feitos, len(lotes)):
        yield (
            min(len(jogadores), (i + 1) * TAMANHO_DO_LOTE),
            linhas_do_lote(reader, lotes[i], sid, ref_date),
        )
