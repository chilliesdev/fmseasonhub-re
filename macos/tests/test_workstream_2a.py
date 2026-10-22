"""Unit tests for Workstream 2A reconstructed modules.
"""

import os
import sys
import tempfile
import unittest
import numpy as np

# Ensure macos/src is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import db
import moneyball
import overall
import player_search
import limites
import acesso
import settings
import legal
import assinatura
import diagnostico_core


class TestWorkstream2A(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_db_schema_and_operations(self):
        """Verify all 17 tables, migrations, snapshots, and relations."""
        test_db = os.path.join(self.temp_dir.name, "test_snapshots.db")
        conn = db.connect(test_db)
        db.init_schema(conn)

        # Verify all 17 tables exist
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cur.fetchall()}
        expected_tables = {
            "snapshots", "players", "player_stats", "player_profile",
            "player_match_stats", "team_match_stats", "player_form",
            "snapshot_ligas", "club_profile", "teams", "player_teams",
            "youth_teams", "youth_comps", "youth_team_comps", "comps",
            "club_leagues", "future_transfers"
        }
        for t in expected_tables:
            self.assertIn(t, tables, f"Missing table: {t}")

        # Create snapshot
        sid = db.create_snapshot(
            conn,
            name="Temporada 2026/27",
            save_name="Benfica Save",
            game_date="2026-06-30",
            in_game_season="2026/27",
            scope="squad",
            club_uid=1023,
            manager="Roger Schmidt",
            savegame_id="sg12345",
            fm_version="26"
        )
        self.assertGreater(sid, 0)

        # Insert player
        db.insert_player(conn, sid, 99999, {
            "name_first": "João",
            "name_last": "Neves",
            "full_name": "João Pedro Gonçalves Neves",
            "common_name": "João Neves",
            "ca": 165,
            "pa": 182,
            "height_cm": 174,
            "club_id": 1023,
            "team_uid": 1023,
            "position": "DM, MC"
        })
        p = conn.execute("SELECT full_name, search_norm FROM players WHERE uid=99999").fetchone()
        self.assertIsNotNone(p)
        self.assertEqual(p[0], "João Pedro Gonçalves Neves")
        self.assertEqual(p[1], "joao pedro goncalves neves")

        # Save club profile
        db.save_club(conn, sid, {
            "club_uid": 1023,
            "name_full": "Sport Lisboa e Benfica",
            "name_short": "SLB",
            "year_founded": 1904,
            "balance": 50000000,
            "transfer_budget": 25000000,
            "wage_budget": 1200000,
            "training_facilities": 19,
            "youth_facilities": 20,
        })
        club = conn.execute("SELECT name_full, youth_facilities FROM club_profile WHERE snapshot_id=?", (sid,)).fetchone()
        self.assertEqual(club[0], "Sport Lisboa e Benfica")
        self.assertEqual(club[1], 20)

        conn.close()

    def test_02_moneyball_metrics_and_percentiles(self):
        """Verify formula evaluation, mid-rank percentiles, and catalog."""
        # Mid-rank percentile test
        pool = np.array([10.0, 20.0, 20.0, 30.0, 40.0])
        queries = np.array([10.0, 20.0, 25.0, 40.0])
        pcts = moneyball.percentile_ranks(pool, queries)

        # 10.0 is index 0: count(<10)=0, count(==10)=1 -> (0 + 0.5) / 5 * 100 = 10.0%
        self.assertAlmostEqual(pcts[0], 10.0, places=2)
        # 20.0: count(<20)=1, count(==20)=2 -> (1 + 1.0) / 5 * 100 = 40.0%
        self.assertAlmostEqual(pcts[1], 40.0, places=2)

        # Per 90 calculations
        mins = np.array([900.0, 1800.0, 450.0])
        tackles = np.array([20.0, 50.0, 10.0])
        per90 = moneyball._per90(tackles, mins)
        self.assertAlmostEqual(per90[0], 2.0, places=2)
        self.assertAlmostEqual(per90[1], 2.5, places=2)
        self.assertAlmostEqual(per90[2], 2.0, places=2)

        # Test catalog presence
        self.assertGreater(len(moneyball.POSITION_GROUPS_ORDER), 0)
        self.assertIn("def", moneyball.POSITION_GROUPS_ORDER)
        self.assertIn("gk", moneyball.POSITION_GROUPS_ORDER)

    def test_03_overall_algorithm_and_roles(self):
        """Verify 19 roles, attribute scoring with Z-scores, and performance combining."""
        self.assertEqual(len(overall.ROTULO_PAPEL), 19)

        # Test position mapping
        self.assertEqual(overall.grupo_de("DC"), "cb")
        self.assertEqual(overall.grupo_de("ST"), "st")
        self.assertEqual(overall.grupo_de("GK"), "gk")
        self.assertEqual(overall.grupo_de("MC"), "cm")

        # Test attribute scoring
        attrs = {
            "tackling": 17,
            "marking": 16,
            "heading": 15,
            "positioning": 16,
            "jumping_reach": 15,
            "strength": 16,
            "anticipation": 15,
            "bravery": 15,
            "concentration": 14,
            "decisions": 15,
            "pace": 13,
            "stamina": 14,
        }
        nota_attr = overall.notas_atributo(attrs, grupo="cb")
        self.assertIsNotNone(nota_attr)
        self.assertGreater(nota_attr, 60.0)

        # Test performance scoring
        percentis = {
            "desarmedec90": 85.0,
            "desarmes": 90.0,
            "aereo": 80.0,
            "aereos90": 82.0,
            "pressoes90": 75.0,
            "bloqueios90": 70.0,
            "cortes90": 88.0,
            "progressao": 60.0,
            "passes": 65.0,
            "passeschave90": 50.0,
            "desarmes90": 85.0,
            "xa90": 40.0,
        }
        nota_perf, papel = overall.notas_desempenho(percentis, minutos=1800, grupo="cb")
        self.assertIsNotNone(nota_perf)
        self.assertEqual(papel, "zagueiro_agressor")

        # Test combined mode
        nota_mista = overall.combinar(nota_attr, nota_perf, modo="misto")
        self.assertAlmostEqual(nota_mista, (nota_attr + nota_perf) / 2.0, places=1)

    def test_04_player_search_operators(self):
        """Verify numeric and text operators, AND/OR logic evaluation."""
        ages = np.array([19.0, 24.0, 29.0, 33.0])
        mask_gt = player_search.num_mask(ages, "gt", 24.0)
        np.testing.assert_array_equal(mask_gt, [False, False, True, True])

        mask_between = player_search.num_mask(ages, "between", (20.0, 30.0))
        np.testing.assert_array_equal(mask_between, [False, True, True, False])

        names = ["Erling Haaland", "Kylian Mbappé", "Vinicius Junior"]
        mask_txt = player_search.text_mask(names, "contains", "haaland")
        np.testing.assert_array_equal(mask_txt, [True, False, False])

    def test_05_acesso_and_limites_offline_unlocked(self):
        """Verify macOS tier 4 full unlock default."""
        st = acesso.estado()
        self.assertEqual(st["nivel"], 4)
        self.assertEqual(st["tier"], "pro")

        # Limits check
        self.assertTrue(limites.cabe_mais_uma(4, 999, "squad"))
        self.assertTrue(limites.cabe_mais_uma(4, 999, "full"))
        l = limites.limites(4)
        self.assertTrue(l["favoritos"])
        self.assertTrue(l["assistente"])
        self.assertTrue(l["financas"])

    def test_06_diagnostico_core(self):
        """Verify diagnostic generator returns all required blocks."""
        rel = diagnostico_core.rodar()
        self.assertIn("ambiente", rel)
        self.assertIn("processos", rel)
        self.assertIn("rede", rel)
        self.assertIn("leitura", rel)


if __name__ == "__main__":
    unittest.main()
