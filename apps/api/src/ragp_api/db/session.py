from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ragp_api.settings import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Standalone context manager for use outside FastAPI request lifecycle
# (e.g. ARQ worker tasks that cannot use dependency injection).
async_session = AsyncSessionLocal
