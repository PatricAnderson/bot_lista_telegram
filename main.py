import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pyrogram import Client
from pyrogram.handlers import MessageHandler

# Importando as configurações e módulos
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID
from database import init_db, close_db, db_pool
from rotinas import scheduler, iniciar_agendamentos

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("main")

# Interceptador para logs globais
async def interceptar_tudo(client, message):
    user_id = message.from_user.id if message.from_user else "Desconhecido"
    texto = message.text or "[Mídia/Sem Texto]"
    logger.info(f"📩 [DEBUG GLOBAL] Mensagem de {user_id}: {texto}")
    message.continue_propagation()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ==========================================
    # 1. A MÁGICA: O Client é criado DENTRO da esteira do Uvicorn!
    # ==========================================
    bot = Client(
        "bot_up_canais",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True,
        plugins=dict(root="plugins")
    )
    
    # Adicionamos o nosso interceptador ao bot recém-criado
    bot.add_handler(MessageHandler(interceptar_tudo), group=-1)

    # 2. Inicia o Banco de Dados
    await init_db()
    
    # 3. Inicia o Bot (agora escutando na frequência correta)
    await bot.start()
    bot_info = await bot.get_me()
    logger.info(f"🤖 Bot @{bot_info.username} Online! (Event Loop Sincronizado)")

    logger.info("🔄 Reconstruindo cache de canais...")
    try:
        async with db_pool.acquire() as conn:
            canais_reais = await conn.fetch("SELECT chat_id FROM canais WHERE ativo = TRUE AND semente = FALSE")
            sucessos = 0
            for c in canais_reais:
                try:
                    await bot.get_chat(c['chat_id'])
                    sucessos += 1
                except Exception:
                    pass
        logger.info(f"✅ Cache reconstruído! {sucessos} canais validados.")
    except Exception as e:
        logger.warning(f"⚠️ Erro ao acessar o banco para o cache: {e}")

    iniciar_agendamentos()
    scheduler.start()
    logger.info("⏰ Cronograma ativado.")

    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, "🚀 Servidor reiniciado e Event Loop corrigido! O bot já está ouvindo as mensagens.")
        except Exception as e:
            logger.error(f"Erro ao enviar aviso: {e}")

    yield # Aqui o servidor FastAPI assume

    # ==========================================
    # PROCESSO DE DESLIGAMENTO
    # ==========================================
    logger.info("🛑 Desligando o sistema...")
    scheduler.shutdown()
    await bot.stop()
    await close_db()

# Inicializando o app
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "Bot UP Canais Online e Operacional"}
