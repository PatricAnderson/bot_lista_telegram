import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pyrogram import Client

from config import API_ID, API_HASH, BOT_TOKEN
from database import init_db
from rotinas import iniciar_agendamentos, scheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger("main")

# ==========================================
# PYROGRAM RAIZ (Sem in_memory, sem Session String)
# ==========================================
bot = Client(
    "bot_up_canais",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

# ==========================================
# CICLO DE VIDA FASTAPI
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("📦 Inicializando banco de dados...")
    await init_db()

    logger.info("🚀 Iniciando cliente do Pyrogram (Padrão)...")
    await bot.start()
    
    try:
        me = await bot.get_me()
        logger.info(f"🤖 Bot @{me.username} Online e Escutando!")
    except Exception:
        logger.info("🤖 Bot Online e Escutando!")

    logger.info("⏰ Registrando rotinas no agendador...")
    iniciar_agendamentos(bot)
    
    if not scheduler.running:
        scheduler.start()

    # Mantém a aplicação rodando
    yield

    logger.info("🛑 Desligando serviços...")
    scheduler.shutdown()
    await bot.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "online"}
