from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChatWriteForbidden, ChatAdminRequired
import database
from config import ADMIN_ID, CATEGORIAS_DISPONIVEIS, admin_estados

@Client.on_callback_query()
async def callback_handler(client: Client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "conta":
        await callback_query.answer("Sua conta está ativa na nossa rede!", show_alert=True)

    elif data == "admin_painel":
        if ADMIN_ID and user_id != ADMIN_ID: return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏳ Canais Pendentes", callback_data="admin_pendentes")],
            [InlineKeyboardButton("➕ Adicionar Link Fixo", callback_data="admin_addlink")],
            [InlineKeyboardButton("📋 Links Fixos Cadastrados", callback_data="admin_listlinks")],
            [InlineKeyboardButton("⬅️ Voltar ao Início", callback_data="voltar_inicio")]
        ])
        await callback_query.message.edit_text("🛠️ **Painel de Administração**", reply_markup=keyboard)

    elif data == "admin_pendentes":
        if ADMIN_ID and user_id != ADMIN_ID: return
        async with database.db_pool.acquire() as conn:
            pendentes = await conn.fetch("SELECT chat_id, titulo, categoria, membros FROM canais WHERE aprovado = FALSE AND ativo = TRUE")

        if not pendentes:
            return await callback_query.message.edit_text("🎉 Nenhum canal pendente!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel")]]))

        texto = "⏳ **Canais Aguardando Aprovação:**\n\n"
        botoes = []
        for p in pendentes:
            texto += f"• **{p['titulo']}**\n  └ Cat: {CATEGORIAS_DISPONIVEIS.get(p['categoria'], '')} | {p['membros']} membros\n\n"
            botoes.append([
                InlineKeyboardButton(f"✅ {p['titulo'][:15]}", callback_data=f"aprovar_{p['chat_id']}"),
                InlineKeyboardButton(f"❌", callback_data=f"rejeitar_{p['chat_id']}")
            ])
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel")])
        await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

    elif data.startswith("aprovar_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn:
            canal = await conn.fetchrow("UPDATE canais SET aprovado = TRUE, ativo = TRUE WHERE chat_id = $1 RETURNING categoria, dono_id, titulo", chat_id)
            if canal:
                await conn.execute("DELETE FROM canais WHERE chat_id IN (SELECT chat_id FROM canais WHERE semente = TRUE AND categoria = $1 LIMIT 1)", canal['categoria'])
        await callback_query.answer("✅ Aprovado!", show_alert=True)
        if canal:
            try: await client.send_message(canal['dono_id'], f"🎉 Canal **{canal['titulo']}** aprovado!")
            except: pass
        callback_query.data = "admin_pendentes"
        return await callback_handler(client, callback_query)

    elif data.startswith("rejeitar_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn:
            await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1", chat_id)
        await callback_query.answer("❌ Rejeitado.", show_alert=True)
        callback_query.data = "admin_pendentes"
        return await callback_handler(client, callback_query)

    elif data == "admin_addlink":
        if ADMIN_ID and user_id != ADMIN_ID: return
        botoes = [[InlineKeyboardButton("🌐 TODAS AS CATEGORIAS", callback_data="admaddcat_todas")]]
        linha = []
        for k, v in CATEGORIAS_DISPONIVEIS.items():
            linha.append(InlineKeyboardButton(v, callback_data=f"admaddcat_{k}"))
            if len(linha) == 2:
                botoes.append(linha); linha = []
        if linha: botoes.append(linha)
        await callback_query.message.edit_text("Selecione a categoria alvo:", reply_markup=InlineKeyboardMarkup(botoes))

    elif data.startswith("admaddcat_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        cat = data.split("_", 1)[1]
        admin_estados[user_id] = {"categoria": cat, "etapa": "aguardando_titulo"}
        await callback_query.message.edit_text(f"✍️ Alvo: {cat}\nEnvie o **Título**:")

    elif data == "admin_listlinks":
        if ADMIN_ID and user_id != ADMIN_ID: return
        async with database.db_pool.acquire() as conn:
            links = await conn.fetch("SELECT id, titulo, url, categoria FROM links_fixos")
        texto = "📋 **Links:**\n\n"
        botoes = []
        for l in links:
            texto += f"• {l['titulo']} ({l['categoria']})\n"
            botoes.append([InlineKeyboardButton(f"🗑️ Remover {l['titulo'][:15]}", callback_data=f"admdel_{l['id']}")])
        botoes.append([InlineKeyboardButton("⬅️ Voltar", callback_data="admin_painel")])
        await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

    elif data.startswith("admdel_"):
        if ADMIN_ID and user_id != ADMIN_ID: return
        link_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn: await conn.execute("DELETE FROM links_fixos WHERE id = $1", link_id)
        await callback_query.answer("Removido!", show_alert=True)
        callback_query.data = "admin_listlinks"
        return await callback_handler(client, callback_query)

    elif data == "meus_canais" or data.startswith("pagcanais_"):
        offset = int(data.split("_")[1]) if "_" in data else 0
        async with database.db_pool.acquire() as conn:
            canais = await conn.fetch("SELECT chat_id, titulo, ativo, aprovado FROM canais WHERE dono_id = $1 LIMIT 5 OFFSET $2", user_id, offset)
            total = await conn.fetchval("SELECT COUNT(*) FROM canais WHERE dono_id = $1", user_id)

        if not canais: return await callback_query.message.edit_text("Você não possui canais.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_inicio")]]))

        texto = f"📢 **Seus Canais** ({total}):\n\n"
        botoes = []
        for c in canais:
            status = "✅" if c['ativo'] and c['aprovado'] else ("⏳" if c['ativo'] else "❌")
            texto += f"• {c['titulo']} [{status}]\n"
            botoes.append([InlineKeyboardButton(f"⚙️ Gerenciar: {c['titulo'][:15]}", callback_data=f"gerenciar_{c['chat_id']}")])

        nav = []
        if offset > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"pagcanais_{offset - 5}"))
        if offset + 5 < total: nav.append(InlineKeyboardButton("➡️", callback_data=f"pagcanais_{offset + 5}"))
        if nav: botoes.append(nav)
        botoes.append([InlineKeyboardButton("⬅️ Início", callback_data="voltar_inicio")])
        await callback_query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(botoes))

    elif data.startswith("gerenciar_"):
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn:
            canal = await conn.fetchrow("SELECT * FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)
        if not canal: return
        texto = f"⚙️ {canal['titulo']}\nMembros: {canal['membros']}\nLink: {canal['invite_link']}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Atualizar e Ativar", callback_data=f"atualizar_{chat_id}")],
            [InlineKeyboardButton("🗑️ Excluir", callback_data=f"remover_{chat_id}")],
            [InlineKeyboardButton("⬅️ Voltar", callback_data="meus_canais")]
        ])
        await callback_query.message.edit_text(texto, reply_markup=kb)

    elif data.startswith("atualizar_"):
        chat_id = int(data.split("_")[1])
        try:
            chat_info = await client.get_chat(chat_id)
            novos_membros = getattr(chat_info, "members_count", 0)
            if novos_membros < 100: return await callback_query.answer("Mínimo de 100 membros exigido.", show_alert=True)
            link = chat_info.invite_link or (f"https://t.me/{chat_info.username}" if chat_info.username else "")
            
            async with database.db_pool.acquire() as conn:
                await conn.execute("UPDATE canais SET titulo = $1, invite_link = $2, membros = $3, ativo = TRUE WHERE chat_id = $4", chat_info.title, link, novos_membros, chat_id)
            await callback_query.answer("Atualizado!", show_alert=True)
            callback_query.data = f"gerenciar_{chat_id}"
            return await callback_handler(client, callback_query)
        except ChatWriteForbidden: await callback_query.answer("O bot precisa ser Admin!", show_alert=True)

    elif data.startswith("remover_"):
        chat_id = int(data.split("_")[1])
        async with database.db_pool.acquire() as conn: await conn.execute("DELETE FROM canais WHERE chat_id = $1 AND dono_id = $2", chat_id, user_id)
        await callback_query.answer("Apagado!", show_alert=True)
        callback_query.data = "meus_canais"
        return await callback_handler(client, callback_query)

    elif data.startswith("setcat_"):
        chat_id, cat = int(data.split("_")[1]), data.split("_")[2]
        async with database.db_pool.acquire() as conn: await conn.execute("UPDATE canais SET categoria = $1 WHERE chat_id = $2", cat, chat_id)
        await callback_query.message.edit_text(f"Categoria `{cat}` salva! Aguarde aprovação.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Início", callback_data="voltar_inicio")]]))
        
        if ADMIN_ID:
            try: await client.send_message(ADMIN_ID, f"🔔 Novo canal pendente. ID: {chat_id}")
            except: pass

    elif data == "voltar_inicio":
        if user_id in admin_estados: del admin_estados[user_id]
        kb = [[InlineKeyboardButton("📢 Meus Canais", callback_data="meus_canais")]]
        if ADMIN_ID and user_id == ADMIN_ID: kb.insert(0, [InlineKeyboardButton("🛠️ Painel Admin", callback_data="admin_painel")])
        await callback_query.message.edit_text("Menu Principal", reply_markup=InlineKeyboardMarkup(kb))
