import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pyrogram import Client

# Importando as configurações e módulos
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID
from database import init_db, close_db, db_pool
from rotinas import scheduler, iniciar_agendamentos

# Configuração de Logs (Forçando a exibição imediata, sem buffer)
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("main")

bot = Client(
    "bot_up_canais",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    plugins=dict(root="plugins")
)

# 🛑 INTERCEPTADOR GLOBAL: Captura TUDO antes de ir pros plugins
# O group=-1 força essa função a rodar com prioridade máxima
@bot.on_message(group=-1)
async def interceptar_tudo(client, message):
    user_id = message.from_user.id if message.from_user else "Desconhecido"
    texto = message.text or "[Mídia/Sem Texto]"
    logger.info(f"📩 [DEBUG GLOBAL] Mensagem de {user_id}: {texto}")
    # continue_propagation() é crucial para a mensagem não morrer aqui e seguir para o comandos.py
    message.continue_propagation() 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ==========================================
    # PROCESSO DE INICIALIZAÇÃO
    # ==========================================
    await init_db()
    
    await bot.start()
    bot_info = await bot.get_me()
    logger.info(f"🤖 Bot @{bot_info.username} Online! (Arquitetura Modular)")

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

    # 🔥 TESTE DE FOGO: O bot consegue enviar mensagem?
    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, "🚀 Servidor reiniciado! O bot está operante. Mande um `/start` agora para testar o interceptador.")
            logger.info("✅ Mensagem de teste enviada ao Admin com sucesso!")
        except Exception as e:
            logger.error(f"❌ Falha ao enviar mensagem ao admin. ADMIN_ID ({ADMIN_ID}) está correto? Erro: {e}")

    yield

    # ==========================================
    # PROCESSO DE DESLIGAMENTO
    # ==========================================
    logger.info("🛑 Desligando o sistema...")
    scheduler.shutdown()
    await bot.stop()
    await close_db()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "Bot UP Canais Online e Operacional (Arquitetura Modular)"}
