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
# 3. LISTA DE CATEGORIAS DISPONÍVEIS
# ==========================================
CATEGORIAS_DISPONIVEIS = {
    "filmes": "🎬 Filmes, Séries & Animes",
    "adulto": "🔞 Adulto / NSFW",
    "tech": "💻 Tecnologia, Games & Softwares",
    "noticias": "📢 Notícias, Política & Utilidades",
    "financas": "📈 Finanças, Cripto & Investimentos",
    "esportes": "⚽ Esportes & Futebol",
    "musica": "🎵 Músicas, Áudios & Valeton",
    "humor": "😂 Humor, Memes & Entretenimento",
    "vendas": "🛒 Vendas, Afiliados & Lojas",
    "geral": "🌐 Variedades & Geral"
}

# ==========================================
# 4. FUNÇÃO DE DISPARO DA TROCA DE DIVULGAÇÃO
# ==========================================
async def disparar_troca_por_categoria():
    if not bot:
        logger.error("Bot não inicializado para o disparo.")
        return

    try:
        async with db_pool.acquire() as conn:
            categorias = await conn.fetch("SELECT DISTINCT categoria FROM canais WHERE ativo = TRUE AND categoria IS NOT NULL")

            for cat_row in categorias:
                categoria = cat_row['categoria']

                vips = await conn.fetch(
                    "SELECT titulo, invite_link FROM canais WHERE categoria = $1 AND vip = TRUE AND ativo = TRUE LIMIT 4", 
                    categoria
                )
                
                normais = await conn.fetch(
                    "SELECT titulo, invite_link FROM canais WHERE categoria = $1 AND vip = FALSE AND ativo = TRUE ORDER BY RANDOM() LIMIT 14", 
                    categoria
                )

                links_fixos = await conn.fetch(
                    "SELECT titulo, url FROM links_fixos WHERE categoria = $1", 
                    categoria
                )

                destinos = await conn.fetch("SELECT chat_id FROM canais WHERE categoria = $1 AND ativo = TRUE", categoria)

                if not destinos:
                    continue

                nome_cat_formatado = CATEGORIAS_DISPONIVEIS.get(categoria, categoria.upper())
                texto_lista = f"🔥 **LISTA DE DIVULGAÇÃO - {nome_cat_formatado}** 🔥\n\n"
                
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

        logger.info("✅ Ciclo de troca de divulgação concluído com sucesso!")

    except Exception as e:
        logger.error(f"❌ Erro no agendador de listas: {e}")

