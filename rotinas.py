import logging
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import db_pool 
from config import CATEGORIAS_DISPONIVEIS, bot

logger = logging.getLogger("rotinas")
scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

async def disparar_troca_por_categoria(client_bot=None):
    logger.info("🔄 Executando rotina: disparar_troca_por_categoria (12h/20h)...")
    
    # Em caso de falha na passagem, utiliza o bot importado do config
    client_bot = client_bot or bot

    if not client_bot:
        logger.error("❌ ERRO CRÍTICO: O client não está disponível para o disparo!")
        return

    try:
        async with db_pool.acquire() as conn:
            canais = await conn.fetch("""
                SELECT chat_id, titulo, invite_link, categoria, semente 
                FROM canais 
                WHERE ativo = TRUE AND aprovado = TRUE
            """)
            canais_destino = await conn.fetch("""
                SELECT chat_id, categoria, ultima_mensagem_id 
                FROM canais 
                WHERE ativo = TRUE AND aprovado = TRUE
            """)

            if not canais or not canais_destino:
                logger.warning(f"⚠️ Canais insuficientes no banco.")
                return

        canais_por_categoria = {cat: [] for cat in CATEGORIAS_DISPONIVEIS.keys()}
        for c in canais:
            cat = c['categoria'] if c['categoria'] in canais_por_categoria else "geral"
            canais_por_categoria[cat].append(c)

        for destino in canais_destino:
            chat_id_destino = destino['chat_id']
            cat_destino = destino['categoria'] if destino['categoria'] in canais_por_categoria else "geral"
            ultima_msg_id = destino['ultima_mensagem_id']
            
            if ultima_msg_id:
                try:
                    await client_bot.delete_message(chat_id_destino, ultima_msg_id)
                    logger.info(f"🗑️ Lista anterior (ID: {ultima_msg_id}) apagada no canal {chat_id_destino}")
                except Exception as del_err:
                    logger.warning(f"⚠️ Não foi possível apagar a lista anterior: {del_err}")

            pool_canais = list(canais_por_categoria.get(cat_destino, canais_por_categoria.get("geral", [])))
            
            if len(pool_canais) < 2:
                continue

            reais = [c for c in pool_canais if not c['semente']]
            sementes = [c for c in pool_canais if c['semente']]

            random.shuffle(reais)
            random.shuffle(sementes)

            selecao_final = reais + sementes
            lote_atual = [c for c in selecao_final if c['chat_id'] != chat_id_destino][:20]

            if not lote_atual:
                continue

            texto_lista = f"📋 **Lista de Canais Parceiros - {CATEGORIAS_DISPONIVEIS.get(cat_destino, 'Geral')}**\n\n"
            for canal in lote_atual:
                link = canal['invite_link'] or "#"
                texto_lista += f"• [{canal['titulo']}]({link})\n"

            texto_lista += f"\n🤖 Divulgue seu canal você também!"

            try:
                # Mudança Pyrogram -> Telebot
                msg_enviada = await client_bot.send_message(chat_id_destino, texto_lista, parse_mode="Markdown")
                
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE canais SET ultima_mensagem_id = $1 WHERE chat_id = $2",
                        msg_enviada.message_id, chat_id_destino
                    )
                logger.info(f"📤 [SUCESSO] Lista enviada para: {chat_id_destino}")
            except Exception as ex:
                logger.error(f"❌ Erro ao enviar para o canal {chat_id_destino}: {ex}")

        logger.info("✅ Rotina finalizada com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro crítico: {e}")

async def monitorar_membros_semanal():
    logger.info("👥 Executando rotina: monitorar_membros_semanal...")
    try:
        async with db_pool.acquire() as conn:
            pass
        logger.info("✅ Rotina 'monitorar_membros_semanal' finalizada com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro na rotina: {e}")

def iniciar_agendamentos(client_bot=None):
    logger.info("⏰ Registrando rotinas no agendador...")
    
    scheduler.add_job(
        disparar_troca_por_categoria, 
        args=[client_bot],
        trigger="cron", 
        hour="12,20", 
        minute=0,
        id="disparar_troca_por_categoria",
        replace_existing=True
    )
    
    scheduler.add_job(
        monitorar_membros_semanal, 
        trigger="cron", 
        day_of_week="sun", 
        hour=0, 
        minute=0, 
        id="monitorar_membros_semanal",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("✅ Todas as rotinas registradas.")
