import os
import asyncio
import asyncpg
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageDeleteForbidden, RPCError
from pyrogram.enums import ChatType

# ==========================================
# 1. CONFIGURAÇÃO (Variáveis de Ambiente)
# ==========================================
# IMPORTANTE: No Railway, garanta que todas estas variáveis estejam preenchidas.
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) # Seu ID numérico do Telegram

# O Railway fornece o DATABASE_URL automaticamente se o Postgres estiver no mesmo projeto.
# O asyncpg exige que o prefixo seja postgres:// em vez de postgresql:// (se aplicável).
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgres://")

if API_ID == 0 or not API_HASH or not BOT_TOKEN or ADMIN_ID == 0 or not DATABASE_URL:
    print("❌ ERRO CRÍTICO: Faltam variáveis de ambiente essenciais (API_ID, API_HASH, BOT_TOKEN, ADMIN_ID, DATABASE_URL).")
    exit(1)

# ==========================================
# 2. INICIALIZAÇÃO DE SERVIÇOS
# ==========================================
# Configuração vital para rodar no Railway (in_memory=True e ipv6=False)
bot = Client(
    "up_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True, # Não cria arquivo de sessão persistente no contêiner
    ipv6=False       # Evita erros de rede comuns na infraestrutura do Railway
)

db_pool = None

# ==========================================
# 3. BANCO DE DADOS (Lógica Assíncrona)
# ==========================================
async def init_db():
    """Inicializa as tabelas do banco de dados caso não existam."""
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS canais (
                chat_id BIGINT PRIMARY KEY,
                dono_id BIGINT,
                nome_canal TEXT,
                categoria TEXT,
                status TEXT DEFAULT 'pendente_categoria', -- pendente_categoria, quarentena, ativo, rejeitado, vip
                last_msg_id BIGINT
            );
        """)
        print("✅ Tabelas do banco de dados garantidas.")

# ==========================================
# 4. AGENDAMENTO (Scheduler Jobs)
# ==========================================
async def deletar_listas_antigas():
    """Busca listas antigas em canais ativos e deleta para limpeza diária."""
    print("🗓️ Executando tarefa agendada: Limpeza de listas antigas...")
    async with db_pool.acquire() as conn:
        canais = await conn.fetch("SELECT chat_id, last_msg_id FROM canais WHERE last_msg_id IS NOT NULL AND status IN ('ativo', 'vip')")
        
        for canal in canais:
            chat_id = canal['chat_id']
            msg_id = canal['last_msg_id']
            try:
                await bot.delete_messages(chat_id=chat_id, message_ids=msg_id)
                await conn.execute("UPDATE canais SET last_msg_id = NULL WHERE chat_id = $1", chat_id)
                print(f"🗑️ Lista antiga deletada no canal {chat_id}")
            except MessageDeleteForbidden:
                print(f"⚠️ Sem permissão para deletar no canal {chat_id}")
            except RPCError:
                pass # Ignora erros genéricos (ex: mensagem já foi apagada pelo dono)
            await asyncio.sleep(1) # Prevenção anti-flood do Telegram

async def gerar_e_enviar_listas():
    """Placeholder para a lógica de montagem e envio da nova lista diária."""
    print("🗓️ Executando tarefa agendada: Sorteio e envio de nova lista...")
    # Lógica complexa com sorteio VIP entrará aqui na próxima fase
    pass

# ==========================================
# 5. HANDLERS DO BOT (Pyrogram)
# ==========================================

# --- COMANDO /START (Privado) ---
@bot.on_message(filters.command("start") & filters.private)
async def comando_start(client, message):
    # DEBUG PRINT - Essencial para o usuário validar se a mensagem chegou no Railway
    print(f"DEBUG: --> RECEBIDO /start de {message.from_user.id}")

    bot_info = await client.get_me()
    # Link especial que leva o usuário para adicionar o bot ao canal como Admin
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
        print(f"DEBUG: ✅ Resposta enviada para {message.from_user.id}")
    except Exception as e:
        print(f"DEBUG: 💥 ERRO AO RESPONDER START: {e}")

# --- BOT ADICIONADO AO CANAL ---
@bot.on_message(filters.new_chat_members)
async def bot_adicionado_canal(client, message):
    bot_info = await client.get_me()
    me_joined = False

    # Verifica se quem entrou foi o próprio bot
    if message.new_chat_members:
        for membro in message.new_chat_members:
            if membro.id == bot_info.id:
                me_joined = True
                break

    # Garante que é um canal ou supergrupo
    if me_joined and (message.chat.type == ChatType.CHANNEL or message.chat.type == ChatType.SUPERGROUP):
        chat_id = message.chat.id
        nome_canal = message.chat.title
        # Se adicionado via startchannel=true, from_user é o dono.
        dono_id = message.from_user.id if message.from_user else None
        
        print(f"🤖 Bot adicionado no canal: {nome_canal} ({chat_id})")

        if not dono_id:
            print(f"⚠️ Não foi possível determinar o dono do canal {chat_id}. Abortando onboarding.")
            return

        # 1. Registra no banco de dados como pendente de categoria
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO canais (chat_id, dono_id, nome_canal, status) 
                VALUES ($1, $2, $3, 'pendente_categoria')
                ON CONFLICT (chat_id) DO UPDATE SET dono_id = $2, nome_canal = $3, status = 'pendente_categoria';
            """, chat_id, dono_id, nome_canal)
        
        # 2. Chama o dono na DM para forçar a escolha da categoria
        markup_categorias = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Filmes e Séries", callback_data=f"cat_filmes_{chat_id}")],
            [InlineKeyboardButton("💻 Tecnologia", callback_data=f"cat_tech_{chat_id}")],
            [InlineKeyboardButton("🔞 NSFW", callback_data=f"cat_nsfw_{chat_id}")]
        ])
        
        try:
            await client.send_message(
                chat_id=dono_id,
                text=f"✅ Fui adicionado no canal **{nome_canal}**!\n\nAgora, selecione a categoria correta abaixo para envio à moderação:",
                reply_markup=markup_categorias
            )
        except Exception as e:
            print(f"⚠️ Erro ao enviar mensagem de categoria para o dono {dono_id}: {e}")

