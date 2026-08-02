import os
import telebot
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

# Variáveis de ambiente puxadas do Railway
TOKEN = os.environ.get("BOT_TOKEN")
# A URL pública que o Railway gera para o seu projeto (ex: https://upcanais-production.up.railway.app)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") 

bot = telebot.TeleBot(TOKEN)

# ---------------------------------------------------------
# Lógica do Bot (Handlers)
# ---------------------------------------------------------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    # Aqui você pode inserir sua lógica de banco de dados (PostgreSQL)
    bot.reply_to(message, "🚀 UP CANAIS migrado e operando via Webhook no Railway!")

# ---------------------------------------------------------
# Configuração do FastAPI e Webhook
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Executado ao ligar o servidor: Limpa webhooks antigos e seta o novo
    bot.remove_webhook()
    if WEBHOOK_URL:
        bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        print(f"Webhook configurado para: {WEBHOOK_URL}/webhook")
    yield
    # Executado ao desligar o servidor
    bot.remove_webhook()

app = FastAPI(lifespan=lifespan)

# Rota que o Telegram vai "bater" para entregar as mensagens
@app.post("/webhook")
async def process_webhook(request: Request):
    if request.headers.get('content-type') == 'application/json':
        json_string = await request.body()
        update = telebot.types.Update.de_json(json_string.decode('utf-8'))
        bot.process_new_updates([update])
        return {"status": "ok"}
    return {"status": "error"}

@app.get("/")
def home():
    return {"status": "Servidor UP CANAIS online e rodando!"}
