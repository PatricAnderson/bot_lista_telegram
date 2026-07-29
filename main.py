import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Voltando para o Pyrogram original
from pyrogram import Client, filters
from pyrogram.errors import FloodWait

# ==========================================
# 1. CONFIGURAÇÃO DE LOGS
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Silenciando os logs do Pyrogram para evitar o bloqueio de 500 logs/sec do Railway
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("asyncpg").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# ==========================================
# 2. VARIÁVEIS DE AMBIENTE
# ==========================================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

db_pool = None

# ==========================================
# 3. INICIALIZAÇÃO DO BOT (PYROGRAM)
# ==========================================
bot = Client(
    "upcanais_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True  # Mantém a sessão na RAM para não travar o disco do Railway
)

# ==========================================
# 4. HANDLERS (COMANDOS DO BOT)
# ==========================================
@bot.on_message(filters.command("start"))
async def start_command(client, message):
    logger.info(f"🔥 START ACIONADO por {message.from_user.first_name}")
    await message.reply_text(f"Olá, {message.from_user.first_name}! O bot está online e rodando no Railway com Pyrogram! 🚀")

# Capturador de Diagnóstico: Se ele ignorar o /start, vai cair aqui e logar
@bot.on_message(filters.all)
async def catch_all(client, message):
    logger.warning(f"👀 MENSAGEM RECEBIDA de {message.from_user.first_name}: {message.text}")

# ==========================================
# 5. FUNÇÕES DO BANCO E SCHEDULER
# ==========================================
async def init_db():
    # Lógica de criação de tabelas
    pass

async def deletar_listas_antigas():
    logger.info("🧹 Limpando listas antigas...")
    pass

# ==========================================
# 6. LIFESPAN (CICLO DE VIDA DA APLICAÇÃO)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    logger.info("🌀 Iniciando infraestrutura do UP CANAIS (Pyrogram)...")
    
    try:
        # 1. Conecta ao Banco
        db_pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        await init_db()
        logger.info("🗄️ Banco de dados conectado com sucesso.")
        
        # 2. Liga o Agendador
        scheduler = AsyncIOScheduler()
        scheduler.add_job(deletar_listas_antigas, 'cron', hour=10, minute=0)
        scheduler.start()
        logger.info("⏰ Agendador ativo.")
        
        # 3. Liga o Bot
        try:
            await bot.start()
            me = await bot.get_me()
            logger.info(f"🤖 Bot @{me.username} Online no Railway!")
        except FloodWait as e:
            logger.warning(f"⚠️ FloodWait. Aguardando {e.value} segundos...")
            await asyncio.sleep(e.value)
            await bot.start()
            me = await bot.get_me()
            logger.info(f"🤖 Bot @{me.username} Online no Railway após espera!")
        
    except Exception as e:
        logger.error(f"💥 ERRO CRÍTICO NA INICIALIZAÇÃO: {type(e).__name__} - {str(e)}")
        if db_pool:
            await db_pool.close()
        raise e

    yield
    
    # 4. Desligamento seguro
    logger.info("🛑 Desligando servidor...")
    try:
        await bot.stop()
    except Exception:
        pass
    scheduler.shutdown()
    if db_pool:
        await db_pool.close()
    logger.info("✅ Servidor desligado com segurança.")

# ==========================================
# 7. FASTAPI APP
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "online", "bot": "UP CANAIS", "lib": "Pyrogram"}
