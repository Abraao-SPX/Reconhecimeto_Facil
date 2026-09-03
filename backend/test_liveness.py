"""
Script de teste sintético para validar a lógica da API de Liveness e Biometria
sem precisar conectar o celular.
"""
import os
import tempfile
import cv2
import numpy as np
from main import validar_reflexo_delta_rgb

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

def testar_algoritmo_delta_rgb():
    print("🧪 Iniciando teste unitário de Liveness Delta RGB...")
    temp_dir = tempfile.mkdtemp()
    
    video_valido = os.path.join(temp_dir, "teste_valido.mp4")
    video_invalido = os.path.join(temp_dir, "teste_invalido.mp4")
    cores_esperadas = ["VERMELHO", "AZUL", "VERDE"]

    try:
        gerar_video_sintetico_com_cores(video_valido, cores_esperadas, simular_sucesso=True)
        sucesso, msg = validar_reflexo_delta_rgb(video_valido, cores_esperadas)
        print(f"  -> Teste com reflexo real: {'PASSOU ✅' if sucesso else 'FALHOU ❌'} ({msg})")
        assert sucesso, "Deveria aprovar vídeo com reflexo correto"

        gerar_video_sintetico_com_cores(video_invalido, cores_esperadas, simular_sucesso=False)
        falha, msg_falha = validar_reflexo_delta_rgb(video_invalido, cores_esperadas)
        print(f"  -> Teste com spoofing (sem reflexo): {'PASSOU ✅' if not falha else 'FALHOU ❌'} ({msg_falha})")
        assert not falha, "Deveria reprovar vídeo sem reflexo correto"

        print("🎉 Todos os testes de validação espectral foram concluídos com sucesso!")
    finally:
        for f in [video_valido, video_invalido]:
            if os.path.exists(f):
                os.remove(f)
        os.rmdir(temp_dir)

if __name__ == "__main__":
    testar_algoritmo_delta_rgb()

