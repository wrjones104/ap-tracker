import sys
import os

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# --- Robust path setup for both host and container environments ---
root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))
backend_dir = os.path.join(root_dir, 'backend')
if os.path.exists(backend_dir):
    sys.path.insert(0, backend_dir)
sys.path.insert(0, root_dir)
sys.path.insert(0, os.getcwd())

try:
    from app.models import Base
except ModuleNotFoundError:
    from backend.app.models import Base
# -----------------------------------

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
# Skipped when the app runs migrations itself on startup (app/db_migrations.py), where this would
# replace the logging configuration the application has already installed.
if config.config_file_name is not None and config.attributes.get('configure_logger', True):
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# --- NEW: Function to get the correct URL ---
def get_url():
    """
    Returns the database URL.
    Pulls from the DATABASE_URL environment variable if set,
    otherwise, falls back to the alembic.ini file.
    """
    url = os.environ.get('DATABASE_URL')
    if url:
        return url
    
    return config.get_main_option("sqlalchemy.url")
# ---------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    ...
    """
    # --- CHANGED: Use our new get_url() function ---
    url = get_url()
    # ---------------------------------------------
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.
    ...
    """
    
    # --- NEW: Create a config dictionary for engine_from_config ---
    # This allows us to inject our dynamic URL
    
    # 1. Get the plain config section from alembic.ini
    connectable_config = config.get_section(config.config_ini_section, {})
    
    # 2. Get our URL (from env var or .ini file)
    url = get_url()
    
    # 3. Set the URL in our config dictionary
    connectable_config['sqlalchemy.url'] = url
    # -------------------------------------------------------------

    connectable = engine_from_config(
        # --- CHANGED: Pass our new config dict ---
        connectable_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata, 
            # This is important for SQLite migrations
            render_as_batch=True 
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()