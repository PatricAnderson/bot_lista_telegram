import asyncpg
import logging
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Variável global que guardará a conexão
db_pool = None

async def iniciar_banco():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    logger.info("📦 Pool do PostgreSQL iniciado.")
    
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    telegram_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    vip BOOLEAN DEFAULT FALSE
                );
                
                CREATE TABLE IF NOT EXISTS canais (
                    chat_id BIGINT PRIMARY KEY,
                    titulo VARCHAR(255),
                    dono_id BIGINT,
                    categoria VARCHAR(100),
                    invite_link TEXT,
                    membros INT DEFAULT 0,
                    vip BOOLEAN DEFAULT FALSE,
                    ativo BOOLEAN DEFAULT TRUE,
                    aprovado BOOLEAN DEFAULT FALSE,
                    ultima_mensagem_id BIGINT,
                    semente BOOLEAN DEFAULT FALSE
                );
                
                -- Alterações de segurança para garantir colunas em bancos existentes
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS invite_link TEXT;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS membros INT DEFAULT 0;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS categoria VARCHAR(100);
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS vip BOOLEAN DEFAULT FALSE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS aprovado BOOLEAN DEFAULT FALSE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS ultima_mensagem_id BIGINT;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS semente BOOLEAN DEFAULT FALSE;

                CREATE TABLE IF NOT EXISTS links_fixos (
                    id SERIAL PRIMARY KEY,
                    titulo VARCHAR(255),
                    url TEXT,
                    categoria VARCHAR(100)
                );
            """)
    logger.info("🗄️ Tabelas estruturadas com sucesso.")