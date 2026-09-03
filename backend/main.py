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

# Inicializa detector Haar Cascade nativo do OpenCV para detecção de face no baseline
FACE_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)

def detectar_face_roi(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    Detecta a maior face no frame e calcula a sub-região de interesse (ROI)
    centralizada na testa e bochechas (evitando cabelos, pescoço, roupas e fundo).
    Retorna (x1, y1, x2, y2) ou None se nenhum rosto for identificado.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(50, 50)
    )
    if len(faces) == 0:
        return None

    # Seleciona o maior rosto presente no frame
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])

    # Recorte proporcional anatômico (testa, nariz e bochechas)
    x1 = x + int(w * 0.20)
    x2 = x + int(w * 0.80)
    y1 = y + int(h * 0.15)
    y2 = y + int(h * 0.70)

    return x1, y1, x2, y2

def extrair_cor_media_face(
    frame: np.ndarray,
    roi_box: tuple[int, int, int, int] | None = None
) -> tuple[float, float, float]:
    """
    Extrai a média dos canais B, G, R na região de interesse do rosto.
    Se roi_box (x1, y1, x2, y2) for informada, utiliza o recorte dinâmico;
    caso contrário, aplica recorte central de segurança (30% a 70%).
    """
    h, w, _ = frame.shape
    if roi_box:
        x1, y1, x2, y2 = roi_box
        x1, x2 = max(0, min(x1, w - 1)), max(1, min(x2, w))
        y1, y2 = max(0, min(y1, h - 1)), max(1, min(y2, h))
        roi = frame[y1:y2, x1:x2]
    else:
        roi = frame[int(h * 0.3):int(h * 0.7), int(w * 0.3):int(w * 0.7)]

    if roi.size == 0:
        b, g, r = cv2.mean(frame)[:3]
    else:
        b, g, r = cv2.mean(roi)[:3]
    return b, g, r

def calcular_nitidez_laplaciano(
    frame: np.ndarray,
    roi_box: tuple[int, int, int, int] | None = None
) -> float:
    """Calcula o índice de foco/nitidez usando a variância do operador Laplaciano."""
    if roi_box:
        x1, y1, x2, y2 = roi_box
        h, w = frame.shape[:2]
        x1, x2 = max(0, min(x1, w - 1)), max(1, min(x2, w))
        y1, y2 = max(0, min(y1, h - 1)), max(1, min(y2, h))
        crop = frame[y1:y2, x1:x2]
        if crop.size > 0:
            frame = crop

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def selecionar_melhor_frame_nitido(
    video_path: str,
    max_frames: int = 10,
    roi_box: tuple[int, int, int, int] | None = None
) -> np.ndarray:
    """
    Varre os primeiros frames do vídeo e seleciona aquele com maior nitidez
    (maior variância Laplaciana), eliminando motion blur e piscadas antes do ArcFace.
    """
    cap = cv2.VideoCapture(video_path)
    best_frame = None
    best_score = -1.0
    frames_lidos = 0

    while cap.isOpened() and frames_lidos < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        score = calcular_nitidez_laplaciano(frame, roi_box)
        if score > best_score:
            best_score = score
            best_frame = frame.copy()

        frames_lidos += 1

    cap.release()

    if best_frame is None:
        raise HTTPException(status_code=400, detail="Não foi possível ler frames do vídeo.")

    return best_frame

def validar_reflexo_delta_rgb(
    video_path: str,
    cores_esperadas: list[str],
    mock_roi: tuple[int, int, int, int] | None = None
) -> tuple[bool, str, tuple[int, int, int, int] | None]:
    """
    Valida a prova de vida calculando o ganho relativo (Delta) de cada canal de cor
    em relação ao frame de iluminação inicial (baseline), resistindo a salas iluminadas.
    Detecta dinamicamente a posição do rosto para garantir amostragem de pele.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, "Não foi possível abrir o arquivo de vídeo gravado.", None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 10:
        cap.release()
        return False, f"Vídeo muito curto para análise ({total_frames} frames).", None

    # 1. Detecção dinâmica do rosto nos primeiros frames
    face_roi = mock_roi
    frames_buffer = []

    if face_roi is None:
        check_frames = min(10, total_frames)
        for _ in range(check_frames):
            ret, f = cap.read()
            if not ret:
                break
            frames_buffer.append(f)
            detected = detectar_face_roi(f)
            if detected:
                face_roi = detected
                break

        if face_roi is None:
            cap.release()
            return False, "Nenhum rosto identificado no vídeo", None

    # 2. Leitura do frame baseline (início do vídeo com tela escura)
    frame_base = frames_buffer[0] if frames_buffer else cap.read()[1]
    if frame_base is None:
        cap.release()
        return False, "Não foi possível ler o primeiro frame de iluminação base.", None

    b_base, g_base, r_base = extrair_cor_media_face(frame_base, face_roi)
    b_base = max(b_base, 1.0)
    g_base = max(g_base, 1.0)
    r_base = max(r_base, 1.0)

    # Reposiciona o ponteiro para leitura dos blocos de cores
    cap.set(cv2.CAP_PROP_POS_FRAMES, 1)

    # 3. Segmentação temporal do vídeo pelas cores
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
            b_atual, g_atual, r_atual = extrair_cor_media_face(frame, face_roi)

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
        return True, "Reflexo espectral correspondente à pele real.", face_roi

    return False, f"Reflexo não compatível ({respostas_corretas}/{len(cores_esperadas)} cores validadas).", face_roi

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

        # 2. ETAPA 1: Prova de Vida Ativa com ROI Dinâmica do Rosto
        is_live, liveness_msg, face_roi = validar_reflexo_delta_rgb(video_path, cores)
        if not is_live:
            return {
                "verified": False,
                "is_live": False,
                "reason": liveness_msg,
                "status": liveness_msg
            }

        # 3. ETAPA 2: Seleção Inteligente do Frame com Maior Nitidez (Filtro Laplaciano)
        melhor_frame = selecionar_melhor_frame_nitido(video_path, max_frames=10, roi_box=face_roi)
        cv2.imwrite(frame_extraido_path, melhor_frame)

        # 4. ETAPA 3: Comparação Biométrica 1:1 com ArcFace
        from deepface import DeepFace
        try:
            resultado = DeepFace.verify(
                img1_path=frame_extraido_path,
                img2_path=profile_path,
                model_name="ArcFace",
                detector_backend="opencv",
                distance_metric="cosine",
                enforce_detection=True
            )
        except ValueError as ve:
            erro_str = str(ve).lower()
            if "face could not be detected" in erro_str or "confirm that the image contains a face" in erro_str:
                # Distingue se o rosto não foi encontrado na foto de cadastro ou na captura
                if "profile_photo" in erro_str or "img2" in erro_str:
                    msg_amigavel = "Não conseguimos identificar seu rosto na foto de cadastro. Por favor, escolha uma foto mais nítida e bem iluminada."
                elif "face_probe" in erro_str or "img1" in erro_str:
                    msg_amigavel = "Não conseguimos identificar seu rosto claramente no vídeo. Por favor, mantenha o rosto centralizado na moldura."
                else:
                    msg_amigavel = "Não conseguimos identificar seu rosto na foto de cadastro. Por favor, escolha uma foto mais nítida e bem iluminada."

                return {
                    "verified": False,
                    "is_live": True,
                    "reason": msg_amigavel,
                    "status": msg_amigavel
                }
            raise ve

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

