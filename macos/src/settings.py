"""Configuracoes do servidor, num JSON irmao do banco.

So entra aqui o que o SERVIDOR precisa saber (ex.: onde fica a pasta graphics --
quem le os arquivos e ele). Preferencia de exibicao (idioma, mostrar CA/PA) fica
no localStorage do front, que ja e o padrao do app.
"""

import json
import os
import threading
from paths import user_data_path

SETTINGS_PATH = user_data_path("fmsh_settings.json")
_TRAVA = threading.Lock()

DEFAULTS = {
    "graphics_dir": None,
    "db_dir": None,
    "currencies": [],
    "currencies_read_at": None,
    "overall_modo": "misto",
    "buscar_como": {
        "tolIdx": 2,
        "modo": "faixa",
        "fora": 2,
        "pisoPct": 85,
        "minMinutos": 900,
        "valor": True,
        "idade": False,
        "contrato12": False,
        "top20": False,
        "pe": False,
    },
    "memoria_max_mb": 2048,
    "ao_fechar": "perguntar",
    "bandeja_aviso_visto": False,
    "bandeja_versao_avisada": "",
    "update_dispensado": False,
    "plugins_desligados": [],
    "plugins_dispensados": [],
    "plugins_oferta_vista": False,
    "plugins_avisar_novos": True,
    "fim_de_temporada_auto": False,
    "auto_snapshot_ligado": False,
    "auto_snapshot_datas": {},
    "auto_snapshot_nome": "{clube} {ano}",
    "auto_snapshot_vagas": "avisar",
    "captura_som_ligado": True,
    "captura_som_volume": 100,
    "fm_origem": None,
    "fm_origem_em": None,
    "acesso_nivel": 4,
    "acesso_tier_nome": "FMSH Pro",
    "acesso_tier": "pro",
    "acesso_origem": "offline_macos",
    "acesso_nome": "FMSH Pro (macOS)",
    "acesso_conferido": True,
    "acesso_conferido_em": None,
    "acesso_maquina": None,
    "acesso_chave": "PRO-UNLOCKED-MACOS",
    "avisos_lidos": [],
    "idioma": None,
    "carreira_ativa": None,
    "carreiras": {},
    "listas_preferenciais": [],
    "favoritos_listas": [],
    "favoritos_lista_padrao": True,
    "favoritos_seq": 0,
    "favoritos_migrado": False,
    "favoritos_aviso": True,
    "dicas_lidas": [],
    "aceite": {
        "versao": "1",
        "em": None,
        "idioma": None,
        "termos_aceitos": True,
        "privacidade_lida": True,
    },
    "onboarding": {
        "concluido": False,
        "etapa": 0,
        "pulado": False,
        "escopo_primeira": None,
        "carreira": None,
    },
}


def load():
    try:
        if os.path.isfile(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    res = dict(DEFAULTS)
                    res.update(data)
                    return res
    except (OSError, ValueError):
        pass
    return dict(DEFAULTS)


def save(**kw):
    """Grava as preferencias. ATOMICO: escreve num temporario e troca no fim.

    `open(..., "w")` trunca o arquivo ANTES de escrever. Uma queda de energia (ou o app
    sendo fechado) no meio deixava um JSON truncado, e `load()` cai nos padroes em
    silencio -- some o nivel de acesso, o aceite dos termos, a pasta de graphics e as
    preferencias de cada carreira. `os.replace` troca o arquivo inteiro de uma vez: ou
    fica o antigo, ou fica o novo, nunca um pela metade.
    """
    with _TRAVA:
        data = load()
        data.update(kw)
        pasta = os.path.dirname(SETTINGS_PATH)
        if pasta:
            try:
                os.makedirs(pasta, exist_ok=True)
            except OSError:
                pass
        tmp = SETTINGS_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, SETTINGS_PATH)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return data
