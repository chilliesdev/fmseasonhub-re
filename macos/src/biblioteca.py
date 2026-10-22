"""Gerenciamento de views de jogo (.fmf) e presets de filtros (.fsh) na Biblioteca.

Permite listar, ler, criar, renomear e excluir arquivos customizados e presets de fabrica.
"""

import os
import re
import shutil
import paths

EXTENSOES_VALIDAS = (".fmf", ".fsh", ".json", ".lsh")
TAMANHO_MAXIMO = 5242880  # 5 MB
MAX_JOGADORES = 5000


class ArquivoInvalido(Exception):
    pass


def nome_seguro(nome):
    """Limpa o nome de arquivo removendo caracteres perigosos ou separadores de caminho."""
    base = os.path.basename(str(nome)).strip()
    return re.sub(r'[\\/*?:"<>|]', "", base)


def _pasta_fabrica():
    """Diretorio de presets embutidos no app."""
    return paths.resource_path("src", "presets_fabrica")


def _caminho(nome, pasta=None):
    """Resolve o caminho absoluto para o arquivo de biblioteca."""
    if not pasta:
        pasta = paths.biblioteca_dir()
    return os.path.join(pasta, nome_seguro(nome))


def _cabe(tamanho):
    return 0 < tamanho <= TAMANHO_MAXIMO


def nome_livre(nome, pasta=None):
    """Gera um nome que nao colida com arquivos ja existentes na pasta."""
    if not pasta:
        pasta = paths.biblioteca_dir()
    seguro = nome_seguro(nome)
    raiz, ext = os.path.splitext(seguro)
    candidato = seguro
    idx = 1
    while os.path.exists(os.path.join(pasta, candidato)):
        candidato = f"{raiz} ({idx}){ext}"
        idx += 1
    return candidato


_nome_livre = nome_livre


def _texto(conteudo):
    if isinstance(conteudo, str):
        return conteudo
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return conteudo.decode("latin1")
        except Exception:
            return str(conteudo)


def _resumo_fmf(conteudo):
    """Extrai informacoes rapidas de uma view .fmf."""
    txt = _texto(conteudo)
    colunas = len(re.findall(r"record\s*id=", txt)) or 0
    return {"tipo": "view_fm", "colunas": colunas}


def resumo(conteudo, extensao):
    ext = extensao.lower()
    if ext == ".fmf":
        return _resumo_fmf(conteudo)
    return {"tipo": "preset_filtro", "tamanho": len(conteudo)}


def conferir(caminho_ou_bytes, extensao=None):
    """Verifica se o conteudo e valido para salvar na biblioteca."""
    if isinstance(caminho_ou_bytes, dict):
        return caminho_ou_bytes
    if isinstance(caminho_ou_bytes, (bytes, bytearray)):
        dados = caminho_ou_bytes
    elif isinstance(caminho_ou_bytes, str) and os.path.exists(caminho_ou_bytes):
        with open(caminho_ou_bytes, "rb") as f:
            dados = f.read(TAMANHO_MAXIMO + 1)
    else:
        return caminho_ou_bytes

    if not _cabe(len(dados)):
        raise ArquivoInvalido("Arquivo excede o tamanho maximo de 5 MB.")
    return caminho_ou_bytes


def _conferir_lista(dados):
    return True


def ler_bytes(nome):
    c = _caminho(nome)
    if not os.path.isfile(c):
        # Tenta na fabrica
        c_fab = os.path.join(_pasta_fabrica(), nome_seguro(nome))
        if os.path.isfile(c_fab):
            c = c_fab
        else:
            return None
    with open(c, "rb") as f:
        return f.read()


def ler_texto(nome_ou_texto, extensao=None):
    if isinstance(nome_ou_texto, str) and not os.path.isfile(nome_ou_texto):
        # Texto ja lido
        if extensao in (".lsh", ".fsh", ".json"):
            import json
            try:
                dados = json.loads(nome_ou_texto)
                return conferir(dados, extensao)
            except Exception as e:
                raise ArquivoInvalido(str(e))
        return nome_ou_texto

    dados = ler_bytes(nome_ou_texto)
    if dados is None:
        return None
    txt = _texto(dados)
    if extensao in (".lsh", ".fsh", ".json"):
        import json
        try:
            return conferir(json.loads(txt), extensao)
        except Exception as e:
            raise ArquivoInvalido(str(e))
    return txt


def ler(nome):
    return ler_bytes(nome)


def gravar_bytes_livre(nome, dados):
    pasta = paths.biblioteca_dir()
    os.makedirs(pasta, exist_ok=True)
    nome_final = nome_livre(nome, pasta)
    caminho = os.path.join(pasta, nome_final)
    with open(caminho, "wb") as f:
        f.write(dados)
    return nome_final


def gravar_fmf(nome, dados):
    return gravar_bytes_livre(nome if nome.endswith(".fmf") else f"{nome}.fmf", dados)


def gravar(nome, dados):
    if isinstance(dados, str):
        dados = dados.encode("utf-8")
    return gravar_bytes_livre(nome, dados)


def apagar(nome):
    c = _caminho(nome)
    if os.path.isfile(c):
        os.remove(c)
        return True
    return False


def renomear(antigo, novo):
    c_antigo = _caminho(antigo)
    if not os.path.isfile(c_antigo):
        return False, "Arquivo de origem nao encontrado"
    pasta = os.path.dirname(c_antigo)
    c_novo = os.path.join(pasta, nome_seguro(novo))
    if os.path.exists(c_novo) and c_novo != c_antigo:
        return False, "Ja existe um arquivo com esse nome"
    os.rename(c_antigo, c_novo)
    return True, os.path.basename(c_novo)


def listar(pasta=None):
    """Lista todos os itens disponiveis na biblioteca pessoal e da fabrica."""
    itens = []
    vistos = set()

    # Pastas de busca: usuario e fabrica
    pastas_busca = [paths.biblioteca_dir()]
    fab = _pasta_fabrica()
    if os.path.isdir(fab):
        pastas_busca.append(fab)

    for p in pastas_busca:
        if not os.path.isdir(p):
            continue
        is_fabrica = (p == fab)
        for arq in sorted(os.listdir(p)):
            if arq.startswith(".") or arq in vistos:
                continue
            ext = os.path.splitext(arq)[1].lower()
            if ext in EXTENSOES_VALIDAS:
                caminho = os.path.join(p, arq)
                st = os.stat(caminho)
                itens.append({
                    "nome": arq,
                    "extensao": ext,
                    "tamanho": st.st_size,
                    "modificado_em": st.st_mtime,
                    "fabrica": is_fabrica,
                })
                vistos.add(arq)

    return itens
