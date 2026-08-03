import logging
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db_pool 
from config import CATEGORIAS_DISPONIVEIS, bot

logger = logging.getLogger("rotinas")
scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

async def disparar_troca_por_categoria(client_bot=None):
    logger.info("🔄 Executando rotina: disparar_troca_por_categoria (12h/20h)...")
    
    client_bot = client_bot or bot

    if not client_bot:
        logger.error("❌ ERRO CRÍTICO: O client não está disponível para o disparo!")
        return

    try:
        # Pega o username do bot para criar o botão de "Participar da Lista"
        try:
            bot_info = await client_bot.get_me()
            bot_link = f"https://t.me/{bot_info.username}"
        except:
            bot_link = "https://t.me/"

        async with db_pool.acquire() as conn:
            # Adicionado a busca da coluna 'membros'
            canais = await conn.fetch("""
                SELECT chat_id, titulo, invite_link, categoria, semente, membros 
                FROM canais 
                WHERE ativo = TRUE AND aprovado = TRUE
            """)
            
            canais_destino = await conn.fetch("""
                SELECT chat_id, categoria, ultima_mensagem_id 
                FROM canais 
                WHERE ativo = TRUE AND aprovado = TRUE AND semente = FALSE
            """)

            links_fixos_db = await conn.fetch("SELECT titulo, url, categoria FROM links_fixos")

            if not canais or not canais_destino:
                logger.warning(f"⚠️ Canais insuficientes no banco.")
                return

        # Calcula totais para a copy do texto
        total_canais = len(canais)
        # Soma os membros (garantindo que ignora valores nulos)
        total_membros = sum(c['membros'] for c in canais if c.get('membros') is not None)
        # Formata o número para o padrão brasileiro (ex: 1.500.000)
        total_membros_fmt = f"{total_membros:,}".replace(",", ".")

        # Organiza os canais por categoria
        canais_por_categoria = {cat: [] for cat in CATEGORIAS_DISPONIVEIS.keys()}
        for c in canais:
            cat = c['categoria'] if c['categoria'] in canais_por_categoria else "geral"
            canais_por_categoria[cat].append(c)

        # Organiza os links fixos por categoria
        links_fixos_por_categoria = {cat: [] for cat in CATEGORIAS_DISPONIVEIS.keys()}
        links_fixos_todas = []
        for lf in links_fixos_db:
            if lf['categoria'] == 'todas':
                links_fixos_todas.append(lf)
            elif lf['categoria'] in links_fixos_por_categoria:
                links_fixos_por_categoria[lf['categoria']].append(lf)

        # Inicia o envio por destino
        for destino in canais_destino:
            chat_id_destino = destino['chat_id']
            cat_destino = destino['categoria'] if destino['categoria'] in canais_por_categoria else "geral"
            ultima_msg_id = destino['ultima_mensagem_id']
            
            if ultima_msg_id:
                try:
                    await client_bot.delete_message(chat_id_destino, ultima_msg_id)
                    logger.info(f"🗑️ Lista apagada no canal {chat_id_destino}")
                except Exception as del_err:
                    logger.warning(f"⚠️ Lista anterior não encontrada no canal {chat_id_destino}: Ignorando...")

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

            # Novo texto formatado com gatilhos e contagem real
            texto_lista = (
                f"💦 **OS MELHORES CANAIS - {CATEGORIAS_DISPONIVEIS.get(cat_destino, 'Geral').upper()}!**\n\n"
                f"📊 Já somos **{total_canais}** canais cadastrados!\n\n"
                f"🚀 **Quer divulgar o seu canal aqui também?**\n"
                f"Cadastre-se no botão abaixo e seja exibido em mais de **{total_canais}** para **{total_membros_fmt} membros** simultâneos!\n\n"
                f"🔥 Acesse agora e divirta-se:"
            )

            markup = InlineKeyboardMarkup()

            # 1. Links Fixos (Máximo 2)
            fixos_deste_nicho = links_fixos_por_categoria.get(cat_destino, []) + links_fixos_todas
            for fixo in fixos_deste_nicho[:2]:
                markup.row(InlineKeyboardButton(text=fixo['titulo'], url=fixo['url']))

            # 2. Botoes dos Canais (2 por linha)
            botoes_canais = []
            for canal in lote_atual:
                link = canal['invite_link'] or "https://t.me/"
                botoes_canais.append(InlineKeyboardButton(text=canal['titulo'], url=link))

            for i in range(0, len(botoes_canais), 2):
                if i + 1 < len(botoes_canais):
                    markup.row(botoes_canais[i], botoes_canais[i+1])
                else:
                    markup.row(botoes_canais[i])

            # 3. Botão de Cadastro no Bot
            markup.row(InlineKeyboardButton(text="📋 Participar da Lista", url=bot_link))

            try:
                msg_enviada = await client_bot.send_message(
                    chat_id_destino, 
                    texto_lista, 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
                
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
        logger.info("✅ Rotina finalizada.")
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
