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
import sqlite3
import cv2
import numpy as np
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Reconhecimento Fácil - Microsserviço de Biometria & Prova de Vida",
    description="Microsserviço independente anti-spoofing com flash espectral de cores, YuNet, SFace, JWT e Rate Limiting",
    version="1.2.0"
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
# SEGURANÇA: EMISSÃO DE TOKEN JWT ASSINADO (HS256)
# ==============================================================================
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "reconhecimento_facil_secret_key_2026")

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def base64url_decode(data_str: str) -> bytes:
    rem = len(data_str) % 4
    if rem > 0:
        data_str += '=' * (4 - rem)
    return base64.urlsafe_b64decode(data_str)

def gerar_jwt_biometria(user_id: str, distance: float, threshold: float) -> str:
    """Gera um Token JWT assinado HMAC-SHA256 para atestar a aprovação biométrica ao backend cliente."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "verified": True,
        "biometrics_model": "YuNet-SFace",
        "distance": round(distance, 4),
        "threshold": threshold,
        "iat": now,
        "exp": now + (24 * 3600), # Válido por 24 horas
        "iss": "reconhecimento-facil-service"
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

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Reconhecimento Fácil - Biometrics API",
        "model": "YuNet-SFace",
        "docs_url": "/docs",
        "health_url": "/health"
    }

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "Reconhecimento Fácil - Biometrics API",
        "model": "YuNet-SFace",
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
    """Permite a sistemas externos (Spring Boot, Node.js, Python, etc.) validar o token emitido."""
    payload = validar_jwt_biometria(token)
    return {"valid": True, "claims": payload}

@app.get("/audit/logs")
def get_audit_logs(limit: int = Query(50, ge=1, le=200)):
    """Retorna os registros de auditoria mais recentes para análise antifraude."""
    return {"total": len(AUDIT_LOGS), "logs": AUDIT_LOGS[-limit:]}

# Inicializa detector Haar Cascade nativo do OpenCV para detecção de face no baseline (fallback seguro)
face_cascade = None
try:
    if hasattr(cv2, "data") and hasattr(cv2, "CascadeClassifier"):
        FACE_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
except Exception:
    face_cascade = None

# ==============================================================================
# BIOMETRIA FACIAL ADAPTATIVA (YUNET + SFACE) - RECONHECIMENTO FÁCIL
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(BASE_DIR, "debug")
os.makedirs(DEBUG_DIR, exist_ok=True)

STORAGE_DIR = os.path.join(BASE_DIR, "storage")
STORAGE_FACES_DIR = os.path.join(STORAGE_DIR, "faces")
DB_PATH = os.path.join(STORAGE_DIR, "biometria.db")
os.makedirs(STORAGE_FACES_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            primary_embedding TEXT NOT NULL,
            centroid_embedding TEXT NOT NULL,
            samples_count INTEGER DEFAULT 1,
            photo_filename TEXT NOT NULL,
            latest_photo_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            embedding TEXT
        )
    """)
    # Migração transparente se a tabela users já existir com formato legado
    cursor.execute("PRAGMA table_info(users)")
    cols = [c[1] for c in cursor.fetchall()]
    if "embedding" in cols and "primary_embedding" not in cols:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN primary_embedding TEXT")
            cursor.execute("ALTER TABLE users ADD COLUMN centroid_embedding TEXT")
            cursor.execute("ALTER TABLE users ADD COLUMN samples_count INTEGER DEFAULT 1")
            cursor.execute("ALTER TABLE users ADD COLUMN latest_photo_filename TEXT")
            cursor.execute("ALTER TABLE users ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            cursor.execute("UPDATE users SET primary_embedding = embedding, centroid_embedding = embedding, latest_photo_filename = photo_filename WHERE primary_embedding IS NULL")
        except Exception:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS biometric_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            embedding TEXT NOT NULL,
            sample_type TEXT NOT NULL,
            distance_to_anchor REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

init_db()

def normalizar_embedding(emb: np.ndarray) -> np.ndarray:
    """Normaliza o vetor embedding para norma unitária (L2 = 1.0)."""
    emb_f = emb.astype(np.float32)
    norm = np.linalg.norm(emb_f)
    if norm > 1e-6:
        return emb_f / norm
    return emb_f

def db_salvar_usuario_inicial(user_id: str, name: str, embedding: np.ndarray, photo_filename: str):
    """
    Cadastra o usuário inicial sem comparação com outros rostos.
    Guarda o vetor biométrico como a Âncora Primária e Centroide inicial (samples_count = 1).
    Registra também a primeira amostra no histórico biometric_samples.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    emb_norm = normalizar_embedding(embedding)
    emb_json = json.dumps(emb_norm.tolist())

    cursor.execute("PRAGMA table_info(users)")
    cols = [c[1] for c in cursor.fetchall()]

    if "embedding" in cols:
        cursor.execute("""
            INSERT OR REPLACE INTO users (
                id, name, primary_embedding, centroid_embedding, samples_count,
                photo_filename, latest_photo_filename, created_at, updated_at, embedding
            ) VALUES (?, ?, ?, ?, 1, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
        """, (user_id, name, emb_json, emb_json, photo_filename, photo_filename, emb_json))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO users (
                id, name, primary_embedding, centroid_embedding, samples_count,
                photo_filename, latest_photo_filename, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (user_id, name, emb_json, emb_json, photo_filename, photo_filename))

    cursor.execute("""
        INSERT INTO biometric_samples (user_id, embedding, sample_type, distance_to_anchor, created_at)
        VALUES (?, ?, 'registration', 0.0, CURRENT_TIMESTAMP)
    """, (user_id, emb_json))

    conn.commit()
    conn.close()

def db_adicionar_amostra_login(user_id: str, new_embedding: np.ndarray, latest_photo_filename: str, distance_to_anchor: float) -> int:
    """
    Aprendizado contínuo: atualiza o perfil biométrico do usuário após cada login aprovado.
    Calcula o novo centroide ponderado normalizado L2 e persiste no histórico.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT centroid_embedding, samples_count FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return 1

    old_centroid = np.array(json.loads(row[0]), dtype=np.float32)
    old_count = int(row[1]) if row[1] else 1

    new_emb_norm = normalizar_embedding(new_embedding)
    new_count = old_count + 1

    # Atualização ponderada cumulativa: Centroid_novo = (Centroid_antigo * N + novo_vetor) / (N + 1)
    updated_centroid = (old_centroid * float(old_count) + new_emb_norm) / float(new_count)
    updated_centroid = normalizar_embedding(updated_centroid)

    emb_json = json.dumps(new_emb_norm.tolist())
    centroid_json = json.dumps(updated_centroid.tolist())

    cursor.execute("""
        INSERT INTO biometric_samples (user_id, embedding, sample_type, distance_to_anchor, created_at)
        VALUES (?, ?, 'login_adaptation', ?, CURRENT_TIMESTAMP)
    """, (user_id, emb_json, round(distance_to_anchor, 4)))

    cursor.execute("PRAGMA table_info(users)")
    cols = [c[1] for c in cursor.fetchall()]

    if "embedding" in cols:
        cursor.execute("""
            UPDATE users
            SET centroid_embedding = ?,
                embedding = ?,
                samples_count = ?,
                latest_photo_filename = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (centroid_json, centroid_json, new_count, latest_photo_filename, user_id))
    else:
        cursor.execute("""
            UPDATE users
            SET centroid_embedding = ?,
                samples_count = ?,
                latest_photo_filename = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (centroid_json, new_count, latest_photo_filename, user_id))

    conn.commit()
    conn.close()
    return new_count

def db_listar_usuarios():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, primary_embedding, centroid_embedding, samples_count,
               photo_filename, latest_photo_filename, created_at, updated_at
        FROM users ORDER BY updated_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    users = []
    for r in rows:
        users.append({
            "id": r[0],
            "name": r[1],
            "primary_embedding": np.array(json.loads(r[2]), dtype=np.float32),
            "centroid_embedding": np.array(json.loads(r[3]), dtype=np.float32),
            "samples_count": r[4] or 1,
            "photo_filename": r[5],
            "latest_photo_filename": r[6] or r[5],
            "created_at": r[7],
            "updated_at": r[8]
        })
    return users

def db_buscar_usuario(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, primary_embedding, centroid_embedding, samples_count,
               photo_filename, latest_photo_filename, created_at, updated_at
        FROM users WHERE id = ?
    """, (user_id,))
    r = cursor.fetchone()
    conn.close()
    if not r:
        return None
    return {
        "id": r[0],
        "name": r[1],
        "primary_embedding": np.array(json.loads(r[2]), dtype=np.float32),
        "centroid_embedding": np.array(json.loads(r[3]), dtype=np.float32),
        "samples_count": r[4] or 1,
        "photo_filename": r[5],
        "latest_photo_filename": r[6] or r[5],
        "created_at": r[7],
        "updated_at": r[8]
    }

def db_buscar_historico_amostras(user_id: str, limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, sample_type, distance_to_anchor, created_at
        FROM biometric_samples
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "sample_type": r[1],
            "distance_to_anchor": r[2],
            "created_at": r[3]
        }
        for r in rows
    ]


YUNET_PATH = os.getenv("YUNET_MODEL_PATH", os.path.join(BASE_DIR, "models", "face_detection_yunet_2023mar.onnx"))
SFACE_PATH = os.getenv("SFACE_MODEL_PATH", os.path.join(BASE_DIR, "models", "face_recognition_sface_2021dec.onnx"))

detector_yunet = None
recognizer_sface = None

if os.path.exists(YUNET_PATH) and os.path.exists(SFACE_PATH):
    try:
        detector_yunet = cv2.FaceDetectorYN.create(
            model=YUNET_PATH,
            config="",
            input_size=[320, 320],
            score_threshold=0.5,
            nms_threshold=0.3,
            top_k=5000
        )
        recognizer_sface = cv2.FaceRecognizerSF.create(
            model=SFACE_PATH,
            config=""
        )
        print("INFO: Pipeline biométrico YuNet + SFace inicializado com sucesso!")
    except Exception as e:
        print(f"WARN: Falha ao carregar YuNet/SFace: {e}")

def detectar_face_yunet(image: np.ndarray):
    """Detecta a face mais proeminente e seus 5 marcos anatômicos com YuNet."""
    if detector_yunet is None or image is None:
        return None
    h, w = image.shape[:2]
    scale = 1.0
    max_dim = 640
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img_resized = cv2.resize(image, (int(w * scale), int(h * scale)))
    else:
        img_resized = image

    h_r, w_r = img_resized.shape[:2]
    detector_yunet.setInputSize((w_r, h_r))
    _, faces = detector_yunet.detect(img_resized)

    if faces is None or len(faces) == 0:
        return None

    best_face = max(faces, key=lambda f: f[-1])
    if scale != 1.0:
        best_face = best_face.copy()
        best_face[:14] /= scale

    return best_face

def extrair_embedding_e_recorte(frame: np.ndarray) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Detecta face com YuNet e extrai vetor embedding SFace (128D) e recorte facial alinhado."""
    if recognizer_sface is None or detector_yunet is None or frame is None:
        return None, None
    face_data = None
    frame_final = frame
    for rot in [None, cv2.ROTATE_90_COUNTERCLOCKWISE, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180]:
        cand = cv2.rotate(frame, rot) if rot is not None else frame
        f_data = detectar_face_yunet(cand)
        if f_data is not None:
            frame_final = cand
            face_data = f_data
            break
    if face_data is None:
        return None, None
    aligned = recognizer_sface.alignCrop(frame_final, face_data)
    feat = recognizer_sface.feature(aligned)
    return feat, aligned

def detectar_face_roi(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    Detecta o rosto e calcula a sub-região de interesse (ROI) para análise de reflexo.
    Utiliza YuNet quando disponível (muito mais preciso) ou Haar Cascade como fallback.
    """
    if detector_yunet is not None:
        face = detectar_face_yunet(frame)
        if face is not None:
            x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
            x1 = max(0, x + int(w * 0.20))
            x2 = min(frame.shape[1], x + int(w * 0.80))
            y1 = max(0, y + int(h * 0.15))
            y2 = min(frame.shape[0], y + int(h * 0.70))
            return x1, y1, x2, y2

    if face_cascade is not None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(50, 50)
        )
        if len(faces) > 0:
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            x1 = x + int(w * 0.20)
            x2 = x + int(w * 0.80)
            y1 = y + int(h * 0.15)
            y2 = y + int(h * 0.70)
            return x1, y1, x2, y2

    return None

def detectar_face_com_rotacao(frame: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int] | None, int | None]:
    """
    Testa rotações (0°, 270°, 90°) para encontrar a face na orientação vertical correta.
    Muitas câmeras frontais Android gravam frames deitados (90°/270° do sensor nativo).
    Retorna o frame rotacionado na vertical, a ROI da face e o rot_code do OpenCV.
    """
    # 1. Tenta orientação original
    roi = detectar_face_roi(frame)
    if roi is not None:
        return frame, roi, None

    # 2. Tenta 270° (rotação padrão da câmera frontal Android para ficar em pé)
    rot270 = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    roi270 = detectar_face_roi(rot270)
    if roi270 is not None:
        return rot270, roi270, cv2.ROTATE_90_COUNTERCLOCKWISE

    # 3. Tenta 90° (horário)
    rot90 = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    roi90 = detectar_face_roi(rot90)
    if roi90 is not None:
        return rot90, roi90, cv2.ROTATE_90_CLOCKWISE

    # 4. Tenta 180°
    rot180 = cv2.rotate(frame, cv2.ROTATE_180)
    roi180 = detectar_face_roi(rot180)
    if roi180 is not None:
        return rot180, roi180, cv2.ROTATE_180

    return frame, None, None

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
    max_frames: int = 40,
    roi_box: tuple[int, int, int, int] | None = None,
    rot_code: int | None = None
) -> np.ndarray:
    """
    Varre os frames do vídeo e seleciona aquele com maior nitidez e melhor iluminação facial,
    garantindo que o rosto esteja perfeitamente orientado na vertical para o ArcFace.
    """
    cap = cv2.VideoCapture(video_path)
    best_frame = None
    best_score = -1.0
    frames_lidos = 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Pula os 3 primeiros frames escuros da inicialização
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(4, total_frames // 4))

    while cap.isOpened() and frames_lidos < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        if rot_code is not None:
            frame = cv2.rotate(frame, rot_code)

        current_roi = detectar_face_roi(frame) or roi_box
        score = calcular_nitidez_laplaciano(frame, current_roi)

        if current_roi:
            x1, y1, x2, y2 = current_roi
            crop = frame[y1:y2, x1:x2]
            if crop.size > 0:
                brilho = np.mean(crop)
                if brilho > 35:
                    score += brilho # Bonifica frames bem iluminados durante o flash

        if score > best_score:
            best_score = score
            best_frame = frame.copy()

        frames_lidos += 1

    cap.release()

    if best_frame is None:
        cap = cv2.VideoCapture(video_path)
        ret, best_frame = cap.read()
        cap.release()
        if rot_code is not None and best_frame is not None:
            best_frame = cv2.rotate(best_frame, rot_code)

    return best_frame if best_frame is not None else np.zeros((240, 320, 3), dtype=np.uint8)

def validar_reflexo_delta_rgb(
    video_path: str,
    cores_esperadas: list[str],
    mock_roi: tuple[int, int, int, int] | None = None
) -> tuple[bool, str, tuple[int, int, int, int] | None]:
    """
    Valida a prova de vida calculando o ganho relativo (Delta) de cada canal de cor
    em relação ao frame de iluminação inicial (baseline), resistindo a salas iluminadas.
    Detecta dinamicamente a posição do rosto e a rotação correta (0°, 90°, 270°).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, "Não foi possível abrir o arquivo de vídeo gravado.", None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 6:
        cap.release()
        return False, f"Vídeo muito curto para análise ({total_frames} frames).", None

    # 1. Detecção dinâmica do rosto e orientação correta nos primeiros frames
    face_roi = mock_roi
    rot_code = None
    frames_buffer = []

    if face_roi is None:
        check_frames = min(15, total_frames)
        for _ in range(check_frames):
            ret, f = cap.read()
            if not ret:
                break
            frames_buffer.append(f)
            _, detected_roi, detected_rot = detectar_face_com_rotacao(f)
            if detected_roi is not None:
                face_roi = detected_roi
                rot_code = detected_rot
                break

        if face_roi is None:
            cap.release()
            return False, "Nenhum rosto identificado no vídeo", None

    # 2. Leitura do frame baseline (início do vídeo com tela escura)
    frame_base_raw = frames_buffer[0] if frames_buffer else cap.read()[1]
    if frame_base_raw is None:
        cap.release()
        return False, "Não foi possível ler o primeiro frame de iluminação base.", None

    frame_base = cv2.rotate(frame_base_raw, rot_code) if rot_code is not None else frame_base_raw
    b_base, g_base, r_base = extrair_cor_media_face(frame_base, face_roi)
    b_base = max(b_base, 1.0)
    g_base = max(g_base, 1.0)
    r_base = max(r_base, 1.0)

    # 3. Segmentação temporal do vídeo pelas cores com amostragem em janela
    frames_restantes = []
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if rot_code is not None:
            frame = cv2.rotate(frame, rot_code)
        frames_restantes.append(frame)
    cap.release()

    total_validos = len(frames_restantes)
    if total_validos < 6:
        return False, f"Vídeo com frames insuficientes ({total_validos} frames).", face_roi

    segmento = total_validos // len(cores_esperadas)
    respostas_corretas = 0

    for cor_idx, cor in enumerate(cores_esperadas):
        cor_esperada = cor.strip().upper()
        # Amostra múltiplos frames no miolo do flash para evitar ruído de exposição/piscadas
        inicio = cor_idx * segmento + max(1, segmento // 4)
        fim = (cor_idx + 1) * segmento - max(1, segmento // 4)
        janela = frames_restantes[inicio:max(inicio + 1, fim)]

        cor_validada = False
        for f in janela:
            b_atual, g_atual, r_atual = extrair_cor_media_face(f, face_roi)
            delta_r = (r_atual - r_base) / r_base
            delta_g = (g_atual - g_base) / g_base
            delta_b = (b_atual - b_base) / b_base

            # Exige que o canal da cor esperada domine os outros canais em pelo menos 10%
            if cor_esperada == "VERMELHO" and (delta_r > delta_g * 1.10 and delta_r > delta_b * 1.10):
                cor_validada = True
                break
            elif cor_esperada == "AZUL" and (delta_b > delta_r * 1.10 and delta_b > delta_g * 1.10):
                cor_validada = True
                break
            elif cor_esperada == "VERDE" and (delta_g > delta_r * 1.10 and delta_g > delta_b * 1.10):
                cor_validada = True
                break

        if cor_validada:
            respostas_corretas += 1

    # Em ambientes reais, validar 2 de 3 cores garante que é uma pessoa real (fotos pontuam 0/3)
    minimo_exigido = 2 if len(cores_esperadas) >= 3 else len(cores_esperadas)
    if respostas_corretas >= minimo_exigido:
        return True, "Reflexo espectral correspondente à pele real.", face_roi

    return False, f"Reflexo não compatível ({respostas_corretas}/{len(cores_esperadas)} cores validadas).", face_roi

def calcular_distancia_usuario(probe_embedding: np.ndarray, user: dict) -> float:
    """
    Compara o embedding ao vivo do login contra o perfil biométrico completo:
    1. Distância contra a Âncora Primária do cadastro (d_anchor).
    2. Distância contra o Centroide Adaptativo consolidado (d_centroid).
    Retorna a menor distância encontrada (quanto menor, mais próximo).
    """
    if recognizer_sface is None or probe_embedding is None:
        return 1.0

    p_norm = normalizar_embedding(probe_embedding)

    # 1. Distância para âncora inicial
    anchor = user.get("primary_embedding")
    sim_anchor = float(recognizer_sface.match(p_norm, anchor, cv2.FaceRecognizerSF_FR_COSINE)) if anchor is not None else -1.0
    dist_anchor = max(0.0, 1.0 - sim_anchor)

    # 2. Distância para o centroide adaptativo
    centroid = user.get("centroid_embedding")
    sim_centroid = float(recognizer_sface.match(p_norm, centroid, cv2.FaceRecognizerSF_FR_COSINE)) if centroid is not None else -1.0
    dist_centroid = max(0.0, 1.0 - sim_centroid)

    return min(dist_anchor, dist_centroid)

@app.post("/register")
async def register_biometrics(
    request: Request,
    video: UploadFile = File(...),
    name: str = Form(...),
    user_id: Optional[str] = Form(None),
    expected_colors: Optional[str] = Form(None)
):
    """
    Cadastra a biometria facial de um novo usuário DIRETAMENTE AO VIVO via vídeo gravado da câmera.
    Sem precisar de foto da galeria.
    Valida a prova de vida se expected_colors for fornecido.
    Extrai o frame mais nítido com Laplaciano, detecta e alinha a face com YuNet,
    calcula o embedding de 128 dimensões com SFace e salva no SQLite e storage/faces.
    """
    client_ip = request.client.host if request.client else "unknown"
    aplicar_rate_limit(client_ip)

    name_clean = name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="O nome do usuário é obrigatório.")

    uid = user_id.strip() if user_id and user_id.strip() else f"user_{int(time.time())}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"

    temp_dir = tempfile.mkdtemp()
    video_path = os.path.join(temp_dir, "register_video.mp4")

    try:
        with open(video_path, "wb") as f:
            shutil.copyfileobj(video.file, f)

        face_roi = None
        if expected_colors and expected_colors.strip():
            cores = [c.strip() for c in expected_colors.split(",") if c.strip()]
            is_live, liveness_msg, face_roi = validar_reflexo_delta_rgb(video_path, cores)
            if not is_live:
                return {
                    "success": False,
                    "is_live": False,
                    "reason": liveness_msg,
                    "status": liveness_msg
                }

        # Seleciona o frame mais nítido
        melhor_frame = selecionar_melhor_frame_nitido(video_path, max_frames=40, roi_box=face_roi)

        # Extrai embedding e recorte facial alinhado com YuNet + SFace
        feat, aligned_crop = extrair_embedding_e_recorte(melhor_frame)
        if feat is None or aligned_crop is None:
            return {
                "success": False,
                "is_live": True,
                "reason": "Não foi possível identificar um rosto nítido e de frente. Mantenha o rosto centralizado e bem iluminado.",
                "status": "Falha na detecção facial"
            }

        photo_filename = f"{uid}_anchor.jpg"
        photo_full_path = os.path.join(STORAGE_FACES_DIR, photo_filename)
        cv2.imwrite(photo_full_path, aligned_crop)

        # Salva o usuário com a primeira amostra no SQLite (sem comparação prévia)
        db_salvar_usuario_inicial(uid, name_clean, feat, photo_filename)

        registrar_auditoria({
            "client_ip": client_ip,
            "user_id": uid,
            "action": "register",
            "name": name_clean,
            "samples_count": 1,
            "success": True
        })

        return {
            "success": True,
            "user_id": uid,
            "name": name_clean,
            "photo_url": f"/faces/{photo_filename}",
            "samples_count": 1,
            "message": f"Biometria facial de {name_clean} cadastrada com sucesso! Primeira amostra âncora armazenada."
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.get("/users")
def list_registered_users():
    """Retorna a lista de todos os usuários cadastrados com suas contagens de amostras aprendidas."""
    users = db_listar_usuarios()
    return {
        "total": len(users),
        "users": [
            {
                "id": u["id"],
                "name": u["name"],
                "samples_count": u["samples_count"],
                "photo_url": f"/faces/{u['photo_filename']}",
                "latest_photo_url": f"/faces/{u['latest_photo_filename']}",
                "created_at": u["created_at"],
                "updated_at": u["updated_at"]
            }
            for u in users
        ]
    }

@app.get("/users/{user_id}/history")
def get_user_biometric_history(user_id: str):
    """Retorna o histórico de amostras biométricas aprendidas nos logins do usuário."""
    user = db_buscar_usuario(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    history = db_buscar_historico_amostras(user_id)
    return {
        "user_id": user["id"],
        "name": user["name"],
        "samples_count": user["samples_count"],
        "created_at": user["created_at"],
        "updated_at": user["updated_at"],
        "history": history
    }

@app.get("/faces/{filename}")
def get_face_photo(filename: str):
    """Serve a foto facial salva no banco de dados biométrico."""
    safe_name = os.path.basename(filename)
    file_path = os.path.join(STORAGE_FACES_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Foto biométrica não encontrada.")
    return FileResponse(file_path, media_type="image/jpeg")

@app.delete("/users/{user_id}")
def delete_registered_user(user_id: str):
    """Remove um usuário, suas fotos biométricas e seu histórico de amostras."""
    user = db_buscar_usuario(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    for p_key in ["photo_filename", "latest_photo_filename"]:
        p_name = user.get(p_key)
        if p_name:
            photo_path = os.path.join(STORAGE_FACES_DIR, p_name)
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except Exception:
                    pass
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM biometric_samples WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Usuário {user_id} e histórico biométrico excluídos com sucesso."}

@app.post("/verify")
async def verify_identity(
    request: Request,
    video: UploadFile = File(...),
    expected_colors: str = Form(...), # Ex: "VERMELHO,AZUL,VERDE"
    profile_photo: Optional[UploadFile] = File(None),
    user_id: Optional[str] = Form(None)
):
    """
    Verificação biométrica ao vivo contra o banco de dados (1:N ou 1:1) ou foto de perfil.
    NÃO exige foto da galeria quando o banco já possui usuários cadastrados.
    """
    client_ip = request.client.host if request.client else "unknown"
    aplicar_rate_limit(client_ip)

    cores = [c.strip() for c in expected_colors.split(",") if c.strip()]
    temp_dir = tempfile.mkdtemp()

    video_path = os.path.join(temp_dir, "challenge_video.mp4")
    profile_path = os.path.join(temp_dir, "profile_photo.jpg") if profile_photo else None

    try:
        # 1. Salva vídeo temporário
        with open(video_path, "wb") as f:
            shutil.copyfileobj(video.file, f)

        if profile_photo and profile_path:
            with open(profile_path, "wb") as f:
                shutil.copyfileobj(profile_photo.file, f)

        # 2. ETAPA 1: Prova de Vida Ativa com reflexo espectral
        is_live, liveness_msg, face_roi = validar_reflexo_delta_rgb(video_path, cores)
        if not is_live:
            registrar_auditoria({
                "client_ip": client_ip,
                "user_id": user_id or "anonymous",
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

        # 3. ETAPA 2: Seleciona o melhor frame com maior nitidez (Laplaciano)
        melhor_frame = selecionar_melhor_frame_nitido(video_path, max_frames=40, roi_box=face_roi)
        cv2.imwrite(os.path.join(DEBUG_DIR, "last_probe_frame.jpg"), melhor_frame)

        # 4. Extrai embedding biométrico do vídeo ao vivo com YuNet + SFace
        feat_probe, aligned_probe = extrair_embedding_e_recorte(melhor_frame)
        if feat_probe is None or aligned_probe is None:
            return {
                "verified": False,
                "is_live": True,
                "reason": "Não foi possível isolar um rosto nítido na gravação. Mantenha o rosto estável e centralizado.",
                "status": "Falha na detecção facial"
            }

        cv2.imwrite(os.path.join(DEBUG_DIR, "last_aligned_probe.jpg"), aligned_probe)

        verified = False
        distance = 1.0
        threshold = 0.35
        matched_user = None

        # CASO A: Comparação direta com foto enviada na requisição (modo legado)
        if profile_path and os.path.exists(profile_path):
            profile_img = cv2.imread(profile_path)
            if profile_img is not None:
                feat_profile, aligned_profile = extrair_embedding_e_recorte(profile_img)
                if feat_profile is not None:
                    similarity = float(recognizer_sface.match(feat_probe, feat_profile, cv2.FaceRecognizerSF_FR_COSINE))
                    distance = max(0.0, 1.0 - similarity)
                    verified = distance <= threshold

        # CASO B: Reconhecimento Facial ao vivo com Aprendizado Adaptativo (sem foto de galeria!)
        else:
            # Subcaso B1: user_id especificado -> comparação 1:1 contra o perfil adaptativo
            if user_id and user_id.strip():
                alvo = db_buscar_usuario(user_id.strip())
                if alvo is not None:
                    distance = calcular_distancia_usuario(feat_probe, alvo)
                    if distance <= threshold:
                        verified = True
                        matched_user = alvo
                else:
                    return {
                        "verified": False,
                        "is_live": True,
                        "reason": f"Usuário '{user_id}' não encontrado no banco de dados.",
                        "status": f"Usuário '{user_id}' não cadastrado."
                    }
            # Subcaso B2: reconhecimento 1:N contra todos os perfis adaptativos
            else:
                todos_usuarios = db_listar_usuarios()
                if not todos_usuarios:
                    return {
                        "verified": False,
                        "is_live": True,
                        "reason": "Nenhum usuário cadastrado no sistema. Por favor, crie sua conta primeiro.",
                        "status": "Nenhum usuário cadastrado."
                    }

                menor_distancia = 999.0
                melhor_candidato = None
                for u in todos_usuarios:
                    dist = calcular_distancia_usuario(feat_probe, u)
                    if dist < menor_distancia:
                        menor_distancia = dist
                        melhor_candidato = u

                distance = menor_distancia
                if distance <= threshold and melhor_candidato is not None:
                    verified = True
                    matched_user = melhor_candidato

        # ======================================================================
        # RETROALIMENTAÇÃO ADAPTATIVA: APRENDIZADO CONTÍNUO AO VIVO
        # ======================================================================
        adaptive_updated = False
        current_samples_count = matched_user["samples_count"] if matched_user else 1

        if verified and matched_user is not None:
            # Salva o novo recorte facial alinhado deste login bem-sucedido
            uid = matched_user["id"]
            login_photo_filename = f"{uid}_latest.jpg"
            login_photo_path = os.path.join(STORAGE_FACES_DIR, login_photo_filename)
            cv2.imwrite(login_photo_path, aligned_probe)

            # Adiciona amostra ao histórico e recalcula o centroide biométrico ponderado
            current_samples_count = db_adicionar_amostra_login(
                user_id=uid,
                new_embedding=feat_probe,
                latest_photo_filename=login_photo_filename,
                distance_to_anchor=distance
            )
            adaptive_updated = True

        # 5. Geração de Token JWT assinado em caso de aprovação
        jwt_token = None
        token_sub = matched_user["id"] if matched_user else (user_id or "senior_user_anonymous")
        if verified:
            jwt_token = gerar_jwt_biometria(token_sub, distance, threshold)

        registrar_auditoria({
            "client_ip": client_ip,
            "user_id": token_sub,
            "verified": verified,
            "is_live": True,
            "distance": round(distance, 4),
            "matched_name": matched_user["name"] if matched_user else None,
            "samples_count": current_samples_count,
            "adaptive_updated": adaptive_updated,
            "reason": "Sucesso" if verified else "Rosto não reconhecido"
        })

        resp_user = {
            "id": matched_user["id"],
            "name": matched_user["name"],
            "samples_count": current_samples_count,
            "photo_url": f"/faces/{matched_user['photo_filename']}",
            "latest_photo_url": f"/faces/{matched_user.get('latest_photo_filename', matched_user['photo_filename'])}"
        } if matched_user else None

        msg_status = (
            f"Olá {matched_user['name']}! Login biométrico aprovado! Perfil atualizado ({current_samples_count} amostras aprendidas)."
            if (verified and matched_user)
            else ("Reconhecimento facial aprovado com sucesso!" if verified else "Rosto não reconhecido ou biometria não confere.")
        )

        return {
            "verified": verified,
            "is_live": True,
            "distance": round(distance, 4),
            "threshold": threshold,
            "samples_count": current_samples_count,
            "adaptive_updated": adaptive_updated,
            "jwt_token": jwt_token,
            "matched_user": resp_user,
            "status": msg_status
        }

    except Exception as e:
        registrar_auditoria({
            "client_ip": client_ip,
            "user_id": user_id or "anonymous",
            "verified": False,
            "is_live": False,
            "error": str(e)
        })
        return {"verified": False, "is_live": False, "error": str(e)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


