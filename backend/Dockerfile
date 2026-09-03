FROM python:3.11-slim

# Instala bibliotecas nativas C++ necessárias para OpenCV e FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalação das dependências Python com versões congeladas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baixa previamente os pesos do ArcFace dentro da imagem Docker
# Garante funcionamento permanente offline mesmo se repositórios externos caírem
RUN python -c "from deepface import DeepFace; DeepFace.build_model('ArcFace')"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

