import os
import random
import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from config import bot, ADMIN_ID, CATEGORIAS_DISPONIVEIS, admin_estados
from rotinas import disparar_troca_por_categoria

logger = logging.getLogger("comandos")[cite: 11]

@bot.message_handler(commands=['start'])
async def start_command(message):
    logger.info(f"📩 /start recebido de: {message.from_user.id}")[cite: 11]
    
    user_id = message.from_user.id
    username = message.from_user.username
    
    try:
        async with database.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO usuarios (telegram_id, username) VALUES ($1, $2)
                ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username
            """, user_id, username)[cite: 11]
    except Exception as e:
        logger.error(f"⚠️ Erro ao registrar usuário no DB: {e}")[cite: 11]

    try:
        bot_info = await bot.get_me()
        b_username = bot_info.username
        link_adicao = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"[cite: 11]

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_adicao))
        markup.row(InlineKeyboardButton("📢 Meus Canais Cadastrados", callback_data="meus_canais"))
        markup.row(InlineKeyboardButton("👤 Minha Conta", callback_data="conta"))
        
        if ADMIN_ID and user_id == ADMIN_ID:
            # Insere no topo
            markup.keyboard.insert(0, [InlineKeyboardButton("🛠️ Painel Admin", callback_data="admin_painel")])[cite: 11]

        await bot.reply_to(
            message,
            "👋 **Bem-vindo ao UP CANAIS!**\n\n"
            "Gerencie seus canais na rede de troca de divulgações através dos botões abaixo:\n\n"
            "*(Para cadastrar um novo canal, adicione-me como administrador nele).* ",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"❌ Erro interno ao processar a interface do /start: {e}")[cite: 11]

@bot.message_handler(commands=['importar'])
async def importar_fakes(message):
    user_id = message.from_user.id
    if ADMIN_ID and user_id != ADMIN_ID: return
        
    if not message.reply_to_message or not message.reply_to_message.document:
        await bot.reply_to(message, "⚠️ Responda a um arquivo `.txt` com: `/importar <categoria>`", parse_mode="Markdown")[cite: 11]
        return
        
    partes = message.text.split()
    if len(partes) < 2 or partes[1] not in CATEGORIAS_DISPONIVEIS:
        await bot.reply_to(message, "⚠️ **Categoria inválida!**", parse_mode="Markdown")[cite: 11]
        return
        
    categoria_alvo = partes[1]
    msg_status = await bot.reply_to(message, "⏳ Processando...")[cite: 11]
    
    try:
        file_info = await bot.get_file(message.reply_to_message.document.file_id)
        arquivo_bytes = await bot.download_file(file_info.file_path)
        
        adicionados = 0
        linhas = arquivo_bytes.decode('utf-8').splitlines()
            
        async with database.db_pool.acquire() as conn:
            for linha in linhas:
                if "|" in linha:
                    titulo, link = linha.split("|", 1)
                    fake_id = -random.randint(100000000000, 999999999999)[cite: 11]
                    await conn.execute("""
                        INSERT INTO canais (chat_id, titulo, dono_id, categoria, invite_link, membros, ativo, aprovado, semente)
                        VALUES ($1, $2, $3, $4, $5, 150, TRUE, TRUE, TRUE)
                        ON CONFLICT DO NOTHING
                    """, fake_id, titulo.strip(), ADMIN_ID, categoria_alvo, link.strip())[cite: 11]
                    adicionados += 1
                    
        await bot.edit_message_text(f"🎉 **{adicionados}** canais sementes injetados em `{categoria_alvo}`.", message.chat.id, msg_status.message_id, parse_mode="Markdown")[cite: 11]
    except Exception as e:
        await bot.edit_message_text(f"❌ **Erro:** {e}", message.chat.id, msg_status.message_id, parse_mode="Markdown")[cite: 11]

@bot.message_handler(commands=['admin'])
async def admin_command(message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID: return[cite: 11]
        
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("⏳ Canais Pendentes", callback_data="admin_pendentes"))
    markup.row(InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink"))
    markup.row(InlineKeyboardButton("📋 Links Fixos Cadastrados", callback_data="admin_listlinks"))
    
    await bot.reply_to(message, "🛠️ **Painel de Administração**", reply_markup=markup, parse_mode="Markdown")[cite: 11]

@bot.message_handler(commands=['testar'])
async def testar_comando(message):
    try:
        await bot.reply_to(message, "🔄 Forçando disparo da rotina de troca...")[cite: 11]
        await disparar_troca_por_categoria(bot)
        await bot.reply_to(message, "✅ Rotina de teste finalizada. Verifique os logs!")[cite: 11]
    except Exception as e:
        await bot.reply_to(message, f"❌ Falha ao disparar o teste: {e}")[cite: 11]

@bot.message_handler(content_types=['text'])
async def capturar_texto_admin(message):
    user_id = message.from_user.id
    if not ADMIN_ID or user_id != ADMIN_ID or user_id not in admin_estados: return[cite: 11]
    if message.text.startswith('/'): return
        
    try:
        estado = admin_estados[user_id]
        texto = message.text.strip()
        
        if estado["etapa"] == "aguardando_titulo":
            estado["titulo"] = texto
            estado["etapa"] = "aguardando_url"[cite: 11]
            await bot.reply_to(message, f"✅ Título: **{texto}**\nEnvie a **URL**:", parse_mode="Markdown")[cite: 11]
        elif estado["etapa"] == "aguardando_url":
            async with database.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO links_fixos (titulo, url, categoria) VALUES ($1, $2, $3)", 
                    estado["titulo"], texto, estado["categoria"]
                )[cite: 11]
            del admin_estados[user_id]
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⬅️ Painel Admin", callback_data="admin_painel"))
            await bot.reply_to(message, "🎉 **Link Fixo cadastrado!**", reply_markup=markup, parse_mode="Markdown")[cite: 11]
    except Exception as e:
        logger.error(f"❌ Erro no capturar_texto_admin: {e}")[cite: 11]
