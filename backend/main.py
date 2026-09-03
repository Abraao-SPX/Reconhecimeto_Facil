import os
import shutil
import tempfile
import random
import string
import time
import json
import hmac
import hashlib
import base64
import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="BeyondTime - Liveness & Face Verification Service",
    description="Serviço biométrico anti-spoofing com flash espectral de cores, ArcFace, JWT e Rate Limiting",
    version="1.1.0"
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

# ==============================================================================
# SEGURANÇA: RATE LIMITING CONTRA FORÇA BRUTA (SLIDING WINDOW)
# ==============================================================================
VERIFY_ATTEMPTS: dict[str, list[float]] = {}
MAX_ATTEMPTS_PER_MINUTE = 5
RATE_LIMIT_WINDOW_SECONDS = 60

def aplicar_rate_limit(client_ip: str):
    """Bloqueia tentativas consecutivas automatizadas por força bruta."""
    now = time.time()
    timestamps = VERIFY_ATTEMPTS.get(client_ip, [])
    # Filtra apenas tentativas dentro da janela recente
    timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(timestamps) >= MAX_ATTEMPTS_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="Muitas tentativas consecutivas de verificação. Por favor, aguarde 1 minuto para tentar novamente."
        )
    timestamps.append(now)
    VERIFY_ATTEMPTS[client_ip] = timestamps

# ==============================================================================
# SEGURANÇA: INTEGRAÇÃO COM SPRING BOOT (TOKEN JWT ASSINADO HS256)
# ==============================================================================
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "beyondtime_super_secret_biometric_key_2026")

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def base64url_decode(data_str: str) -> bytes:
    rem = len(data_str) % 4
    if rem > 0:
        data_str += '=' * (4 - rem)
    return base64.urlsafe_b64decode(data_str)

def gerar_jwt_biometria(user_id: str, distance: float, threshold: float) -> str:
    """Gera um Token JWT assinado HMAC-SHA256 para atestar a aprovação biométrica ao backend principal."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "verified": True,
        "badge": "SELO_VERIFICADO_OURO",
        "biometrics_model": "ArcFace",
        "distance": round(distance, 4),
        "threshold": threshold,
        "iat": now,
        "exp": now + (24 * 3600), # Válido por 24 horas
        "iss": "beyondtime-biometrics-service"
    }
    header_bytes = json.dumps(header, separators=(',', ':')).encode('utf-8')
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')

    h_b64 = base64url_encode(header_bytes)
    p_b64 = base64url_encode(payload_bytes)
    message = f"{h_b64}.{p_b64}".encode('utf-8')

    signature = hmac.new(JWT_SECRET_KEY.encode('utf-8'), message, hashlib.sha256).digest()
    sig_b64 = base64url_encode(signature)

    return f"{h_b64}.{p_b64}.{sig_b64}"

def validar_jwt_biometria(token: str) -> dict:
    """Valida e decodifica o Token JWT gerado pelo serviço biométrico."""
    parts = token.split('.')
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Formato de token JWT inválido.")

    h_b64, p_b64, sig_b64 = parts
    message = f"{h_b64}.{p_b64}".encode('utf-8')
    expected_sig = hmac.new(JWT_SECRET_KEY.encode('utf-8'), message, hashlib.sha256).digest()

    if not hmac.compare_digest(base64url_encode(expected_sig), sig_b64):
        raise HTTPException(status_code=401, detail="Assinatura de token biométrico inválida.")

    payload = json.loads(base64url_decode(p_b64).decode('utf-8'))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="Token biométrico expirado.")

    return payload

# ==============================================================================
# AUDITORIA ANTIFRAUDE: REGISTRO DE TENTATIVAS EM MEMÓRIA
# ==============================================================================
AUDIT_LOGS: list[dict] = []
MAX_AUDIT_LOGS = 200

def registrar_auditoria(entry: dict):
    """Armazena logs de auditoria para inspeção de tentativas de fraude."""
    entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    AUDIT_LOGS.append(entry)
    if len(AUDIT_LOGS) > MAX_AUDIT_LOGS:
        AUDIT_LOGS.pop(0)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "BeyondTime Liveness & Biometrics API",
        "model": "ArcFace",
        "version": "1.1.0"
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

@app.get("/verify/token/validate")
def validate_token_endpoint(token: str = Query(..., description="Token JWT biométrico")):
    """Permite ao backend Spring Boot do BeyondTime validar o token emitido."""
    payload = validar_jwt_biometria(token)
    return {"valid": True, "claims": payload}

@app.get("/audit/logs")
def get_audit_logs(limit: int = Query(50, ge=1, le=200)):
    """Retorna os registros de auditoria mais recentes para análise antifraude."""
    return {"total": len(AUDIT_LOGS), "logs": AUDIT_LOGS[-limit:]}

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
    request: Request,
    video: UploadFile = File(...),
    profile_photo: UploadFile = File(...),
    expected_colors: str = Form(...), # Ex: "VERMELHO,AZUL,VERDE"
    user_id: str = Form("senior_user_anonymous")
):
    # 1. Proteção contra ataques automatizados (Rate Limiting de 5 req/min por IP)
    client_ip = request.client.host if request.client else "unknown"
    aplicar_rate_limit(client_ip)

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
            registrar_auditoria({
                "client_ip": client_ip,
                "user_id": user_id,
                "verified": False,
                "is_live": False,
                "reason": liveness_msg
            })
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

                registrar_auditoria({
                    "client_ip": client_ip,
                    "user_id": user_id,
                    "verified": False,
                    "is_live": True,
                    "reason": msg_amigavel
                })
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

        # 5. ETAPA 4: Geração de Token JWT Assinado e Atribuição de Selo
        badge = None
        jwt_token = None
        if verified:
            badge = "SELO_VERIFICADO_OURO"
            jwt_token = gerar_jwt_biometria(user_id, distance, threshold)

        registrar_auditoria({
            "client_ip": client_ip,
            "user_id": user_id,
            "verified": verified,
            "is_live": True,
            "distance": round(distance, 4),
            "badge": badge,
            "reason": "Sucesso" if verified else "Distância acima do limiar"
        })

        return {
            "verified": verified,
            "is_live": True,
            "distance": round(distance, 4),
            "threshold": threshold,
            "badge": badge,
            "jwt_token": jwt_token,
            "status": "Identidade confirmada com sucesso!" if verified else "Rosto não compatível com o perfil cadastrado."
        }

    except Exception as e:
        registrar_auditoria({
            "client_ip": client_ip,
            "user_id": user_id,
            "verified": False,
            "is_live": False,
            "error": str(e)
        })
        return {"verified": False, "is_live": False, "error": str(e)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

