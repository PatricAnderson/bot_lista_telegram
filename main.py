import logging

# ==========================================
# RAIO-X: LOGS PROFUNDOS ATIVADOS
# ==========================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("pyrogram").setLevel(logging.DEBUG)

import os
import asyncio
import asyncpg
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageDeleteForbidden, RPCError
from pyrogram.enums import ChatType

# ==========================================
# 1. CONFIGURAÇÃO (Variáveis de Ambiente)
# ==========================================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgres://")

if API_ID == 0 or not API_HASH or not BOT_TOKEN or ADMIN_ID == 0 or not DATABASE_URL:
    print("❌ ERRO CRÍTICO: Faltam variáveis de ambiente essenciais.", flush=True)
    exit(1)

# ==========================================
# 2. INICIALIZAÇÃO DE SERVIÇOS
# ==========================================
# REMOVIDO: in_memory=True
# Agora o bot criará um arquivo up_bot.session físico para não perder a identidade.
bot = Client(
    "up_bot_v2",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    ipv6=False
)

db_pool = None

# ==========================================
# 3. BANCO DE DADOS
# ==========================================
async def init_db():
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
        print("✅ Tabelas do banco de dados garantidas.", flush=True)

# ==========================================
# 4. AGENDAMENTO (Scheduler Jobs)
# ==========================================
async def deletar_listas_antigas():
    print("🗓️ Executando tarefa agendada: Limpeza de listas antigas...", flush=True)
    async with db_pool.acquire() as conn:
        canais = await conn.fetch("SELECT chat_id, last_msg_id FROM canais WHERE last_msg_id IS NOT NULL AND status IN ('ativo', 'vip')")
        for canal in canais:
            chat_id = canal['chat_id']
            msg_id = canal['last_msg_id']
            try:
                await bot.delete_messages(chat_id=chat_id, message_ids=msg_id)
                await conn.execute("UPDATE canais SET last_msg_id = NULL WHERE chat_id = $1", chat_id)
            except Exception:
                pass
            await asyncio.sleep(1)

async def gerar_e_enviar_listas():
    pass

# ==========================================
# 5. HANDLERS DO BOT (Pyrogram)
# ==========================================

# --- COMANDO /START ---
@bot.on_message(filters.command("start") & filters.private)
async def comando_start(client, message):
    print(f"🔥 DEBUG COMANDO: --> RECEBIDO /start de {message.from_user.id}", flush=True)

    bot_info = await client.get_me()
    url_adicionar = f"https://t.me/{bot_info.username}?startchannel=true&admin=post_messages,edit_messages,delete_messages,invite_users"
    
    texto = (
        "👋 **Bem-vindo ao UP CANAIS!**\n\n"
        "Para incluir seu canal em nossas listas diárias, adicione este bot "
        "ao seu canal como **Administrador** clicando no botão abaixo.\n\n"
        "Depois de adicionar, eu chamarei você aqui na DM para configurar."
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Adicionar ao meu Canal", url=url_adicionar)]])
    
    try:
        await message.reply_text(texto, reply_markup=markup)
        print(f"✅ DEBUG COMANDO: Resposta enviada para {message.from_user.id}", flush=True)
    except Exception as e:
        print(f"💥 ERRO AO RESPONDER START: {e}", flush=True)

# --- BOT ADICIONADO AO CANAL ---
@bot.on_message(filters.new_chat_members)
async def bot_adicionado_canal(client, message):
    bot_info = await client.get_me()
    me_joined = any(membro.id == bot_info.id for membro in (message.new_chat_members or []))

    if me_joined and message.chat.type in (ChatType.CHANNEL, ChatType.SUPERGROUP):
        chat_id = message.chat.id
        nome_canal = message.chat.title
        dono_id = message.from_user.id if message.from_user else None
        
        print(f"🤖 Bot adicionado no canal: {nome_canal} ({chat_id})", flush=True)

        if not dono_id:
            return

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO canais (chat_id, dono_id, nome_canal, status) 
                VALUES ($1, $2, $3, 'pendente_categoria')
                ON CONFLICT (chat_id) DO UPDATE SET dono_id = $2, nome_canal = $3, status = 'pendente_categoria';
            """, chat_id, dono_id, nome_canal)
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Filmes e Séries", callback_data=f"cat_filmes_{chat_id}")],
            [InlineKeyboardButton("💻 Tecnologia", callback_data=f"cat_tech_{chat_id}")],
            [InlineKeyboardButton("🔞 NSFW", callback_data=f"cat_nsfw_{chat_id}")]
        ])
        
        try:
            await client.send_message(dono_id, f"✅ Fui adicionado no canal **{nome_canal}**!\n\nAgora, selecione a categoria:", reply_markup=markup)
        except Exception as e:
            print(f"⚠️ Erro DM de categoria para {dono_id}: {e}", flush=True)

# --- ESCOLHA DE CATEGORIA ---
@bot.on_callback_query(filters.regex(r"^cat_"))
async def processar_categoria(client, callback_query):
    dados = callback_query.data.split("_")
    categoria_limpa = dados[1].upper()
    chat_id = int(dados[2])
    dono_id = callback_query.from_user.id
    
    async with db_pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE canais SET categoria = $1, status = 'quarentena' 
            WHERE chat_id = $2 AND dono_id = $3 AND status = 'pendente_categoria';
        """, categoria_limpa, chat_id, dono_id)
        
        if result == "UPDATE 0":
            await callback_query.answer("⚠️ Já configurado ou não pertence a você.")
            return

        row = await conn.fetchrow("SELECT nome_canal FROM canais WHERE chat_id = $1", chat_id)
        nome_canal = row['nome_canal']
    
    await callback_query.edit_message_text(f"✅ Categoria **{categoria_limpa}** salva! Canal enviado para quarentena.")
    
    texto_admin = f"🚨 **QUARENTENA**\n**Canal:** {nome_canal}\n**Cat:** {categoria_limpa}\n**ID:** `{chat_id}`"
    markup_admin = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_{chat_id}_{dono_id}"),
         InlineKeyboardButton("❌ Rejeitar", callback_data=f"rejeitar_{chat_id}_{dono_id}")]
    ])
    
    try:
        await client.send_message(ADMIN_ID, texto_admin, reply_markup=markup_admin)
    except: pass

