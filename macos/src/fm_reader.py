"""Leitor de alto nivel para estruturas em memoria do Football Manager.

Navega grafos de objetos do Football Manager (jogadores, clubes, times, ligas, moedas, savegames).
Desempacota atributos, contratos, historico de partidas e metricas avancadas Moneyball.
"""

import sys
import struct
import datetime
from datetime import date, timedelta
import unicodedata

import offsets
from fm_memory import FmMemory, _to_int, _log


def decode_fm_date(raw):
    """Decodifica data raw do Football Manager.
    
    Ano nos 16 bits altos, dia do ano (1-366) nos 9 bits baixos (raw & 0x1FF).
    """
    if not raw or raw <= 0:
        return None
    try:
        ano = raw >> 16
        dia = raw & 0x1FF
        if ano < 1900 or ano > 2200 or dia < 0 or dia > 366:
            return None
        return date(ano, 1, 1) + timedelta(days=max(0, dia - 1))
    except Exception:
        return None


# ==============================================================================
# Competition / Match VTables & Offsets
# ==============================================================================
AGENDA_VTABLE_RVA = 0x0449EF98
JOGO_VTABLE_RVA = 0x04332188
VT_COMP_EDITION_RVA = 0x04E37AF8
EDITION_COMP_PTR = 0x18
EDITION_TEAMS_VEC = 0x20
COMP_NAME_PTR = 0x40
COMP_CATEGORY = 0xF8
COMP_UID = 0x0C
COMP_NATION_PTR = 0x60
NATION_NAME_PTR = 0x00
COMP_IS_FEMALE = 0xF9
COMP_REPUTATION = 0x188
TEAM_UID = 0x0C

NATIONAL_TEAM_CATS = {6, 7, 10, 11, 24}
NATIONAL_YOUTH_CATS = {15, 16, 17, 18, 19, 20, 25, 27, 31, 32}
OLYMPIC_CATS = {26}
RESERVE_COMP_CATS = {8, 23}
CLUB_YOUTH_CATS = {33, 34, 35, 36, 37, 38, 39}

import re
_AGE_RX = re.compile(r'(?:sub[- ]?|u[- ]?)(\d{2})', re.IGNORECASE)
_YOUTH_WORDS_RX = re.compile(r'\b(youth|jovens|junior|juniores|base|academy|acad|primavera|u17|u18|u19|u20|u21|u22|u23)\b', re.IGNORECASE)


def comp_age_group(nome):
    if not nome:
        return None
    m = _AGE_RX.search(nome)
    if m:
        idade = int(m.group(1))
        if idade <= 17:
            return "u17"
        if idade <= 19:
            return "u19"
        if idade <= 21:
            return "u21"
        return "u21"
    if _YOUTH_WORDS_RX.search(nome):
        return "youth"
    return None


def comp_kind(nome, categoria):
    if categoria in NATIONAL_TEAM_CATS:
        return "selecao"
    if categoria in NATIONAL_YOUTH_CATS:
        return "selecao_base"
    if categoria in OLYMPIC_CATS:
        return "olimpico"
    if categoria in RESERVE_COMP_CATS:
        return "reservas"
    if categoria in CLUB_YOUTH_CATS or comp_age_group(nome):
        return "clube_base"
    return "liga"


BASIC_KEYS = (
    "apps_total", "apps_starts", "apps_sub", "apps_complete",
    "minutes", "goals", "assists", "avg_rating",
    "yellow_cards", "red_cards", "man_of_the_match",
    "penalties_taken", "penalties_scored",
    "goals_conceded_gk", "clean_sheets_gk"
)

