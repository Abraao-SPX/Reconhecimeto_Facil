"""
Script de teste sintético para validar a lógica da API de Liveness e Biometria
sem precisar conectar o celular.
Testa:
1. Rejeição imediata quando nenhum rosto for identificado no vídeo ("Nenhum rosto identificado no vídeo").
2. Seleção inteligente do frame com maior nitidez via variância do operador Laplaciano.
3. Prova de vida espectral Delta RGB com reflexo real e prevenção contra spoofing.
"""
import os
import tempfile
import cv2
import numpy as np
from main import (
    validar_reflexo_delta_rgb,
    calcular_nitidez_laplaciano,
    selecionar_melhor_frame_nitido
)

def gerar_video_sintetico_com_cores(caminho_arquivo: str, cores: list[str], simular_sucesso: bool = True):
    """
    Gera um arquivo de vídeo .mp4 simulando uma pessoa em frente à tela
    com reflexos nos canais de cores.
    """
    largura, altura = 320, 240
    fps = 10
    frames_por_cor = 8
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(caminho_arquivo, fourcc, fps, (largura, altura))

    # Frame baseline (escuro)
    frame_escuro = np.full((altura, largura, 3), 40, dtype=np.uint8)
    out.write(frame_escuro)
    out.write(frame_escuro)

    color_bgr = {
        "VERMELHO": (30, 30, 200),  # BGR
        "AZUL": (200, 30, 30),
        "VERDE": (30, 200, 30),
    }

    for cor in cores:
        b, g, r = color_bgr.get(cor, (50, 50, 50))
        if not simular_sucesso:
            # Inverte para simular ataque de spoofing
            b, g, r = (100, 100, 100)

        for _ in range(frames_por_cor):
            # Desenha um "rosto" simulado no centro com reflexo
            frame = np.full((altura, largura, 3), 50, dtype=np.uint8)
            cv2.circle(frame, (largura // 2, altura // 2), 60, (b, g, r), -1)
            out.write(frame)

    out.release()

def testar_rejeicao_sem_rosto():
    print("\n🧪 [1/3] Testando rejeição imediata quando nenhum rosto é detectado...")
    temp_dir = tempfile.mkdtemp()
    video_sem_rosto = os.path.join(temp_dir, "sem_rosto.mp4")
    cores = ["VERMELHO", "AZUL", "VERDE"]
    try:
        # Vídeo puramente geométrico (círculo sem marcos faciais humanos reais)
        gerar_video_sintetico_com_cores(video_sem_rosto, cores, simular_sucesso=True)
        sucesso, msg, face_roi = validar_reflexo_delta_rgb(video_sem_rosto, cores)
        print(f"  -> Resultado: sucesso={sucesso}, mensagem='{msg}'")
        assert not sucesso, "Deveria rejeitar vídeo sem face humana detectada"
        assert msg == "Nenhum rosto identificado no vídeo", f"Mensagem esperada diferente: {msg}"
        print("  -> Rejeição sem rosto: PASSOU ✅")
    finally:
        if os.path.exists(video_sem_rosto):
            os.remove(video_sem_rosto)
        os.rmdir(temp_dir)

def testar_selecao_melhor_frame_laplaciano():
    print("\n🧪 [2/3] Testando seleção inteligente do melhor frame com filtro Laplaciano...")
    temp_dir = tempfile.mkdtemp()
    video_path = os.path.join(temp_dir, "teste_nitidez.mp4")
    try:
        largura, altura = 320, 240
        out = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'mp4v'), 10, (largura, altura))

        # Frame 0 a 3: muito borrados
        for _ in range(4):
            f = np.zeros((altura, largura, 3), dtype=np.uint8)
            cv2.putText(f, "TESTE", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 2)
            blurred = cv2.GaussianBlur(f, (31, 31), 10)
            out.write(blurred)

        # Frame 4: extremamente nítido (alto contraste de bordas)
        sharp_frame = np.zeros((altura, largura, 3), dtype=np.uint8)
        for i in range(0, largura, 10):
            cv2.line(sharp_frame, (i, 0), (i, altura), (255, 255, 255), 2)
        out.write(sharp_frame)

        # Frame 5 a 9: borrados novamente
        for _ in range(5):
            out.write(blurred)

        out.release()

        melhor_frame = selecionar_melhor_frame_nitido(video_path, max_frames=10)
        score_melhor = calcular_nitidez_laplaciano(melhor_frame)
        score_borrado = calcular_nitidez_laplaciano(blurred)

        print(f"  -> Score frame selecionado: {score_melhor:.2f} vs borrado: {score_borrado:.2f}")
        assert score_melhor > score_borrado, "O algoritmo Laplaciano deveria escolher o frame nítido"
        print("  -> Seleção Laplaciana: PASSOU ✅")
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        os.rmdir(temp_dir)

def testar_algoritmo_delta_rgb():
    print("\n🧪 [3/3] Testando algoritmo Delta RGB com ROI dinâmica...")
    temp_dir = tempfile.mkdtemp()
    video_valido = os.path.join(temp_dir, "teste_valido.mp4")
    video_invalido = os.path.join(temp_dir, "teste_invalido.mp4")
    cores_esperadas = ["VERMELHO", "AZUL", "VERDE"]
    roi_simulada = (100, 60, 220, 180)

    try:
        gerar_video_sintetico_com_cores(video_valido, cores_esperadas, simular_sucesso=True)
        sucesso, msg, face_roi = validar_reflexo_delta_rgb(video_valido, cores_esperadas, mock_roi=roi_simulada)
        print(f"  -> Teste com reflexo real: {'PASSOU ✅' if sucesso else 'FALHOU ❌'} ({msg})")
        assert sucesso, "Deveria aprovar vídeo com reflexo correto"

        gerar_video_sintetico_com_cores(video_invalido, cores_esperadas, simular_sucesso=False)
        falha, msg_falha, _ = validar_reflexo_delta_rgb(video_invalido, cores_esperadas, mock_roi=roi_simulada)
        print(f"  -> Teste com spoofing (sem reflexo): {'PASSOU ✅' if not falha else 'FALHOU ❌'} ({msg_falha})")
        assert not falha, "Deveria reprovar vídeo sem reflexo correto"

        print("  -> Validação espectral Delta RGB: PASSOU ✅")
    finally:
        for f in [video_valido, video_invalido]:
            if os.path.exists(f):
                os.remove(f)
        os.rmdir(temp_dir)

if __name__ == "__main__":
    testar_rejeicao_sem_rosto()
    testar_selecao_melhor_frame_laplaciano()
    testar_algoritmo_delta_rgb()
    print("\n🎉 Todos os testes unitários foram concluídos com 100% de sucesso!")


