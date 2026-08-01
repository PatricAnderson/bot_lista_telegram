from pyrogram import Client
from pyrogram.types import ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatMemberStatus
import database
from config import CATEGORIAS_DISPONIVEIS

@Client.on_chat_member_updated()
async def bot_added_to_channel(client: Client, update: ChatMemberUpdated):
    if update.new_chat_member and update.new_chat_member.user.is_self and update.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
        chat_id = update.chat.id
        chat_title = update.chat.title
        user_id = update.from_user.id if update.from_user else None
        
        if not user_id: return
        
        try:
            chat_info = await client.get_chat(chat_id)
            membros = getattr(chat_info, "members_count", 0)
            
            if membros < 100:
                await client.send_message(user_id, f"❌ O canal **{chat_title}** possui apenas {membros} inscritos. O mínimo é 100.")
                return

            invite_link = chat_info.invite_link or (f"https://t.me/{chat_info.username}" if chat_info.username else "")

            async with database.db_pool.acquire() as conn:
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
                    botoes.append(linha); linha = []
            if linha: botoes.append(linha)

            await client.send_message(user_id, f"✅ Adicionado em **{chat_title}**!\nSelecione a categoria:", reply_markup=InlineKeyboardMarkup(botoes))
        except Exception: pass