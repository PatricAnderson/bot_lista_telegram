import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Importando o pool do banco para poder fazer consultas dentro das rotinas
from database import db_pool 

# Configuração de Logs
logger = logging.getLogger("rotinas")

# 1. Cria a instância global do agendador com o fuso horário correto
scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

# ==========================================
# LÓGICA DAS ROTINAS (Jobs)
# ==========================================

async def disparar_troca_por_categoria():
    logger.info("🔄 Executando rotina: disparar_troca_por_categoria...")
    try:
        # Exemplo de como usar o banco de dados dentro da rotina
        async with db_pool.acquire() as conn:
            # canais = await conn.fetch("SELECT chat_id FROM canais WHERE ativo = TRUE")
            pass
            
        # TODO: Cole aqui a sua lógica de rotação de diretórios, 
        # limite de 20 canais por lista e configuração de títulos limpos (sem os foguetes).
        
        logger.info("✅ Rotina 'disparar_troca_por_categoria' finalizada com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro na rotina de troca por categoria: {e}")

async def monitorar_membros_semanal():
    logger.info("👥 Executando rotina: monitorar_membros_semanal...")
    try:
        # Exemplo de como usar o banco de dados dentro da rotina
        async with db_pool.acquire() as conn:
            # strikes = await conn.fetch("SELECT * FROM strikes_tabela...")
            pass
            
        # TODO: Cole aqui a sua lógica de validação de membros e gerenciamento de strikes.
        
        logger.info("✅ Rotina 'monitorar_membros_semanal' finalizada com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro na rotina de monitoramento semanal: {e}")


# ==========================================
# FUNÇÃO DE REGISTRO (Importada pelo main.py)
# ==========================================

def iniciar_agendamentos():
    """
    Esta função é chamada pelo main.py (no lifespan do FastAPI) quando o sistema liga.
    Ela diz ao scheduler exatamente QUANDO cada função acima deve ser executada.
    """
    logger.info("⏰ Registrando rotinas no agendador...")
    
    # 1. Agendamento de Intervalo (Ex: Rodar a cada 2 horas)
    # Altere "hours=2" para o tempo que desejar (pode usar minutes=30, etc.)
    scheduler.add_job(
        disparar_troca_por_categoria, 
        trigger="interval", 
        hours=2, 
        id="disparar_troca_por_categoria",
        replace_existing=True
    )
    
    # 2. Agendamento Cronometrado (Ex: Rodar todo Domingo à meia-noite)
    # day_of_week="sun" (domingo), hour=0, minute=0
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
