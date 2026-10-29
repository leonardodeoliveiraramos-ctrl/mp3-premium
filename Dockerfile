FROM python:3.11-slim

# Instalação do FFmpeg e dependências essenciais do Linux
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python garantindo yt-dlp sempre atualizado
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -U yt-dlp && \
    pip install --no-cache-dir -r requirements.txt

# Copiar arquivos do projeto
COPY . .

# Porta padrão (ajustada automaticamente na nuvem pela variável $PORT)
ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
