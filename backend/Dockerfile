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

# Baixa previamente os modelos neurais para operação autônoma offline
RUN mkdir -p /app/models && \
    python3 -c "import urllib.request; \
    urllib.request.urlretrieve('https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx', '/app/models/face_detection_yunet_2023mar.onnx'); \
    urllib.request.urlretrieve('https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx', '/app/models/face_recognition_sface_2021dec.onnx')" && \
    python -c "from deepface import DeepFace; DeepFace.build_model('ArcFace')"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

