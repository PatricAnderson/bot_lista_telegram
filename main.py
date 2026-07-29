import os
import logging
from contextlib import asynccontextmanager
import asyncpg
from fastapi import FastAPI
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.enums import ChatMemberStatus

# ==========================================
# 1. CONFIGURAÇÃO DE LOGS
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# 2. VARIÁVEIS DE AMBIENTE (RAILWAY)
# ==========================================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ==========================================
# 3. CONFIGURAÇÃO DO BOT (PYROGRAM)
# ==========================================
if SESSION_STRING:
    bot = Client(
        "bot_up_canais",
        session_string=SESSION_STRING,
        api_id=API_ID,
        api_hash=API_HASH
    )
else:
    bot = Client(
        "bot_up_canais",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True
    )

# Variável global para o pool do banco de dados
db_pool = None

# ==========================================
# 4. HANDLERS DO BOT (COMANDOS E BOTÕES)
# ==========================================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Salva ou atualiza o usuário no banco de dados
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO usuarios (telegram_id, username)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO UPDATE 
            SET username = EXCLUDED.username
        """, user_id, username)

    # Teclado interativo principal
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Adicionar Canal", callback_data="add_canal")],
        [InlineKeyboardButton("💎 VIP", callback_data="vip"), 
         InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
    ])
    
    await message.reply_text(
        "Olá! Bem-vindo ao **UP CANAIS** 🚀\n\n"
        "Aqui você pode promover o seu canal e ganhar mais membros! "
        "Escolha uma das opções abaixo para começar:",
        reply_markup=keyboard
    )


@bot.on_callback_query()
async def callback_handler(client: Client, callback_query):
    data = callback_query.data
    
    if data == "add_canal":
        # Gera o link para o usuário adicionar o bot no canal dele já como admin
        bot_username = client.me.username
        link = f"https://t.me/{bot_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link)],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_menu")]
        ])
        
        await callback_query.message.edit_text(
            "Para adicionar seu canal no sistema, eu preciso ser **Administrador** dele.\n\n"
            "Clique no botão abaixo para me adicionar ao seu canal. Depois, eu te mandarei uma mensagem no privado confirmando o cadastro!",
            reply_markup=keyboard
        )
        
    elif data == "vip":
        await callback_query.answer("Área VIP em construção! 🚧", show_alert=True)
        
    elif data == "conta":
        await callback_query.answer("Sua conta está ativa e registrada no banco!", show_alert=True)
        
    elif data == "voltar_menu":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar Canal", callback_data="add_canal")],
            [InlineKeyboardButton("💎 VIP", callback_data="vip"), 
             InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
        ])
        await callback_query.message.edit_text(
            "Bem-vindo de volta ao menu principal! Escolha uma opção:",
            reply_markup=keyboard
        )


@bot.on_chat_member_updated()
async def bot_added_to_channel(client: Client, update: ChatMemberUpdated):
    # Detecta se o bot foi adicionado a um canal e promovido a administrador
    if update.new_chat_member and update.new_chat_member.user.is_self:
        if update.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
            chat_id = update.chat.id
            chat_title = update.chat.title
            
            # Pega o ID de quem adicionou o bot
            user_id = update.from_user.id if update.from_user else None
            
            if user_id:
                async with db_pool.acquire() as conn:
                    # Registra o canal no banco e vincula ao dono
                    await conn.execute("""
                        INSERT INTO canais (chat_id, titulo, dono_id)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (chat_id) DO UPDATE 
                        SET titulo = EXCLUDED.titulo, dono_id = EXCLUDED.dono_id
                    """, chat_id, chat_title, user_id)
                
                # Avisa o dono no privado que deu tudo certo
                try:
                    await client.send_message(
                        chat_id=user_id,
                        text=f"✅ Sucesso! Eu fui adicionado como administrador no canal **{chat_title}** e ele já está registrado no nosso banco de dados!"
                    )
                except Exception as e:
                    logger.error(f"Não consegui enviar mensagem para o usuário {user_id}: {e}")

# ==========================================
# 5. GERENCIADOR DE CICLO DE VIDA (FASTAPI)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    
    # 1. Inicia conexão com banco de dados
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    logger.info("📦 Pool do PostgreSQL iniciado.")
    
    # 2. Cria as tabelas se for a primeira vez
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                telegram_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                vip BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS canais (
                chat_id BIGINT PRIMARY KEY,
                titulo VARCHAR(255),
                dono_id BIGINT REFERENCES usuarios(telegram_id)
            );
        """)
    logger.info("🗄️ Tabelas do banco de dados verificadas.")

    # 3. Liga o Bot
    await bot.start()
    logger.info(f"🤖 Bot @{bot.me.username} Online e Blindado no Railway!")
    
    # Mantém a aplicação rodando
    yield
    
    # 4. Desliga tudo com segurança
    await bot.stop()
    await db_pool.close()
    logger.info("🛑 Bot e Banco de dados encerrados com segurança.")

# ==========================================
# 6. ROTAS DO FASTAPI (WEBHOOK / HEALTHCHECK)
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "UP CANAIS Bot rodando 100% blindado!"}
