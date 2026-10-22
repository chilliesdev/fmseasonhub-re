"""Termos de Uso e Politica de Privacidade: leitura dos textos e versao do aceite.

Os quatro arquivos vivem na raiz do projeto e viajam DENTRO do .exe (ver o `datas` do
fmsh.spec), no mesmo molde do PATCH_NOTES.txt.
"""

import json
import os
import paths
import settings

VERSAO = "1"
VERSAO_PLUGINS = "1"
ARQUIVO_ACEITE_INSTALADOR = "aceite_instalador.json"

_ARQUIVOS = {
    "termos": {
        "pt": "TERMOS.txt",
        "en": "TERMOS.en.txt",
    },
    "privacidade": {
        "pt": "PRIVACIDADE.txt",
        "en": "PRIVACIDADE.en.txt",
    },
}


def idioma_do_documento(qual, lang="pt"):
    """Descobre o melhor idioma para o documento pedido."""
    par = _ARQUIVOS.get(qual, _ARQUIVOS["termos"])
    if lang in par:
        return lang
    if "pt" in par:
        return "pt"
    return next(iter(par.keys()))


def documento(qual, lang="pt"):
    """O texto cru de um dos dois documentos. A tela formata.

    Idioma que nao existir cai no outro, em vez de devolver erro: documento no idioma
    errado ainda e o documento, e tela vazia num aceite seria pior que tudo. Mesma regra do
    /api/patch-notes.
    """
    par = _ARQUIVOS.get(qual, _ARQUIVOS.get("termos", {}))
    escolhido = idioma_do_documento(qual, lang)
    nome = par.get(escolhido) or par.get("pt") or par.get("en")
    if not nome:
        return ""

    caminhos = [
        paths.resource_path("legal", nome),
        paths.resource_path(nome),
        paths.user_data_path(nome),
    ]
    for c in caminhos:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
    return ""


def aceito(s=None):
    """A pessoa ja aceitou ESTA versao? `s` e o dicionario de settings."""
    if s is None:
        try:
            import settings
            s = settings.load()
        except Exception:
            return True
    if not isinstance(s, dict):
        return True
    dados = s.get("aceite") or {}
    if not isinstance(dados, dict):
        return True
    return bool(
        str(dados.get("versao")) == str(VERSAO)
        and dados.get("termos_aceitos")
        and dados.get("privacidade_lida")
    )


def aceito_plugins(s=None):
    """A pessoa ja aceitou os termos de plugins? `s` e o dicionario de settings."""
    if s is None:
        try:
            import settings
            s = settings.load()
        except Exception:
            return True
    if not isinstance(s, dict):
        return True
    dados = s.get("aceite") or {}
    if not isinstance(dados, dict):
        return True
    return bool(dados.get("plugins_aceitos", True))


def importar_aceite_do_instalador(log=None):
    """Traz para o fmsh_settings.json o aceite dado no instalador, e apaga o arquivo dele.

    So vale se for DESTA versao dos documentos e com os dois atos marcados (aceite dos
    Termos e ciencia da Privacidade) -- registro de outra versao, incompleto ou ilegivel e
    descartado, e o app pede o aceite na propria tela, como antes. O idioma escolhido no
    instalador vira o idioma do app so se a pessoa ainda nao escolheu nenhum.
    """
    caminho = paths.user_data_path(ARQUIVO_ACEITE_INSTALADOR)
    if not os.path.isfile(caminho):
        return False

    try:
        with open(caminho, "r", encoding="utf-8-sig") as f:
            dados = json.load(f)
    except Exception as e:
        if log:
            log(f"aceite do instalador ilegivel: {caminho}: {e}")
        try:
            os.remove(caminho)
        except OSError:
            pass
        return False

    try:
        versao = str(dados.get("versao", ""))
        termos = bool(dados.get("termos_aceitos"))
        privacidade = bool(dados.get("privacidade_lida"))
        valido = (versao == VERSAO) and termos and privacidade

        if valido:
            s = settings.load()
            idioma = dados.get("idioma")
            kw = {
                "aceite": {
                    "versao": VERSAO,
                    "em": dados.get("em"),
                    "idioma": idioma,
                    "termos_aceitos": True,
                    "privacidade_lida": True,
                    "origem": "instalador",
                }
            }
            if idioma and not s.get("idioma"):
                kw["idioma"] = idioma
            settings.save(**kw)
            if log:
                log(f"aceite do instalador importado (versao {versao})")
        else:
            if log:
                log(f"aceite do instalador descartado (versao {versao})")
    finally:
        try:
            os.remove(caminho)
        except OSError:
            pass

    return valido
