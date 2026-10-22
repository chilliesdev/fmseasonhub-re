"""Confere a assinatura do manifesto de atualizacao (RSA PKCS#1 v1.5 com SHA-256).

O manifesto diz qual instalador e o legitimo (versao, SHA-256 e tamanho). O hash sozinho
so prova que o arquivo e o que o SERVIDOR disse; a assinatura prova que foi o dono da
chave privada quem disse -- um servidor adulterado nao consegue forjar isso.

Sem biblioteca nova: a conferencia RSA e uma exponenciacao modular (`pow`) e uma
comparacao de bytes. Aceita qualquer uma das chaves de `chaves_publicas` (a atual e a
reserva -- ver tools/gerar_chaves.py).
"""

import base64
import hashlib
import hmac
import chaves_publicas

EXPOENTE = getattr(chaves_publicas, "EXPOENTE", 65537)
MODULOS = chaves_publicas.MODULOS
_PREFIXO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def _bloco_esperado(conteudo, tamanho):
    """Monta o bloco PKCS#1 v1.5 com o hash SHA-256 do conteudo."""
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    digest = hashlib.sha256(conteudo).digest()
    pad_len = tamanho - 3 - len(_PREFIXO_SHA256) - len(digest)
    if pad_len < 8:
        return b""
    return b"\x00\x01" + (b"\xff" * pad_len) + b"\x00" + _PREFIXO_SHA256 + digest


def confere(conteudo, assinatura, modulos=None, expoente=None):
    """A `assinatura` (bytes) do `conteudo` (bytes) foi feita por uma das nossas chaves?"""
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")

    if isinstance(assinatura, str):
        try:
            assinatura_bytes = base64.b64decode(assinatura)
        except Exception:
            try:
                assinatura_bytes = bytes.fromhex(assinatura)
            except Exception:
                assinatura_bytes = assinatura.encode("latin1")
    else:
        assinatura_bytes = bytes(assinatura)

    if not assinatura_bytes:
        return False

    if modulos is None:
        modulos = chaves_publicas.MODULOS
    if expoente is None:
        expoente = getattr(chaves_publicas, "EXPOENTE", EXPOENTE)

    chaves = modulos.values() if isinstance(modulos, dict) else modulos
    sig_int = int.from_bytes(assinatura_bytes, "big")

    for modulo in chaves:
        try:
            tamanho = (modulo.bit_length() + 7) // 8
            if sig_int >= modulo:
                continue
            dec = pow(sig_int, expoente, modulo)
            bloco = dec.to_bytes(tamanho, "big")
            esperado = _bloco_esperado(conteudo, tamanho)
            if esperado and hmac.compare_digest(bloco, esperado):
                return True
        except Exception:
            continue

    return False
