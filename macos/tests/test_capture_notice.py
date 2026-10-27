"""Unit tests for capture notification callback and moment resolution."""

from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app_main
import server


class CaptureNoticeTests(unittest.TestCase):
    def test_resolver_momento_captura_handles_dictionary_payloads(self):
        # Database capture payload with snapshot id and name
        estado, tipo = app_main.resolver_momento_captura({"sid": 123, "nome": "Test Season"})
        self.assertEqual(estado, "concluida")
        self.assertIsNone(tipo)

        # Simulation payload with estado and tipo
        estado, tipo = app_main.resolver_momento_captura(
            {"simulada": True, "estado": "concluida", "tipo": "auto"}
        )
        self.assertEqual(estado, "concluida")
        self.assertEqual(tipo, "auto")

        # Simulation payload with failure state and tracker mode
        estado, tipo = app_main.resolver_momento_captura(
            {"simulada": True, "estado": "falhou", "tipo": "tracker"}
        )
        self.assertEqual(estado, "falhou")
        self.assertEqual(tipo, "tracker")

        # Generic dictionary payloads with momento or status
        estado, tipo = app_main.resolver_momento_captura({"momento": "inicio"})
        self.assertEqual(estado, "inicio")
        self.assertIsNone(tipo)

        estado, tipo = app_main.resolver_momento_captura({"status": "fechar"})
        self.assertEqual(estado, "fechar")
        self.assertIsNone(tipo)

    def test_resolver_momento_captura_handles_string_and_none(self):
        self.assertEqual(app_main.resolver_momento_captura("inicio"), ("inicio", None))
        self.assertEqual(app_main.resolver_momento_captura("concluida"), ("concluida", None))
        self.assertEqual(app_main.resolver_momento_captura("falhou"), ("falhou", None))
        self.assertEqual(app_main.resolver_momento_captura("fechar"), ("fechar", None))
        self.assertEqual(app_main.resolver_momento_captura(None), ("concluida", None))

    def test_aviso_da_captura_plays_sound_on_saved_snapshot_dict(self):
        tocar_som = Mock()
        janelas = {}
        trava = threading.Lock()
        webview_mock = Mock()
        fake_window = Mock()
        webview_mock.create_window.return_value = fake_window
        mock_server = SimpleNamespace(SIMULACAO={}, CAPTURA_AUTO={})

        aviso = app_main.criar_aviso_da_captura(
            mock_server,
            tocar_som,
            janelas,
            trava,
            "http://127.0.0.1:8000",
            webview_mod=webview_mock,
        )

        # Passing dict payload must play captura-fim and open window without error
        aviso({"sid": 42, "nome": "Campeonato Brasileiro"})
        tocar_som.assert_called_once_with("captura-fim")
        webview_mock.create_window.assert_called_once()
        self.assertIs(janelas.get("faixa"), fake_window)
        self.assertEqual(janelas.get("faixa_tamanho"), (app_main.LARGURA_FAIXA, app_main.ALTURA_FAIXA))

    def test_aviso_da_captura_handles_simulated_capture(self):
        tocar_som = Mock()
        janelas = {}
        trava = threading.Lock()
        webview_mock = Mock()
        webview_mock.create_window.return_value = Mock()
        mock_server = SimpleNamespace(SIMULACAO={}, CAPTURA_AUTO={})

        aviso = app_main.criar_aviso_da_captura(
            mock_server,
            tocar_som,
            janelas,
            trava,
            "http://127.0.0.1:8000",
            webview_mod=webview_mock,
        )

        # Simulation failure plays alerta sound
        aviso({"simulada": True, "estado": "falhou", "tipo": "auto"})
        tocar_som.assert_called_once_with("captura-alerta")

    def test_aviso_da_captura_suppresses_sound_for_tracker_and_ja_salva(self):
        tocar_som = Mock()
        janelas = {}
        trava = threading.Lock()
        webview_mock = Mock()
        webview_mock.create_window.return_value = Mock()

        # Tracker mode (pilula) suppresses sound
        mock_server = SimpleNamespace(SIMULACAO={"estado": "concluida", "tipo": "tracker"}, CAPTURA_AUTO={})
        aviso = app_main.criar_aviso_da_captura(
            mock_server,
            tocar_som,
            janelas,
            trava,
            "http://127.0.0.1:8000",
            webview_mod=webview_mock,
        )
        aviso({"simulada": True, "estado": "concluida", "tipo": "tracker"})
        tocar_som.assert_not_called()
        self.assertEqual(janelas.get("faixa_tamanho"), (app_main.LARGURA_PILULA, app_main.ALTURA_PILULA))

        # ja_salva auto capture suppresses sound
        mock_server = SimpleNamespace(SIMULACAO={}, CAPTURA_AUTO={"estado": "ja_salva", "tipo": "auto"})
        aviso = app_main.criar_aviso_da_captura(
            mock_server,
            tocar_som,
            janelas,
            trava,
            "http://127.0.0.1:8000",
            webview_mod=webview_mock,
        )
        aviso("concluida")
        tocar_som.assert_not_called()

    def test_aviso_da_captura_closes_window_on_fechar(self):
        tocar_som = Mock()
        existing_window = Mock()
        janelas = {"faixa": existing_window, "faixa_tamanho": (app_main.LARGURA_FAIXA, app_main.ALTURA_FAIXA)}
        trava = threading.Lock()
        mock_server = SimpleNamespace(SIMULACAO={}, CAPTURA_AUTO={})

        aviso = app_main.criar_aviso_da_captura(
            mock_server,
            tocar_som,
            janelas,
            trava,
            "http://127.0.0.1:8000",
            webview_mod=Mock(),
        )

        # Close via string
        aviso("fechar")
        existing_window.destroy.assert_called_once()
        self.assertIsNone(janelas.get("faixa"))

        # Close via dict
        existing_window_2 = Mock()
        janelas["faixa"] = existing_window_2
        aviso({"estado": "fechar"})
        existing_window_2.destroy.assert_called_once()
        self.assertIsNone(janelas.get("faixa"))

    def test_simular_captura_endpoint_notifies_callback_safely(self):
        calls = []
        with patch.object(server, "AO_AVISO_DA_CAPTURA", side_effect=lambda payload: calls.append(payload)):
            result = server.simular_captura(estado="concluida", tipo="auto")
            self.assertEqual(result, {"ok": True})
            self.assertEqual(server.SIMULACAO["estado"], "concluida")
            self.assertEqual(server.SIMULACAO["tipo"], "auto")
            self.assertEqual(calls, [{"simulada": True, "estado": "concluida", "tipo": "auto"}])


if __name__ == "__main__":
    unittest.main()
