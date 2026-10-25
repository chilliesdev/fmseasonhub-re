"""The shipped access gates consume flat permissions from both access routes."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import acesso
import limites
import server
import settings


class AccessContractTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(settings.DEFAULTS)
        for patcher in (
            patch.object(settings, "load", side_effect=lambda: dict(self.saved)),
            patch.object(acesso, "impressao_maquina", return_value="qa-machine"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def state(self, level):
        with patch.object(acesso.sys, "platform", "win32"):
            self.saved["acesso_nivel"] = level
            return acesso.estado()

    def assert_permissions(self, state, level):
        expected = limites.limites(level)
        self.assertEqual(state["nivel"], level)
        self.assertEqual(state["limites"], expected)
        # The flat `nome` is the account identity, not the Portuguese tier name.
        for key, value in expected.items():
            if key != "nome":
                self.assertEqual(state[key], value, key)
        self.assertEqual(state["escada"], limites.escada())

    def test_default_mac_offline_pro_has_flat_permissions_without_remote_access(self):
        self.saved["acesso_nivel"] = 0
        with patch.object(acesso.sys, "platform", "darwin"), patch.object(acesso, "_chamar") as remote:
            state = acesso.estado()
            self.assert_permissions(state, 4)
            self.assertEqual(acesso.revalidar(forcar=True), (state, None))
            remote.assert_not_called()
        self.assertEqual(state["tier"], "pro")
        self.assertEqual(state["nome"], "FMSH Pro (macOS)")
        self.assertEqual(state["origem"], "offline_macos")
        self.assertEqual(state["chave"], "PRO-UNLOCKED-MACOS")
        self.assertTrue(state["conferido"])
        self.assertFalse(state["pausado"])
        self.assertTrue(state["favoritos"])
        self.assertIsNone(state["max_listas_favoritos"])

    def test_all_tiers_keep_permission_thresholds_and_quotas(self):
        for level in range(5):
            with self.subTest(level=level):
                state = self.state(level)
                self.assert_permissions(state, level)
                self.assertEqual(state["favoritos"], level >= 1)
                for permission in ("comparar", "assistente", "financas", "lista_fm_completa"):
                    self.assertEqual(state[permission], level >= 2, permission)
                self.assertEqual(state["acesso_antecipado"], level >= 3)
                self.assertEqual(state["max_listas_favoritos"], (1, 1, 3, 10, None)[level])
                self.assertEqual(state["max_temporadas"], (2, 2, 4, 10, None)[level])

    def test_saved_identity_is_not_replaced_by_permission_names(self):
        identity = {
            "tier": "saved-tier", "tier_nome": "Saved tier", "nome": "QA Person",
            "origem": "codigo", "chave": "QA-CODE", "conferido": False,
            "conferido_em": 1234567890, "maquina": "saved-machine",
        }
        self.saved.update({"acesso_" + key: value for key, value in identity.items()})
        state = self.state(2)
        self.assert_permissions(state, 2)
        for key, value in identity.items():
            self.assertEqual(state[key], value, key)
        self.assertEqual(state["limites"]["nome"], "Season Analyst")

    def test_both_http_route_aliases_return_the_contract_at_every_tier(self):
        async def get(route, query):
            messages = []

            async def receive():
                return {"type": "http.request", "body": b""}

            async def send(message):
                messages.append(message)

            await server.app({
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "scheme": "http", "method": "GET", "path": route,
                "raw_path": route.encode(), "query_string": query, "headers": [],
                "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 12345),
            }, receive, send)
            self.assertEqual(messages[0]["status"], 200)
            return json.loads(b"".join(message.get("body", b"") for message in messages[1:]))

        for level in range(5):
            with self.subTest(level=level), patch.object(acesso, "_nivel_guardado", return_value=level):
                expected = acesso.estado()
                for route in ("/api/acesso", "/api/acesso/estado"):
                    for query in (b"", b"revalidar=1"):
                        self.assertEqual(asyncio.run(get(route, query)), expected)
                self.assert_permissions(expected, level)

    def test_shipped_access_hook_and_favorites_and_soon_screen_renderers(self):
        states = [self.state(level) for level in range(5)]
        script = Path(__file__).with_name("access_contract_ui.mjs")
        result = subprocess.run(["node", str(script)], input=json.dumps(states),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Access renderer regressions passed: 5 tiers", result.stdout)


if __name__ == "__main__":
    unittest.main()
