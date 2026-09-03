import os
import shutil
import tempfile
import random
import string
import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="BeyondTime - Liveness & Face Verification Service",
    description="Serviço biométrico anti-spoofing com flash espectral de cores e ArcFace",
    version="1.0.0"
)

# Habilita CORS para permitir chamadas diretas do React Native no celular
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CORES_DISPONIVEIS = ["VERMELHO", "AZUL", "VERDE"]

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "BeyondTime Liveness & Biometrics API",
        "model": "ArcFace"
    }

@app.get("/challenge")
def get_challenge():
    """
    Sorteia uma ordem aleatória de cores para o aplicativo exibir na tela
    e gera um token de sessão para validação.
    """
    cores_sorteadas = random.sample(CORES_DISPONIVEIS, 3)
    token = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    return {
        "session_token": token,
        "colors": cores_sorteadas,
        "flash_duration_ms": 750
    }

def extrair_cor_media_face(frame: np.ndarray) -> tuple[float, float, float]:
    """Extrai média dos canais B, G, R na região central onde o rosto se encontra."""
    h, w, _ = frame.shape
    # Recorte da região central (30% a 70% vertical e horizontal)
    roi = frame[int(h * 0.3):int(h * 0.7), int(w * 0.3):int(w * 0.7)]
    b, g, r = cv2.mean(roi)[:3]
    return b, g, r

def validar_reflexo_delta_rgb(video_path: str, cores_esperadas: list[str]) -> tuple[bool, str]:
    """
    Valida a prova de vida calculando o ganho relativo (Delta) de cada canal de cor
    em relação ao frame de iluminação inicial (baseline), resistindo a salas iluminadas.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, "Não foi possível abrir o arquivo de vídeo gravado."

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 10:
        cap.release()
        return False, f"Vídeo muito curto para análise ({total_frames} frames)."

    # 1. Leitura do frame baseline (início do vídeo com tela escura)
    ret, frame_base = cap.read()
    if not ret:
        cap.release()
        return False, "Não foi possível ler o primeiro frame de iluminação base."

    b_base, g_base, r_base = extrair_cor_media_face(frame_base)
    b_base = max(b_base, 1.0)
    g_base = max(g_base, 1.0)
    r_base = max(r_base, 1.0)

    # 2. Segmentação temporal do vídeo pelas cores
    segmento = (total_frames - 2) // len(cores_esperadas)
    frame_idx = 1
    cor_idx = 0
    respostas_corretas = 0

    while cap.isOpened() and cor_idx < len(cores_esperadas):
        ret, frame = cap.read()
        if not ret:
            break

        # Amostra no ponto central de cada bloco de cor
        if frame_idx == 2 + (cor_idx * segmento) + (segmento // 2):
            b_atual, g_atual, r_atual = extrair_cor_media_face(frame)

            delta_r = (r_atual - r_base) / r_base
            delta_g = (g_atual - g_base) / g_base
            delta_b = (b_atual - b_base) / b_base

            cor_esperada = cores_esperadas[cor_idx].strip().upper()

            # Valida se o canal esperado teve o maior ganho relativo de reflexo na pele
            if cor_esperada == "VERMELHO" and (delta_r > delta_g and delta_r > delta_b):
                respostas_corretas += 1
            elif cor_esperada == "AZUL" and (delta_b > delta_r and delta_b > delta_g):
                respostas_corretas += 1
            elif cor_esperada == "VERDE" and (delta_g > delta_r and delta_g > delta_b):
                respostas_corretas += 1

            cor_idx += 1

        frame_idx += 1

    cap.release()
    
    if respostas_corretas == len(cores_esperadas):
        return True, "Reflexo espectral correspondente à pele real."
    
    return False, f"Reflexo não compatível ({respostas_corretas}/{len(cores_esperadas)} cores validadas)."

@app.post("/verify")
async def verify_identity(
    video: UploadFile = File(...),
    profile_photo: UploadFile = File(...),
    expected_colors: str = Form(...) # Ex: "VERMELHO,AZUL,VERDE"
):
    cores = [c.strip() for c in expected_colors.split(",") if c.strip()]
    temp_dir = tempfile.mkdtemp()

    video_path = os.path.join(temp_dir, "challenge_video.mp4")
    profile_path = os.path.join(temp_dir, "profile_photo.jpg")
    frame_extraido_path = os.path.join(temp_dir, "face_probe.jpg")

    try:
        # 1. Salva uploads em diretório temporário
        with open(video_path, "wb") as f:
            shutil.copyfileobj(video.file, f)
        with open(profile_path, "wb") as f:
            shutil.copyfileobj(profile_photo.file, f)

        # 2. ETAPA 1: Prova de Vida Ativa por Reflexo Espectral
        is_live, liveness_msg = validar_reflexo_delta_rgb(video_path, cores)
        if not is_live:
            return {
                "verified": False,
                "is_live": False,
                "reason": f"Falha na prova de vida: {liveness_msg}",
                "status": "Falha na prova de vida"
            }

        # 3. ETAPA 2: Extração de frame nítido do início do vídeo
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, 5)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            raise HTTPException(status_code=400, detail="Não foi possível ler frames do vídeo.")

        cv2.imwrite(frame_extraido_path, frame)

        # 4. ETAPA 3: Comparação Biométrica 1:1 com ArcFace
        from deepface import DeepFace
        resultado = DeepFace.verify(
            img1_path=frame_extraido_path,
            img2_path=profile_path,
            model_name="ArcFace",
            detector_backend="opencv",
            distance_metric="cosine",
            enforce_detection=True
        )

        verified = bool(resultado.get("verified", False))
        distance = float(resultado.get("distance", 1.0))
        threshold = float(resultado.get("threshold", 0.68))

        return {
            "verified": verified,
            "is_live": True,
            "distance": round(distance, 4),
            "threshold": threshold,
            "status": "Identidade confirmada com sucesso!" if verified else "Rosto não compatível com o perfil cadastrado."
        }

    except Exception as e:
        return {"verified": False, "is_live": False, "error": str(e)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
