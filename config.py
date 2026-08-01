import os

# Credenciais
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

# Categorias
CATEGORIAS_DISPONIVEIS = {
    "filmes": "🎬 Filmes, Séries & Animes",
    "adulto": "🔞 Adulto / NSFW",
    "tech": "💻 Tecnologia, Games & Softwares",
    "noticias": "📢 Notícias, Política & Utilidades",
    "financas": "📈 Finanças, Cripto & Investimentos",
    "esportes": "⚽ Esportes & Futebol",
    "musica": "🎵 Músicas, Áudios & Entretenimento",
    "humor": "😂 Humor, Memes & Comédia",
    "vendas": "🛒 Vendas, Afiliados & Lojas",
    "geral": "🌐 Variedades & Geral"
}

# Dicionário compartilhado em memória para criar os links fixos
admin_estados = {}