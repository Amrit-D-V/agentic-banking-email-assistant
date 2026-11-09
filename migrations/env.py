from alembic import context
from sqlalchemy import create_engine

from config.settings import settings
from utils.store import metadata


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with create_engine(context.config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL).connect() as conn:
        run(conn)
        conn.commit()
