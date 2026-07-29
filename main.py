import os
import asyncio
import asyncpg
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageDeleteForbidden, RPCError

# ==========================================
# 1. VARIÁVEIS DE AMBIENTE
# ==========================================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# O Railway fornece o DATABASE_URL automaticamente.
# O asyncpg exige que o prefixo seja postgres:// em vez de postgresql:// (se aplicável).
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgres://")

# ==========================================
# 2. INICIALIZAÇÃO DO CLIENTE (BOT)
# ==========================================
# Forçamos IPv4 para evitar problemas de rede comuns no Railway
bot = Client(
    "mega_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True, # Vital para rodar em nuvem sem persistência de arquivo de sessão
    ipv6=False       
)

db_pool = None

# ==========================================
# 3. FUNÇÕES DE BANCO DE DADOS
# ==========================================
async def init_db():
    """Cria as tabelas caso não existam no PostgreSQL."""
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS canais (
                chat_id BIGINT PRIMARY KEY,
                dono_id BIGINT,
                nome_canal TEXT,
                categoria TEXT,
                status TEXT DEFAULT 'pendente_categoria',
                last_msg_id BIGINT
            );
        """)
        print("✅ Banco de dados inicializado.")

# ==========================================
# 4. ROTINAS DE AGENDAMENTO (SCHEDULER)
# ==========================================
async def deletar_listas_antigas():
    """Busca listas antigas e deleta para manter o canal limpo."""
    async with db_pool.acquire() as conn:
        canais = await conn.fetch("SELECT chat_id, last_msg_id FROM canais WHERE last_msg_id IS NOT NULL")
        
        for canal in canais:
            chat_id = canal['chat_id']
            msg_id = canal['last_msg_id']
            try:
                await bot.delete_messages(chat_id=chat_id, message_ids=msg_id)
                await conn.execute("UPDATE canais SET last_msg_id = NULL WHERE chat_id = $1", chat_id)
                print(f"🗑️ Lista antiga deletada no canal {chat_id}")
            except MessageDeleteForbidden:
                print(f"⚠️ Sem permissão para deletar no canal {chat_id}")
            except RPCError as e:
                print(f"⚠️ Erro ao deletar no canal {chat_id}: {e}")
            await asyncio.sleep(1) # Prevenção anti-flood do Telegram

async def rotina_diaria_listas():
    """Orquestra a limpeza e o disparo da nova lista."""
    print("🌅 Iniciando rotina diária de listas...")
    await deletar_listas_antigas()
    # A lógica de envio virá aqui...
    print("✅ Rotina diária finalizada.")

# ==========================================
# 5. HANDLERS DO BOT (PYROGRAM)
# ==========================================
# Removi filtros complexos para garantir que responda
@bot.on_message(filters.command("start") & filters.private)
async def comando_start(client, message):
    print(f"📩 Recebido /start de {message.from_user.id}")
    
    bot_info = await client.get_me()
    url_adicionar = f"https://t.me/{bot_info.username}?startchannel=true&admin=post_messages,edit_messages,delete_messages,invite_users"
    
    texto = (
        "👋 **Bem-vindo ao UP CANAIS!**\n\n"
        "Para incluir seu canal em nossas listas diárias, adicione este bot "
        "ao seu canal como **Administrador**.\n\n"
        "Depois de adicionar, eu chamarei você aqui na DM para configurar."
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Adicionar ao meu Canal", url=url_adicionar)]])
    await message.reply_text(texto, reply_markup=markup)

# Mantemos os outros handlers (new_chat_members, callback_query) iguais abaixo...
# ... (Para economizar espaço, pulei a repetição, mas garanta que eles estejam no seu arquivo final)
# ... Handler de bot_adicionado_canal, processar_categoria, processar_moderacao ...

# ==========================================
# 6. FASTAPI LIFESPAN & ENGINE (AJUSTADO)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    print("🌀 Iniciando aplicação FastAPI...")
    
    try:
        # 1. Inicia o Pool do Banco de Dados
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        await init_db()
        
        # 2. Inicia o Scheduler
        scheduler = AsyncIOScheduler()
        # Horário do disparo (ex: 10:00 da manhã)
        scheduler.add_job(rotina_diaria_listas, 'cron', hour=10, minute=0)
        scheduler.start()
        print("⏰ Scheduler ativo.")
        
        # 3. NOVO AJUSTE: Inicia o Bot corretamente
        # Conecta o bot
        await bot.start()
        
        # Cria uma tarefa em background para rodar o loop de updates do bot (polling)
        # Isso garante que ele não trave o FastAPI e continue escutando mensagens.
        app.state.bot_updater = asyncio.create_task(idle())
        
        print(f"🤖 Bot @{(await bot.get_me()).username} Ativo e Escutando (Polling)!")
        print("🚀 Infraestrutura completa online no Railway!")
        
    except Exception as e:
        print(f"💥 ERRO CRÍTICO NA INICIALIZAÇÃO: {e}")
        # Tenta fechar o pool se ele já tiver sido criado antes do erro
        if db_pool:
            await db_pool.close()
        raise e

    yield
    
    # Desligamento seguro (Graceful Shutdown)
    print("🛑 Desligando aplicação...")
    
    # Cancela a tarefa de polling do bot
    if hasattr(app.state, 'bot_updater'):
        app.state.bot_updater.cancel()
        try:
            await app.state.bot_updater
        except asyncio.CancelledError:
            pass
            
    await bot.stop()
    scheduler.shutdown()
    
    if db_pool:
        await db_pool.close()
    print("✅ Aplicação desligada com segurança.")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    """Rota pública para o Railway saber que o app está vivo."""
    return {"status": "online", "service": "UP CANAIS Engine"}

@app.post("/pagamentos/webhook")
async def webhook_pagamento(request: Request):
    """Rota futura para receber webhooks de pagamentos."""
    # (Lógica de processamento de VIPs entrará aqui...)
    return {"status": "recebido"}
