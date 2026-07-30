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
from zoneinfo import ZoneInfo  # Importante para corrigir o fuso horário

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
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

# Variáveis globais
db_pool = None
bot = None
scheduler = AsyncIOScheduler()
admin_estados = {}

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
        return False

    try:
        async with db_pool.acquire() as conn:
            # Apenas canais ativos E aprovados participam
            categorias = await conn.fetch("SELECT DISTINCT categoria FROM canais WHERE ativo = TRUE AND aprovado = TRUE AND categoria IS NOT NULL")

            if not categorias:
                logger.info("⚠️ Nenhuma categoria com canais aprovados e ativos encontrada para disparo.")
                return False

            for cat_row in categorias:
                categoria = cat_row['categoria']

                vips = await conn.fetch(
                    "SELECT titulo, invite_link FROM canais WHERE categoria = $1 AND vip = TRUE AND ativo = TRUE AND aprovado = TRUE LIMIT 4", 
                    categoria
                )
                
                normais = await conn.fetch(
                    "SELECT titulo, invite_link FROM canais WHERE categoria = $1 AND vip = FALSE AND ativo = TRUE AND aprovado = TRUE ORDER BY RANDOM() LIMIT 14", 
                    categoria
                )

                links_fixos = await conn.fetch(
                    "SELECT id, titulo, url FROM links_fixos WHERE categoria = $1 OR categoria = 'todas'", 
                    categoria
                )

                # Busca também a última mensagem enviada para poder deletar
                destinos = await conn.fetch("SELECT chat_id, ultima_mensagem_id FROM canais WHERE categoria = $1 AND ativo = TRUE AND aprovado = TRUE", categoria)

                if not destinos:
                    continue

                nome_cat_formatado = CATEGORIAS_DISPONIVEIS.get(categoria, categoria.upper())
                
                texto_lista = (
                    f"🔥 **MELHORES CANAIS - {nome_cat_formatado}** 🔥\n\n"
                    f"✨ Conteúdos exclusivos, atualizados e sem censura.\n\n"
                    f"👇 *Escolha abaixo e acesse agora!*"
                )

                botoes = []

                for v in vips:
                    link = v['invite_link'] or "https://t.me/"
                    botoes.append([InlineKeyboardButton(f"💎 {v['titulo']}", url=link)])

                for lf in links_fixos:
                    botoes.append([InlineKeyboardButton(f"⭐ {lf['titulo']}", url=lf['url'])])

                linha_dupla = []
                for n in normais:
                    link = n['invite_link'] or "https://t.me/"
                    linha_dupla.append(InlineKeyboardButton(f"🚀 {n['titulo']}", url=link))
                    if len(linha_dupla) == 2:
                        botoes.append(linha_dupla)
                        linha_dupla = []
                if linha_dupla:
                    botoes.append(linha_dupla)

                bot_username = bot.me.username
                botoes.append([
                    InlineKeyboardButton("📋 Participar da Lista Grátis", url=f"https://t.me/{bot_username}?start=start")
                ])

                keyboard = InlineKeyboardMarkup(botoes)

                for dest in destinos:
                    chat_id = dest['chat_id']
                    ultima_msg_id = dest['ultima_mensagem_id']

                    # 1. Apaga a lista anterior (se existir)
                    if ultima_msg_id:
                        try:
                            await bot.delete_messages(chat_id=chat_id, message_ids=ultima_msg_id)
                        except Exception as e:
                            logger.warning(f"Aviso: Não foi possível apagar mensagem antiga {ultima_msg_id} no canal {chat_id}: {e}")

                    # 2. Envia a lista nova
                    try:
                        nova_msg = await bot.send_message(
                            chat_id=chat_id,
                            text=texto_lista,
                            reply_markup=keyboard,
                            disable_web_page_preview=True
                        )
                        # 3. Salva o ID da nova lista no banco de dados
                        await conn.execute("UPDATE canais SET ultima_mensagem_id = $1 WHERE chat_id = $2", nova_msg.id, chat_id)
                        logger.info(f"📤 Lista enviada com sucesso para o canal {chat_id} ({categoria})")
                    except Exception as e:
                        logger.error(f"❌ Erro ao enviar lista para o canal {chat_id}: {e}")

        logger.info("✅ Ciclo de troca de divulgação concluído com sucesso!")
        return True

    except Exception as e:
        logger.error(f"❌ Erro no agendador de listas: {e}")
        return False

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
                    ativo BOOLEAN DEFAULT TRUE,
                    aprovado BOOLEAN DEFAULT FALSE,
                    ultima_mensagem_id BIGINT
                );
                
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS invite_link TEXT;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS membros INT DEFAULT 0;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS categoria VARCHAR(100);
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS vip BOOLEAN DEFAULT FALSE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS aprovado BOOLEAN DEFAULT FALSE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS ultima_mensagem_id BIGINT;

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

        keyboard_rows = [
            [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_adicao)],
            [InlineKeyboardButton("📢 Meus Canais Cadastrados", callback_data="meus_canais")],
            [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
        ]
        
        if ADMIN_ID and user_id == ADMIN_ID:
            keyboard_rows.insert(0, [InlineKeyboardButton("🛠️ Painel Admin", callback_data="admin_painel")])

        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await message.reply_text(
            "👋 **Bem-vindo ao UP CANAIS!**\n\n"
            "Gerencie seus canais na rede de troca de divulgações através dos botões abaixo:\n\n"
            "*(Para cadastrar um novo canal, adicione-me como administrador nele).* ",
            reply_markup=keyboard
        )

    @bot.on_message(filters.command("admin") & filters.private)
    async def admin_command(client: Client, message):
        user_id = message.from_user.id
        if ADMIN_ID and user_id != ADMIN_ID:
            await message.reply_text("⛔ Acesso negado.")
            return
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏳ Canais Pendentes de Aprovação", callback_data="admin_pendentes")],
            [InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink")],
            [InlineKeyboardButton("📋 Listar / Remover Links Fixos", callback_data="admin_listlinks")],
            [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")]
        ])
        await message.reply_text("🛠️ **Painel de Administração**\n\nEscolha uma opção:", reply_markup=keyboard)

    @bot.on_message(filters.command("testar") & filters.private)
    async def testar_comando(client: Client, message):
        user_id = message.from_user.id
        if ADMIN_ID and user_id != ADMIN_ID:
            await message.reply_text("⛔ Acesso negado.")
            return

        await message.reply_text("🚀 Executando disparo de teste das listas (Apagando as antigas e enviando as novas)...")
        sucesso = await disparar_troca_por_categoria()
        if sucesso:
            await message.reply_text("✅ Disparo de teste concluído com sucesso!")
        else:
            await message.reply_text("❌ Falha no disparo ou nenhum canal aprovado/ativo encontrado.")

    @bot.on_callback_query()
    async def callback_handler(client: Client, callback_query):
        data = callback_query.data
        user_id = callback_query.from_user.id
        
        if data == "conta":
            await callback_query.answer("Sua conta está ativa na nossa rede!", show_alert=True)

        elif data == "admin_painel":
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏳ Canais Pendentes de Aprovação", callback_data="admin_pendentes")],
                [InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink")],
                [InlineKeyboardButton("📋 Listar / Remover Links Fixos", callback_data="admin_listlinks")],
                [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")]
            ])
            await callback_query.message.edit_text("🛠️ **Painel de Administração**\n\nEscolha uma opção:", reply_markup=keyboard)

        elif data == "admin_pendentes":
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return

            async with db_pool.acquire() as conn:
                pendentes = await conn.fetch("SELECT chat_id, titulo, categoria, membros, dono_id FROM canais WHERE aprovado = FALSE AND ativo = TRUE")

            if not pendentes:
                await callback_query.message.edit_text(
                    "🎉 Não há nenhum canal pendente de aprovação no momento!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Painel", callback_data="admin_painel")]])
                )
                return

            texto = "⏳ **Canais Aguardando Aprovação:**\n\n"
            botoes = []
            for p in pendentes:
                cat_nome = CATEGORIAS_DISPONIVEIS.get(p['categoria'], "Não definida")
                texto += f"• **{p['titulo']}**\n  └ Cat: {cat_nome} | Membros: {p['membros']}\n\n"
                botoes.append([
                    InlineKeyboardButton(f"✅ Aprovar: {p['titulo'][:15]}", callback_data=f"aprovar_{p['chat_id']}"),
                    InlineKeyboardButton(f"❌ Rejeitar", callback_data=f"rejeitar_{p['chat_id']}")
                ])

            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Painel", callback_data="admin_painel")])
            await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

        elif data.startswith("aprovar_"):
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return
            chat_id = int(data.split("_")[1])

            async with db_pool.acquire() as conn:
                canal = await conn.fetchrow("UPDATE canais SET aprovado = TRUE WHERE chat_id = $1 RETURNING titulo, dono_id", chat_id)

            await callback_query.answer("✅ Canal aprovado com sucesso!", show_alert=True)

            if canal and canal['dono_id']:
                try:
                    await client.send_message(
                        chat_id=canal['dono_id'],
                        text=f"🎉 Parabéns! Seu canal **{canal['titulo']}** foi **aprovado** pelo administrador e já está participando da rede de divulgação!"
                    )
                except:
                    pass

            callback_query.data = "admin_pendentes"
            return await callback_handler(client, callback_query)

        elif data.startswith("rejeitar_"):
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return
            chat_id = int(data.split("_")[1])

            async with db_pool.acquire() as conn:
                canal = await conn.fetchrow("UPDATE canais SET ativo = FALSE WHERE chat_id = $1 RETURNING titulo, dono_id", chat_id)

            await callback_query.answer("❌ Canal rejeitado/removido.", show_alert=True)

            if canal and canal['dono_id']:
                try:
                    await client.send_message(
                        chat_id=canal['dono_id'],
                        text=f"❌ Infelizmente, o cadastro do seu canal **{canal['titulo']}** foi rejeitado pelo administrador."
                    )
                except:
                    pass

            callback_query.data = "admin_pendentes"
            return await callback_handler(client, callback_query)

        elif data == "admin_addlink":
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return
            
            botoes = [
                [InlineKeyboardButton("🌐 TODAS AS CATEGORIAS (Global)", callback_data="admaddcat_todas")]
            ]
            linha = []
            for cat_key, cat_nome in CATEGORIAS_DISPONIVEIS.items():
                linha.append(InlineKeyboardButton(cat_nome, callback_data=f"admaddcat_{cat_key}"))
                if len(linha) == 2:
                    botoes.append(linha)
                    linha = []
            if linha:
                botoes.append(linha)
            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Painel", callback_data="admin_painel")])

            await callback_query.message.edit_text(
                "➕ **Adicionar Link Fixo**\n\nSelecione em qual categoria este link fixo vai aparecer:",
                reply_markup=InlineKeyboardMarkup(botoes)
            )

        elif data.startswith("admaddcat_"):
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return
            cat_key = data.split("_", 1)[1]
            admin_estados[user_id] = {"categoria": cat_key, "etapa": "aguardando_titulo"}
            
            nome_exibicao = "🌐 Todas as Categorias" if cat_key == "todas" else CATEGORIAS_DISPONIVEIS.get(cat_key, cat_key)
            await callback_query.message.edit_text(
                f"✍️ Alvo selecionado: **{nome_exibicao}**\n\n"
                f"Agora, envie o **Título** que aparecerá no link fixo:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="admin_painel")]])
            )

        elif data == "admin_listlinks":
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return
            
            async with db_pool.acquire() as conn:
                links = await conn.fetch("SELECT id, titulo, url, categoria FROM links_fixos ORDER BY categoria")

            if not links:
                await callback_query.message.edit_text(
                    "📂 Nenhum link fixo cadastrado no momento.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel")]])
                )
                return

            texto = "📋 **Links Fixos Cadastrados:**\n\n"
            botoes = []
            for l in links:
                cat_nome = "🌐 Todas as Categorias" if l['categoria'] == 'todas' else CATEGORIAS_DISPONIVEIS.get(l['categoria'], l['categoria'])
                texto += f"• **{l['titulo']}** ({cat_nome})\n  └ `{l['url']}`\n\n"
                botoes.append([InlineKeyboardButton(f"🗑️ Remover: {l['titulo'][:25]}", callback_data=f"admdel_{l['id']}")])

            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Painel", callback_data="admin_painel")])
            await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

        elif data.startswith("admdel_"):
            if ADMIN_ID and user_id != ADMIN_ID:
                await callback_query.answer("Acesso negado.", show_alert=True)
                return
            link_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                await conn.execute("DELETE FROM links_fixos WHERE id = $1", link_id)
            
            await callback_query.answer("🗑️ Link fixo removido com sucesso!", show_alert=True)
            callback_query.data = "admin_listlinks"
            return await callback_handler(client, callback_query)

        elif data == "meus_canais" or data.startswith("pagcanais_"):
            offset = 0
            if data.startswith("pagcanais_"):
                offset = int(data.split("_")[1])

            async with db_pool.acquire() as conn:
                canais = await conn.fetch(
                    "SELECT chat_id, titulo, categoria, membros, aprovado FROM canais WHERE dono_id = $1 AND ativo = TRUE LIMIT 5 OFFSET $2",
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
                status_aprovacao = "✅ Aprovado" if canal['aprovado'] else "⏳ Pendente de Aprovação"
                texto += f"• **{canal['titulo']}**\n  └ Categoria: {cat_nome}\n  └ Status: {status_aprovacao}\n\n"
                
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
            status_aprovacao = "✅ Aprovado" if canal['aprovado'] else "⏳ Pendente de Aprovação"
            texto = (
                f"⚙️ **Gerenciando Canal:** {canal['titulo']}\n\n"
                f"📁 Categoria: {cat_nome}\n"
                f"👥 Membros: {canal['membros']}\n"
                f"📌 Status: {status_aprovacao}\n"
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
                    status_aprovacao = "✅ Aprovado" if canal['aprovado'] else "⏳ Pendente de Aprovação"
                    texto = (
                        f"⚙️ **Gerenciando Canal:** {canal['titulo']}\n\n"
                        f"📁 Categoria: {cat_nome}\n"
                        f"👥 Membros: {canal['membros']}\n"
                        f"📌 Status: {status_aprovacao}\n"
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

            await callback_query.answer("🗑️ Canal removido com sucesso!", show_alert=True)
            
            async with db_pool.acquire() as conn:
                canais = await conn.fetch(
                    "SELECT chat_id, titulo, categoria, membros, aprovado FROM canais WHERE dono_id = $1 AND ativo = TRUE LIMIT 5 OFFSET 0",
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
                texto += f"• **{canal['titulo']}**\n  └ Categoria: {cat_nome}\n\n"
                botoes.append([
                    InlineKeyboardButton(f"⚙️ Gerenciar: {canal['titulo'][:20]}...", callback_data=f"gerenciar_{canal['chat_id']}")
                ])
            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")])
            await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

        elif data == "voltar_inicio":
            if user_id in admin_estados:
                del admin_estados[user_id]

            b_username = client.me.username
            link_adicao = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"
            
            keyboard_rows = [
                [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_adicao)],
                [InlineKeyboardButton("📢 Meus Canais Cadastrados", callback_data="meus_canais")],
                [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
            ]
            if ADMIN_ID and user_id == ADMIN_ID:
                keyboard_rows.insert(0, [InlineKeyboardButton("🛠️ Painel Admin", callback_data="admin_painel")])

            keyboard = InlineKeyboardMarkup(keyboard_rows)
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
                    f"⏳ *Seu canal foi enviado para aprovação do administrador e logo estará participando das listas!*",
                    reply_markup=keyboard
                )

                if ADMIN_ID:
                    try:
                        async with db_pool.acquire() as conn:
                            info_canal = await conn.fetchrow("SELECT titulo, membros FROM canais WHERE chat_id = $1", chat_id)
                        
                        await client.send_message(
                            chat_id=ADMIN_ID,
                            text=f"🔔 **Novo Canal Pendente de Aprovação!**\n\n"
                                 f"📌 Canal: **{info_canal['titulo'] if info_canal else 'Desconhecido'}**\n"
                                 f"📁 Categoria: {nome_cat}\n"
                                 f"👥 Membros: {info_canal['membros'] if info_canal else 0}\n\n"
                                 f"Acesse o `/admin` para aprovar ou rejeitar.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🛠️ Ir para Painel de Pendentes", callback_data="admin_pendentes")]
                            ])
                        )
                    except Exception as ex:
                        logger.error(f"Erro ao notificar admin sobre novo canal: {ex}")

    @bot.on_message(filters.private & ~filters.command(["start", "admin", "testar"]))
    async def capturar_texto_admin(client: Client, message):
        user_id = message.from_user.id
        if not ADMIN_ID or user_id != ADMIN_ID:
            return

        if user_id not in admin_estados:
            return

        estado = admin_estados[user_id]
        texto = message.text.strip()

        if estado["etapa"] == "aguardando_titulo":
            estado["titulo"] = texto
            estado["etapa"] = "aguardando_url"
            await message.reply_text(
                f"✅ Título salvo: **{texto}**\n\n"
                f"Agora, envie a **URL / Link de destino**:"
            )
        elif estado["etapa"] == "aguardando_url":
            categoria = estado["categoria"]
            titulo = estado["titulo"]
            url = texto

            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO links_fixos (titulo, url, categoria) VALUES ($1, $2, $3)",
                    titulo, url, categoria
                )

            del admin_estados[user_id]
            
            nome_cat_exibicao = "🌐 Todas as Categorias" if categoria == "todas" else CATEGORIAS_DISPONIVEIS.get(categoria, categoria)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Adicionar Outro Link", callback_data="admin_addlink")],
                [InlineKeyboardButton("🛠️ Voltar ao Painel Admin", callback_data="admin_painel")]
            ])
            await message.reply_text(
                f"🎉 **Link Fixo cadastrado com sucesso!**\n\n"
                f"📌 Alvo: {nome_cat_exibicao}\n"
                f"📝 Título: {titulo}\n"
                f"🔗 URL: {url}",
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
                            INSERT INTO canais (chat_id, titulo, dono_id, invite_link, membros, ativo, aprovado)
                            VALUES ($1, $2, $3, $4, $5, TRUE, FALSE)
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
                    logger.info(f"✅ Canal {chat_title} ({chat_id}) registrado como pendente para o usuário {user_id}!")

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

    # Corrigindo o Fuso Horário para as 12:00 e 20:00 de Brasília
    fuso_horario = ZoneInfo("America/Sao_Paulo")
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=12, minute=0, timezone=fuso_horario))
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=20, minute=0, timezone=fuso_horario))
    
    scheduler.start()
    logger.info("⏰ Agendador de listas por categoria ativado (Fuso: America/Sao_Paulo).")
    
    yield
    
    scheduler.shutdown()
    await bot.stop()
    await db_pool.close()
    logger.info("🛑 Sistema encerrado.")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "UP CANAIS - Sistema Rodando 100%!"}
