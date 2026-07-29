import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Usando o Pyrogram original
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.errors import FloodWait

# ==========================================
# 1. CONFIGURAÇÃO DE LOGS
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Silenciando os logs para evitar o bloqueio de 500 logs/sec do Railway
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
# Inicializado vazio para não conflitar com o Event Loop do FastAPI
bot = None 

# ==========================================
# 4. HANDLERS (COMANDOS DO BOT)
# ==========================================
async def start_command(client, message):
    logger.info(f"🔥 START ACIONADO por {message.from_user.first_name}")
    await message.reply_text(f"Olá, {message.from_user.first_name}! O bot está online e rodando no Railway com Pyrogram! 🚀")

# Capturador de Diagnóstico: Se ele ignorar o /start, vai cair aqui e logar
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

async def iniciar_pyrogram():
    """Função separada para lidar com o bot sem travar o FastAPI"""
    global bot
    try:
        await bot.start()
        me = await bot.get_me()
        logger.info(f"🤖 Bot @{me.username} Online no Railway!")
    except FloodWait as e:
        logger.warning(f"⚠️ FloodWait detectado. O servidor FastAPI continuará rodando enquanto o bot aguarda {e.value} segundos em background...")
        await asyncio.sleep(e.value)
        await bot.start()
        me = await bot.get_me()
        logger.info(f"🤖 Bot @{me.username} Online após sair do castigo!")
    except Exception as e:
        logger.error(f"💥 Erro ao ligar o bot: {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, bot
    logger.info("🌀 Iniciando infraestrutura do UP CANAIS (Pyrogram)...")
    
    try:
        # 1. CRIAMOS O BOT AQUI DENTRO (No loop correto do FastAPI)
        bot = Client(
            "upcanais_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True 
        )

        # 2. REGISTRAMOS OS HANDLERS
        # A ordem importa: o catch_all (filters.all) deve ser o último
        bot.add_handler(MessageHandler(start_command, filters.command("start")))
        bot.add_handler(MessageHandler(catch_all, filters.all))

        # 3. Conecta ao Banco
        db_pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        await init_db()
        logger.info("🗄️ Banco de dados conectado com sucesso.")
        
        # 4. Liga o Agendador
        scheduler = AsyncIOScheduler()
        scheduler.add_job(deletar_listas_antigas, 'cron', hour=10, minute=0)
        scheduler.start()
        logger.info("⏰ Agendador ativo.")
        
        # 5. Dispara a inicialização do bot em SEGUNDO PLANO
        asyncio.create_task(iniciar_pyrogram())
        
    except Exception as e:
        logger.error(f"💥 ERRO CRÍTICO NA INICIALIZAÇÃO: {type(e).__name__} - {str(e)}")
        if db_pool:
            await db_pool.close()
        raise e

    # Libera o Uvicorn para ligar e passar no teste do Railway
    yield
    
    # 6. Desligamento seguro
    logger.info("🛑 Desligando servidor...")
    try:
        if bot:
            await bot.stop()
    except Exception:
        pass
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
