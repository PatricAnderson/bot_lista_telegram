import os
import logging
import random
from contextlib import asynccontextmanager
import asyncpg
from fastapi import FastAPI
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import ChatWriteForbidden, ChatAdminRequired, ChannelPrivate, UserBannedInChannel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

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
    "musica": "🎵 Músicas, Áudios & Entretenimento",
    "humor": "😂 Humor, Memes & Comédia",
    "vendas": "🛒 Vendas, Afiliados & Lojas",
    "geral": "🌐 Variedades & Geral"
}

# ==========================================
# 4. FUNÇÕES DE AUTOMAÇÃO E VARREDURA
# ==========================================

# Rotina 1: Disparo Diário das Listas (com Sistema de Strikes e Contagem)
async def disparar_troca_por_categoria():
    if not bot:
        logger.error("Bot não inicializado para o disparo.")
        return False

    try:
        async with db_pool.acquire() as conn:
            categorias = await conn.fetch("SELECT DISTINCT categoria FROM canais WHERE ativo = TRUE AND aprovado = TRUE AND categoria IS NOT NULL")

            if not categorias:
                logger.info("⚠️ Nenhuma categoria ativa encontrada para disparo.")
                return False

            # Pega a contagem total de canais reais + fakes para mostrar na mensagem
            # ... (código anterior)
            total_canais = await conn.fetchval("SELECT COUNT(*) FROM canais WHERE ativo = TRUE AND aprovado = TRUE")

            for cat_row in categorias:
                categoria = cat_row['categoria']

                # 1. Puxamos TODOS os canais normais e VIPs da categoria (trazendo o chat_id para filtrar depois)
                todos_normais = await conn.fetch("SELECT chat_id, titulo, invite_link FROM canais WHERE categoria = $1 AND vip = FALSE AND ativo = TRUE AND aprovado = TRUE", categoria)
                vips = await conn.fetch("SELECT chat_id, titulo, invite_link FROM canais WHERE categoria = $1 AND vip = TRUE AND ativo = TRUE AND aprovado = TRUE LIMIT 4", categoria)
                links_fixos = await conn.fetch("SELECT id, titulo, url FROM links_fixos WHERE categoria = $1 OR categoria = 'todas'", categoria)

                # Busca destinos reais (ignora fakes que tem ID negativo)
                destinos = await conn.fetch("SELECT chat_id, ultima_mensagem_id, dono_id, titulo FROM canais WHERE categoria = $1 AND ativo = TRUE AND aprovado = TRUE AND semente = FALSE", categoria)

                if not destinos:
                    continue

                nome_cat_formatado = CATEGORIAS_DISPONIVEIS.get(categoria, categoria.upper())
                
                texto_lista = (
                    f"🔥 **MELHORES CANAIS - {nome_cat_formatado}** 🔥\n\n"
                    f"✨ Conteúdos exclusivos, atualizados e sem censura.\n"
                    f"📈 **{total_canais} canais** cadastrados na nossa rede!\n\n"
                    f"👇 *Escolha abaixo e acesse agora!*"
                )

                for dest in destinos:
                    chat_id_destino = dest['chat_id']
                    ultima_msg_id = dest['ultima_mensagem_id']
                    dono_id = dest['dono_id']
                    titulo_canal = dest['titulo']

                    # --- LÓGICA DE ROTAÇÃO E EXCLUSÃO DO PRÓPRIO CANAL ---
                    # Remove o próprio canal de destino da lista de botões
                    elegiveis = [c for c in todos_normais if c['chat_id'] != chat_id_destino]
                    
                    # Embaralha a lista e pega até 20 canais SÓ para este destino
                    selecionados = random.sample(elegiveis, min(20, len(elegiveis)))

                    # Monta os botões do zero para cada canal
                    botoes = []
                    for v in vips:
                        # Evita que o VIP apareça na própria lista dele
                        if v['chat_id'] != chat_id_destino:
                            botoes.append([InlineKeyboardButton(f"💎 {v['titulo']}", url=v['invite_link'] or "https://t.me/")])
                            
                    for lf in links_fixos:
                        botoes.append([InlineKeyboardButton(f"⭐ {lf['titulo']}", url=lf['url'])])

                    linha_dupla = []
                    for n in selecionados:
                        linha_dupla.append(InlineKeyboardButton(n['titulo'], url=n['invite_link'] or "https://t.me/"))
                        if len(linha_dupla) == 2:
                            botoes.append(linha_dupla)
                            linha_dupla = []
                    if linha_dupla:
                        botoes.append(linha_dupla)

                    botoes.append([InlineKeyboardButton("📋 Participar da Lista Grátis", url=f"https://t.me/{bot.me.username}?start=start")])
                    keyboard = InlineKeyboardMarkup(botoes)
                    # -----------------------------------------------------

                    try:
                        # Tenta apagar a lista anterior
                        if ultima_msg_id:
                            try:
                                await bot.delete_messages(chat_id=chat_id_destino, message_ids=ultima_msg_id)
                            except Exception:
                                pass

                        # Envia a nova lista
                        nova_msg = await bot.send_message(
                            chat_id=chat_id_destino,
                            text=texto_lista,
                            reply_markup=keyboard,
                            disable_web_page_preview=True
                        )
                        await conn.execute("UPDATE canais SET ultima_mensagem_id = $1 WHERE chat_id = $2", nova_msg.id, chat_id_destino)
                        logger.info(f"📤 Lista enviada com sucesso para o canal {chat_id_destino}")
                        # ... resto do código dos excepts (strikes) continua igual

                    except (ChatWriteForbidden, ChatAdminRequired, ChannelPrivate, UserBannedInChannel) as e:
                        logger.warning(f"🚫 Strike! Sem permissão no canal {chat_id}. Pausando canal.")
                        await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1", chat_id)
                        try:
                            await bot.send_message(
                                dono_id,
                                f"⚠️ **Aviso de Desligamento Automático!**\n\n"
                                f"Fui impedido de enviar a lista no seu canal **{titulo_canal}**. Isso geralmente acontece se eu for removido dos administradores ou banido.\n\n"
                                f"Seu canal foi **pausado** da rede. Para voltar, adicione o bot novamente como Administrador e clique em 'Atualizar Nome e Link' no seu painel."
                            )
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(f"❌ Erro ao enviar lista para o canal {chat_id}: {e}")

        logger.info("✅ Ciclo de troca de divulgação concluído com sucesso!")
        return True
    except Exception as e:
        logger.error(f"❌ Erro no agendador de listas: {e}")
        return False

