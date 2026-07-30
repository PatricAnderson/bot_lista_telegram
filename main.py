import os
import logging
from contextlib import asynccontextmanager
import asyncpg
from fastapi import FastAPI
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.enums import ChatMemberStatus
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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

# Variáveis globais
db_pool = None
bot = None
scheduler = AsyncIOScheduler()

# ==========================================
# 3. FUNÇÃO DE DISPARO DA TROCA DE DIVULGAÇÃO POR CATEGORIA
# ==========================================
async def disparar_troca_por_categoria():
    if not bot:
        logger.error("Bot não inicializado para o disparo.")
        return

    try:
        async with db_pool.acquire() as conn:
            # Busca todas as categorias ativas que possuem canais cadastrados
            categorias = await conn.fetch("SELECT DISTINCT categoria FROM canais WHERE ativo = TRUE")

            for cat_row in categorias:
                categoria = cat_row['categoria']

                # 1. Busca 4 VIPs da categoria (ou rotação geral se preferir)
                vips = await conn.fetch(
                    "SELECT titulo, invite_link FROM canais WHERE categoria = $1 AND vip = TRUE AND ativo = TRUE LIMIT 4", 
                    categoria
                )
                
                # 2. Busca 14 canais normais da categoria (embaralhados)
                normais = await conn.fetch(
                    "SELECT titulo, invite_link FROM canais WHERE categoria = $1 AND vip = FALSE AND ativo = TRUE ORDER BY RANDOM() LIMIT 14", 
                    categoria
                )

                # 3. Busca os links fixos do dono para esta categoria específica
                links_fixos = await conn.fetch(
                    "SELECT titulo, url FROM links_fixos WHERE categoria = $1", 
                    categoria
                )

                # 4. Pega todos os canais que devem RECEBER a lista nesta categoria
                destinos = await conn.fetch("SELECT chat_id FROM canais WHERE categoria = $1 AND ativo = TRUE", categoria)

                if not destinos:
                    continue

                # Montagem da Lista
                texto_lista = f"🔥 **LISTA DE DIVULGAÇÃO - {categoria.upper()}** 🔥\n\n"
                
                if vips:
                    texto_lista += "💎 **DESTAQUES VIP** 💎\n"
                    for v in vips:
                        link = v['invite_link'] or "https://t.me/"
                        texto_lista += f"• [{v['titulo']}]({link})\n"
                    texto_lista += "\n"

                if links_fixos:
                    texto_lista += "⭐ **NOSSAS REDES / INDICADOS** ⭐\n"
                    for lf in links_fixos:
                        texto_lista += f"• [{lf['titulo']}]({lf['url']})\n"
                    texto_lista += "\n"

                if normais:
                    texto_lista += "🚀 **CANAIS PARCEIROS** 🚀\n"
                    for n in normais:
                        link = n['invite_link'] or "https://t.me/"
                        texto_lista += f"• [{n['titulo']}]({link})\n"
                
                texto_lista += "\n👇 *Quer seu canal na próxima lista? Clique abaixo!*"

                bot_username = bot.me.username
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 Cadastrar Meu Canal Grátis", url=f"https://t.me/{bot_username}?start=start")]
                ])

                # Dispara a lista para cada canal participante da categoria
                for dest in destinos:
                    try:
                        await bot.send_message(
                            chat_id=dest['chat_id'],
                            text=texto_lista,
                            reply_markup=keyboard,
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        logger.error(f"Erro ao enviar lista para o canal {dest['chat_id']}: {e}")

        logger.info("✅ Ciclo de troca de divulgação por categorias concluído com sucesso!")

    except Exception as e:
        logger.error(f"❌ Erro no agendador de listas: {e}")

# ==========================================
# 4. CICLO DE VIDA DO FASTAPI E BOT
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, bot
    
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    logger.info("📦 Pool do PostgreSQL iniciado.")
    
    # Criação segura das tabelas com suporte a categorias, links fixos e controle de status
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    telegram_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    vip BOOLEAN DEFAULT FALSE
                );
                CREATE TABLE IF NOT EXISTS canais (
                    chat_id BIGINT PRIMARY KEY,
                    titulo VARCHAR(255),
                    dono_id BIGINT,
                    categoria VARCHAR(100),
                    invite_link TEXT,
                    membros INT DEFAULT 0,
                    vip BOOLEAN DEFAULT FALSE,
                    ativo BOOLEAN DEFAULT TRUE
                );
                CREATE TABLE IF NOT EXISTS links_fixos (
                    id SERIAL PRIMARY KEY,
                    titulo VARCHAR(255),
                    url TEXT,
                    categoria VARCHAR(100)
                );
            """)
    logger.info("🗄️ Tabelas estruturadas com sucesso.")

    if SESSION_STRING:
        bot = Client("bot_up_canais", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
    else:
        bot = Client("bot_up_canais", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

    # Handler /start e Seleção de Categoria
    @bot.on_message(filters.command("start") & filters.private)
    async def start_command(client: Client, message):
        user_id = message.from_user.id
        username = message.from_user.username
        
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO usuarios (telegram_id, username) VALUES ($1, $2)
                ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username
            """, user_id, username)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar Canal", callback_data="add_canal")],
            [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
        ])
        await message.reply_text(
            "👋 **Bem-vindo ao UP CANAIS!**\n\n"
            "O sistema oficial de troca de divulgação inteligente do Telegram.\n"
            "Escolha uma opção abaixo:",
            reply_markup=keyboard
        )

    @bot.on_callback_query()
    async def callback_handler(client: Client, callback_query):
        data = callback_query.data
        
        if data == "add_canal":
            # Exibe as categorias permitidas por botões inline (Evita erros de digitação)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎬 Filmes & Séries", callback_data="cat_filmes")],
                [InlineKeyboardButton("🔞 Adulto / NSFW", callback_data="cat_adulto")],
                [InlineKeyboardButton("💻 Tecnologia & Games", callback_data="cat_tech")],
                [InlineKeyboardButton("📢 Notícias & Utilidades", callback_data="cat_noticias")],
                [InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_menu")]
            ])
            await callback_query.message.edit_text(
                "📁 **Selecione a Categoria do seu Canal:**\n\n"
                "Isso garante que seu link só aparecerá no nicho correto.",
                reply_markup=keyboard
            )
            
        elif data.startswith("cat_"):
            categoria = data.replace("cat_", "")
            b_username = client.me.username
            # Link com permissões necessárias exigidas
            link = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link)],
                [InlineKeyboardButton("⬅️ Escolher Outra Categoria", callback_data="add_canal")]
            ])
            await callback_query.message.edit_text(
                f"✅ Categoria selecionada: **{categoria.upper()}**\n\n"
                "Agora clique no botão abaixo para adicionar o bot como administrador no seu canal com todas as permissões necessárias:",
                reply_markup=keyboard
            )
            
        elif data == "conta":
            await callback_query.answer("Sua conta está ativa na nossa rede!", show_alert=True)
            
        elif data == "voltar_menu":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Adicionar Canal", callback_data="add_canal")],
                [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
            ])
            await callback_query.message.edit_text("Menu principal:", reply_markup=keyboard)

    @bot.on_chat_member_updated()
    async def bot_added_to_channel(client: Client, update: ChatMemberUpdated):
        if update.new_chat_member and update.new_chat_member.user.is_self:
            if update.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
                chat_id = update.chat.id
                chat_title = update.chat.title
                user_id = update.from_user.id if update.from_user else None
                
                if user_id:
                    try:
                        # Obtém link de convite e contagem de membros atualizada
                        chat_info = await client.get_chat(chat_id)
                        membros = await client.get_chat_member_count(chat_id)
                        invite_link = chat_info.invite_link or chat_info.username

                        # Validação mínima de inscritos (Ex: 500 membros)
                        if membros < 500:
                            await client.send_message(
                                chat_id=user_id,
                                text=f"❌ O canal **{chat_title}** possui apenas {membros} inscritos. O requisito mínimo é de 500 membros para participar."
                            )
                            return

                        # Salvando pendente ou ativo no banco (conforme sua preferência de controle)
                        async with db_pool.acquire() as conn:
                            await conn.execute("""
                                INSERT INTO canais (chat_id, titulo, dono_id, invite_link, membros, ativo)
                                VALUES ($1, $2, $3, $4, $5, TRUE)
                                ON CONFLICT (chat_id) DO UPDATE 
                                SET titulo = EXCLUDED.titulo, dono_id = EXCLUDED.dono_id, 
                                    invite_link = EXCLUDED.invite_link, membros = EXCLUDED.membros, ativo = TRUE
                            """, chat_id, chat_title, user_id, invite_link, membros)
                        
                        await client.send_message(
                            chat_id=user_id,
                            text=f"✅ Sucesso! O canal **{chat_title}** foi cadastrado com {membros} membros e está apto para as trocas!"
                        )
                    except Exception as e:
                        logger.error(f"Erro ao registrar canal {chat_id}: {e}")

    await bot.start()
    logger.info(f"🤖 Bot @{bot.me.username} Online e pronto!")

    # Configuração do Agendador (Disparo 2 vezes ao dia, ex: 12:00 e 20:00)
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=12, minute=0))
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=20, minute=0))
    scheduler.start()
    logger.info("⏰ Agendador de listas por categoria ativado.")
    
    yield
    
    scheduler.shutdown()
    await bot.stop()
    await db_pool.close()
    logger.info("🛑 Sistema encerrado.")

# ==========================================
# 5. ROTAS DO FASTAPI
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "UP CANAIS - Sistema de Troca por Categoria Rodando 100%!"}
