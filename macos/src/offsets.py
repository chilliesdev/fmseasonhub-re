import copy
import json
import paths

_cache = {}


def _ler(arquivo, nome):
    if nome not in _cache:
        try:
            import offsets_embutidos
            _cache[nome] = getattr(offsets_embutidos, nome)
        except ImportError:
            with open(paths.resource_path('signatures', arquivo), encoding='utf-8') as f:
                _cache[nome] = json.load(f)
    return copy.deepcopy(_cache[nome])


def assinaturas():
    return _ler('fm_signatures.json', 'ASSINATURAS')


def mapa_de_tracos():
    return _ler('trait_map.json', 'TRACOS')
