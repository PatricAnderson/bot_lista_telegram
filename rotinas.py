import logging
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import db_pool 
from config import CATEGORIAS_DISPONIVEIS

logger = logging.getLogger("rotinas")
scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

async def disparar_troca_por_categoria(client=None):
    logger.info("🔄 Executando rotina: disparar_troca_por_categoria (12h/20h)...")
    try:
        async with db_pool.acquire() as conn:
            # 1. Busca todos os canais aptos (reais aprovados + sementes)
            canais = await conn.fetch("""
                SELECT chat_id, titulo, invite_link, categoria, semente 
                FROM canais 
                WHERE ativo = TRUE AND (aprovado = TRUE OR semente = TRUE)
            """)
            
            # 2. Busca todos os canais de destino onde a lista é postada
            # (Adicionamos uma coluna 'ultima_mensagem_id' na tabela canais para guardar o ID da lista anterior)
            canais_destino = await conn.fetch("""
                SELECT chat_id, categoria, ultima_mensagem_id 
                FROM canais 
                WHERE ativo = TRUE AND aprovado = TRUE
            """)

            if not canais or not canais_destino:
                logger.warning("⚠️ Canais insuficientes para o disparo da troca.")
                return

        # Agrupa os canais de conteúdo por categoria
        canais_por_categoria = {cat: [] for cat in CATEGORIAS_DISPONIVEIS.keys()}
        for c in canais:
            cat = c['categoria'] if c['categoria'] in canais_por_categoria else "geral"
            canais_por_categoria[cat].append(c)

        # 3. Para cada canal de destino, apaga a anterior e envia uma lista EXCLUSIVA
        for destino in canais_destino:
            chat_id_destino = destino['chat_id']
            cat_destino = destino['categoria'] if destino['categoria'] in canais_por_categoria else "geral"
            ultima_msg_id = destino['ultima_mensagem_id']
            
            # Se o bot salvou o ID da última lista enviada neste canal, tenta apagá-la primeiro
            if client and ultima_msg_id:
                try:
                    await client.delete_messages(chat_id_destino, ultima_msg_id)
                    logger.info(f"🗑️ Lista anterior (ID: {ultima_msg_id}) apagada no canal {chat_id_destino}")
                except Exception as del_err:
                    logger.warning(f"⚠️ Não foi possível apagar a lista anterior no canal {chat_id_destino}: {del_err}")

            # Pega o pool da categoria do canal
            pool_canais = list(canais_por_categoria.get(cat_destino, canais_por_categoria["geral"]))
            
            if len(pool_canais) < 2:
                continue

            # Separa reais e sementes para garantir prioridade aos usuários reais
            reais = [c for c in pool_canais if not c['semente']]
            sementes = [c for c in pool_canais if c['semente']]

            # EMBARALHAMENTO INDIVIDUAL: Cada canal recebe uma ordem única
            random.shuffle(reais)
            random.shuffle(sementes)

            selecao_final = reais + sementes
            limite_por_lista = 20
            
            # Remove o próprio canal da lista para ele não se recomendar
            lote_atual = [c for c in selecao_final if c['chat_id'] != chat_id_destino][:limite_por_lista]

            if not lote_atual:
                continue

            # Montagem do texto personalizado
            texto_lista = f"📋 **Lista de Canais Parceiros - {CATEGORIAS_DISPONIVEIS.get(cat_destino, 'Geral')}**\n\n"
            for canal in lote_atual:
                link = canal['invite_link'] or "#"
                texto_lista += f"• [{canal['titulo']}]({link})\n"

            texto_lista += f"\n🤖 Divulgue seu canal você também!"

            # Envia a nova lista e salva o ID da mensagem no banco
            if client:
                try:
                    msg_enviada = await client.send_message(chat_id_destino, texto_lista)
                    
                    # Atualiza o banco com o ID da nova mensagem para conseguir apagá-la na próxima rodada
                    async with db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE canais SET ultima_mensagem_id = $1 WHERE chat_id = $2",
                            msg_enviada.id, chat_id_destino
                        )

                    logger.info(f"📤 Nova lista exclusiva enviada e registrada para o canal ID: {chat_id_destino}")
                except Exception as ex:
                    logger.error(f"❌ Erro ao enviar nova lista para o canal {chat_id_destino}: {ex}")

        logger.info("✅ Rotina 'disparar_troca_por_categoria' finalizada com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro na rotina de troca por categoria: {e}")

async def monitorar_membros_semanal():
    logger.info("👥 Executando rotina: monitorar_membros_semanal...")
    try:
        async with db_pool.acquire() as conn:
            pass
        logger.info("✅ Rotina 'monitorar_membros_semanal' finalizada com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro na rotina de monitoramento semanal: {e}")

def iniciar_agendamentos(client_bot=None):
    logger.info("⏰ Registrando rotinas no agendador...")
    
    # Agendamento fixo às 12:00 e às 20:00 todos os dias usando Cron Trigger
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
    
    logger.info("✅ Todas as rotinas foram registradas no APScheduler com sucesso.")
