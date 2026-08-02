import logging
import requests
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pyrogram import Client

from config import API_ID, API_HASH, BOT_TOKEN
from database import init_db
from rotinas import iniciar_agendamentos, scheduler

# ==========================================
# CONFIGURAÇÃO DE LOGS
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger("main")

# ==========================================
# PYROGRAM RAIZ (Forçando Memória RAM)
# ==========================================
bot = Client(
    "bot_up_canais",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,  # Impede que o Railway puxe um arquivo .session sujo do cache
    plugins=dict(root="plugins")
)

# ==========================================
# RADAR DE MENSAGENS (Isolado de Filtros)
# ==========================================
@bot.on_message(group=-1)
async def radar_de_mensagens(client, message):
    # Captura quem enviou (pode vir de usuário ou canal)
    remetente = message.from_user.id if message.from_user else "Desconhecido/Canal"
    
    # Tenta extrair texto da mensagem (texto puro ou legenda de mídia)
    texto = message.text or message.caption or "Mídia/Ação do Sistema"
    
    logger.info(f"🚨 RADAR ATIVADO: Recebi requisição de {remetente} -> {texto}")

# ==========================================
# CICLO DE VIDA FASTAPI E DESOBSTRUÇÃO
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("📦 Inicializando banco de dados...")
    await init_db()

    # Aplica um "Hard Reset" na comunicação do Telegram antes do bot ligar
    logger.info("🧹 Forçando limpeza de Webhooks e limpando fila presa...")
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"
        r = requests.get(url)
        logger.info(f"Resposta da limpeza do Telegram: {r.json()}")
    except Exception as e:
        logger.error(f"Erro ao limpar webhook via API oficial: {e}")

    logger.info("🚀 Iniciando cliente do Pyrogram (Polling puro)...")
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

    logger.info("🛑 Desligando serviços e fechando conexões...")
    scheduler.shutdown()
    await bot.stop()

# ==========================================
# INICIALIZAÇÃO FASTAPI
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "online", "message": "Bot UP Canais rodando"}
