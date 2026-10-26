import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading

import paths

RESERVA = ('en', 'pt')
PADRAO = 'pt'
ARQUIVOS = ('interface', 'colunas')


def escapar(v):
    return (v or '').replace('\\', '\\\\').replace('\n', '\\n')


def _desescapa(v):
    saida = []
    i = 0
    n = len(v)
    while i < n:
        if v[i] == '\\' and i + 1 < n:
            prox = v[i + 1]
            if prox == 'n':
                saida.append('\n')
                i += 2
                continue
            if prox == '\\':
                saida.append('\\')
                i += 2
                continue
        saida.append(v[i])
        i += 1
    return ''.join(saida)


def analisar_texto(bruto):
    dados = {}
    problemas = []
    for n, linha in enumerate(bruto.replace('\r\n', '\n').split('\n'), 1):
        crua = linha.strip()
        if not crua or crua.startswith('#'):
            continue
        if '=' not in crua:
            problemas.append({'linha': n, 'erro': 'sem_igual', 'texto': crua[:60]})
            continue
        chave, valor = crua.split('=', 1)
        chave = chave.strip()
        valor = valor.strip()
        if not chave:
            problemas.append({'linha': n, 'erro': 'sem_chave', 'texto': crua[:60]})
            continue
        if chave in dados:
            problemas.append({'linha': n, 'erro': 'repetida', 'texto': chave})
        if valor:
            dados[chave] = _desescapa(valor)
    return dados, problemas


def analisar_json(bruto):
    try:
        cru = json.loads(bruto)
    except Exception as e:
        return {}, [{'linha': 0, 'erro': 'json_invalido', 'texto': str(e)}]
    if not isinstance(cru, dict):
        return {}, [{'linha': 0, 'erro': 'json_invalido', 'texto': 'nao e um objeto'}]
    dados = {}
    for k, v in cru.items():
        if isinstance(v, str) and v:
            dados[k] = v
        elif isinstance(v, dict):
            for sub, texto in v.items():
                if isinstance(texto, str) and texto:
                    dados[f'{k}.{sub}'] = texto
    return dados, []


def _ler_arquivo(caminho):
    try:
        with io.open(caminho, encoding='utf-8-sig') as f:
            bruto = f.read()
    except OSError:
        return {}, []
    if caminho.lower().endswith('.json'):
        return analisar_json(bruto)
    return analisar_texto(bruto)