# --- ESCOLHA DE CATEGORIA (Usuário) ---
@bot.on_callback_query(filters.regex(r"^cat_"))
async def processar_categoria(client, callback_query):
    # Formato: cat_NOME_CHATID
    dados = callback_query.data.split("_")
    categoria_limpa = dados[1].upper() # FILMES, TECH, NSFW
    chat_id = int(dados[2])
    dono_id = callback_query.from_user.id
    
    # Atualiza o banco com a categoria e envia pra quarentena
    async with db_pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE canais SET categoria = $1, status = 'quarentena' 
            WHERE chat_id = $2 AND dono_id = $3 AND status = 'pendente_categoria';
        """, categoria_limpa, chat_id, dono_id)
        
        if result == "UPDATE 0":
            await callback_query.answer("⚠️ Este canal já foi configurado ou não pertence a você.")
            return

        row = await conn.fetchrow("SELECT nome_canal FROM canais WHERE chat_id = $1", chat_id)
        nome_canal = row['nome_canal']
    
    # Responde ao usuário na DM
    await callback_query.edit_message_text(
        f"✅ Categoria **{categoria_limpa}** salva para o canal **{nome_canal}**!\n\n"
        "Agora o canal foi enviado para a **moderação manual (quarentena)**.\n"
        "Você será notificado aqui se ele for aprovado ou rejeitado."
    )
    
    # Notifica o Admin (Você)
    texto_admin = (
        "🚨 **QUARENTENA: NOVO CANAL**\n\n"
        f"**Nome:** {nome_canal}\n"
        f"**Categoria:** {categoria_limpa}\n"
        f"**Chat ID:** `{chat_id}`\n"
        f"**Dono ID:** `{dono_id}`\n\n"
        "Verifique o conteúdo e tome uma decisão:"
    )
    markup_admin = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprovar", callback_data=f"aprovar_{chat_id}_{dono_id}"),
            InlineKeyboardButton("❌ Rejeitar", callback_data=f"rejeitar_{chat_id}_{dono_id}")
        ]
    ])
    
    try:
        await client.send_message(chat_id=ADMIN_ID, text=texto_admin, reply_markup=markup_admin)
    except Exception as e:
        print(f"⚠️ Erro ao notificar admin ({ADMIN_ID}) sobre quarentena: {e}")

# --- DECISÃO DE MODERAÇÃO (Admin) ---
@bot.on_callback_query(filters.regex(r"^(aprovar|rejeitar)_") & filters.user(ADMIN_ID))
async def processar_moderacao(client, callback_query):
    # Formato: ACAO_CHATID_DONOID
    dados = callback_query.data.split("_")
    acao = dados[0]
    chat_id = int(dados[1])
    dono_id = int(dados[2])
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT nome_canal, status FROM canais WHERE chat_id = $1", chat_id)
        
        if not row or row['status'] != 'quarentena':
            await callback_query.answer("⚠️ Este canal já não está mais em quarentena.")
            await callback_query.message.delete()
            return

        nome_canal = row['nome_canal']

        if acao == "aprovar":
            await conn.execute("UPDATE canais SET status = 'ativo' WHERE chat_id = $1", chat_id)
            await callback_query.edit_message_text(f"✅ Canal `{chat_id}` ({nome_canal}) APROVADO por você.")
            
            # Avisa o dono
            try:
                await client.send_message(
                    chat_id=dono_id, 
                    text=f"🎉 **Parabéns!** Seu canal **{nome_canal}** foi aprovado pela moderação e já participará das próximas listas!"
                )
            except: pass # Ignora se o dono bloqueou o bot

        elif acao == "rejeitar":
            await conn.execute("UPDATE canais SET status = 'rejeitado' WHERE chat_id = $1", chat_id)
            await callback_query.edit_message_text(f"❌ Canal `{chat_id}` ({nome_canal}) REJEITADO por você.")
            
            # Avisa o dono e o bot sai do canal
            try:
                await client.send_message(
                    chat_id=dono_id, 
                    text=f"⚠️ Seu canal **{nome_canal}** não foi aprovado para participar das listas no momento.\n\nVerifique se o conteúdo e categoria estão corretos e tente novamente."
                )
                await client.leave_chat(chat_id) # Bot sai do canal rejeitado para não ocupar espaço
            except: pass

# ==========================================
# 6. CICLO DE VIDA FASTAPI (Startup/Shutdown)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    print("🌀 Iniciando infraestrutura do UP CANAIS...")
    
    try:
        # 1. Inicia o Pool do Banco de Dados (PostgreSQL)
        db_pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        await init_db()
        
        # 2. Inicia o Scheduler (Agendador de Listas)
        scheduler = AsyncIOScheduler()
        # Horário do disparo diário (ex: 10:00 da manhã). Railway usa horário UTC.
        scheduler.add_job(deletar_listas_antigas, 'cron', hour=10, minute=0)
        # Sorteio/Envio ocorre 1 min depois (exemplo)
        # scheduler.add_job(gerar_e_enviar_listas, 'cron', hour=10, minute=1)
        scheduler.start()
        print("⏰ Agendador ativo (Limpeza diária configurada).")
        
        # 3. Inicia o Bot no modo Polling Assíncrono (AJUSTADO PARA RAILWAY)
        await bot.start()
        print(f"🤖 Bot @{(await bot.get_me()).username} Online no Railway (Polling IPv4)!")
        
        # MANTÉM O LOOP DE UPDATES DO BOT RODANDO EM BACKGROUND TASK
        app.state.bot_updater = asyncio.create_task(idle())
        
        print("🚀 Servidor online: API, Banco de Dados, Agendador e Bot Ativos!")
        
    except Exception as e:
        print(f"💥 ERRO CRÍTICO NA INICIALIZAÇÃO: {e}")
        # Tenta fechar o pool se ele já tiver sido criado antes do erro
        if db_pool:
            await db_pool.close()
        raise e

    yield
    
    # --- DESLIGAMENTO SEGURO (Graceful Shutdown) ---
    print("🛑 Desligando servidor...")
    
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
    print("✅ Servidor desligado com segurança.")

# ==========================================
# 7. ROTAS FASTAPI (Web)
# ==========================================
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def health_check():
    """Rota pública para o Railway saber que o app está vivo (Health Check)."""
    return {"status": "online", "service": "UP CANAIS SaaS Engine", "version": "1.0.0"}

@app.get("/logs")
async def get_logs():
    """Rota segura apenas para você baixar o arquivo de logs se houver um erro grave."""
    # (Lógica de segurança entrará aqui...)
    return {"error": "Acesso não autorizado"}

@app.post("/pagamentos/webhook")
async def webhook_pagamento(request: Request):
    """Rota futura para receber webhooks de gateways de pagamento."""
    dados = await request.json()
    print("💰 Webhook de pagamento recebido:", dados)
    # Lógica de processamento de VIPs entrará aqui na fase 3...
    return {"status": "recebido"}
