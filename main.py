import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram.errors import FloodWait

# ==========================================
# 1. CONFIGURAÇÃO DE LOGS E VARIÁVEIS
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

db_pool = None

# ==========================================
# 2. INICIALIZAÇÃO DO HYDROGRAM (MODO BOT)
# ==========================================
bot = Client(
    name="up_bot_v2",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    ipv6=False,
    in_memory=True
)

# ==========================================
# 3. ROTINAS DE BANCO DE DADOS E TAREFAS
# ==========================================
async def init_db():
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                command TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

async def deletar_listas_antigas():
    logger.info("Executando limpeza diária de registros antigos...")

# ==========================================
# 4. HANDLERS / EVENTOS DO TELEGRAM
# ==========================================
@bot.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    logger.info(f"🔥 START ACIONADO por {message.from_user.id if message.from_user else 'Desconhecido'}")
    await message.reply_text("👋 Olá! O bot **UP CANAIS** está online, conectado e operando com sucesso no Railway!")

@bot.on_message()
async def cata_tudo(client: Client, message: Message):
    logger.info(f"🔥 CATA-TUDO ACIONADO | Mensagem de {message.chat.id}: {message.text}")

# ==========================================
# 5. CICLO DE VIDA FASTAPI (LIFESPAN)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    logger.info("🌀 Iniciando infraestrutura do UP CANAIS...")
    
    try:
        db_pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        await init_db()
        logger.info("🗄️ Banco de dados conectado com sucesso.")
        
        scheduler = AsyncIOScheduler()
        scheduler.add_job(deletar_listas_antigas, 'cron', hour=10, minute=0)
        scheduler.start()
        logger.info("⏰ Agendador ativo.")
        
        try:
            await bot.start()
            if not bot.dispatcher.started:
                await bot.dispatcher.start()
            me = await bot.get_me()
            logger.info(f"🤖 Bot @{me.username} Online no Railway!")
        except FloodWait as e:
            logger.warning(f"⚠️ FloodWait detectado pelo Telegram. O bot vai aguardar {e.value} segundos...")
            await asyncio.sleep(e.value)
            await bot.start()
            if not bot.dispatcher.started:
                await bot.dispatcher.start()
            me = await bot.get_me()
            logger.info(f"🤖 Bot @{me.username} Online no Railway após espera!")
        
    except Exception as e:
        logger.error(f"💥 ERRO CRÍTICO NA INICIALIZAÇÃO: {e}")
        if db_pool:
            await db_pool.close()
        raise e

    yield
    
    logger.info("🛑 Desligando servidor...")
    try:
        if bot.dispatcher.started:
            await bot.dispatcher.stop()
        await bot.stop()
    except Exception:
        pass
    scheduler.shutdown()
    if db_pool:
        await db_pool.close()
    logger.info("✅ Servidor desligado com segurança.")

# ==========================================
# 6. APLICAÇÃO FASTAPI
# ==========================================
app = FastAPI(title="UP CANAIS Bot API", lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "online", "bot": "upacanais_bot"}