def _mesma_pasta(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def _pastas(codigo):
    embarcado = paths.idiomas_embarcados()
    do_usuario = paths.idiomas_dir()
    if _mesma_pasta(embarcado, do_usuario):
        return (os.path.join(embarcado, codigo),)
    return (os.path.join(embarcado, codigo), os.path.join(do_usuario, codigo))


def _cadeia(codigo):
    ordem = [c for c in reversed(RESERVA) if c != codigo]
    ordem.append(codigo)
    return ordem


def _carimbo(codigo):
    marcas = []
    for pasta in _pastas(codigo):
        for nome in ARQUIVOS:
            for ext in ('.txt', '.json'):
                p = os.path.join(pasta, nome + ext)
                try:
                    marcas.append(os.path.getmtime(p))
                except OSError:
                    pass
    return tuple(marcas)


_CACHE = {}


def carregar(codigo, arquivo='interface'):
    chave = (codigo, arquivo)
    carimbo = _carimbo(codigo)
    guardado = _CACHE.get(chave)
    if guardado and guardado[0] == carimbo:
        return guardado[1], guardado[2]
    dados = {}
    problemas = []
    for pasta in _pastas(codigo):
        # Editable text exports override JSON without removing the saved source.
        for ext in ('.json', '.txt'):
            d, p = _ler_arquivo(os.path.join(pasta, arquivo + ext))
            dados.update(d)
            problemas.extend(p)
    _CACHE[chave] = (carimbo, dados, problemas)
    return dados, problemas


def resolver(codigo, arquivo='interface'):
    saida = {}
    for c in _cadeia(codigo):
        saida.update(carregar(c, arquivo)[0])
    return saida


def texto(codigo, chave, padrao=None):
    d = resolver(codigo)
    v = d.get(chave)
    if v:
        return v
    if padrao is not None:
        return padrao
    return chave


def colunas(codigo):
    plano = resolver(codigo, 'colunas')
    saida = {}
    for k, v in plano.items():
        base, _, campo = k.rpartition('.')
        if campo in ('nome', 'sigla') and base:
            saida.setdefault(base, {})[campo] = v
    return saida


def _meta(codigo):
    d = carregar(codigo)[0]
    return {
        'nome': d.get('_idioma.nome') or codigo,
        'autor': d.get('_idioma.autor') or '',
    }


def disponiveis():
    base = set(carregar('en')[0]) | set(carregar('pt')[0])
    base = {k for k in base if not k.startswith('_idioma.')}
    total = len(base)
    embarcado = paths.idiomas_embarcados()
    do_usuario = paths.idiomas_dir()
    fontes = [(embarcado, 'app')]
    if not _mesma_pasta(embarcado, do_usuario):
        fontes.append((do_usuario, 'usuario'))
    achados = {}
    for pasta, origem in fontes:
        try:
            for nome in sorted(os.listdir(pasta)):
                if nome.startswith(('.', '_')):
                    continue
                if os.path.isdir(os.path.join(pasta, nome)):
                    if nome not in achados:
                        achados[nome] = origem
                    else:
                        achados[nome] = 'app+usuario'
        except OSError:
            pass
    saida = []
    for codigo in sorted(achados):
        proprios = set(carregar(codigo)[0]) - {'_idioma.codigo', '_idioma.nome', '_idioma.autor'}
        if not proprios and not carregar(codigo, 'colunas')[0]:
            continue
        problemas = carregar(codigo)[1] + carregar(codigo, 'colunas')[1]
        m = _meta(codigo)
        traduzidos = len(proprios & base)
        cobertura = int(100 * traduzidos / total) if total else 0
        saida.append({
            'codigo': codigo,
            'nome': m['nome'],
            'autor': m['autor'],
            'origem': achados[codigo],
            'completo': cobertura,
            'cobertura': cobertura,
            'traduzidos': traduzidos,
            'total': total,
            'problemas': problemas[:20],
            'n_problemas': len(problemas),
        })
    return saida


def modelo(codigo, base=None, arquivo='interface'):
    base = base or 'en'
    mesma_origem = base == codigo
    origem = carregar(base, arquivo)[0]
    if not origem:
        origem = carregar('en', arquivo)[0]
        base = 'en'
        mesma_origem = codigo == 'en'
    meu = carregar(codigo, arquivo)[0]
    chaves = sorted(set(origem) | set(meu))
    chaves = [k for k in chaves if not k.startswith('_idioma.')]
    faltando = [k for k in chaves if not meu.get(k)]
    return {
        'codigo': codigo,
        'base': base,
        'mesma_origem': mesma_origem,
        'chaves': chaves,
        'faltando': faltando,
        'origem': {k: origem.get(k, '') for k in chaves},
        'atual': {k: meu.get(k, '') for k in chaves},
    }


_EXPORTAR_LOCK = threading.Lock()


def exportar(codigo, base='en', nome=None):
    """Create editable user translations without changing the shipped files."""
    for valor in (codigo, base):
        if not re.fullmatch(r'[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*', valor) or len(valor) > 35:
            raise ValueError('Codigo de idioma invalido')
    with _EXPORTAR_LOCK:
        return _exportar(codigo, base, nome)


def _exportar(codigo, base, nome):
    raiz = Path(paths.idiomas_dir())
    destino = raiz / codigo
    if destino.is_symlink() or (destino.exists() and not destino.is_dir()):
        raise ValueError('Pasta de idioma invalida')
    for arquivo in ARQUIVOS:
        for ext in ('.txt', '.json'):
            caminho = destino / (arquivo + ext)
            if caminho.is_symlink() or (caminho.exists() and not caminho.is_file()):
                raise ValueError('Arquivo de idioma invalido')

    meta = carregar(codigo)[0]
    arquivos = []
    with tempfile.TemporaryDirectory(prefix='.idioma-', dir=raiz) as temporaria:
        for arquivo in ARQUIVOS:
            dados = modelo(codigo, base, arquivo)
            linhas = [
                '# FM Season Hub - ' + arquivo,
                '# Keep keys before =. Edit translations after =.',
                '# Copy {{placeholders}} unchanged. Use \\n for a new line.',
                '# Base text is shown in the comment above each translation.',
                '',
            ]
            if arquivo == 'interface':
                linhas.extend([
                    '_idioma.codigo = ' + codigo,
                    '_idioma.nome = ' + escapar(nome or meta.get('_idioma.nome') or codigo),
                    '_idioma.autor = ' + escapar(meta.get('_idioma.autor', '')),
                    '',
                ])
            for chave in dados['chaves']:
                linhas.extend([
                    '# ' + dados['base'] + ': ' + escapar(dados['origem'][chave]),
                    chave + ' = ' + escapar(dados['atual'][chave]),
                    '',
                ])
            arquivo_txt = arquivo + '.txt'
            (Path(temporaria) / arquivo_txt).write_text('\n'.join(linhas), encoding='utf-8')
            arquivos.append({
                'arquivo': arquivo_txt,
                'total': len(dados['chaves']),
                'faltando': len(dados['faltando']),
            })
        destino.mkdir(exist_ok=True)
        for item in arquivos:
            os.replace(Path(temporaria) / item['arquivo'], destino / item['arquivo'])
    _CACHE.clear()
    return {'ok': True, 'pasta': str(destino), 'arquivos': arquivos}