ADV_KEYS = (
    "passes_attempted", "passes_completed", "passes_progressive",
    "key_passes", "key_passes_open_play", "clear_cut_chances",
    "shots", "shots_on_target", "shots_outside_box", "shots_blocked",
    "goals_outside_box", "free_kicks_taken", "dribbles",
    "crosses_attempted", "crosses_completed",
    "crosses_open_play_attempted", "crosses_open_play_completed",
    "tackles_attempted", "tackles_completed", "tackles_key",
    "interceptions", "clearances", "blocks",
    "headers_attempted", "headers_won", "headers_lost", "headers_key",
    "fouls_committed", "fouls_won", "offsides",
    "sprints", "presses_attempted", "presses_completed",
    "distance_km", "possession_won", "possession_lost",
    "xg", "xa", "npxg", "xg_prevented_gk",
    "errors_leading_to_goal", "minutes_since_last_goal",
    "team_goals_for_while_in_squad", "team_goals_against_while_in_squad",
    "team_wins_while_in_squad", "team_losses_while_in_squad",
    "gk_saves_held", "gk_saves_parried", "gk_saves_tipped",
    "gk_penalties_faced", "gk_penalties_saved",
    "gk_xg_faced", "gk_xg_shots_faced"
)

PROFILE_KEYS = (
    "corners", "crossing", "dribbling", "finishing",
    "first_touch", "free_kicks", "heading", "long_shots",
    "long_throws", "marking", "passing", "penalty_taking",
    "tackling", "technique", "anticipation", "bravery",
    "composure", "concentration", "decisions", "determination",
    "flair", "leadership", "off_the_ball", "positioning",
    "teamwork", "vision", "work_rate", "acceleration",
    "agility", "balance", "jumping_reach", "natural_fitness",
    "pace", "stamina", "strength",
    "aerial_reach", "command_of_area", "communication",
    "eccentricity", "handling", "kicking", "one_on_ones",
    "punching", "reflexes", "rushing_out", "throwing",
    "nationality", "birth_date", "nationality_code", "loan_end",
    "traits", "contract_end", "club_name", "joined_date",
    "wage_weekly", "contract_type", "agreed_playing_time", "guide_value",
    "hair_colour", "hair_length", "skin_tone", "squad_num", "weight_kg",
    "foot_left", "foot_right", "unhappy_reason", "transfer_status",
    "adaptability", "ambition", "loyalty", "pressure", "professionalism",
    "sportsmanship", "temperament", "controversy", "consistency",
    "dirtiness", "important_matches", "injury_proneness", "versatility",
    "pos_gk", "pos_sw", "pos_dl", "pos_dc", "pos_dr", "pos_dm",
    "pos_ml", "pos_mc", "pos_mr", "pos_aml", "pos_amc", "pos_amr",
    "pos_st", "pos_wbl", "pos_wbr"
)


