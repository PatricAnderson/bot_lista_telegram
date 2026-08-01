import os
import asyncpg
import logging

# Configuração de Logs
logger = logging.getLogger("database")

# Classe para gerenciar o Pool globalmente e permitir o uso de "async with db_pool.acquire()"
class Database:
    def __init__(self):
        self.pool = None

    def acquire(self):
        return self.pool.acquire()

db_pool = Database()

async def init_db():
    logger.info("📦 Conectando ao PostgreSQL...")
    try:
        # Puxa a URL do banco diretamente das variáveis do Railway
        db_url = os.getenv("DATABASE_URL") 
        
        # Cria o pool de conexões
        db_pool.pool = await asyncpg.create_pool(db_url)
        
        # Garante que as tabelas essenciais existem
        async with db_pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS canais (
                    chat_id BIGINT PRIMARY KEY,
                    ativo BOOLEAN DEFAULT TRUE,
                    semente BOOLEAN DEFAULT FALSE
                );
            ''')
        logger.info("🗄️ Tabelas estruturadas com sucesso.")
        
    except Exception as e:
        logger.error(f"❌ Erro crítico ao conectar no banco de dados: {e}")

async def close_db():
    if db_pool.pool:
        logger.info("🛑 Fechando pool de conexões do PostgreSQL...")
        await db_pool.pool.close()
