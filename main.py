import os
import asyncio
import asyncpg
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from pyrogram import Client, filters
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
# 2. INICIALIZAÇÃO DE SERVIÇOS
# ==========================================
# in_memory=True evita que o Railway tente salvar arquivos .session locais (o que gera erros em nuvem)
bot = Client("mega_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
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
            except MessageDeleteForbidden:
                print(f"Sem permissão para deletar no canal {chat_id}")
            except RPCError:
                pass
            await asyncio.sleep(1) # Prevenção anti-flood do Telegram

async def rotina_diaria_listas():
    """Orquestra a limpeza e o disparo da nova lista."""
    print("Iniciando rotina diária...")
    await deletar_listas_antigas()
    # Aqui entrará a lógica de montagem e envio da lista...
    print("Rotina diária finalizada.")

# ==========================================
# 5. HANDLERS DO BOT (PYROGRAM)
# ==========================================
@bot.on_message(filters.command("start") & filters.private)
async def comando_start(client, message):
    bot_info = await client.get_me()
    url_adicionar = f"https://t.me/{bot_info.username}?startchannel=true&admin=post_messages,edit_messages,delete_messages,invite_users"
    
    texto = (
        "👋 **Bem-vindo ao Mega Divulgações!**\n\n"
        "Para incluir seu canal em nossas listas diárias, adicione este bot "
        "ao seu canal como **Administrador**.\n\n"
        "Depois de adicionar, eu chamarei você aqui na DM para configurar."
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Adicionar ao meu Canal", url=url_adicionar)]])
    await message.reply_text(texto, reply_markup=markup)

@bot.on_message(filters.new_chat_members)
async def bot_adicionado_canal(client, message):
    bot_info = await client.get_me()
    
    for membro in message.new_chat_members:
        if membro.id == bot_info.id:
            chat_id = message.chat.id
            nome_canal = message.chat.title
            dono_id = message.from_user.id
            
            # Registra no banco como pendente de categoria
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO canais (chat_id, dono_id, nome_canal, status) 
                    VALUES ($1, $2, $3, 'pendente_categoria')
                    ON CONFLICT (chat_id) DO NOTHING
                """, chat_id, dono_id, nome_canal)
            
            # Envia opções de categoria na DM do dono
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 Filmes e Séries", callback_data=f"cat_filmes_{chat_id}")],
                [InlineKeyboardButton("💻 Tecnologia", callback_data=f"cat_tech_{chat_id}")],
                [InlineKeyboardButton("🔞 NSFW", callback_data=f"cat_nsfw_{chat_id}")]
            ])
            
            await client.send_message(
                chat_id=dono_id,
                text=f"✅ Fui adicionado no canal **{nome_canal}**!\n\nAgora, selecione a categoria correta abaixo:",
                reply_markup=markup
            )

@bot.on_callback_query(filters.regex(r"^cat_"))
async def processar_categoria(client, callback_query):
    dados = callback_query.data.split("_")
    categoria = dados[1]
    chat_id = int(dados[2])
    dono_id = callback_query.from_user.id
    
    # Atualiza a categoria e joga pra quarentena
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE canais SET categoria = $1, status = 'quarentena' WHERE chat_id = $2
        """, categoria, chat_id)
        nome_canal = await conn.fetchval("SELECT nome_canal FROM canais WHERE chat_id = $1", chat_id)
    
    await callback_query.edit_message_text("⏳ Categoria salva! Seu canal foi enviado para moderação. Você será avisado em breve.")
    
    # Notifica o Admin (Você)
    texto_admin = (
        "🚨 **Quarentena: Novo Canal**\n\n"
        f"**Nome:** {nome_canal}\n"
        f"**Categoria:** {categoria}\n"
        f"**ID do Canal:** `{chat_id}`\n"
        f"**Dono ID:** `{dono_id}`\n"
    )
    markup_admin = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_{chat_id}_{dono_id}"),
            InlineKeyboardButton("❌ Rejeitar", callback_data=f"rejeitar_{chat_id}_{dono_id}")
        ]
    ])
    await client.send_message(chat_id=ADMIN_ID, text=texto_admin, reply_markup=markup_admin)

@bot.on_callback_query(filters.regex(r"^(aprovar|rejeitar)_") & filters.user(ADMIN_ID))
async def processar_moderacao(client, callback_query):
    dados = callback_query.data.split("_")
    acao = dados[0]
    chat_id = int(dados[1])
    dono_id = int(dados[2])
    
    async with db_pool.acquire() as conn:
        if acao == "aprovar":
            await conn.execute("UPDATE canais SET status = 'ativo' WHERE chat_id = $1", chat_id)
            await callback_query.edit_message_text(f"✅ Canal `{chat_id}` aprovado.")
            await client.send_message(chat_id=dono_id, text="🎉 **Parabéns!** Seu canal foi aprovado e participará das próximas listas!")
        
        elif acao == "rejeitar":
            await conn.execute("UPDATE canais SET status = 'rejeitado' WHERE chat_id = $1", chat_id)
            await callback_query.edit_message_text(f"❌ Canal `{chat_id}` rejeitado.")
            await client.send_message(chat_id=dono_id, text="⚠️ Seu canal não foi aprovado para as listas no momento.")
            await client.leave_chat(chat_id)

# ==========================================
# 6. FASTAPI LIFESPAN & ROTAS
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    
    # 1. Inicia o Pool do Banco de Dados
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    await init_db()
    
    # 2. Inicia o Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(rotina_diaria_listas, 'cron', hour=10, minute=0) # Altere o horário conforme necessário
    scheduler.start()
    
    # 3. Inicia o Bot no modo Polling em background
    await bot.start()
    print("🚀 Servidor online: API, Scheduler e Bot ativos!")
    
    yield
    
    # Desligamento seguro
    await bot.stop()
    scheduler.shutdown()
    await db_pool.close()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    """Rota para o Railway saber que o app está vivo."""
    return {"status": "online", "service": "Mega SaaS"}

@app.post("/pagamentos/webhook")
async def webhook_pagamento(request: Request):
    """Rota futura para receber webhooks de Mercado Pago, Stripe, etc."""
    dados = await request.json()
    print("Recebido webhook de pagamento:", dados)
    # Lógica de processamento de VIPs entrará aqui...
    return {"status": "recebido"}