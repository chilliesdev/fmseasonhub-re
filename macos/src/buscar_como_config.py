"""Validated defaults shared by Preferences and the player similarity dialog."""

import threading
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

import settings


class BuscarComoConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tolIdx: Optional[Annotated[int, Field(strict=True, ge=0, le=5)]] = None
    modo: Optional[Literal["faixa", "melhor", "pct"]] = None
    fora: Optional[Annotated[int, Field(strict=True, ge=0, le=4)]] = None
    pisoPct: Optional[Annotated[int, Field(strict=True, ge=60, le=100)]] = None
    minMinutos: Optional[Annotated[int, Field(strict=True, ge=300, le=2000)]] = None
    valor: Optional[StrictBool] = None
    idade: Optional[StrictBool] = None
    contrato12: Optional[StrictBool] = None
    top20: Optional[StrictBool] = None
    pe: Optional[StrictBool] = None
    # Retain the old response fields; faixa never represented a saved range.
    faixa: None = None
    melhor: Optional[StrictBool] = None
    pct: Optional[StrictBool] = None


_PREFS_LOCK = threading.Lock()


def _effective(saved):
    result = dict(settings.DEFAULTS["buscar_como"], faixa=None, melhor=True, pct=True)
    if isinstance(saved, dict):
        for key, value in saved.items():
            try:
                valid = BuscarComoConfigBody.model_validate({key: value})
            except ValidationError:
                # Older files can contain partial configs or pe=1024.
                continue
            result.update(valid.model_dump(exclude_none=True))
    return result


def load():
    return _effective(settings.load().get("buscar_como"))


def save(body):
    updates = body.model_dump(exclude_none=True)
    with _PREFS_LOCK:
        saved = settings.load().get("buscar_como")
        result = _effective(saved)
        if updates:
            result.update(updates)
            stored = dict(saved) if isinstance(saved, dict) else {}
            stored.update(result)
            settings.save(buscar_como=stored)
        return result
