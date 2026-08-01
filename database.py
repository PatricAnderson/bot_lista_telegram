import os
import asyncpg
import logging

# Configuração de Logs
logger = logging.getLogger("database")

class DBPool:
    def __init__(self):
        self.pool = None

    def acquire(self):
        """
        Retorna uma conexão do pool. 
        Uso: async with db_pool.acquire() as conn:
        """
        if not self.pool:
            raise Exception("Pool do banco de dados não inicializado! Verifique o init_db.")
        return self.pool.acquire()
        
    async def close(self):
        """Fecha todas as conexões do pool no desligamento da aplicação."""
        if self.pool:
            await self.pool.close()
            logger.info("🔌 Conexões com o banco de dados encerradas.")

# Instância global para ser importada em outros arquivos (como comandos.py e rotinas.py)
db_pool = DBPool()

async def init_db():
    """Inicializa o pool e estrutura as tabelas essenciais."""
    logger.info("📦 Conectando ao PostgreSQL...")
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("A variável de ambiente DATABASE_URL não foi encontrada.")
            
        # Cria o pool de conexões
        db_pool.pool = await asyncpg.create_pool(db_url)
        
        async with db_pool.acquire() as conn:
            # 1. Cria tabela de usuários se não existir
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    telegram_id BIGINT PRIMARY KEY,
                    username TEXT
                );
            ''')
            
            # 2. Cria tabela de canais se não existir
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS canais (
                    chat_id BIGINT PRIMARY KEY,
                    titulo TEXT,
                    dono_id BIGINT,
                    categoria TEXT,
                    invite_link TEXT,
                    membros INT DEFAULT 0,
                    ativo BOOLEAN DEFAULT TRUE,
                    aprovado BOOLEAN DEFAULT TRUE,
                    semente BOOLEAN DEFAULT FALSE
                );
            ''')
            
            # 3. Cria tabela de links fixos se não existir
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS links_fixos (
                    id SERIAL PRIMARY KEY,
                    titulo TEXT,
                    url TEXT,
                    categoria TEXT
                );
            ''')
            
        logger.info("🗄️ Tabelas estruturadas com sucesso.")
        
    except Exception as e:
        logger.error(f"❌ Erro crítico ao conectar no banco de dados: {e}")
        raise e
