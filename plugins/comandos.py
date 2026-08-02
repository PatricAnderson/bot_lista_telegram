import os
import random
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

import database
from config import ADMIN_ID, CATEGORIAS_DISPONIVEIS, admin_estados
from rotinas import disparar_troca_por_categoria

# Configuração de log para este arquivo específico
logger = logging.getLogger("comandos")

# ==========================================
# COMANDO /start
# ==========================================
@Client.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    logger.info(f"📩 /start recebido de: {message.from_user.id}")
    
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Proteção: Grava o usuário no banco, garantindo que falhas de DB não travem a resposta
    try:
        async with database.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO usuarios (telegram_id, username) VALUES ($1, $2)
                ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username
            """, user_id, username)
        logger.info(f"✅ Usuário {user_id} salvo/atualizado no DB com sucesso.")
    except Exception as e:
        logger.error(f"⚠️ Erro ao registrar usuário no DB: {e}")

    try:
        b_username = client.me.username
        link_adicao = f"https://t.me/{b_username}?startchannel=true&admin=post_messages+edit_messages+delete_messages+invite_users"

        keyboard_rows = [
            [InlineKeyboardButton("➕ Adicionar Bot ao Canal", url=link_adicao)],
            [InlineKeyboardButton("📢 Meus Canais Cadastrados", callback_data="meus_canais")],
            [InlineKeyboardButton("👤 Minha Conta", callback_data="conta")]
        ]
        if ADMIN_ID and user_id == ADMIN_ID:
            keyboard_rows.insert(0, [InlineKeyboardButton("🛠️ Painel Admin", callback_data="admin_painel")])

        await message.reply_text(
            "👋 **Bem-vindo ao UP CANAIS!**\n\n"
            "Gerencie seus canais na rede de troca de divulgações através dos botões abaixo:\n\n"
            "*(Para cadastrar um novo canal, adicione-me como administrador nele).* ",
            reply_markup=InlineKeyboardMarkup(keyboard_rows)
        )
        logger.info("✅ Resposta do /start enviada.")
    except Exception as e:
        logger.error(f"❌ Erro interno ao processar a interface do /start: {e}")

# ==========================================
# COMANDO /importar
# ==========================================
@Client.on_message(filters.command("importar") & filters.private)
async def importar_fakes(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"📩 /importar recebido de: {user_id}")
    
    if ADMIN_ID and user_id != ADMIN_ID:
        return
        
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply_text("⚠️ Responda a um arquivo `.txt` com: `/importar <categoria>`")
        return
        
    partes = message.text.split()
    if len(partes) < 2 or partes[1] not in CATEGORIAS_DISPONIVEIS:
        await message.reply_text("⚠️ **Categoria inválida!**")
        return
        
    categoria_alvo = partes[1]
    msg_status = await message.reply_text("⏳ Processando...")
    
    try:
        arquivo_path = await client.download_media(message.reply_to_message)
        adicionados = 0
        
        with open(arquivo_path, 'r', encoding='utf-8') as f: 
            linhas = f.readlines()
            
        async with database.db_pool.acquire() as conn:
            for linha in linhas:
                if "|" in linha:
                    titulo, link = linha.split("|", 1)
                    fake_id = -random.randint(100000000000, 999999999999)
                    await conn.execute("""
                        INSERT INTO canais (chat_id, titulo, dono_id, categoria, invite_link, membros, ativo, aprovado, semente)
                        VALUES ($1, $2, $3, $4, $5, 150, TRUE, TRUE, TRUE)
                        ON CONFLICT DO NOTHING
                    """, fake_id, titulo.strip(), ADMIN_ID, categoria_alvo, link.strip())
                    adicionados += 1
                    
        os.remove(arquivo_path)
        await msg_status.edit_text(f"🎉 **{adicionados}** canais sementes injetados em `{categoria_alvo}`.")
        logger.info(f"✅ Importação concluída: {adicionados} inseridos em {categoria_alvo}")
    except Exception as e:
        logger.error(f"❌ Erro no /importar: {e}")
        await msg_status.edit_text(f"❌ **Erro:** {e}")

# ==========================================
# COMANDO /admin
# ==========================================
@Client.on_message(filters.command("admin") & filters.private)
async def admin_command(client: Client, message: Message):
    logger.info(f"📩 /admin recebido de: {message.from_user.id}")
    
    if ADMIN_ID and message.from_user.id != ADMIN_ID: 
        return
        
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏳ Canais Pendentes", callback_data="admin_pendentes")],
            [InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink")],
            [InlineKeyboardButton("📋 Links Fixos Cadastrados", callback_data="admin_listlinks")]
        ])
        await message.reply_text("🛠️ **Painel de Administração**", reply_markup=keyboard)
        logger.info("✅ Resposta do /admin enviada.")
    except Exception as e:
        logger.error(f"❌ Erro no /admin: {e}")

# ==========================================
# COMANDO /testar
# ==========================================
@Client.on_message(filters.command("testar"))
async def testar_comando(client: Client, message: Message):
    logger.info(f"📩 /testar recebido de: {message.from_user.id}")
    
    try:
        await message.reply("🔄 Forçando disparo da rotina de troca...")
        await disparar_troca_por_categoria(client)
        await message.reply("✅ Rotina de teste finalizada. Verifique os logs!")
        logger.info("✅ Rotina de teste executada com sucesso.")
    except Exception as e:
        logger.error(f"❌ Falha ao disparar o teste: {e}")
        await message.reply_text(f"❌ Falha ao disparar o teste: {e}")

# ==========================================
# CAPTURAR TEXTO ADMIN
# ==========================================
@Client.on_message(filters.private & ~filters.command(["start", "admin", "testar", "importar"]))
async def capturar_texto_admin(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not ADMIN_ID or user_id != ADMIN_ID or user_id not in admin_estados: 
        return
        
    logger.info(f"📩 Texto capturado do admin {user_id}: {message.text[:20]}...")
        
    try:
        estado = admin_estados[user_id]
        texto = message.text.strip()
        
        if estado["etapa"] == "aguardando_titulo":
            estado["titulo"] = texto
            estado["etapa"] = "aguardando_url"
            await message.reply_text(f"✅ Título: **{texto}**\nEnvie a **URL**:")
        elif estado["etapa"] == "aguardando_url":
            async with database.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO links_fixos (titulo, url, categoria) VALUES ($1, $2, $3)", 
                    estado["titulo"], texto, estado["categoria"]
                )
            del admin_estados[user_id]
            await message.reply_text(
                "🎉 **Link Fixo cadastrado!**", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Painel Admin", callback_data="admin_painel")]])
            )
            logger.info("✅ Link Fixo cadastrado com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro no capturar_texto_admin: {e}")
