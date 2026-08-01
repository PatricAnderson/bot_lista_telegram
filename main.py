import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pyrogram import Client
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from config import API_ID, API_HASH, BOT_TOKEN, SESSION_STRING
from database import iniciar_banco, db_pool
from rotinas import disparar_troca_por_categoria, monitorar_membros_semanal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = None
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    
    # 1. Inicia Banco de Dados
    await iniciar_banco()
    
    # 2. Configura o Pyrogram para ler a pasta "plugins"
    plugins = dict(root="plugins") 
    
    if SESSION_STRING:
        bot = Client("bot_up_canais", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH, plugins=plugins)
    else:
        bot = Client("bot_up_canais", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True, plugins=plugins)

    await bot.start()
    logger.info(f"🤖 Bot @{bot.me.username} Online! (Arquitetura Modular)")

    # 3. Proteção contra PeerIdInvalid (Reconstrução de Cache)
    logger.info("🔄 Reconstruindo cache de canais na memória...")
    try:
        async for dialog in bot.get_dialogs(): pass
        logger.info("✅ Cache reconstruído com sucesso!")
    except Exception as e:
        logger.warning(f"⚠️ Erro no cache: {e}")

    # 4. Inicia o Agendador (Passando o bot como argumento)
    fuso = ZoneInfo("America/Sao_Paulo")
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=14, minute=0, timezone=fuso), args=[bot])
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=21, minute=0, timezone=fuso), args=[bot])
    scheduler.add_job(monitorar_membros_semanal, CronTrigger(day_of_week='sun', hour=3, minute=0, timezone=fuso), args=[bot])
    
    scheduler.start()
    logger.info("⏰ Cronograma ativado.")
    
    yield
    
    # 5. Desligamento Seguro
    scheduler.shutdown()
    await bot.stop()
    if db_pool:
        await db_pool.close()

# 6. O Servidor FastAPI
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "UP CANAIS - Sistema Modular Rodando 100%!"}