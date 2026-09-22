import asyncio

from bot import db


def test_user_key_roundtrip(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "uk.db"))
        try:
            assert await db.get_user_key(1) is None

            await db.set_user_key(1, b"blob-v1")
            assert await db.get_user_key(1) == b"blob-v1"

            await db.set_user_key(1, b"blob-v2")  # апдейт того самого юзера
            assert await db.get_user_key(1) == b"blob-v2"

            await db.set_user_key(2, b"other-user")
            assert await db.get_user_key(1) == b"blob-v2"
            assert await db.get_user_key(2) == b"other-user"

            assert await db.remove_user_key(1) is True
            assert await db.get_user_key(1) is None
            assert await db.get_user_key(2) == b"other-user"

            assert await db.remove_user_key(999) is False
        finally:
            await db.close()

    asyncio.run(go())