# ==========================================
# 5. CICLO DE VIDA DO FASTAPI E BOT
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, bot
    
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    logger.info("📦 Pool do PostgreSQL iniciado.")
    
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
                
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS invite_link TEXT;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS membros INT DEFAULT 0;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS categoria VARCHAR(100);
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS vip BOOLEAN DEFAULT FALSE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE;

                CREATE TABLE IF NOT EXISTS links_fixos (
                    id SERIAL PRIMARY KEY,
                    titulo VARCHAR(255),
                    url TEXT,
                    categoria VARCHAR(100)
                );
            """)
    logger.info("🗄️ Tabelas e colunas estruturadas com sucesso.")

    if SESSION_STRING:
        bot = Client("bot_up_canais", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
    else:
        bot = Client("bot_up_canais", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

    @bot.on_message(filters.command("start") & filters.private)
    async def start_command(client: Client, message):
        user_id = message.from_user.id
        username = message.from_user.username
        
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO usuarios (telegram_id, username) VALUES ($1, $2)
                ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username
            """, user_id, username)

        b_username = client.me.username
        link_adicao = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_adicao)],
            [InlineKeyboardButton("📢 Meus Canais Cadastrados", callback_data="meus_canais")],
            [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
        ])
        await message.reply_text(
            "👋 **Bem-vindo ao UP CANAIS!**\n\n"
            "Gerencie seus canais na rede de troca de divulgações através dos botões abaixo:\n\n"
            "*(Para cadastrar um novo canal, adicione-me como administrador nele).* ",
            reply_markup=keyboard
        )

    @bot.on_callback_query()
    async def callback_handler(client: Client, callback_query):
        data = callback_query.data
        user_id = callback_query.from_user.id
        
        if data == "conta":
            await callback_query.answer("Sua conta está ativa na nossa rede!", show_alert=True)

        elif data == "meus_canais" or data.startswith("pagcanais_"):
            offset = 0
            if data.startswith("pagcanais_"):
                offset = int(data.split("_")[1])

            async with db_pool.acquire() as conn:
                canais = await conn.fetch(
                    "SELECT chat_id, titulo, categoria, membros FROM canais WHERE dono_id = $1 AND ativo = TRUE LIMIT 5 OFFSET $2",
                    user_id, offset
                )
                total_row = await conn.fetchval("SELECT COUNT(*) FROM canais WHERE dono_id = $1 AND ativo = TRUE", user_id)

            if not canais:
                await callback_query.message.edit_text(
                    "📂 Você não possui nenhum canal cadastrado ativo no momento.\n\n"
                    "Adicione o bot como Administrador em um canal para começar!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_inicio")]])
                )
                return

            texto = f"📢 **Seus Canais Cadastrados** (Total: {total_row}):\n\n"
            botoes = []

            for canal in canais:
                cat_nome = CATEGORIAS_DISPONIVEIS.get(canal['categoria'], "Não definida")
                texto += f"• **{canal['titulo']}**\n  └ Categoria: {cat_nome} | Membros: {canal['membros']}\n\n"
                
                botoes.append([
                    InlineKeyboardButton(f"⚙️ Gerenciar: {canal['titulo'][:20]}...", callback_data=f"gerenciar_{canal['chat_id']}")
                ])

            botoes_nav = []
            if offset > 0:
                botoes_nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"pagcanais_{offset - 5}"))
            if offset + 5 < total_row:
                botoes_nav.append(InlineKeyboardButton("Próxima ➡️", callback_data=f"pagcanais_{offset + 5}"))
            
            if botoes_nav:
                botoes.append(botoes_nav)

            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")])

            await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

        elif data.startswith("gerenciar_"):
            chat_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                canal = await conn.fetchrow("SELECT * FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)

            if not canal:
                await callback_query.answer("Canal não encontrado ou sem permissão.", show_alert=True)
                return

            cat_nome = CATEGORIAS_DISPONIVEIS.get(canal['categoria'], "Não definida")
            texto = (
                f"⚙️ **Gerenciando Canal:** {canal['titulo']}\n\n"
                f"📁 Categoria: {cat_nome}\n"
                f"👥 Membros: {canal['membros']}\n"
                f"🔗 Link Atual: `{canal['invite_link'] or 'Nenhum'}`\n\n"
                f"Escolha o que deseja fazer:"
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Atualizar Nome e Link", callback_data=f"atualizar_{chat_id}")],
                [InlineKeyboardButton("🗑️ Remover Canal", callback_data=f"remover_{chat_id}")],
                [InlineKeyboardButton("⬅️ Voltar aos Meus Canais", callback_data="meus_canais")]
            ])
            await callback_query.message.edit_text(texto, reply_markup=keyboard)

        elif data.startswith("atualizar_"):
            chat_id = int(data.split("_")[1])
            try:
                chat_info = await client.get_chat(chat_id)
                novo_titulo = chat_info.title
                novo_link = chat_info.invite_link or chat_info.username or (f"https://t.me/{chat_info.username}" if chat_info.username else "")
                novos_membros = getattr(chat_info, "members_count", 0)

                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE canais SET titulo = $1, invite_link = $2, membros = $3 WHERE chat_id = $4",
                        novo_titulo, novo_link, novos_membros, chat_id
                    )

                await callback_query.answer("✅ Informações atualizadas com sucesso a partir do Telegram!", show_alert=True)
                
                async with db_pool.acquire() as conn:
                    canal = await conn.fetchrow("SELECT * FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)

                if canal:
                    cat_nome = CATEGORIAS_DISPONIVEIS.get(canal['categoria'], "Não definida")
                    texto = (
                        f"⚙️ **Gerenciando Canal:** {canal['titulo']}\n\n"
                        f"📁 Categoria: {cat_nome}\n"
                        f"👥 Membros: {canal['membros']}\n"
                        f"🔗 Link Atual: `{canal['invite_link'] or 'Nenhum'}`\n\n"
                        f"Escolha o que deseja fazer:"
                    )
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Atualizar Nome e Link", callback_data=f"atualizar_{chat_id}")],
                        [InlineKeyboardButton("🗑️ Remover Canal", callback_data=f"remover_{chat_id}")],
                        [InlineKeyboardButton("⬅️ Voltar aos Meus Canais", callback_data="meus_canais")]
                    ])
                    try:
                        await callback_query.message.edit_text(texto, reply_markup=keyboard)
                    except Exception as ex:
                        if "MESSAGE_NOT_MODIFIED" not in str(ex):
                            raise ex

            except Exception as e:
                logger.error(f"Erro ao atualizar canal {chat_id}: {e}")
                await callback_query.answer("⚠️ As informações já estão atualizadas ou o bot precisa ser admin.", show_alert=True)

        elif data.startswith("remover_"):
            chat_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)

            await callback_query.answer("🗑️ Canal removido da rede de divulgação com sucesso!", show_alert=True)
            
            async with db_pool.acquire() as conn:
                canais = await conn.fetch(
                    "SELECT chat_id, titulo, categoria, membros FROM canais WHERE dono_id = $1 AND ativo = TRUE LIMIT 5 OFFSET 0",
                    user_id
                )
                total_row = await conn.fetchval("SELECT COUNT(*) FROM canais WHERE dono_id = $1 AND ativo = TRUE", user_id)

            if not canais:
                await callback_query.message.edit_text(
                    "📂 Você não possui nenhum canal cadastrado ativo no momento.\n\n"
                    "Adicione o bot como Administrador em um canal para começar!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_inicio")]])
                )
                return

            texto = f"📢 **Seus Canais Cadastrados** (Total: {total_row}):\n\n"
            botoes = []
            for canal in canais:
                cat_nome = CATEGORIAS_DISPONIVEIS.get(canal['categoria'], "Não definida")
                texto += f"• **{canal['titulo']}**\n  └ Categoria: {cat_nome} | Membros: {canal['membros']}\n\n"
                botoes.append([
                    InlineKeyboardButton(f"⚙️ Gerenciar: {canal['titulo'][:20]}...", callback_data=f"gerenciar_{canal['chat_id']}")
                ])
            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")])
            await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

        elif data == "voltar_inicio":
            b_username = client.me.username
            link_adicao = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_adicao)],
                [InlineKeyboardButton("📢 Meus Canais Cadastrados", callback_data="meus_canais")],
                [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
            ])
            try:
                await callback_query.message.edit_text(
                    "👋 **Painel Principal - UP CANAIS**\n\n"
                    "Gerencie seus canais na rede de troca de divulgações através dos botões abaixo:",
                    reply_markup=keyboard
                )
            except Exception as ex:
                if "MESSAGE_NOT_MODIFIED" not in str(ex):
                    raise ex

        elif data.startswith("setcat_"):
            partes = data.split("_", 2)
            if len(partes) == 3:
                chat_id = int(partes[1])
                categoria = partes[2]
                
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE canais SET categoria = $1 WHERE chat_id = $2",
                        categoria, chat_id
                    )
                
                nome_cat = CATEGORIAS_DISPONIVEIS.get(categoria, categoria)
                b_username = client.me.username
                link_adicao = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Ver Meus Canais", callback_data="meus_canais")],
                    [InlineKeyboardButton("➕ Adicionar Outro Canal", url=link_adicao)]
                ])
                await callback_query.message.edit_text(
                    f"🎉 **Canal configurado com sucesso!**\n\n"
                    f"📁 Categoria definida: **{nome_cat}**\n"
                    f"Seu canal já está participando das trocas automáticas de divulgação!",
                    reply_markup=keyboard
                )

    @bot.on_chat_member_updated()
    async def bot_added_to_channel(client: Client, update: ChatMemberUpdated):
        if update.new_chat_member and update.new_chat_member.user.is_self:
            if update.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
                chat_id = update.chat.id
                chat_title = update.chat.title
                user_id = update.from_user.id if update.from_user else None
                
                if not user_id:
                    logger.warning(f"⚠️ O bot foi adicionado ao canal {chat_title} ({chat_id}), mas o ID do usuário não foi retornado.")
                    return

                try:
                    chat_info = await client.get_chat(chat_id)
                    membros = getattr(chat_info, "members_count", 0)
                    invite_link = chat_info.invite_link or chat_info.username or (f"https://t.me/{chat_info.username}" if chat_info.username else "")

                    if membros > 0 and membros < 500:
                        await client.send_message(
                            chat_id=user_id,
                            text=f"❌ O canal **{chat_title}** possui apenas {membros} inscritos. O requisito mínimo é de 500 membros para participar."
                        )
                        return

                    async with db_pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO canais (chat_id, titulo, dono_id, invite_link, membros, ativo)
                            VALUES ($1, $2, $3, $4, $5, TRUE)
                            ON CONFLICT (chat_id) DO UPDATE 
                            SET titulo = EXCLUDED.titulo, dono_id = EXCLUDED.dono_id, 
                                invite_link = EXCLUDED.invite_link, membros = EXCLUDED.membros, ativo = TRUE
                        """, chat_id, chat_title, user_id, invite_link, membros)

                    botoes_categorias = []
                    linha_temp = []
                    for cat_key, cat_nome in CATEGORIAS_DISPONIVEIS.items():
                        linha_temp.append(InlineKeyboardButton(cat_nome, callback_data=f"setcat_{chat_id}_{cat_key}"))
                        if len(linha_temp) == 2:
                            botoes_categorias.append(linha_temp)
                            linha_temp = []
                    if linha_temp:
                        botoes_categorias.append(linha_temp)

                    keyboard_cats = InlineKeyboardMarkup(botoes_categorias)

                    await client.send_message(
                        chat_id=user_id,
                        text=f"✅ Fui adicionado com sucesso no canal **{chat_title}**!\n\n"
                             f"Agora, selecione abaixo a **categoria** correta do seu canal:",
                        reply_markup=keyboard_cats
                    )
                    logger.info(f"✅ Canal {chat_title} ({chat_id}) registrado com sucesso para o usuário {user_id}!")

                except Exception as e:
                    logger.error(f"❌ Erro ao processar canal adicionado {chat_id}: {e}")
                    try:
                        await client.send_message(
                            chat_id=user_id,
                            text="⚠️ Fui adicionado ao canal, mas ocorreu um erro interno. Verifique se você já iniciou uma conversa comigo no chat privado (/start)."
                        )
                    except:
                        pass

    await bot.start()
    logger.info(f"🤖 Bot @{bot.me.username} Online e pronto!")

    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=12, minute=0))
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=20, minute=0))
    scheduler.start()
    logger.info("⏰ Agendador de listas por categoria ativado.")
    
    yield
    
    scheduler.shutdown()
    await bot.stop()
    await db_pool.close()
    logger.info("🛑 Sistema encerrado.")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "UP CANAIS - Sistema Rodando 100%!"}