# --- DECISÃO DE MODERAÇÃO ---
@bot.on_callback_query(filters.regex(r"^(aprovar|rejeitar)_") & filters.user(ADMIN_ID))
async def processar_moderacao(client, callback_query):
    dados = callback_query.data.split("_")
    acao, chat_id, dono_id = dados[0], int(dados[1]), int(dados[2])
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT nome_canal, status FROM canais WHERE chat_id = $1", chat_id)
        if not row or row['status'] != 'quarentena': return
        nome_canal = row['nome_canal']

        if acao == "aprovar":
            await conn.execute("UPDATE canais SET status = 'ativo' WHERE chat_id = $1", chat_id)
            await callback_query.edit_message_text(f"✅ Canal `{chat_id}` APROVADO.")
            try: await client.send_message(dono_id, f"🎉 Canal **{nome_canal}** aprovado!")
            except: pass
        elif acao == "rejeitar":
            await conn.execute("UPDATE canais SET status = 'rejeitado' WHERE chat_id = $1", chat_id)
            await callback_query.edit_message_text(f"❌ Canal `{chat_id}` REJEITADO.")
            try:
                await client.send_message(dono_id, f"⚠️ Canal **{nome_canal}** rejeitado.")
                await client.leave_chat(chat_id)
            except: pass

# --- BLOCO CATA-TUDO (DEBUG) ---
@bot.on_message(filters.private)
async def cata_tudo(client, message):
    print(f"🔥 DEBUG MÁXIMO: Recebi a mensagem: '{message.text}' de ID: {message.from_user.id}", flush=True)
    try:
        await message.reply_text("Estou vivo no Railway! Recebi sua mensagem, mas não é um comando reconhecido. Se quiser iniciar, digite /start")
    except Exception as e:
        print(f"💥 ERRO CATA-TUDO: Não consegui responder: {e}", flush=True)

# ==========================================
# 6. CICLO DE VIDA FASTAPI
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    print("🌀 Iniciando infraestrutura do UP CANAIS...", flush=True)
    
    try:
        db_pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        await init_db()
        
        scheduler = AsyncIOScheduler()
        scheduler.add_job(deletar_listas_antigas, 'cron', hour=10, minute=0)
        scheduler.start()
        print("⏰ Agendador ativo.", flush=True)
        
        await bot.start()
        print(f"🤖 Bot @{(await bot.get_me()).username} Online no Railway (Polling IPv4)!", flush=True)
        print("🚀 Servidor online!", flush=True)
        
    except Exception as e:
        print(f"💥 ERRO CRÍTICO NA INICIALIZAÇÃO: {e}", flush=True)
        if db_pool: await db_pool.close()
        raise e

    yield
    
    print("🛑 Desligando servidor...", flush=True)
    await bot.stop()
    scheduler.shutdown()
    if db_pool: await db_pool.close()
    print("✅ Servidor desligado com segurança.", flush=True)

# ==========================================
# 7. ROTAS FASTAPI
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "online"}
