from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import database
from config import bot, ADMIN_ID, CATEGORIAS_DISPONIVEIS, admin_estados

@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    data = call.data
    user_id = call.from_user.id
    chat_id_msg = call.message.chat.id
    msg_id = call.message.message_id
    
    if data == "conta":
        await bot.answer_callback_query(call.id, "Sua conta está ativa na nossa rede!", show_alert=True)

    elif data == "admin_painel":
        if ADMIN_ID and user_id != ADMIN_ID: return
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("⏳ Canais Pendentes", callback_data="admin_pendentes"))
        markup.row(InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink"))
        markup.row(InlineKeyboardButton("📋 Links Fixos Cadastrados", callback_data="admin_listlinks"))
        markup.row(InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio"))
        await bot.edit_message_text("🛠️ **Painel de Administração**", chat_id_msg, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data == "admin_pendentes":
        if ADMIN_ID and user_id != ADMIN_ID: return
        async with database.db_pool.acquire() as conn:
            pendentes = await conn.fetch("SELECT chat_id, titulo, categoria, membros FROM canais WHERE aprovado = FALSE AND ativo = TRUE")

        if not pendentes:
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel"))
            return await bot.edit_message_text("🎉 Nenhum canal pendente!", chat_id_msg, msg_id, reply_markup=markup)

        texto = "⏳ **Canais Aguardando Aprovação:**\n\n"
        markup = InlineKeyboardMarkup()
        for p in pendentes:
            texto += f"• **{p['titulo']}**\n  └ Cat: {CATEGORIAS_DISPONIVEIS.get(p['categoria'], '')} | {p['membros']} membros\n\n"
            markup.row(
                InlineKeyboardButton(f"✅ {p['titulo'][:15]}", callback_data=f"aprovar_{p['chat_id']}"),
                InlineKeyboardButton(f"❌", callback_data=f"rejeitar_{p['chat_id']}")
            )
        markup.row(InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel"))
        await bot.edit_message_text(texto, chat_id_msg, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("aprovar_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn:
            canal = await conn.fetchrow("UPDATE canais SET aprovado = TRUE, ativo = TRUE WHERE chat_id = $1 RETURNING categoria, dono_id, titulo", chat_id)
            if canal:
                await conn.execute("DELETE FROM canais WHERE chat_id IN (SELECT chat_id FROM canais WHERE semente = TRUE AND categoria = $1 LIMIT 1)", canal['categoria'])
        await bot.answer_callback_query(call.id, "✅ Aprovado!", show_alert=True)
        if canal:
            try: await bot.send_message(canal['dono_id'], f"🎉 Canal **{canal['titulo']}** aprovado!", parse_mode="Markdown")
            except: pass
        call.data = "admin_pendentes"
        return await callback_handler(call)

    elif data.startswith("rejeitar_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn:
            await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1", chat_id)
        await bot.answer_callback_query(call.id, "❌ Rejeitado.", show_alert=True)
        call.data = "admin_pendentes"
        return await callback_handler(call)

    elif data == "admin_addlink":
        if ADMIN_ID and user_id != ADMIN_ID: return
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🌐 TODAS AS CATEGORIAS", callback_data="admaddcat_todas"))
        
        chaves = list(CATEGORIAS_DISPONIVEIS.keys())
        for i in range(0, len(chaves), 2):
            linha = [InlineKeyboardButton(CATEGORIAS_DISPONIVEIS[chaves[i]], callback_data=f"admaddcat_{chaves[i]}")]
            if i + 1 < len(chaves):
                linha.append(InlineKeyboardButton(CATEGORIAS_DISPONIVEIS[chaves[i+1]], callback_data=f"admaddcat_{chaves[i+1]}"))
            markup.row(*linha)
            
        await bot.edit_message_text("Selecione a categoria alvo:", chat_id_msg, msg_id, reply_markup=markup)

    elif data.startswith("admaddcat_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        cat = data.split("_", 1)[1]
        admin_estados[user_id] = {"categoria": cat, "etapa": "aguardando_titulo"}
        await bot.edit_message_text(f"✍️ Alvo: {cat}\nEnvie o **Título**:", chat_id_msg, msg_id, parse_mode="Markdown")

    elif data == "admin_listlinks":
        if ADMIN_ID and user_id != ADMIN_ID: return
        async with database.db_pool.acquire() as conn:
            links = await conn.fetch("SELECT id, titulo, url, categoria FROM links_fixos")
        texto = "📋 **Links:**\n\n"
        markup = InlineKeyboardMarkup()
        for l in links:
            texto += f"• {l['titulo']} ({l['categoria']})\n"
            markup.row(InlineKeyboardButton(f"🗑️ Remover {l['titulo'][:15]}", callback_data=f"admdel_{l['id']}"))
        markup.row(InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel"))
        await bot.edit_message_text(texto, chat_id_msg, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("admdel_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        link_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn: await conn.execute("DELETE FROM links_fixos WHERE id = $1", link_id)
        await bot.answer_callback_query(call.id, "Removido!", show_alert=True)
        call.data = "admin_listlinks"
        return await callback_handler(call)

    elif data == "meus_canais" or data.startswith("pagcanais_"):
        partes = data.split("_")
        offset = int(partes[-1]) if len(partes) > 1 and partes[-1].isdigit() else 0
        
        async with database.db_pool.acquire() as conn:
            canais = await conn.fetch("SELECT chat_id, titulo, ativo, aprovado FROM canais WHERE dono_id = $1 LIMIT 5 OFFSET $2", user_id, offset)
            total = await conn.fetchval("SELECT COUNT(*) FROM canais WHERE dono_id = $1", user_id)

        markup = InlineKeyboardMarkup()
        if not canais:
            markup.row(InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_inicio"))
            return await bot.edit_message_text("Você não possui canais.", chat_id_msg, msg_id, reply_markup=markup)

        texto = f"📢 **Seus Canais** ({total}):\n\n"
        for c in canais:
            status = "✅" if c['ativo'] and c['aprovado'] else ("⏳" if c['ativo'] else "❌")
            texto += f"• {c['titulo']} [{status}]\n"
            markup.row(InlineKeyboardButton(f"⚙️ Gerenciar: {c['titulo'][:15]}", callback_data=f"gerenciar_{c['chat_id']}"))

        nav = []
        if offset > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"pagcanais_{offset - 5}"))
        if offset + 5 < total: nav.append(InlineKeyboardButton("➡️", callback_data=f"pagcanais_{offset + 5}"))
        if nav: markup.row(*nav)
        markup.row(InlineKeyboardButton("⬅️ Início", callback_data="voltar_inicio"))
        
        await bot.edit_message_text(texto, chat_id_msg, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("gerenciar_"):
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn:
            canal = await conn.fetchrow("SELECT * FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)
        if not canal: return
        texto = f"⚙️ {canal['titulo']}\nMembros: {canal['membros']}\nLink: {canal['invite_link']}"
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔄 Atualizar e Ativar", callback_data=f"atualizar_{chat_id}"))
        markup.row(InlineKeyboardButton("🗑️ Excluir", callback_data=f"remover_{chat_id}"))
        markup.row(InlineKeyboardButton("⬅️ Voltar", callback_data="meus_canais"))
        await bot.edit_message_text(texto, chat_id_msg, msg_id, reply_markup=markup)

    elif data.startswith("atualizar_"):
        chat_id = int(data.split("_")[1])
        try:
            chat_info = await bot.get_chat(chat_id)
            novos_membros = await bot.get_chat_member_count(chat_id)
            if novos_membros < 100: 
                return await bot.answer_callback_query(call.id, "Mínimo de 100 membros exigido.", show_alert=True)
                
            link = chat_info.invite_link or (f"https://t.me/{chat_info.username}" if chat_info.username else "")
            
            async with database.db_pool.acquire() as conn:
                await conn.execute("UPDATE canais SET titulo = $1, invite_link = $2, membros = $3, ativo = TRUE WHERE chat_id = $4", chat_info.title, link, novos_membros, chat_id)
            await bot.answer_callback_query(call.id, "Atualizado com sucesso!", show_alert=True)
            call.data = f"gerenciar_{chat_id}"
            return await callback_handler(call)
            
        except Exception as e:
            await bot.answer_callback_query(call.id, "⚠️ Bot perdeu o acesso ao canal ou precisa de admin!", show_alert=True)
            await bot.send_message(
                user_id,
                "⚠️ **Sincronização Necessária!**\n\n"
                "Como o sistema foi reiniciado, o bot esqueceu a chave de acesso deste canal.\n"
                "👉 **Para resolver:** Vá no canal, **encaminhe qualquer mensagem de lá para cá** e depois clique em 'Atualizar' novamente!",
                parse_mode="Markdown"
            )

    elif data.startswith("remover_"):
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn: await conn.execute("DELETE FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)
        await bot.answer_callback_query(call.id, "Apagado!", show_alert=True)
        call.data = "meus_canais"
        return await callback_handler(call)

    elif data.startswith("setcat_"):
        chat_id, cat = int(data.split("_")[1]), data.split("_")[2]
        async with database.db_pool.acquire() as conn: await conn.execute("UPDATE canais SET categoria = $1 WHERE chat_id = $2", cat, chat_id)
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Início", callback_data="voltar_inicio"))
        await bot.edit_message_text(f"Categoria `{cat}` salva! Aguarde aprovação.", chat_id_msg, msg_id, reply_markup=markup, parse_mode="Markdown")
        
        if ADMIN_ID:
            try: await bot.send_message(ADMIN_ID, f"🔔 Novo canal pendente. ID: {chat_id}")
            except: pass

    elif data == "voltar_inicio":
        if user_id in admin_estados: del admin_estados[user_id]
        markup = InlineKeyboardMarkup()
        if ADMIN_ID and user_id == ADMIN_ID: 
            markup.row(InlineKeyboardButton("🛠️ Painel Admin", callback_data="admin_painel"))
        markup.row(InlineKeyboardButton("📢 Meus Canais", callback_data="meus_canais"))
        await bot.edit_message_text("Menu Principal", chat_id_msg, msg_id, reply_markup=markup)
