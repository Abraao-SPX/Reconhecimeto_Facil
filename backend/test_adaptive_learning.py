"""
Testes Unitários e de Integração: Biometria Adaptativa com Aprendizado Contínuo
Valida:
1. Cadastro sem comparação prévia (armazenamento de âncora inicial imutável).
2. Login com matching adaptativo e incorporação da 2ª e 3ª amostras.
3. Convergência e normalização matemática do Centroide Adaptativo.
4. Rejeição inequívoca de impostores (distância > limiar 0.35).
5. Histórico e auditoria de evolução biométrica.
"""
import os
import json
import sqlite3
import tempfile
import numpy as np
import pytest

from main import (
    init_db,
    normalizar_embedding,
    db_salvar_usuario_inicial,
    db_adicionar_amostra_login,
    db_buscar_usuario,
    db_listar_usuarios,
    db_buscar_historico_amostras,
    calcular_distancia_usuario
)

def test_fluxo_biometria_adaptativa():
    print("\n🧠 [Adaptativo 1/4] Testando cadastro sem comparação e criação da âncora inicial...")

    import time
    user_id = f"user_adapt_{int(time.time()*1000)}"
    name = "Abraão Adaptativo"
    photo_file = f"{user_id}_anchor.jpg"

    try:
        # Vetor unitário aleatório simulando SFace 128D
        np.random.seed(42)
        v1 = np.random.randn(128).astype(np.float32)
        v1_norm = normalizar_embedding(v1)

        # Salva cadastro inicial
        db_salvar_usuario_inicial(user_id, name, v1_norm, photo_file)

        user = db_buscar_usuario(user_id)
        assert user is not None, "Usuário deveria existir no banco"
        assert user["name"] == name
        assert user["samples_count"] == 1
        assert user["photo_filename"] == photo_file
        assert user["latest_photo_filename"] == photo_file

        # Verifica se a âncora e o centroide são idênticos no início
        np.testing.assert_allclose(user["primary_embedding"], v1_norm, rtol=1e-5)
        np.testing.assert_allclose(user["centroid_embedding"], v1_norm, rtol=1e-5)

        # Verifica amostra em biometric_samples
        historico = db_buscar_historico_amostras(user_id)
        assert len(historico) == 1
        assert historico[0]["sample_type"] == "registration"
        print("  -> Cadastro inicial sem comparação: PASSOU ✅ (samples_count=1)")

        # --------------------------------------------------------------------------
        # 2. Primeiro Login (Sample 2): pequena variação de iluminação/expressão
        # --------------------------------------------------------------------------
        print("\n🧠 [Adaptativo 2/4] Testando primeiro login e aprendizado da 2ª amostra...")
        ruido_leve = np.random.randn(128).astype(np.float32) * 0.05
        v2 = normalizar_embedding(v1_norm + ruido_leve)

        # Distância deve ser baixa
        dist_v2 = calcular_distancia_usuario(v2, user)
        assert dist_v2 <= 0.35, f"V2 deveria ser aprovado (distância={dist_v2})"

        # Executa a retroalimentação adaptativa
        new_count = db_adicionar_amostra_login(user_id, v2, f"{user_id}_login1.jpg", dist_v2)
        assert new_count == 2

        user_apos_login1 = db_buscar_usuario(user_id)
        assert user_apos_login1["samples_count"] == 2
        assert user_apos_login1["latest_photo_filename"] == f"{user_id}_login1.jpg"

        # A âncora inicial original permanece IMUTÁVEL
        np.testing.assert_allclose(user_apos_login1["primary_embedding"], v1_norm, rtol=1e-5)

        # O centroide deve ter sido atualizado com média ponderada normalizada
        centroide_esperado = normalizar_embedding((v1_norm + v2) / 2.0)
        np.testing.assert_allclose(user_apos_login1["centroid_embedding"], centroide_esperado, rtol=1e-4)

        historico = db_buscar_historico_amostras(user_id)
        assert len(historico) == 2
        assert historico[0]["sample_type"] == "login_adaptation"
        print("  -> Primeiro login e agregação da amostra 2: PASSOU ✅ (samples_count=2)")

        # --------------------------------------------------------------------------
        # 3. Segundo Login (Sample 3): nova variação gradual
        # --------------------------------------------------------------------------
        print("\n🧠 [Adaptativo 3/4] Testando segundo login e aprendizado da 3ª amostra...")
        ruido_leve2 = np.random.randn(128).astype(np.float32) * 0.05
        v3 = normalizar_embedding(v2 + ruido_leve2)

        dist_v3 = calcular_distancia_usuario(v3, user_apos_login1)
        assert dist_v3 <= 0.35, f"V3 deveria ser aprovado (distância={dist_v3})"

        new_count3 = db_adicionar_amostra_login(user_id, v3, f"{user_id}_login2.jpg", dist_v3)
        assert new_count3 == 3

        user_apos_login2 = db_buscar_usuario(user_id)
        assert user_apos_login2["samples_count"] == 3
        assert len(db_buscar_historico_amostras(user_id)) == 3
        print("  -> Segundo login e consolidação da amostra 3: PASSOU ✅ (samples_count=3)")

        # --------------------------------------------------------------------------
        # 4. Tentativa com Impostor: Rosto de Terceiro (Vetor Completamente Diferente)
        # --------------------------------------------------------------------------
        print("\n🧠 [Adaptativo 4/4] Testando tentativa de login de impostor...")
        v_impostor = normalizar_embedding(-v1_norm + np.random.randn(128).astype(np.float32) * 0.1)
        dist_impostor = calcular_distancia_usuario(v_impostor, user_apos_login2)
        assert dist_impostor > 0.35, f"Impostor deveria ser rejeitado (distância={dist_impostor})"
        print(f"  -> Impostor rejeitado categoricamente (distância={dist_impostor:.4f} > 0.35): PASSOU ✅")

    finally:
        # Limpeza definitiva
        try:
            conn = sqlite3.connect("storage/biometria.db")
            conn.execute("DELETE FROM biometric_samples WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    test_fluxo_biometria_adaptativa()
