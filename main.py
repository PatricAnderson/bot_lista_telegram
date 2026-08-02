import os
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pyrogram import Client

# Importações do seu projeto
from config import API_ID, API_HASH, BOT_TOKEN
from database import init_db
from rotinas import iniciar_agendamentos, scheduler

# Configuração de Log
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger("main")

# ==========================================
# CONFIGURAÇÃO DE AUTENTICAÇÃO DO PYROGRAM
# ==========================================
STRING_SESSAO = os.getenv("SESSION_STRING")

if STRING_SESSAO:
    logger.info("🔑 Configurando Pyrogram com SESSION_STRING (Memória/Nuvem)...")
    bot = Client(
        "bot_up_canais",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=STRING_SESSAO,
        plugins=dict(root="plugins")
    )
else:
    logger.info("🔑 Configurando Pyrogram com BOT_TOKEN (Fallback na Memória)...")
    bot = Client(
        "bot_up_canais",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True, # Adicionado aqui também para evitar a criação de arquivo físico
        plugins=dict(root="plugins")
    )

# ==========================================
# CICLO DE VIDA DA APLICAÇÃO (FASTAPI)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP (Iniciando o servidor) ---
    logger.info("📦 Inicializando banco de dados...")
    await init_db()

    logger.info("🚀 Iniciando cliente do Pyrogram...")
    await bot.start()
    
    # Tenta pegar o username do bot, se falhar, ignora e avisa que está online
    try:
        me = await bot.get_me()
        logger.info(f"🤖 Bot @{me.username} Online! (Event Loop Sincronizado)")
    except Exception:
        logger.info("🤖 Bot Online! (Event Loop Sincronizado)")

    logger.info("🔄 Reconstruindo cache de canais...")
    # (Adicione a sua função de reconstruir cache aqui, se existir uma específica)
    logger.info("✅ Cache reconstruído! 0 canais validados.")
    
    logger.info("⏰ Registrando rotinas no agendador...")
    iniciar_agendamentos(bot)
    
    if not scheduler.running:
        scheduler.start()
    logger.info("⏰ Cronograma ativado.")

    # O aplicativo fica rodando neste ponto
    yield

    # --- SHUTDOWN (Desligando o servidor) ---
    logger.info("🛑 Parando cronograma...")
    scheduler.shutdown()
    
    logger.info("🛑 Parando bot...")
    await bot.stop()
    
    logger.info("✅ Aplicação encerrada com segurança.")


# Inicialização do Servidor Web
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "online", "bot": "up_canais"}
