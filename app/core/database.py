"""数据库引擎和会话管理（支持 SQLite 和 PostgreSQL）

根据 config.use_sqlite 自动切换：
  SQLite (dev):  无需 Docker，开箱即用
  PostgreSQL:    需要 docker compose up -d
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # SQLite 需要 connect_args；PG 不需要
    connect_args={"check_same_thread": False} if settings.use_sqlite else {},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """启动时创建所有表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
