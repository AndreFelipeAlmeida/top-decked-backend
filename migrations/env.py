import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Garante que `app` seja importável independente de onde o comando `alembic`
# for chamado (normalmente já é o caso, já que alembic.ini vive na raiz do
# projeto, mas isso protege contra invocações de outro diretório).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importa TODOS os models — é essa importação que registra cada `table=True`
# em `SQLModel.metadata`; sem isso, `target_metadata` ficaria vazio e o
# autogenerate nunca detectaria nenhuma tabela.
from sqlmodel import SQLModel
import app.models  # noqa: F401
from app.core.config import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Fonte de verdade da URL do banco é `app.core.config.settings` (lê de
# `.env`/variáveis de ambiente) — não duplicamos a URL no `alembic.ini` pra
# não ter duas fontes de configuração podendo divergir (dev usa SQLite, prod
# usa Postgres, ambos resolvidos pelo mesmo `Settings` que a aplicação usa).
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite não suporta ALTER TABLE de verdade (não dá pra adicionar
        # FK/alterar coluna direto) — "batch mode" recria a tabela por trás
        # dos panos pra simular isso. Sem custo em Postgres (só sqlite usa).
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
