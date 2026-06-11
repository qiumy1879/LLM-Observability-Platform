"""pytest 配置 — 每个测试用独立 SQLite 文件数据库，测试完自动清理"""

import os
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def db_session():
    """每个测试独立的数据库，同一连接上建表和操作"""
    from app.core.database import Base

    db_path = f"test_{uuid.uuid4().hex}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        # 在 session 的连接上建表，保证可见性
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        await session.commit()

        yield session
        await session.rollback()

    await engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest_asyncio.fixture
async def client(db_session):
    """提供 httpx AsyncClient，走 ASGI 传输。复写 get_db 复用测试会话。"""
    from app.main import app
    from app.core.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
