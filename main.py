import os
import logging
import asyncpg
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler, ChatMemberUpdatedHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ChatType, ChatMemberStatus

# ==========================================
# 1. CONFIGURAÇÃO DE LOGS
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. VARIÁVEIS DE AMBIENTE
# ==========================================
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Variável global para o pool do banco de dados
db_pool = None

# ==========================================
# 3. FUNÇÕES DO BANCO DE DADOS
# ==========================================
async def init_db():
    """Cria as tabelas necessárias no banco de dados, se não existirem."""
    async with db_pool.acquire() as conn:
        # Criando a tabela de usuários
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id BIGINT PRIMARY KEY,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_ate TIMESTAMP
            );
        ''')
        
        # Criando a tabela de canais
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS canais (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES usuarios(user_id),
                username VARCHAR(255) NOT NULL,
                titulo VARCHAR(255) NOT NULL,
                adicionado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        logger.info("🗂️ Tabelas do banco de dados criadas/verificadas com sucesso.")

# ==========================================
# 4. COMANDOS E HANDLERS DO BOT (PYROGRAM)
# ==========================================
async def start_command(client, message):
    logger.info(f"🔥 START ACIONADO por {message.from_user.first_name}")
    user_id = message.from_user.id
    
    # Salva o usuário no banco de dados (se já existir, ignora)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO usuarios (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
            user_id
        )
        
    # Cria os botões do menu
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Adicionar Meu Canal", callback_data="add_canal")],
        [InlineKeyboardButton("💎 Seja VIP", callback_data="info_vip"), InlineKeyboardButton("👤 Minha Conta", callback_data="minha_conta")],
        [InlineKeyboardButton("📞 Falar com o Suporte", url="https://t.me/SEU_USUARIO_AQUI")] # <- Mude seu usuário aqui
    ])
    
    # Envia a mensagem com o menu
    texto = (
        f"Olá, {message.from_user.first_name}! Bem-vindo ao **UP CANAIS** 🚀\n\n"
        "Aqui você divulga seu canal e ganha novos membros.\n\n"
        "Escolha uma opção abaixo para começar:"
    )
    
    await message.reply_text(texto, reply_markup=teclado)

async def callback_handler(client, query: CallbackQuery):
    dados = query.data
    logger.info(f"🖱️ Botão clicado: {dados} por {query.from_user.id}")
    
    if dados == "add_canal":
        await query.answer()
        
        # Pega as informações do próprio bot para montar o link
        bot_info = await client.get_me()
        
        # Link mágico do Telegram para adicionar o bot direto como Admin no canal
        link_admin = f"https://t.me/{bot_info.username}?startchannel=true&admin=post_messages+edit_messages+delete_messages"
        
        teclado_add = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_admin)]
        ])
        
        await query.message.reply_text(
            "Para participar da lista, eu preciso ser **Administrador** do seu canal (com permissões para postar, editar e apagar mensagens).\n\n"
            "Clique no botão abaixo, selecione seu canal e me adicione. Eu farei a verificação e o cadastro automaticamente!",
            reply_markup=teclado_add
        )
        
    elif dados == "info_vip":
        await query.answer()
        texto_vip = (
            "💎 **VANTAGENS DO VIP:**\n\n"
            "✅ Seu canal no TOPO da lista\n"
            "✅ Mais cliques e mais membros\n"
            "✅ Não precisa retribuir postagem\n\n"
            "Fale com o administrador para adquirir!"
        )
        await query.message.reply_text(texto_vip)
        
    elif dados == "minha_conta":
        await query.answer()
        await query.message.reply_text(f"👤 **Sua Conta:**\nID: `{query.from_user.id}`\nStatus: Grátis\n\n*(Em breve mostraremos seus canais cadastrados aqui!)*")

async def verificar_novo_canal(client, update):
    # Verifica se a atualização de status envolve o próprio bot
    bot_info = await client.get_me()
    
    if update.new_chat_member and update.new_chat_member.user.id == bot_info.id:
        
        # Verifica se o local onde ele foi adicionado é um CANAL e se o status é ADMINISTRADOR
        if update.chat.type == ChatType.CHANNEL and update.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
            
            canal_titulo = update.chat.title
            canal_username = update.chat.username or str(update.chat.id)
            user_id = update.from_user.id # Pega o ID do usuário que fez a ação
            
            # Conecta ao banco para salvar o canal validado
            async with db_pool.acquire() as conn:
                # Verifica se o canal já existe para evitar duplicidade na lista
                existe = await conn.fetchval("SELECT id FROM canais WHERE username = $1", canal_username)
                
                if not existe:
                    await conn.execute(
                        "INSERT INTO canais (user_id, username, titulo) VALUES ($1, $2, $3)",
                        user_id, canal_username, canal_titulo
                    )
                    logger.info(f"✅ Canal {canal_titulo} (@{canal_username}) adicionado por {user_id}")
                    
                    # Avisa o dono no privado que deu tudo certo
                    try:
                        await client.send_message(
                            user_id,
                            f"✅ **Verificação Concluída!**\n\nO canal **{canal_titulo}** foi aprovado e adicionado à nossa base de dados com sucesso. Ele já está apto para participar das listas de divulgação!"
                        )
                    except Exception as e:
                        logger.error(f"Erro ao avisar usuário {user_id} no privado: {e}")
                else:
                    try:
                        await client.send_message(user_id, f"⚠️ O canal **{canal_titulo}** já está cadastrado no sistema.")
                    except:
                        pass

async def catch_all(client, message):
    # Função para capturar mensagens de texto normais
    if message.text and not message.text.startswith("/"):
        logger.info(f"Mensagem recebida de {message.from_user.first_name}: {message.text}")

# ==========================================
# 5. INFRAESTRUTURA LIFESPAN (FASTAPI + PYROGRAM)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    
    logger.info("🌀 Iniciando infraestrutura do UP CANAIS (Pyrogram + Banco)...")
    
    # 1. Conecta ao Banco de Dados
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    logger.info("🗄️ Banco de dados conectado com sucesso.")
    await init_db()
    
    # 2. Instancia o bot garantindo que usará o event loop atual
    bot = Client(
        "upcanais_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True
    )
    
    # 3. Registra os handlers do bot
    bot.add_handler(MessageHandler(start_command, filters.command("start")))
    bot.add_handler(CallbackQueryHandler(callback_handler))
    bot.add_handler(ChatMemberUpdatedHandler(verificar_novo_canal))
    bot.add_handler(MessageHandler(catch_all, filters.text & ~filters.command("start")))
    
    # 4. Inicia o bot do Telegram
    await bot.start()
    logger.info(f"🤖 Bot @{bot.me.username} Online no Railway!")
    
    # Entrega o controle para o FastAPI rodar
    yield
    
    # 5. Quando o servidor desligar, fechamos tudo com segurança
    logger.info("🛑 Desligando serviços...")
    await bot.stop()
    await db_pool.close()
    logger.info("👋 Bot desligado em segurança.")

# ==========================================
# 6. APP FASTAPI
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    """Rota de saúde para o Railway manter a porta aberta e confirmar que está online."""
    return {"status": "online", "bot": "UP CANAIS"}
