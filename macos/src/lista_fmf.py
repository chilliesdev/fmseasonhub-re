# Decompiled from lista_fmf.pyc (Python 3.14) with macOS adaptations
import datetime
import glob
import os
import struct
import threading
import time
import uuid

try:
    from compression import zstd
except ImportError:
    zstd = None

TAMANHO_MAXIMO_ARQUIVO = 2097152
TAMANHO_MAXIMO_ABERTO = 4194304
MAXIMO_MEMBROS = 64
INICIO_MEMBROS = 26
MARCA_CONTEINER = b'\x02\x01afe.'
MARCA_INDICE = b'\x02\x01fmf.'
CABECALHO_QUADRO_INDICE = 9
CABECALHO_MEMBRO = 40
MAGIC_ZSTD = b'(\xb5/\xfd'
MARCA_LISTA = b'\x03\x01fls.'
MARCA_LISTA_ANTIGA = b'\x02\x01fls.'
NOME_MAXIMO = 200


class ListaInvalida(Exception):
    pass


class NaoEhFmf(ListaInvalida):
    pass


class NaoEhLista(ListaInvalida):
    pass


class ArquivoCorrompido(ListaInvalida):
    pass


def _montar_sbox():
    sbox = [0] * 256
    p = 1
    q = 1
    while True:
        p = p ^ ((p << 1) & 0xff) ^ (27 if (p & 128) else 0)
        q ^= (q << 1)
        q ^= (q << 2)
        q ^= (q << 4)
        q &= 0xff
        if q & 128:
            q ^= 9
        x = (
            q
            ^ (((q << 1) | (q >> 7)) & 0xff)
            ^ (((q << 2) | (q >> 6)) & 0xff)
            ^ (((q << 3) | (q >> 5)) & 0xff)
            ^ (((q << 4) | (q >> 4)) & 0xff)
        )
        sbox[p] = (x ^ 99) & 0xff
        if p == 1:
            break
    sbox[0] = 99
    return sbox


_SBOX = _montar_sbox()
_XTIME = [((v << 1) ^ 27) & 0xff if (v & 128) else (v << 1) for v in range(256)]