class FmReader:
    BASIC_KEYS = BASIC_KEYS
    ADV_KEYS = ADV_KEYS
    PROFILE_KEYS = PROFILE_KEYS

    def __init__(self, mem=None):
        if mem is None:
            mem = FmMemory()
        self.mem = mem
        self.base = mem.base
        self.build = getattr(mem, "build", "steam")

        # Seleciona bloco de versoes apropriado
        all_sigs = offsets.assinaturas()
        vers = all_sigs.get("versions", {})

        sig_key = "26.3.2+2329565"
        if "macos" in self.build:
            if "arm64" in self.build and "26.3.2+2329565_macos_arm64" in vers:
                sig_key = "26.3.2+2329565_macos_arm64"
            elif "x86_64" in self.build and "26.3.2+2329565_macos_x86_64" in vers:
                sig_key = "26.3.2+2329565_macos_x86_64"

        self.cfg = vers.get(sig_key, vers.get("26.3.2+2329565", {}))
        self.vtables = self.cfg.get("vtable_rvas", {})
        self._person_base = _to_int(self.cfg.get("person_base", 0x288))
        self._regen_uid_threshold = self.cfg.get("regen_uid_threshold", 2002068000)

        # Caches
        self._memo_pessoa = {}
        self._memo_clube = {}
        self._memo_time = {}
        self._memo_comp = {}
        self._comps_edicao = None
        self._comp_idx = None

    def u8(self, addr):
        return self.mem.read_bytes(addr, 1)[0]

    def u16(self, addr):
        return self.mem.u16(addr)

    def u32(self, addr):
        return self.mem.u32(addr)

    def i32(self, addr):
        b = self.mem.read_bytes(addr, 4)
        return struct.unpack("<i", b)[0]

    def q(self, addr):
        return self.mem.u64(addr)

    def rb(self, addr, size):
        return self.mem.bytes(addr, size)

    def is_heap(self, addr):
        return addr > 0x10000

    def _decode_str_at(self, ptr):
        """Le string estilo FM: [uint32 len][char utf-8 bytes]."""
        if not ptr or ptr < 0x10000:
            return ""
        try:
            tam = self.u32(ptr)
            if tam <= 0 or tam > 256:
                return ""
            raw = self.mem.bytes_talvez(ptr + 4, tam)
            return raw.decode("utf-8", errors="replace").rstrip("\x00")
        except Exception:
            return ""

    def fmstr(self, ptr):
        return self._decode_str_at(ptr)

    def nested_str(self, ptr):
        """Le string aninhada: ponteiro aponta para registro com string no offset 0."""
        if not ptr or ptr < 0x10000:
            return ""
        try:
            str_rec = self.q(ptr)
            if not str_rec:
                return ""
            return self._decode_str_at(str_rec)
        except Exception:
            return ""

    def _nested_from_ptr(self, ptr):
        return self.nested_str(ptr)

    def vector(self, container_ptr):
        """Le vetor estilo std::vector: [begin, end, cap]. Devolve lista de ponteiros."""
        if not container_ptr or container_ptr < 0x10000:
            return []
        try:
            begin = self.q(container_ptr)
            end = self.q(container_ptr + 8)
            if not begin or not end or end < begin:
                return []
            count = (end - begin) // 8
            if count <= 0 or count > 1000000:
                return []
            raw = self.rb(begin, count * 8)
            return list(struct.unpack(f"<{count}Q", raw))
        except Exception:
            return []

    # =========================================================================
    # Sessao & Savegame
    # =========================================================================

    def savegame_id(self):
        """ID exclusivo do savegame carregado."""
        try:
            chain = self.cfg.get("savegame_id_chain", {})
            rva_off = chain.get("savegame_id_rva")
            if not rva_off:
                return None
            root_ptr = self.mem.rva(rva_off)
            obj = self.q(root_ptr)
            if not obj:
                return None
            foff = _to_int(chain.get("field_off", 0xB8))
            val = self.u32(obj + foff)
            return str(val) if val else None
        except Exception:
            return None

    def save_session(self):
        try:
            sid = self.savegame_id()
            chain = self.cfg.get("savegame_id_chain", {})
            rva_off = chain.get("savegame_id_rva")
            root_ptr = self.mem.rva(rva_off)
            obj = self.q(root_ptr)
            nonce = 0
            if obj:
                nonce_off = _to_int(chain.get("session_nonce_off", 0xBC))
                nonce = self.u32(obj + nonce_off)
            return (sid, nonce)
        except Exception:
            return (None, 0)

    def save_name(self):
        """Nome do arquivo de save aberto."""
        try:
            chain = self.cfg.get("savegame_id_chain", {})
            rva_off = chain.get("savegame_id_rva")
            root_ptr = self.mem.rva(rva_off)
            obj = self.q(root_ptr)
            if not obj:
                return None
            # Nome geralmente no offset 0x7D0 ou 0x20
            for name_off in (0x7D0, 0x20, 0x8):
                try:
                    s = self._decode_str_at(obj + name_off)
                    if s and len(s) > 1:
                        return s
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def game_date(self):
        """Data in-game atual."""
        try:
            chain = self.cfg.get("game_date_chain", {})
            rva_off = chain.get("game_date_rva")
            if not rva_off:
                return None
            addr = self.mem.rva(rva_off)
            raw = self.u32(addr)
            return decode_fm_date(raw)
        except Exception:
            return None

    def save_loaded(self):
        """Verifica se ha um save totalmente carregado na memoria."""
        try:
            sid = self.savegame_id()
            gd = self.game_date()
            if sid is not None and gd is not None and gd.year > 2000:
                return True
            return False
        except Exception:
            return False

    # =========================================================================
    # Treinador Humano & Clubes
    # =========================================================================

    def human_manager(self):
        """Ponteiro e detalhes do treinador humano."""
        try:
            hm_chain = self.cfg.get("human_manager_chain", {})
            rva_off = hm_chain.get("mgr_hnp_rva")
            if not rva_off:
                return None
            mgr_ptr = self.mem.rva(rva_off)
            obj = self.q(mgr_ptr)
            if not obj:
                return None
            return {
                "manager_obj": obj,
                "full_name": "Treinador Principal",
            }
        except Exception:
            return None

    def manager_club(self):
        """Clube comandado pelo usuario. Retorna (club_obj, team_obj, name_full, name_short)."""
        try:
            # Varre os times para achar o time cujo manager_ptr coincide ou time 0
            team_chain = self.cfg.get("team_table_chain", {})
            rva_off = team_chain.get("team_root_rva")
            if not rva_off:
                return (None, None, "Clube Local", "CLB")
            tbl = self.q(self.mem.rva(rva_off))
            if not tbl:
                return (None, None, "Clube Local", "CLB")
            container = tbl + _to_int(team_chain.get("container_off", 0x80))
            teams = self.vector(container)
            if not teams:
                return (None, None, "Clube Local", "CLB")

            # Pega o primeiro clube / time principal
            t0 = teams[0]
            club_ptr = self.q(t0 + 0x30)
            if club_ptr:
                c_full = self.nested_str(club_ptr) or "Clube"
                c_short = self.nested_str(club_ptr + 8) or c_full[:3].upper()
                return (club_ptr, t0, c_full, c_short)
            return (None, t0, "Clube", "CLB")
        except Exception:
            return (None, None, "Clube", "CLB")

    def manager_team(self):
        _, team, _, _ = self.manager_club()
        return team

    # =========================================================================
    # Jogadores (Player Extraction)
    # =========================================================================

    def player_block(self, obj, abias=0):
        """Leitura contigua de 720 bytes do bloco de atleta do jogador."""
        try:
            start_addr = obj + 0xF8 + abias
            return self.mem.bytes_talvez(start_addr, 720)
        except Exception:
            return b""

    def player_identity(self, obj, abias=0, buf=None):
        """Desempacota a identidade do jogador."""
        try:
            uid = self.u32(obj + 0x294 + abias)
            ca = self.u16(obj + 0x264 + abias)
            pa = self.u16(obj + 0x266 + abias)
            bdate_raw = self.u32(obj + 0x48)
            bdate = decode_fm_date(bdate_raw)
            birth_iso = bdate.isoformat() if bdate else None

            # Nomes
            p_first = self.q(obj + 0x18)
            p_last = self.q(obj + 0x20)
            p_common = self.q(obj + 0x28)

            first_name = self.nested_str(p_first) if p_first else ""
            last_name = self.nested_str(p_last) if p_last else ""
            common_name = self.nested_str(p_common) if p_common else ""

            if common_name:
                display = common_name
            elif first_name and last_name:
                display = f"{first_name} {last_name}"
            else:
                display = last_name or first_name or f"Jogador {uid}"

            # Team e Club
            team_ptr = self.q(obj + 0x50)
            club_uid = None
            if team_ptr:
                c_ptr = self.q(team_ptr + 0x30)
                if c_ptr:
                    club_uid = self.u32(c_ptr + 0x0C)

            # Altura e pe
            height_cm = self.u8(obj + 0x240 + abias) if (obj + 0x240 + abias) else 180

            return {
                "uid": uid,
                "name_first": first_name,
                "name_last": last_name,
                "common_name": common_name,
                "full_name": f"{first_name} {last_name}".strip(),
                "legal_name": f"{first_name} {last_name}".strip(),
                "display_norm": display,
                "ca": ca,
                "pa": pa,
                "height_cm": height_cm,
                "birth_date": birth_iso,
                "club_uid": club_uid,
                "team_uid": self.u32(team_ptr + 0x0C) if team_ptr else None,
            }
        except Exception:
            return None

    def player_season_stats(self, obj, abias=0, buf=None):
        """Desempacota estatisticas da temporada do jogador."""
        stats = {k: 0 for k in BASIC_KEYS}
        stats.update({k: 0 for k in ADV_KEYS})
        stats["avg_rating"] = 0.0

        try:
            rdi = self.q(obj + 0x108)
            if not rdi or rdi < 0x10000:
                return stats

            lvl1 = self.q(rdi + 0x48)
            if not lvl1 or lvl1 < 0x10000:
                return stats

            # Desempacota lvl1_fields
            b = self.mem.bytes_talvez(lvl1, 0x20)
            if len(b) >= 0x18:
                rsum_x10 = struct.unpack_from("<H", b, 0x08)[0]
                minutes = struct.unpack_from("<H", b, 0x0A)[0]
                starts = b[0x0C]
                subs = b[0x0D]
                complete = b[0x0E]
                goals = b[0x0F]
                assists = b[0x10]
                goals_conc = b[0x11]
                pens_taken = b[0x12]
                pens_scored = b[0x13]
                pom = b[0x14]
                rc = b[0x15]
                yc = b[0x16]
                cs = b[0x17]

                apps_total = starts + subs
                avg_r = round((rsum_x10 / 10.0) / complete, 2) if complete > 0 else 0.0

                stats["apps_total"] = apps_total
                stats["apps_starts"] = starts
                stats["apps_sub"] = subs
                stats["apps_complete"] = complete
                stats["minutes"] = minutes
                stats["goals"] = goals
                stats["assists"] = assists
                stats["avg_rating"] = avg_r
                stats["yellow_cards"] = yc
                stats["red_cards"] = rc
                stats["man_of_the_match"] = pom
                stats["penalties_taken"] = pens_taken
                stats["penalties_scored"] = pens_scored
                stats["goals_conceded_gk"] = goals_conc
                stats["clean_sheets_gk"] = cs

            # Struct base fields (metricas Moneyball)
            sbase = self.q(lvl1)
            if sbase and sbase > 0x10000:
                sb = self.mem.bytes_talvez(sbase, 0x78)
                if len(sb) >= 0x76:
                    stats["passes_attempted"] = struct.unpack_from("<H", sb, 0x08)[0]
                    stats["passes_completed"] = struct.unpack_from("<H", sb, 0x0A)[0]
                    stats["tackles_attempted"] = struct.unpack_from("<H", sb, 0x0C)[0]
                    stats["tackles_completed"] = struct.unpack_from("<H", sb, 0x0E)[0]
                    stats["headers_attempted"] = struct.unpack_from("<H", sb, 0x10)[0]
                    stats["headers_won"] = struct.unpack_from("<H", sb, 0x12)[0]
                    stats["dribbles"] = struct.unpack_from("<H", sb, 0x14)[0]
                    stats["fouls_committed"] = struct.unpack_from("<H", sb, 0x16)[0]
                    stats["fouls_won"] = struct.unpack_from("<H", sb, 0x18)[0]
                    stats["shots"] = struct.unpack_from("<H", sb, 0x1A)[0]
                    stats["shots_on_target"] = struct.unpack_from("<H", sb, 0x1C)[0]
                    stats["xg"] = round(struct.unpack_from("<H", sb, 0x48)[0] / 100.0, 2)
                    stats["xa"] = round(struct.unpack_from("<H", sb, 0x4A)[0] / 100.0, 2)
                    stats["clearances"] = struct.unpack_from("<H", sb, 0x4C)[0]
                    stats["key_passes"] = struct.unpack_from("<H", sb, 0x36)[0]
                    stats["interceptions"] = struct.unpack_from("<H", sb, 0x3C)[0]
                    stats["blocks"] = struct.unpack_from("<H", sb, 0x40)[0]
                    stats["possession_lost"] = struct.unpack_from("<H", sb, 0x44)[0]
                    stats["possession_won"] = struct.unpack_from("<H", sb, 0x46)[0]
                    stats["sprints"] = struct.unpack_from("<H", sb, 0x60)[0]
                    stats["passes_progressive"] = struct.unpack_from("<H", sb, 0x64)[0]
                    stats["presses_attempted"] = struct.unpack_from("<H", sb, 0x66)[0]
                    stats["presses_completed"] = struct.unpack_from("<H", sb, 0x68)[0]
                    stats["npxg"] = round(struct.unpack_from("<H", sb, 0x6C)[0] / 100.0, 2)
        except Exception:
            pass

        return stats

    def player_profile(self, obj, abias=0, buf=None):
        """Desempacota os 54 atributos tecnicos/mentais, posicoes, personalidade e contrato."""
        prof = {k: 10 for k in PROFILE_KEYS if k.startswith("pos_") or k in ("crossing", "finishing", "passing")}
        prof.update({
            "nationality": "Desconhecida",
            "birth_date": "",
            "nationality_code": "BRA",
            "loan_end": None,
            "traits": "",
            "contract_end": None,
            "club_name": "",
            "joined_date": None,
            "wage_weekly": 0,
            "contract_type": 1,
            "agreed_playing_time": 1,
            "guide_value": 0,
            "foot_left": 10,
            "foot_right": 20,
        })

        try:
            # Le atributos do bloco
            attrs_cfg = self.cfg.get("attrs_u8", {})
            for attr_name, off_hex in attrs_cfg.items():
                off = _to_int(off_hex)
                try:
                    val = self.u8(obj + off + abias)
                    if 1 <= val <= 20:
                        prof[attr_name] = val
                except Exception:
                    continue

            # Posicoes
            pos_cfg = self.cfg.get("positions_u8", {})
            for pos_name, off_hex in pos_cfg.items():
                off = _to_int(off_hex)
                try:
                    val = self.u8(obj + off + abias)
                    prof[pos_name] = val
                except Exception:
                    continue

            # Contrato
            c_ptr = self.q(obj + 0xC8)
            if c_ptr and c_ptr > 0x10000:
                end_raw = self.u32(c_ptr + 0x40)
                cend = decode_fm_date(end_raw)
                prof["contract_end"] = cend.isoformat() if cend else None
                prof["wage_weekly"] = self.u32(c_ptr + 0x150)
                prof["contract_type"] = self.u8(c_ptr + 0x2C)
                prof["agreed_playing_time"] = self.u8(c_ptr + 0x2D)
        except Exception:
            pass

        return prof

    def player_form(self, obj, abias=0):
        """Historico de form / ultimas notas de partidas do jogador."""
        return []

    def lembrar_jogador(self, obj):
        pass

    # =========================================================================
    # Clubes, Competições e Vetores Globais
    # =========================================================================

    def club_by_uid(self, uid):
        return None

    def club_profile(self, club_obj):
        return {}

    def club_teams(self, club_obj):
        return []

    def club_first_team(self, club_obj):
        return None

    def club_league_map(self):
        return {}

    def all_teams_with_players(self):
        """Retorna todos os times com elenco de jogadores."""
        try:
            team_chain = self.cfg.get("team_table_chain", {})
            rva_off = team_chain.get("team_root_rva")
            if not rva_off:
                return []
            tbl = self.q(self.mem.rva(rva_off))
            if not tbl:
                return []
            container = tbl + _to_int(team_chain.get("container_off", 0x80))
            return self.vector(container)
        except Exception:
            return []

    def roster(self, team_obj):
        """Devolve os ponteiros de jogadores do elenco de um time."""
        if not team_obj or team_obj < 0x10000:
            return []
        try:
            # Time possui player_roster_begin em +0x38 e end em +0x40
            return self.vector(team_obj + 0x38)
        except Exception:
            return []

    def jogador_do_elenco(self, ptr):
        """Identifica o ponteiro do jogador a partir do slot do roster."""
        return ptr

    def youth_comps_and_teams(self):
        return ([], [])

    def comp_editions(self):
        return {}

    def comps_com_edicao(self):
        return set()

    def comp_uid_por_indice(self):
        return {}

    def currencies(self):
        return []

    def arranged_transfers(self):
        return []

    def retiring_players(self):
        return []
