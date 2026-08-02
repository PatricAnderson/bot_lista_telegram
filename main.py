import os
import telebot
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

from config import bot, WEBHOOK_URL
from database import init_db, close_db
from rotinas import iniciar_agendamentos

# Importação dos módulos de plugins para registro
import plugins.comandos
import plugins.callbacks
import plugins.eventos

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa o pool de conexões com o banco[cite: 5, 6]
    await init_db()
    
    # Inicia os agendamentos das listas
    iniciar_agendamentos(bot)
    
    # Configuração do Webhook do Telebot[cite: 6]
    await bot.remove_webhook()
    if WEBHOOK_URL:
        url_formatada = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        await bot.set_webhook(url=url_formatada)
        print(f"✅ Webhook configurado para: {url_formatada}")
    yield
    # Limpeza no encerramento
    await bot.remove_webhook()
    await close_db()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def process_webhook(request: Request):
    if request.headers.get('content-type') == 'application/json':
        json_string = await request.body()
        update = telebot.types.Update.de_json(json_string.decode('utf-8'))
        # Processamento assíncrono para compatibilidade com o banco de dados
        await bot.process_new_updates([update])
        return {"status": "ok"}
    return {"status": "error"}

@app.get("/")
def home():
    return {"status": "Servidor UP CANAIS online e rodando!"}