def _expandir_chave(chave):
    palavras = [list(chave[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        anterior = list(palavras[i - 1])
        if i % 4 == 0:
            anterior = anterior[1:] + anterior[:1]
            anterior = [_SBOX[b] for b in anterior]
            anterior[0] ^= rcon
            rcon = _XTIME[rcon]
        palavras.append([a ^ b for a, b in zip(palavras[i - 4], anterior)])
    chaves = []
    for r in range(11):
        bloco = []
        for c in range(4):
            bloco.extend(palavras[r * 4 + c])
        chaves.append(bloco)
    return chaves


def _cifrar_bloco(chaves_rodada, bloco):
    estado = [b ^ k for b, k in zip(bloco, chaves_rodada[0])]
    for rodada in range(1, 11):
        estado = [_SBOX[b] for b in estado]
        estado = [
            estado[0], estado[5], estado[10], estado[15],
            estado[4], estado[9], estado[14], estado[3],
            estado[8], estado[13], estado[2], estado[7],
            estado[12], estado[1], estado[6], estado[11],
        ]
        if rodada < 10:
            misturado = []
            for col in range(0, 16, 4):
                a0, a1, a2, a3 = estado[col:col + 4]
                todos = a0 ^ a1 ^ a2 ^ a3
                misturado += [
                    a0 ^ todos ^ _XTIME[a0 ^ a1],
                    a1 ^ todos ^ _XTIME[a1 ^ a2],
                    a2 ^ todos ^ _XTIME[a2 ^ a3],
                    a3 ^ todos ^ _XTIME[a3 ^ a0],
                ]
            estado = misturado
        estado = [b ^ k for b, k in zip(estado, chaves_rodada[rodada])]
    return estado


def aes128_ctr(chave, iv, dados):
    chaves_rodada = _expandir_chave(chave)
    contador = int.from_bytes(iv, 'big')
    saida = bytearray(len(dados))
    for inicio in range(0, len(dados), 16):
        fluxo = _cifrar_bloco(chaves_rodada, contador.to_bytes(16, 'big'))
        contador = (contador + 1) & ((1 << 128) - 1)
        for i, byte in enumerate(dados[inicio:inicio + 16]):
            saida[inicio + i] = byte ^ fluxo[i]
    return bytes(saida)


class _Cursor:
    def __init__(self, dados):
        self.dados = dados
        self.pos = 0

    def pegar(self, quantidade):
        fim = self.pos + quantidade
        if quantidade < 0 or fim > len(self.dados):
            raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
        trecho = self.dados[self.pos:fim]
        self.pos = fim
        return trecho

    def u32(self):
        return struct.unpack('<I', self.pegar(4))[0]

    def u64(self):
        return struct.unpack('<Q', self.pegar(8))[0]

    def texto(self):
        tamanho = self.u32()
        if tamanho > NOME_MAXIMO:
            raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
        return self.pegar(tamanho).decode('utf-8', errors='replace')


def _abrir_zlib(quadro, limite):
    import zlib
    decodificador = zlib.decompressobj()
    try:
        aberto = decodificador.decompress(quadro, limite)
    except zlib.error as exc:
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.') from exc
    if decodificador.unconsumed_tail or not decodificador.eof:
        raise ArquivoCorrompido('O arquivo esta incompleto, corrompido ou grande demais.')
    return aberto


def _abrir_zstd(quadro, limite):
    if zstd is None:
        raise ListaInvalida('Este computador nao consegue abrir listas (falta o zstd do Python 3.14).')
    decodificador = zstd.ZstdDecompressor()
    try:
        aberto = decodificador.decompress(quadro, max_length=limite)
    except zstd.ZstdError as exc:
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.') from exc
    if not decodificador.eof:
        raise ArquivoCorrompido('O arquivo esta incompleto, corrompido ou grande demais.')
    return aberto


def _ler_indice(dados):
    if len(dados) < INICIO_MEMBROS + 9 or not dados.startswith(MARCA_CONTEINER):
        raise NaoEhFmf('Este arquivo nao e um .fmf do Football Manager.')
    tamanho_secao = struct.unpack_from('<Q', dados, 9)[0]
    inicio_indice = 9 + tamanho_secao
    if tamanho_secao < INICIO_MEMBROS or inicio_indice + CABECALHO_QUADRO_INDICE >= len(dados):
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
    if dados[inicio_indice:inicio_indice + 6] != MARCA_INDICE:
        raise NaoEhFmf('Este arquivo nao e um .fmf do Football Manager.')
    quadro = inicio_indice + CABECALHO_QUADRO_INDICE
    if dados[quadro:quadro + 4] == MAGIC_ZSTD:
        bruto = _abrir_zstd(dados[quadro:], 1048576)
    elif dados[quadro + 4:quadro + 8] == MAGIC_ZSTD:
        bruto = _abrir_zstd(dados[quadro + 4:], 1048576)
    elif dados[quadro:quadro + 1] == b'x':
        bruto = _abrir_zlib(dados[quadro:], 1048576)
    else:
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')

    cursor = _Cursor(bruto)
    cursor.texto()

    def membro():
        nome = cursor.texto()
        extensao = cursor.texto()
        deslocamento = cursor.u64()
        tamanho_arquivo = cursor.u64()
        tamanho_aberto = cursor.u64()
        cursor.pegar(16)
        return (nome, extensao, deslocamento, tamanho_arquivo, tamanho_aberto)

    pos_antes = cursor.pos
    try:
        membros = []
        quantidade = cursor.u32()
        if quantidade > MAXIMO_MEMBROS:
            raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
        membros += [membro() for _ in range(quantidade)]
        if cursor.pos < len(cursor.dados):
            pastas = cursor.u32()
            if pastas > MAXIMO_MEMBROS:
                raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
            for _ in range(pastas):
                cursor.texto()
                qtd_pasta = cursor.u32()
                if qtd_pasta > MAXIMO_MEMBROS:
                    raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
                membros += [membro() for _ in range(qtd_pasta)]
        return membros
    except (ArquivoCorrompido, struct.error):
        cursor.pos = pos_antes
        pastas = cursor.u32()
        if pastas == 0:
            quantidade = cursor.u32()
            if quantidade > MAXIMO_MEMBROS:
                raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
            return [membro() for _ in range(quantidade)]
        if pastas > MAXIMO_MEMBROS:
            raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
        membros = []
        for _ in range(pastas):
            cursor.texto()
            quantidade = cursor.u32()
            if quantidade > MAXIMO_MEMBROS:
                raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
            membros += [membro() for _ in range(quantidade)]
        return membros


def _abrir_membro(dados, deslocamento, tamanho_arquivo, tamanho_aberto):
    inicio = INICIO_MEMBROS + deslocamento
    fim = inicio + tamanho_arquivo
    if tamanho_arquivo < CABECALHO_MEMBRO or tamanho_aberto > TAMANHO_MAXIMO_ABERTO or inicio < INICIO_MEMBROS or fim > len(dados):
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
    cursor = _Cursor(dados[inicio:fim])
    if cursor.u32() != 16 or cursor.u32() != 16:
        raise ArquivoCorrompido('O arquivo usa um formato de cifra desconhecido.')
    iv = cursor.pegar(16)
    chave = cursor.pegar(16)
    quadro = aes128_ctr(chave, iv, cursor.dados[CABECALHO_MEMBRO:])
    comprimido = (quadro[:4] == MAGIC_ZSTD)
    aberto = _abrir_zstd(quadro, tamanho_aberto) if comprimido else quadro
    if len(aberto) != tamanho_aberto:
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
    return aberto, comprimido


def _ler_lista(aberto):
    cursor = _Cursor(aberto)
    marca = cursor.pegar(len(MARCA_LISTA))
    if marca == MARCA_LISTA:
        cabecalho = cursor.pegar(7)
    elif marca == MARCA_LISTA_ANTIGA:
        cabecalho = cursor.pegar(8)
    else:
        raise ArquivoCorrompido('O conteudo da lista nao foi reconhecido.')
    save = struct.unpack_from('<I', cabecalho, len(cabecalho) - 4)[0]
    nome = cursor.texto()
    quantidade = cursor.u32()
    if quantidade * 4 > len(aberto) - cursor.pos:
        raise ArquivoCorrompido('O arquivo esta incompleto ou corrompido.')
    uids = list(struct.unpack(f'<{quantidade}I', cursor.pegar(quantidade * 4)))
    return (nome, uids, save or None)


def ler(dados: bytes) -> dict:
    if len(dados) > TAMANHO_MAXIMO_ARQUIVO:
        raise ArquivoCorrompido('O arquivo e grande demais para ser uma lista (limite de 2 MB).')
    membros = _ler_indice(dados)
    listas = [m for m in membros if m[1].lower() == '.slf']
    if not listas:
        if any(m[1].lower() == '.view' for m in membros):
            raise NaoEhLista('Este arquivo e uma view do FM (configuracao de colunas), nao uma lista de jogadores.')
        if any(m[1].lower() == '.pft' for m in membros):
            raise NaoEhLista('Este arquivo e um filtro do FM, nao uma lista de jogadores.')
        if any(m[1].lower() == '.ssf' for m in membros):
            raise NaoEhLista('Este arquivo e uma lista de staff (treinadores e funcionarios), nao de jogadores.')
        raise NaoEhLista('Este arquivo .fmf nao contem uma lista de jogadores.')

    _, _, deslocamento, tamanho_arquivo, tamanho_aberto = listas[0]
    aberto, comprimido = _abrir_membro(dados, deslocamento, tamanho_arquivo, tamanho_aberto)
    nome, uids, save = _ler_lista(aberto)
    versao = struct.unpack_from('<H', dados, 6)[0]
    formato = '26' if comprimido else ('antigo' if versao < 8 else None)
    return {
        'nome': nome,
        'uids': uids,
        'save': save,
        'formato': formato,
    }


_TRAVA = threading.RLock()


def listar() -> list[dict]:
    import settings
    return settings.load().get('listas_preferenciais') or []


def _mesmo_caminho(a, b):
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def adicionar(dados: bytes, arquivo: str | None = None, origem: str | None = None, arquivo_em: str | None = None, arquivo_biblioteca: str | None = None, sem_substituir: bool = False, teto: int | None = None) -> dict:
    import limites
    import settings

    lida = ler(dados)
    with _TRAVA:
        existentes = listar()
        nome = lida['nome']
        anterior = next((x for x in existentes if (
            _mesmo_caminho(x.get('origem'), origem) if origem else
            not x.get('origem') and x.get('arquivo') == arquivo and (arquivo or x['nome'] == nome)
        )), None)
        if arquivo_biblioteca:
            anterior = next((x for x in existentes if x.get('arquivo_biblioteca') == arquivo_biblioteca), anterior)
        if anterior and sem_substituir and anterior.get('arquivo_biblioteca') != arquivo_biblioteca:
            anterior = None
        if any(x is not anterior and x['nome'].casefold() == nome.casefold() for x in existentes):
            usados = {x['nome'].casefold() for x in existentes if x is not anterior}
            n = 2
            while f"{nome} ({n})".casefold() in usados:
                n += 1
            nome = f"{nome} ({n})"
            lida['nome'] = nome
        if not anterior:
            limites.conferir_listas('listas_fm', teto, len(existentes))
        agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        nova = {
            'id': anterior['id'] if anterior else str(uuid.uuid4()),
            'nome': nome,
            'arquivo': arquivo or (anterior.get('arquivo') if anterior else None),
            'origem': origem or (anterior.get('origem') if anterior else None),
            'arquivo_em': arquivo_em or (anterior.get('arquivo_em') if anterior else None),
            'adicionada_em': anterior['adicionada_em'] if anterior else agora,
            'atualizada_em': agora,
            'uids': lida['uids'],
            'total': len(lida['uids']),
            'save': lida['save'],
            'formato': lida['formato'],
            **_sobre_o_jogo(lida, origem),
        }
        ocupados = {x.get('arquivo_biblioteca') for x in existentes if x is not anterior}
        nova['arquivo_biblioteca'] = _espelhar(dados, nova, ocupados)
        restantes = [x for x in existentes if x is not anterior]
        settings.save(listas_preferenciais=restantes + [nova])
        return nova


def jogo_da_pasta(caminho):
    if not caminho:
        return None
    partes = os.path.normpath(caminho).split(os.sep)
    for p in reversed(partes):
        if p.startswith('Football Manager 20') or p.startswith('Football Manager 2'):
            return p
    return None


def _sobre_o_jogo(lida, origem):
    return {
        'save': lida.get('save'),
        'formato': lida.get('formato'),
        'jogo_pasta': jogo_da_pasta(origem),
    }


def completar_sobre_o_jogo() -> int:
    import paths
    import settings

    feitas = 0
    with _TRAVA:
        existentes = listar()
        for x in existentes:
            if 'formato' in x:
                continue
            caminhos = (
                x.get('origem'),
                os.path.join(paths.biblioteca_dir(), x['arquivo_biblioteca']) if x.get('arquivo_biblioteca') else None,
            )
            for caminho in caminhos:
                if not caminho or not os.path.isfile(caminho):
                    continue
                try:
                    dados, _ = _ler_arquivo(caminho)
                    x.update(_sobre_o_jogo(ler(dados), x.get('origem')))
                    feitas += 1
                    break
                except ListaInvalida:
                    continue
        if feitas:
            settings.save(listas_preferenciais=existentes)
    return feitas


def _nome_na_biblioteca(registro):
    import biblioteca

    for candidato in (registro.get('arquivo'), f"{registro.get('nome')}.fmf"):
        nome = biblioteca.nome_seguro(candidato or '')
        if nome.lower().endswith('.fmf'):
            return nome
    return f"lista {registro['id']}.fmf"


def _espelhar(dados, registro, ocupados):
    import biblioteca
    import paths

    pasta = paths.biblioteca_dir()
    for nome in sorted(os.listdir(pasta)):
        caminho = os.path.join(pasta, nome)
        if nome in ocupados or not nome.lower().endswith('.fmf') or os.path.islink(caminho) or not os.path.isfile(caminho):
            continue
        if os.path.getsize(caminho) == len(dados):
            with open(caminho, 'rb') as fh:
                if fh.read() == dados:
                    return nome

    nome_base = _nome_na_biblioteca(registro)
    candidato = nome_base
    n = 2
    while True:
        try:
            if candidato in ocupados:
                raise FileExistsError(candidato)
            with open(os.path.join(pasta, candidato), 'xb') as fh:
                fh.write(dados)
            return candidato
        except FileExistsError:
            candidato = f"{nome_base[:-4]} ({n}).fmf"
            n += 1


def espelhar_existentes() -> int:
    import settings
    feitas = 0
    with _TRAVA:
        existentes = listar()
        mudou = False
        ocupados = {x.get('arquivo_biblioteca') for x in existentes if x.get('arquivo_biblioteca')}
        for x in existentes:
            if x.get('arquivo_biblioteca'):
                continue
            origem = x.get('origem')
            if not origem or not os.path.isfile(origem):
                continue
            try:
                dados, _ = _ler_arquivo(origem)
                x['arquivo_biblioteca'] = _espelhar(dados, x, ocupados)
                ocupados.add(x['arquivo_biblioteca'])
                feitas += 1
                mudou = True
            except ListaInvalida:
                continue
        if mudou:
            settings.save(listas_preferenciais=existentes)
    return feitas


def _documentos():
    bases = []
    try:
        import ctypes
        if hasattr(ctypes, 'windll'):
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
                bases.append(buf.value)
    except Exception:
        pass
    home = os.path.expanduser('~')
    bases += [
        os.path.join(home, p)
        for p in (
            'Documents',
            os.path.join('OneDrive', 'Documentos'),
            os.path.join('OneDrive', 'Documents'),
            'Documentos',
            os.path.join('Library', 'Application Support'),
        )
    ]
    return bases


def _caminho_no_xml(arquivo, atributo):
    import xml.etree.ElementTree as ET
    try:
        if os.path.getsize(arquivo) > 65536:
            return None
        raiz = ET.parse(arquivo).getroot()
        for elem in raiz.iter():
            if elem.attrib.get('id') == atributo or elem.attrib.get('name') == atributo:
                return elem.attrib.get('value')
    except Exception:
        pass
    return None


def _pasta_pelas_preferencias(pasta_prefs):
    if not os.path.isdir(pasta_prefs):
        return None
    xml_path = os.path.join(pasta_prefs, 'preferences.xml')
    if os.path.isfile(xml_path):
        return _caminho_no_xml(xml_path, 'user_data_location')
    return None


def _discos_fixos():
    try:
        import ctypes
        if hasattr(ctypes, 'windll'):
            mascara = ctypes.windll.kernel32.GetLogicalDrives()
            return [chr(65 + i) + ':\\' for i in range(26) if (mascara >> i) & 1 and ctypes.windll.kernel32.GetDriveTypeW(chr(65 + i) + ':\\') == 3]
    except Exception:
        pass
    return []


_PASTAS_CACHE = {'quando': 0.0, 'pastas': None}


def pastas_dos_jogos() -> list[dict]:
    agora = time.time()
    if _PASTAS_CACHE['pastas'] is not None and agora - _PASTAS_CACHE['quando'] < 10.0:
        return _PASTAS_CACHE['pastas']

    achadas = {}

    def anotar(jogo, pasta):
        if not os.path.isdir(pasta):
            return
        caminho_norm = os.path.normcase(os.path.normpath(pasta))
        if caminho_norm not in achadas:
            achadas[caminho_norm] = {'jogo': jogo, 'pasta': pasta}

    for base in _documentos():
        padrao = os.path.join(base, 'Sports Interactive', 'Football Manager *')
        for pasta in glob.glob(padrao):
            anotar(os.path.basename(pasta), pasta)

    for disco in _discos_fixos():
        for padrao in (
            ('Sports Interactive', 'Football Manager *'),
            ('*', 'Sports Interactive', 'Football Manager *'),
        ):
            for pasta in glob.glob(os.path.join(disco, *padrao)):
                anotar(os.path.basename(pasta), pasta)

    pastas = sorted(achadas.values(), key=lambda p: p['jogo'], reverse=True)
    _PASTAS_CACHE.update(quando=agora, pastas=pastas)
    return pastas


def pasta_listas(jogo: str | None = None) -> str | None:
    for p in pastas_dos_jogos():
        if jogo is None or p['jogo'] == str(jogo):
            candidata = os.path.join(p['pasta'], 'shortlists')
            if not os.path.isdir(candidata):
                candidata = os.path.join(p['pasta'], 'listas')
            if os.path.isdir(candidata):
                return candidata
            return os.path.join(p['pasta'], 'shortlists')
    return None


def _ler_arquivo(caminho: str) -> tuple[bytes, float]:
    if '\0' in caminho:
        raise ListaInvalida('Nome de arquivo invalido.')
    if os.path.splitext(caminho)[1].lower() != '.fmf':
        raise NaoEhFmf('Este arquivo nao e um .fmf do Football Manager.')
    try:
        tamanho = os.path.getsize(caminho)
        if tamanho > TAMANHO_MAXIMO_ARQUIVO:
            raise ArquivoCorrompido('O arquivo e grande demais para ser uma lista (limite de 2 MB).')
        with open(caminho, 'rb') as fh:
            dados = fh.read(TAMANHO_MAXIMO_ARQUIVO + 1)
        modificado = os.path.getmtime(caminho)
        return dados, modificado
    except OSError as err:
        raise ListaInvalida('Nao foi possivel ler o arquivo.') from err


def listar_pasta() -> dict:
    existentes = listar()
    pastas = []
    for p in pastas_dos_jogos():
        caminho_listas = os.path.join(p['pasta'], 'shortlists')
        if not os.path.isdir(caminho_listas):
            caminho_listas = os.path.join(p['pasta'], 'listas')
        listas, invalidas = _listas_da_pasta(caminho_listas, existentes) if os.path.isdir(caminho_listas) else ([], [])
        pastas.append({
            **p,
            'listas': listas,
            'invalidas': invalidas,
            'arquivos_invalidos': invalidas,
        })
    return {'pastas': pastas}


def _listas_da_pasta(pasta, existentes):
    saida = []
    invalidas = []
    try:
        nomes = sorted(f for f in os.listdir(pasta) if f.lower().endswith('.fmf'))[:200]
    except OSError:
        return saida, invalidas

    for arquivo in nomes:
        caminho = os.path.join(pasta, arquivo)
        try:
            dados, modificado = _ler_arquivo(caminho)
            lida = ler(dados)
            ja = next(
                (x for x in existentes if _mesmo_caminho(x.get('origem'), caminho) or (not x.get('origem') and x['nome'].casefold() == lida['nome'].casefold())),
                None,
            )
            saida.append({
                'arquivo': arquivo,
                'nome': lida['nome'],
                'quantidade': len(lida['uids']),
                'modificado': modificado,
                'carregada': ja is not None,
                'id': ja['id'] if ja else None,
            })
        except ListaInvalida as exc:
            try:
                modificado = os.path.getmtime(caminho)
            except OSError:
                modificado = 0.0
            invalidas.append({
                'arquivo': arquivo,
                'erro': str(exc),
                'modificado': modificado,
            })
            continue
    saida.sort(key=lambda x: x['modificado'], reverse=True)
    saida.sort(key=lambda x: x['carregada'])
    return saida, invalidas


def importar_da_pasta(arquivo: str, jogo: str | None = None, teto: int | None = None) -> dict:
    if not arquivo or '\0' in arquivo or os.path.basename(arquivo.replace('\\', '/')) != arquivo or arquivo in ('.', '..') or '\\' in arquivo or '/' in arquivo:
        raise ListaInvalida('Nome de arquivo invalido.')
    pasta = pasta_listas(jogo)
    if not pasta:
        raise ListaInvalida('A pasta de listas do Football Manager nao foi encontrada neste computador.')
    caminho = os.path.join(pasta, arquivo)
    dados, modificado = _ler_arquivo(caminho)
    return adicionar(dados, arquivo=arquivo, origem=caminho, arquivo_em=modificado, teto=teto)


def importar_do_caminho(caminho: str, teto: int | None = None) -> dict:
    dados, modificado = _ler_arquivo(caminho)
    return adicionar(dados, arquivo=os.path.basename(caminho), origem=caminho, arquivo_em=modificado, teto=teto)


def atualizar(id_lista: str) -> dict:
    import settings
    existentes = listar()
    atual = next((x for x in existentes if x['id'] == id_lista), None)
    if atual is None:
        raise KeyError(id_lista)
    origem = atual.get('origem')
    if not origem:
        raise ListaInvalida('Esta lista nao tem um arquivo de origem conhecido.')
    dados, modificado = _ler_arquivo(origem)
    lida = ler(dados)
    with _TRAVA:
        existentes = listar()
        nome = lida['nome']
        if any(x['id'] != id_lista and x['nome'].casefold() == nome.casefold() for x in existentes):
            usados = {x['nome'].casefold() for x in existentes if x['id'] != id_lista}
            n = 2
            while f"{nome} ({n})".casefold() in usados:
                n += 1
            nome = f"{nome} ({n})"
            lida['nome'] = nome
        agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        nova = {
            **atual,
            'nome': nome,
            'arquivo': os.path.basename(origem),
            'origem': origem,
            'arquivo_em': modificado,
            'atualizada_em': agora,
            'uids': lida['uids'],
            'total': len(lida['uids']),
            'save': lida['save'],
            'formato': lida['formato'],
            **_sobre_o_jogo(lida, origem),
        }
        ocupados = {x.get('arquivo_biblioteca') for x in existentes if x['id'] != id_lista}
        nova['arquivo_biblioteca'] = _espelhar(dados, nova, ocupados)
        restantes = [x for x in existentes if x['id'] != id_lista]
        settings.save(listas_preferenciais=restantes + [nova])
        return nova


def remover(id_lista: str) -> bool:
    import settings
    with _TRAVA:
        existentes = listar()
        restantes = [x for x in existentes if x['id'] != id_lista]
        if len(restantes) == len(existentes):
            return False
        settings.save(listas_preferenciais=restantes)
        return True
