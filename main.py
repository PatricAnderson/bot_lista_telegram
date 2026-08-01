import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pyrogram import Client

# Importando as configurações e módulos da nossa arquitetura modular
from config import API_ID, API_HASH, BOT_TOKEN
from database import init_db, close_db, db_pool
from rotinas import scheduler, iniciar_agendamentos

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# Inicializando o Bot do Pyrogram com a pasta "plugins" (Smart Plugins)
bot = Client(
    "bot_up_canais",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ==========================================
    # PROCESSO DE INICIALIZAÇÃO (STARTUP)
    # ==========================================
    
    # 1. Inicia o Pool de conexões do Banco de Dados
    await init_db()
    
    # 2. Inicia o Bot do Pyrogram
    await bot.start()
    bot_info = await bot.get_me()
    logger.info(f"🤖 Bot @{bot_info.username} Online! (Arquitetura Modular)")

    # 3. Proteção contra PeerIdInvalid (Reconstrução de Cache Inteligente via DB)
    logger.info("🔄 Reconstruindo cache de canais na memória via Banco de Dados...")
    try:
        async with db_pool.acquire() as conn:
            # Pega apenas os canais reais e ativos para colocar no cache
            canais_reais = await conn.fetch("SELECT chat_id FROM canais WHERE ativo = TRUE AND semente = FALSE")
            sucessos = 0
            for c in canais_reais:
                try:
                    await bot.get_chat(c['chat_id'])
                    sucessos += 1
                except Exception:
                    pass # Se der erro em um (ex: bot foi expulso), apenas ignora e segue pro próximo
                    
        logger.info(f"✅ Cache reconstruído! {sucessos} canais validados na memória.")
    except Exception as e:
        logger.warning(f"⚠️ Erro ao acessar o banco para o cache: {e}")

    # 4. Inicia as rotinas automáticas (APScheduler)
    iniciar_agendamentos() # Certifique-se de que sua função no rotinas.py se chama assim
    scheduler.start()
    logger.info("⏰ Cronograma ativado.")

    yield # Aqui o servidor FastAPI assume e fica rodando

    # ==========================================
    # PROCESSO DE DESLIGAMENTO (SHUTDOWN)
    # ==========================================
    logger.info("🛑 Desligando o sistema...")
    scheduler.shutdown()
    await bot.stop()
    await close_db()


# Inicializando o aplicativo Web FastAPI (Essencial para a porta do Railway)
app = FastAPI(lifespan=lifespan)

# Rota simples de verificação de status para o servidor
@app.get("/")
async def health_check():
    return {"status": "Bot UP Canais Online e Operacional (Arquitetura Modular)"}
