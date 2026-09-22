import asyncio

from cryptography.fernet import Fernet

from bot import crypto_store, db, handlers


def _secret_key() -> str:
    return Fernet.generate_key().decode()


class _FakeLisBuy:
    def __init__(self, balance=None, fail=False):
        self._balance = balance
        self._fail = fail

    async def get_balance(self, api_key):
        if self._fail:
            raise RuntimeError("боом")
        return self._balance


def test_key_view_no_key_saved(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "k1.db"))
        try:
            text, kb = await handlers._key_view(1, _secret_key())
            assert "Ще не задано" in text
            assert kb.inline_keyboard[0][0].callback_data == "keyset"
        finally:
            await db.close()

    asyncio.run(go())


def test_key_view_key_saved(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "k2.db"))
        try:
            await db.set_user_key(1, b"blob")
            text, kb = await handlers._key_view(1, _secret_key())
            assert "Збережено" in text
            labels = [b.text for row in kb.inline_keyboard for b in row]
            assert any("Баланс" in l for l in labels)
            assert any("Видалити" in l for l in labels)
        finally:
            await db.close()

    asyncio.run(go())


def test_start_setkey_without_secrets_key_refuses():
    handlers._pending_setkey.pop(999, None)
    text, kb = asyncio.run(handlers._start_setkey(999, None))
    assert "SECRETS_KEY" in text
    assert 999 not in handlers._pending_setkey


def test_start_setkey_with_secrets_key_sets_pending_state():
    uid = 998
    handlers._pending_setkey.pop(uid, None)
    handlers._setkey_tmp.pop(uid, None)
    try:
        text, kb = asyncio.run(handlers._start_setkey(uid, _secret_key()))
        assert "Встав свій API-ключ" in text
        assert handlers._pending_setkey[uid] == "key"
        assert kb.inline_keyboard[0][0].callback_data == "keycancel"
    finally:
        handlers._pending_setkey.pop(uid, None)


def test_balance_text_no_key(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "k3.db"))
        try:
            text, kb = await handlers._balance_text(1, _secret_key(), _FakeLisBuy())
            assert "/setkey" in text
        finally:
            await db.close()

    asyncio.run(go())


def test_balance_text_success(tmp_path):
    async def go():
        secret = _secret_key()
        await db.init_db(str(tmp_path / "k4.db"))
        try:
            blob = crypto_store.encrypt(secret, {"api_key": "abc", "partner": "1", "token": "t"})
            await db.set_user_key(1, blob)
            text, kb = await handlers._balance_text(1, secret, _FakeLisBuy(balance=42.5))
            assert "$42.50" in text
        finally:
            await db.close()

    asyncio.run(go())


def test_balance_text_key_broken_reports_error(tmp_path):
    async def go():
        secret = _secret_key()
        await db.init_db(str(tmp_path / "k5.db"))
        try:
            blob = crypto_store.encrypt(secret, {"api_key": "abc", "partner": "1", "token": "t"})
            await db.set_user_key(1, blob)
            text, kb = await handlers._balance_text(1, secret, _FakeLisBuy(fail=True))
            assert "недійсним" in text
        finally:
            await db.close()

    asyncio.run(go())


def test_remove_key_clears_pending_and_db(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "k6.db"))
        try:
            uid = 5
            handlers._pending_setkey[uid] = "key"
            handlers._setkey_tmp[uid] = "somekey"
            await db.set_user_key(uid, b"blob")
            text = await handlers._remove_key(uid)
            assert "видалено" in text
            assert uid not in handlers._pending_setkey
            assert uid not in handlers._setkey_tmp
            assert await db.get_user_key(uid) is None

            text2 = await handlers._remove_key(uid)
            assert "не було" in text2
        finally:
            await db.close()

    asyncio.run(go())
