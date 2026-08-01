import logging
import random
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChatWriteForbidden, ChatAdminRequired, ChannelPrivate, UserBannedInChannel, PeerIdInvalid
import database
from config import CATEGORIAS_DISPONIVEIS

logger = logging.getLogger(__name__)

async def disparar_troca_por_categoria(bot: Client):
    logger.info("Iniciando disparo de listas...")
    try:
        async with database.db_pool.acquire() as conn:
            categorias = await conn.fetch("SELECT DISTINCT categoria FROM canais WHERE ativo = TRUE AND aprovado = TRUE AND categoria IS NOT NULL")

            if not categorias:
                logger.info("⚠️ Nenhuma categoria ativa encontrada para disparo.")
                return False

            total_canais = await conn.fetchval("SELECT COUNT(*) FROM canais WHERE ativo = TRUE AND aprovado = TRUE")

            for cat_row in categorias:
                categoria = cat_row['categoria']

                todos_normais = await conn.fetch("SELECT chat_id, titulo, invite_link FROM canais WHERE categoria = $1 AND vip = FALSE AND ativo = TRUE AND aprovado = TRUE", categoria)
                vips = await conn.fetch("SELECT chat_id, titulo, invite_link FROM canais WHERE categoria = $1 AND vip = TRUE AND ativo = TRUE AND aprovado = TRUE LIMIT 4", categoria)
                links_fixos = await conn.fetch("SELECT id, titulo, url FROM links_fixos WHERE categoria = $1 OR categoria = 'todas'", categoria)
                destinos = await conn.fetch("SELECT chat_id, ultima_mensagem_id, dono_id, titulo FROM canais WHERE categoria = $1 AND ativo = TRUE AND aprovado = TRUE AND semente = FALSE", categoria)

                if not destinos: continue

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

                    elegiveis = [c for c in todos_normais if c['chat_id'] != chat_id_destino]
                    selecionados = random.sample(elegiveis, min(20, len(elegiveis)))

                    botoes = []
                    for v in vips:
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
                    if linha_dupla: botoes.append(linha_dupla)

                    botoes.append([InlineKeyboardButton("📋 Participar da Lista Grátis", url=f"https://t.me/{bot.me.username}?start=start")])
                    keyboard = InlineKeyboardMarkup(botoes)

                    try:
                        if ultima_msg_id:
                            try: await bot.delete_messages(chat_id=chat_id_destino, message_ids=ultima_msg_id)
                            except Exception: pass

                        nova_msg = await bot.send_message(chat_id=chat_id_destino, text=texto_lista, reply_markup=keyboard, disable_web_page_preview=True)
                        await conn.execute("UPDATE canais SET ultima_mensagem_id = $1 WHERE chat_id = $2", nova_msg.id, chat_id_destino)
                        logger.info(f"📤 Lista enviada com sucesso para o canal {chat_id_destino}")

                    except (ChatWriteForbidden, ChatAdminRequired, ChannelPrivate, UserBannedInChannel, PeerIdInvalid) as e:
                        logger.warning(f"🚫 Strike! Sem permissão no canal {chat_id_destino}. Motivo: {e}")
                        await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1", chat_id_destino)
                        try:
                            await bot.send_message(
                                dono_id,
                                f"⚠️ **Aviso de Desligamento Automático!**\n\nFui impedido de enviar a lista no seu canal **{titulo_canal}**.\nSeu canal foi **pausado**. Para voltar, me adicione novamente como Admin e clique em 'Atualizar Nome e Link'."
                            )
                        except Exception: pass
                    except Exception as e:
                        logger.error(f"❌ Erro ao enviar para canal {chat_id_destino}: {e}")

        logger.info("✅ Ciclo de troca de divulgação concluído!")
        return True
    except Exception as e:
        logger.error(f"❌ Erro no disparo diário: {e}")
        return False

async def monitorar_membros_semanal(bot: Client):
    logger.info("🔍 Iniciando varredura semanal de membros...")
    try:
        async with database.db_pool.acquire() as conn:
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
                        logger.info(f"📉 Canal {chat_id} pausado (queda: {membros_atuais}).")
                        try:
                            await bot.send_message(dono_id, f"📉 **Alerta!** O canal **{titulo}** caiu para {membros_atuais} membros (Mínimo: 100). Foi pausado.")
                        except: pass
                except (ChatWriteForbidden, ChatAdminRequired, ChannelPrivate, UserBannedInChannel, PeerIdInvalid):
                    await conn.execute("UPDATE canais SET ativo = FALSE WHERE chat_id = $1", chat_id)
                except Exception: pass
        logger.info("✅ Varredura semanal concluída!")
    except Exception as e:
        logger.error(f"Erro na varredura: {e}")