import asyncio

import pytest


@pytest.fixture(autouse=True)
def fast_asyncio_sleep(monkeypatch):
    """Unit tests assert UI decisions, not real device wait timing."""

    async def _sleep(delay=0, result=None):
        return result

    monkeypatch.setattr(asyncio, "sleep", _sleep)