# Rotina 2: Varredura Semanal de Membros (Valida apenas reais)
async def monitorar_membros_semanal():
    if not bot:
        return
    logger.info("🔍 Iniciando varredura semanal de quantidade de membros...")
    try:
        async with db_pool.acquire() as conn:
            canais_ativos = await conn.fetch("SELECT chat_id, titulo, dono_id FROM canais WHERE ativo = TRUE AND aprovado = TRUE AND semente = FALSE")
            
            for c in canais_ativos:
                chat_id = c['chat_id']
                dono_id = c['dono_id']
                titulo = c['titulo']

                try:
                    chat_info = await bot.get_chat(chat_id)
                    membros_atuais = getattr(chat_info, "members_count", 0)

                    await conn.execute("UPDATE canais SET membros = $1 WHERE chat_id = $2", membros_atuais, chat_id)

                    if 0 < membros_atuais < 100:
                        await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1", chat_id)
                        logger.info(f"📉 Canal {chat_id} pausado por queda de membros ({membros_atuais}).")
                        try:
                            await bot.send_message(
                                dono_id,
                                f"📉 **Alerta de Queda de Membros!**\n\n"
                                f"Durante nossa varredura semanal, notamos que seu canal **{titulo}** caiu para {membros_atuais} membros.\n"
                                f"Como nossa regra exige um mínimo de **100 membros**, seu canal foi temporariamente **pausado**.\n\n"
                                f"Assim que recuperar o engajamento, acesse seu painel e atualize os dados para voltar!"
                            )
                        except Exception:
                            pass
                            
                except (ChatWriteForbidden, ChatAdminRequired, ChannelPrivate, UserBannedInChannel):
                    await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1", chat_id)
                except Exception as e:
                    logger.error(f"Erro ao consultar canal {chat_id} na varredura: {e}")
                    
        logger.info("✅ Varredura semanal concluída!")
    except Exception as e:
        logger.error(f"Erro na varredura semanal: {e}")

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
                    ultima_mensagem_id BIGINT,
                    semente BOOLEAN DEFAULT FALSE
                );
                
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS invite_link TEXT;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS membros INT DEFAULT 0;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS categoria VARCHAR(100);
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS vip BOOLEAN DEFAULT FALSE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS aprovado BOOLEAN DEFAULT FALSE;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS ultima_mensagem_id BIGINT;
                ALTER TABLE canais ADD COLUMN IF NOT EXISTS semente BOOLEAN DEFAULT FALSE;

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

    # ----------------------------------------------------
    # NOVO: COMANDO DE IMPORTAÇÃO DE TXT
    # ----------------------------------------------------
    @bot.on_message(filters.command("importar") & filters.private)
    async def importar_fakes(client: Client, message):
        user_id = message.from_user.id
        if ADMIN_ID and user_id != ADMIN_ID:
            return
            
        if not message.reply_to_message or not message.reply_to_message.document:
            await message.reply_text("⚠️ **Modo de Uso:**\nEnvie o arquivo `.txt` gerado pelo scraper.\nResponda ao arquivo com o comando: `/importar <categoria>`\nExemplo: `/importar adulto`")
            return
            
        partes = message.text.split()
        if len(partes) < 2 or partes[1] not in CATEGORIAS_DISPONIVEIS:
            cats = ", ".join(CATEGORIAS_DISPONIVEIS.keys())
            await message.reply_text(f"⚠️ **Categoria inválida!**\nEscolha uma destas: `{cats}`")
            return
            
        categoria_alvo = partes[1]
        msg_status = await message.reply_text("⏳ Baixando e processando o arquivo...")
        
        arquivo_path = await client.download_media(message.reply_to_message)
        adicionados = 0
        
        try:
            with open(arquivo_path, 'r', encoding='utf-8') as f:
                linhas = f.readlines()
                
            async with db_pool.acquire() as conn:
                for linha in linhas:
                    if "|" in linha:
                        titulo, link = linha.split("|", 1)
                        titulo = titulo.strip()
                        link = link.strip()
                        
                        # Gera um ID falso, alto e negativo para nunca conflitar com grupos do Telegram
                        fake_chat_id = -random.randint(100000000000, 999999999999)
                        
                        # Injeta no banco com semente = TRUE
                        await conn.execute("""
                            INSERT INTO canais (chat_id, titulo, dono_id, categoria, invite_link, membros, ativo, aprovado, semente)
                            VALUES ($1, $2, $3, $4, $5, $6, TRUE, TRUE, TRUE)
                            ON CONFLICT DO NOTHING
                        """, fake_chat_id, titulo, ADMIN_ID, categoria_alvo, link, 150)
                        
                        adicionados += 1
                        
            os.remove(arquivo_path)
            await msg_status.edit_text(f"🎉 **Importação Concluída!**\n\nForam adicionados **{adicionados}** canais sementes (fakes) na categoria `{categoria_alvo}`.")
            
        except Exception as e:
            await msg_status.edit_text(f"❌ **Erro na importação:** {e}")

    @bot.on_message(filters.command("admin") & filters.private)
    async def admin_command(client: Client, message):
        user_id = message.from_user.id
        if ADMIN_ID and user_id != ADMIN_ID:
            await message.reply_text("⛔ Acesso negado.")
            return
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏳ Canais Pendentes", callback_data="admin_pendentes")],
            [InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink")],
            [InlineKeyboardButton("📋 Links Fixos Cadastrados", callback_data="admin_listlinks")],
            [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")]
        ])
        await message.reply_text("🛠️ **Painel de Administração**\n\nEscolha uma opção:", reply_markup=keyboard)

    @bot.on_message(filters.command("testar") & filters.private)
    async def testar_comando(client: Client, message):
        user_id = message.from_user.id
        if ADMIN_ID and user_id != ADMIN_ID:
            return

        await message.reply_text("🚀 Executando disparo de teste manual...")
        sucesso = await disparar_troca_por_categoria()
        if sucesso:
            await message.reply_text("✅ Disparo de teste concluído com sucesso!")
        else:
            await message.reply_text("❌ Falha no disparo.")

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
                [InlineKeyboardButton("⏳ Canais Pendentes", callback_data="admin_pendentes")],
                [InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink")],
                [InlineKeyboardButton("📋 Links Fixos Cadastrados", callback_data="admin_listlinks")],
                [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")]
            ])
            await callback_query.message.edit_text("🛠️ **Painel de Administração**\n\nEscolha uma opção:", reply_markup=keyboard)

        elif data == "admin_pendentes":
            if ADMIN_ID and user_id != ADMIN_ID:
                return
            async with db_pool.acquire() as conn:
                pendentes = await conn.fetch("SELECT chat_id, titulo, categoria, membros, dono_id FROM canais WHERE aprovado = FALSE AND ativo = TRUE")

            if not pendentes:
                await callback_query.message.edit_text("🎉 Não há nenhum canal pendente de aprovação!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Painel", callback_data="admin_painel")]]))
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
            if ADMIN_ID and user_id != ADMIN_ID: return
            chat_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                canal = await conn.fetchrow("UPDATE canais SET aprovado = TRUE, ativo = TRUE WHERE chat_id = $1 RETURNING titulo, dono_id, categoria", chat_id)
                
                # ----------------------------------------------------
                # LÓGICA DE SUBSTITUIÇÃO (Remove 1 Semente da Categoria)
                # ----------------------------------------------------
                if canal:
                    await conn.execute("""
                        DELETE FROM canais 
                        WHERE chat_id IN (
                            SELECT chat_id FROM canais 
                            WHERE semente = TRUE AND categoria = $1 
                            LIMIT 1
                        )
                    """, canal['categoria'])

            await callback_query.answer("✅ Canal aprovado! Um link semente foi removido (se houver).", show_alert=True)
            if canal and canal['dono_id']:
                try: await client.send_message(canal['dono_id'], f"🎉 Parabéns! Seu canal **{canal['titulo']}** foi **aprovado** na rede UP CANAIS!")
                except: pass
            callback_query.data = "admin_pendentes"
            return await callback_handler(client, callback_query)

        elif data.startswith("rejeitar_"):
            if ADMIN_ID and user_id != ADMIN_ID: return
            chat_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                canal = await conn.fetchrow("UPDATE canais SET ativo = FALSE WHERE chat_id = $1 RETURNING titulo, dono_id", chat_id)
            await callback_query.answer("❌ Canal rejeitado.", show_alert=True)
            if canal and canal['dono_id']:
                try: await client.send_message(canal['dono_id'], f"❌ Infelizmente, o cadastro do canal **{canal['titulo']}** foi rejeitado pelo administrador.")
                except: pass
            callback_query.data = "admin_pendentes"
            return await callback_handler(client, callback_query)

        elif data == "admin_addlink":
            if ADMIN_ID and user_id != ADMIN_ID: return
            botoes = [[InlineKeyboardButton("🌐 TODAS AS CATEGORIAS (Global)", callback_data="admaddcat_todas")]]
            linha = []
            for cat_key, cat_nome in CATEGORIAS_DISPONIVEIS.items():
                linha.append(InlineKeyboardButton(cat_nome, callback_data=f"admaddcat_{cat_key}"))
                if len(linha) == 2:
                    botoes.append(linha)
                    linha = []
            if linha: botoes.append(linha)
            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Painel", callback_data="admin_painel")])
            await callback_query.message.edit_text("➕ **Adicionar Link Fixo**\n\nSelecione a categoria alvo:", reply_markup=InlineKeyboardMarkup(botoes))

        elif data.startswith("admaddcat_"):
            if ADMIN_ID and user_id != ADMIN_ID: return
            cat_key = data.split("_", 1)[1]
            admin_estados[user_id] = {"categoria": cat_key, "etapa": "aguardando_titulo"}
            nome_exibicao = "🌐 Todas as Categorias" if cat_key == "todas" else CATEGORIAS_DISPONIVEIS.get(cat_key, cat_key)
            await callback_query.message.edit_text(f"✍️ Alvo: **{nome_exibicao}**\n\nEnvie o **Título** do link fixo:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="admin_painel")]]))

        elif data == "admin_listlinks":
            if ADMIN_ID and user_id != ADMIN_ID: return
            async with db_pool.acquire() as conn:
                links = await conn.fetch("SELECT id, titulo, url, categoria FROM links_fixos ORDER BY categoria")
            if not links:
                await callback_query.message.edit_text("📂 Nenhum link fixo cadastrado.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel")]]))
                return
            texto = "📋 **Links Fixos Cadastrados:**\n\n"
            botoes = []
            for l in links:
                cat_nome = "🌐 Todas" if l['categoria'] == 'todas' else CATEGORIAS_DISPONIVEIS.get(l['categoria'], l['categoria'])
                texto += f"• **{l['titulo']}** ({cat_nome})\n  └ `{l['url']}`\n\n"
                botoes.append([InlineKeyboardButton(f"🗑️ Remover: {l['titulo'][:25]}", callback_data=f"admdel_{l['id']}")])
            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Painel", callback_data="admin_painel")])
            await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

        elif data.startswith("admdel_"):
            if ADMIN_ID and user_id != ADMIN_ID: return
            link_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                await conn.execute("DELETE FROM links_fixos WHERE id = $1", link_id)
            await callback_query.answer("🗑️ Link removido!", show_alert=True)
            callback_query.data = "admin_listlinks"
            return await callback_handler(client, callback_query)

        elif data == "meus_canais" or data.startswith("pagcanais_"):
            offset = 0
            if data.startswith("pagcanais_"):
                offset = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                canais = await conn.fetch("SELECT chat_id, titulo, categoria, membros, aprovado, ativo FROM canais WHERE dono_id = $1 LIMIT 5 OFFSET $2", user_id, offset)
                total_row = await conn.fetchval("SELECT COUNT(*) FROM canais WHERE dono_id = $1", user_id)

            if not canais:
                await callback_query.message.edit_text("📂 Você não possui canais cadastrados.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_inicio")]]))
                return

            texto = f"📢 **Seus Canais Cadastrados** (Total: {total_row}):\n\n"
            botoes = []
            for canal in canais:
                cat_nome = CATEGORIAS_DISPONIVEIS.get(canal['categoria'], "Não definida")
                if not canal['ativo']: status = "❌ Pausado / Removido"
                elif not canal['aprovado']: status = "⏳ Pendente"
                else: status = "✅ Ativo e Aprovado"
                
                texto += f"• **{canal['titulo']}**\n  └ Status: {status}\n\n"
                botoes.append([InlineKeyboardButton(f"⚙️ Gerenciar: {canal['titulo'][:20]}...", callback_data=f"gerenciar_{canal['chat_id']}")])

            botoes_nav = []
            if offset > 0: botoes_nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"pagcanais_{offset - 5}"))
            if offset + 5 < total_row: botoes_nav.append(InlineKeyboardButton("Próxima ➡️", callback_data=f"pagcanais_{offset + 5}"))
            if botoes_nav: botoes.append(botoes_nav)
            botoes.append([InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")])
            await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

        elif data.startswith("gerenciar_"):
            chat_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                canal = await conn.fetchrow("SELECT * FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)
            if not canal:
                await callback_query.answer("Canal não encontrado.", show_alert=True)
                return

            cat_nome = CATEGORIAS_DISPONIVEIS.get(canal['categoria'], "Não definida")
            if not canal['ativo']: status = "❌ Pausado / Desativado (Atualize os dados para tentar reativar)"
            elif not canal['aprovado']: status = "⏳ Pendente de Aprovação"
            else: status = "✅ Ativo e Aprovado"

            texto = (
                f"⚙️ **Gerenciando:** {canal['titulo']}\n\n"
                f"📁 Categoria: {cat_nome}\n"
                f"👥 Membros: {canal['membros']}\n"
                f"📌 Status: {status}\n"
                f"🔗 Link: `{canal['invite_link'] or 'Nenhum'}`\n\n"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Atualizar Nome, Link e Reativar", callback_data=f"atualizar_{chat_id}")],
                [InlineKeyboardButton("🗑️ Excluir Definitivamente", callback_data=f"remover_{chat_id}")],
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

                if novos_membros > 0 and novos_membros < 100:
                    await callback_query.answer(f"O canal tem apenas {novos_membros} inscritos. O mínimo é 100. Não é possível ativar.", show_alert=True)
                    return

                async with db_pool.acquire() as conn:
                    await conn.execute("UPDATE canais SET titulo = $1, invite_link = $2, membros = $3, ativo = TRUE WHERE chat_id = $4", novo_titulo, novo_link, novos_membros, chat_id)
                await callback_query.answer("✅ Informações atualizadas e canal ativado com sucesso!", show_alert=True)
                
                callback_query.data = f"gerenciar_{chat_id}"
                return await callback_handler(client, callback_query)

            except (ChatWriteForbidden, ChatAdminRequired):
                await callback_query.answer("⚠️ O bot não tem permissões de Admin neste canal! Dê a permissão antes de atualizar.", show_alert=True)
            except Exception as e:
                await callback_query.answer("⚠️ Ocorreu um erro ao buscar os dados do canal.", show_alert=True)

        elif data.startswith("remover_"):
            chat_id = int(data.split("_")[1])
            async with db_pool.acquire() as conn:
                await conn.execute("DELETE FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)
            await callback_query.answer("🗑️ Canal apagado do sistema!", show_alert=True)
            callback_query.data = "meus_canais"
            return await callback_handler(client, callback_query)

        elif data == "voltar_inicio":
            if user_id in admin_estados: del admin_estados[user_id]
            b_username = client.me.username
            link_adicao = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"
            keyboard_rows = [
                [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_adicao)],
                [InlineKeyboardButton("📢 Meus Canais Cadastrados", callback_data="meus_canais")],
                [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
            ]
            if ADMIN_ID and user_id == ADMIN_ID:
                keyboard_rows.insert(0, [InlineKeyboardButton("🛠️ Painel Admin", callback_data="admin_painel")])
            try: await callback_query.message.edit_text("👋 **Painel Principal - UP CANAIS**\n\nGerencie através dos botões abaixo:", reply_markup=InlineKeyboardMarkup(keyboard_rows))
            except Exception: pass

        elif data.startswith("setcat_"):
            partes = data.split("_", 2)
            if len(partes) == 3:
                chat_id = int(partes[1])
                categoria = partes[2]
                async with db_pool.acquire() as conn:
                    await conn.execute("UPDATE canais SET categoria = $1 WHERE chat_id = $2", categoria, chat_id)
                nome_cat = CATEGORIAS_DISPONIVEIS.get(categoria, categoria)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Ver Meus Canais", callback_data="meus_canais")]])
                await callback_query.message.edit_text(f"🎉 **Canal configurado com sucesso!**\n\n📁 Categoria: **{nome_cat}**\n⏳ *Enviado para aprovação do administrador.*", reply_markup=keyboard)

                if ADMIN_ID:
                    try:
                        async with db_pool.acquire() as conn:
                            info = await conn.fetchrow("SELECT titulo, membros FROM canais WHERE chat_id = $1", chat_id)
                        await client.send_message(ADMIN_ID, f"🔔 **Novo Canal Pendente!**\n\n📌 Canal: **{info['titulo']}**\n📁 Categoria: {nome_cat}\n👥 Membros: {info['membros']}\n\nAcesse o `/admin`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Ir para Painel", callback_data="admin_pendentes")]]))
                    except Exception: pass

    @bot.on_message(filters.private & ~filters.command(["start", "admin", "testar", "importar"]))
    async def capturar_texto_admin(client: Client, message):
        user_id = message.from_user.id
        if not ADMIN_ID or user_id != ADMIN_ID or user_id not in admin_estados:
            return
        estado = admin_estados[user_id]
        texto = message.text.strip()
        if estado["etapa"] == "aguardando_titulo":
            estado["titulo"] = texto
            estado["etapa"] = "aguardando_url"
            await message.reply_text(f"✅ Título salvo: **{texto}**\n\nAgora, envie a **URL**:")
        elif estado["etapa"] == "aguardando_url":
            async with db_pool.acquire() as conn:
                await conn.execute("INSERT INTO links_fixos (titulo, url, categoria) VALUES ($1, $2, $3)", estado["titulo"], texto, estado["categoria"])
            del admin_estados[user_id]
            await message.reply_text("🎉 **Link Fixo cadastrado com sucesso!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Painel Admin", callback_data="admin_painel")]]))

    @bot.on_chat_member_updated()
    async def bot_added_to_channel(client: Client, update: ChatMemberUpdated):
        if update.new_chat_member and update.new_chat_member.user.is_self and update.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
            chat_id = update.chat.id
            chat_title = update.chat.title
            user_id = update.from_user.id if update.from_user else None
            if not user_id: return
            try:
                chat_info = await client.get_chat(chat_id)
                membros = getattr(chat_info, "members_count", 0)
                invite_link = chat_info.invite_link or chat_info.username or (f"https://t.me/{chat_info.username}" if chat_info.username else "")

                if membros > 0 and membros < 100:
                    await client.send_message(user_id, f"❌ O canal **{chat_title}** possui apenas {membros} inscritos. O mínimo é 100.")
                    return

                async with db_pool.acquire() as conn:
                    # Registra garantindo que semente seja FALSO
                    await conn.execute("""
                        INSERT INTO canais (chat_id, titulo, dono_id, invite_link, membros, ativo, aprovado, semente)
                        VALUES ($1, $2, $3, $4, $5, TRUE, FALSE, FALSE)
                        ON CONFLICT (chat_id) DO UPDATE 
                        SET titulo = EXCLUDED.titulo, dono_id = EXCLUDED.dono_id, 
                            invite_link = EXCLUDED.invite_link, membros = EXCLUDED.membros, ativo = TRUE, semente = FALSE
                    """, chat_id, chat_title, user_id, invite_link, membros)

                botoes = []
                linha = []
                for k, v in CATEGORIAS_DISPONIVEIS.items():
                    linha.append(InlineKeyboardButton(v, callback_data=f"setcat_{chat_id}_{k}"))
                    if len(linha) == 2:
                        botoes.append(linha)
                        linha = []
                if linha: botoes.append(linha)

                await client.send_message(user_id, f"✅ Fui adicionado no canal **{chat_title}**!\n\nSelecione a **categoria** do seu canal:", reply_markup=InlineKeyboardMarkup(botoes))
            except Exception: pass

    await bot.start()
    logger.info(f"🤖 Bot @{bot.me.username} Online e pronto!")

    fuso_horario = ZoneInfo("America/Sao_Paulo")
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=14, minute=0, timezone=fuso_horario))
    scheduler.add_job(disparar_troca_por_categoria, CronTrigger(hour=21, minute=0, timezone=fuso_horario))
    
    scheduler.add_job(monitorar_membros_semanal, CronTrigger(day_of_week='sun', hour=3, minute=0, timezone=fuso_horario))
    
    scheduler.start()
    logger.info("⏰ Agendador de listas e varreduras ativado (Fuso: America/Sao_Paulo).")
    
    yield
    
    scheduler.shutdown()
    await bot.stop()
    await db_pool.close()
    logger.info("🛑 Sistema encerrado.")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "UP CANAIS - Sistema Rodando 100%!"}
