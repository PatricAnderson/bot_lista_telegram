from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import database
from config import bot, CATEGORIAS_DISPONIVEIS

@bot.my_chat_member_handler()
async def bot_added_to_channel(update):
    new_status = update.new_chat_member.status
    if new_status == 'administrator':
        chat_id = update.chat.id
        chat_title = update.chat.title
        user_id = update.from_user.id if update.from_user else None
        
        if not user_id: return
        
        try:
            chat_info = await bot.get_chat(chat_id)
            membros = await bot.get_chat_member_count(chat_id)
            
            if membros < 100:
                await bot.send_message(user_id, f"❌ O canal **{chat_title}** possui apenas {membros} inscritos. O mínimo é 100.", parse_mode="Markdown")
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

            markup = InlineKeyboardMarkup()
            chaves = list(CATEGORIAS_DISPONIVEIS.keys())
            for i in range(0, len(chaves), 2):
                linha = [InlineKeyboardButton(CATEGORIAS_DISPONIVEIS[chaves[i]], callback_data=f"setcat_{chat_id}_{chaves[i]}")]
                if i + 1 < len(chaves):
                    linha.append(InlineKeyboardButton(CATEGORIAS_DISPONIVEIS[chaves[i+1]], callback_data=f"setcat_{chat_id}_{chaves[i+1]}"))
                markup.row(*linha)

            await bot.send_message(user_id, f"✅ Adicionado em **{chat_title}**!\nSelecione a categoria:", reply_markup=markup, parse_mode="Markdown")
        except Exception: pass
