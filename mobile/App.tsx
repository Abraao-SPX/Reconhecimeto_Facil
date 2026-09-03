import React, { useState, useRef, useEffect } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  SafeAreaView,
  Dimensions,
  Image,
} from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Brightness from 'expo-brightness';
import * as ImagePicker from 'expo-image-picker';
import axios from 'axios';
import { StatusBar } from 'expo-status-bar';

// Altere para o IP local do seu computador na mesma rede Wi-Fi (ex: http://192.168.1.15:8000)
const API_BASE_URL = 'http://192.168.1.15:8000';

type ScreenState = 'START' | 'LIVENESS' | 'PROCESSING' | 'SUCCESS' | 'FAILURE';

const COLOR_MAP: Record<string, string> = {
  VERMELHO: '#FF0000',
  AZUL: '#0000FF',
  VERDE: '#00FF00',
};

export default function App() {
  const [screenState, setScreenState] = useState<ScreenState>('START');
  const [permission, requestPermission] = useCameraPermissions();
  const [profileImageUri, setProfileImageUri] = useState<string | null>(null);
  const [backgroundColor, setBackgroundColor] = useState('#000000');
  const [statusMessage, setStatusMessage] = useState('');
  const [verificationData, setVerificationData] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState('');

  const cameraRef = useRef<CameraView>(null);

  // Solicita permissão ao carregar se não tiver
  useEffect(() => {
    if (!permission?.granted) {
      requestPermission();
    }
  }, [permission]);

  // Escolhe a foto de referência (foto do perfil/documento)
  const pickProfilePhoto = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      quality: 0.8,
    });

    if (!result.canceled && result.assets[0]) {
      setProfileImageUri(result.assets[0].uri);
      return result.assets[0].uri;
    }
    return null;
  };

  // Botão "INICIAR TESTE" da Tela 1
  const handleStartPress = async () => {
    let photoUri = profileImageUri;
    if (!photoUri) {
      Alert.alert(
        'Foto de Cadastro',
        'Selecione primeiro a foto de perfil/cadastro que será usada para comparar com o seu rosto.',
        [
          {
            text: 'Escolher Foto',
            onPress: async () => {
              const selected = await pickProfilePhoto();
              if (selected) {
                setScreenState('LIVENESS');
              }
            },
          },
          { text: 'Cancelar', style: 'cancel' },
        ]
      );
      return;
    }

    setScreenState('LIVENESS');
  };

  // Executa o desafio do flash de cores na Tela 2
  const runLivenessSequence = async () => {
    try {
      setStatusMessage('Buscando sequência com o servidor...');
      
      // 1. Obtém desafio dinâmico da API
      const res = await axios.get(`${API_BASE_URL}/challenge`, { timeout: 5000 });
      const { colors, flash_duration_ms } = res.data;

      // 2. Eleva brilho da tela ao máximo
      const { status } = await Brightness.requestPermissionsAsync();
      let originalBrightness = 0.5;
      if (status === 'granted') {
        originalBrightness = await Brightness.getBrightnessAsync();
        await Brightness.setBrightnessAsync(1.0);
      }

      setStatusMessage('Fique olhando para a tela...');

      // 3. Inicia gravação de vídeo
      const recordPromise = cameraRef.current?.recordAsync({ maxDuration: 5 });

      // Frame inicial neutro escuro (300ms)
      setBackgroundColor('#000000');
      await new Promise((r) => setTimeout(r, 300));

      // 4. Alterna as cores do desafio
      for (const color of colors) {
        setBackgroundColor(COLOR_MAP[color] || '#FFFFFF');
        await new Promise((r) => setTimeout(r, flash_duration_ms || 750));
      }

      // 5. Finaliza a gravação e restaura brilho
      setBackgroundColor('#000000');
      cameraRef.current?.stopRecording();
      const videoData = await recordPromise;

      if (status === 'granted') {
        await Brightness.setBrightnessAsync(originalBrightness);
      }

      // 6. Passa para processamento
      setScreenState('PROCESSING');
      setStatusMessage('Analisando reflexo e linhas faciais (ArcFace)...');

      if (videoData?.uri && profileImageUri) {
        await sendVerification(videoData.uri, profileImageUri, colors);
      } else {
        throw new Error('Vídeo ou foto de perfil não disponível.');
      }
    } catch (error: any) {
      console.error(error);
      setBackgroundColor('#000000');
      setErrorMessage(error.message || 'Falha ao conectar com o servidor.');
      setScreenState('FAILURE');
    }
  };

  // Dispara automaticamente a sequência ao entrar na tela de Liveness
  useEffect(() => {
    if (screenState === 'LIVENESS') {
      setStatusMessage('Posicione o rosto no círculo...');
      const timer = setTimeout(() => {
        runLivenessSequence();
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [screenState]);

  // Envia vídeo e foto para o Backend
  const sendVerification = async (videoUri: string, profileUri: string, colors: string[]) => {
    try {
      const formData = new FormData();
      formData.append('expected_colors', colors.join(','));

      formData.append('video', {
        uri: videoUri,
        name: 'challenge_video.mp4',
        type: 'video/mp4',
      } as any);

      formData.append('profile_photo', {
        uri: profileUri,
        name: 'profile_photo.jpg',
        type: 'image/jpeg',
      } as any);

      const response = await axios.post(`${API_BASE_URL}/verify`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 35000,
      });

      setVerificationData(response.data);

      if (response.data.verified) {
        setScreenState('SUCCESS');
      } else {
        setErrorMessage(
          response.data.reason ||
          response.data.status ||
          'A verificação não atingiu o nível de confiança necessário.'
        );
        setScreenState('FAILURE');
      }
    } catch (err: any) {
      console.error(err);
      setErrorMessage(err.response?.data?.detail || err.message || 'Erro de comunicação com o servidor.');
      setScreenState('FAILURE');
    }
  };

  // Reinicia o fluxo para a Tela 1
  const resetToStart = () => {
    setVerificationData(null);
    setErrorMessage('');
    setBackgroundColor('#000000');
    setScreenState('START');
  };

  // ==========================================
  // RENDERIZAÇÃO: TELA 1 - INICIAL
  // ==========================================
  if (screenState === 'START') {
    return (
      <SafeAreaView style={styles.startContainer}>
        <StatusBar style="light" />
        <View style={styles.header}>
          <Text style={styles.appTitle}>BEYONDTIME</Text>
          <Text style={styles.appSubtitle}>Verificação Facial Anti-Golpe</Text>
        </View>

        <View style={styles.startCard}>
          <Text style={styles.cardEmoji}>🛡️</Text>
          <Text style={styles.startInstruction}>
            Teste de prova de vida e reconhecimento facial com flash de cores.
          </Text>

          {profileImageUri ? (
            <View style={styles.profileBadge}>
              <Image source={{ uri: profileImageUri }} style={styles.thumbImage} />
              <View style={{ marginLeft: 12 }}>
                <Text style={styles.profileBadgeTitle}>Foto Selecionada</Text>
                <TouchableOpacity onPress={pickProfilePhoto}>
                  <Text style={styles.changePhotoText}>Trocar foto</Text>
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            <TouchableOpacity style={styles.pickPhotoBtn} onPress={pickProfilePhoto}>
              <Text style={styles.pickPhotoBtnText}>📷 Escolher Foto de Cadastro</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* BOTÃO ÚNICO DE INICIAR */}
        <View style={styles.bottomArea}>
          <TouchableOpacity style={styles.startMainButton} onPress={handleStartPress}>
            <Text style={styles.startMainButtonText}>INICIAR TESTE</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // ==========================================
  // RENDERIZAÇÃO: TELA 2 - RECONHECIMENTO FACIAL
  // ==========================================
  if (screenState === 'LIVENESS') {
    return (
      <SafeAreaView style={[styles.livenessContainer, { backgroundColor }]}>
        <StatusBar style="light" />
        <Text style={styles.livenessStatusText}>{statusMessage}</Text>

        <View style={styles.ovalMask}>
          <CameraView
            ref={cameraRef}
            style={styles.cameraView}
            facing="front"
            mode="video"
          />
        </View>

        <Text style={styles.livenessTip}>Mantenha o rosto parado na moldura</Text>
      </SafeAreaView>
    );
  }

  // ==========================================
  // RENDERIZAÇÃO: PROCESSAMENTO
  // ==========================================
  if (screenState === 'PROCESSING') {
    return (
      <SafeAreaView style={styles.processingContainer}>
        <StatusBar style="light" />
        <ActivityIndicator size="large" color="#007AFF" />
        <Text style={styles.processingTitle}>Processando Autenticação</Text>
        <Text style={styles.processingSubtitle}>{statusMessage}</Text>
      </SafeAreaView>
    );
  }

  // ==========================================
  // RENDERIZAÇÃO: TELA 3 - SUCESSO (BEM SUCEDIDO)
  // ==========================================
  if (screenState === 'SUCCESS') {
    return (
      <SafeAreaView style={styles.successContainer}>
        <StatusBar style="light" />
        <View style={styles.successContent}>
          <View style={styles.successIconCircle}>
            <Text style={styles.successCheckIcon}>✓</Text>
          </View>

          <Text style={styles.successTitle}>TESTE BEM SUCEDIDO!</Text>
          <Text style={styles.successSubtitle}>
            Sua identidade foi verificada com sucesso.
          </Text>

          <View style={styles.resultDetailsCard}>
            <Text style={styles.detailItem}>✅ Prova de Vida por Luz: Aprovada</Text>
            <Text style={styles.detailItem}>✅ Rosto Compatível com Cadastro</Text>
            {verificationData?.distance !== undefined && (
              <Text style={styles.distanceText}>
                Distância Biométrica: {verificationData.distance} (Limite: {verificationData.threshold})
              </Text>
            )}
          </View>

          <TouchableOpacity style={styles.successButton} onPress={resetToStart}>
            <Text style={styles.successButtonText}>FAZER NOVO TESTE</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // ==========================================
  // RENDERIZAÇÃO: TELA DE FALHA (COM OPÇÃO DE REPETIR)
  // ==========================================
  return (
    <SafeAreaView style={styles.failureContainer}>
      <StatusBar style="light" />
      <View style={styles.successContent}>
        <View style={styles.failureIconCircle}>
          <Text style={styles.failureCheckIcon}>✕</Text>
        </View>

        <Text style={styles.failureTitle}>Teste Não Aprovado</Text>
        <Text style={styles.failureSubtitle}>{errorMessage}</Text>

        <TouchableOpacity style={styles.retryButton} onPress={resetToStart}>
          <Text style={styles.retryButtonText}>TENTAR NOVAMENTE</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const { width } = Dimensions.get('window');

const styles = StyleSheet.create({
  // TELA 1: START
  startContainer: {
    flex: 1,
    backgroundColor: '#0F172A',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 30,
    paddingHorizontal: 24,
  },
  header: {
    alignItems: 'center',
    marginTop: 20,
  },
  appTitle: {
    fontSize: 28,
    fontWeight: '900',
    color: '#38BDF8',
    letterSpacing: 2,
  },
  appSubtitle: {
    fontSize: 16,
    color: '#94A3B8',
    marginTop: 4,
  },
  startCard: {
    backgroundColor: '#1E293B',
    width: '100%',
    padding: 24,
    borderRadius: 20,
    alignItems: 'center',
  },
  cardEmoji: {
    fontSize: 48,
    marginBottom: 12,
  },
  startInstruction: {
    fontSize: 18,
    color: '#F8FAFC',
    textAlign: 'center',
    lineHeight: 26,
    marginBottom: 20,
  },
  profileBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#334155',
    padding: 12,
    borderRadius: 14,
    width: '100%',
  },
  thumbImage: {
    width: 50,
    height: 50,
    borderRadius: 25,
  },
  profileBadgeTitle: {
    color: '#FFFFFF',
    fontWeight: 'bold',
    fontSize: 15,
  },
  changePhotoText: {
    color: '#38BDF8',
    fontSize: 14,
    marginTop: 2,
  },
  pickPhotoBtn: {
    backgroundColor: '#334155',
    paddingVertical: 14,
    paddingHorizontal: 20,
    borderRadius: 12,
    width: '100%',
    alignItems: 'center',
  },
  pickPhotoBtnText: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: '600',
  },
  bottomArea: {
    width: '100%',
  },
  startMainButton: {
    backgroundColor: '#2563EB',
    paddingVertical: 20,
    borderRadius: 16,
    alignItems: 'center',
    elevation: 4,
    shadowColor: '#2563EB',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  startMainButtonText: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: 'bold',
    letterSpacing: 1,
  },

  // TELA 2: LIVENESS
  livenessContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 30,
  },
  livenessStatusText: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#FFFFFF',
    textAlign: 'center',
    paddingHorizontal: 20,
    marginTop: 20,
  },
  ovalMask: {
    width: width * 0.74,
    height: width * 0.98,
    borderRadius: (width * 0.74) / 2,
    overflow: 'hidden',
    borderWidth: 4,
    borderColor: '#FFFFFF',
    backgroundColor: '#000000',
  },
  cameraView: {
    flex: 1,
  },
  livenessTip: {
    color: '#E2E8F0',
    fontSize: 16,
    marginBottom: 20,
  },

  // PROCESSAMENTO
  processingContainer: {
    flex: 1,
    backgroundColor: '#0F172A',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 24,
  },
  processingTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: 'bold',
    marginTop: 20,
  },
  processingSubtitle: {
    color: '#94A3B8',
    fontSize: 16,
    textAlign: 'center',
    marginTop: 8,
  },

  // TELA 3: SUCESSO
  successContainer: {
    flex: 1,
    backgroundColor: '#064E3B', // Verde elegante escuro
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  successContent: {
    width: '100%',
    alignItems: 'center',
  },
  successIconCircle: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: '#10B981',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 24,
  },
  successCheckIcon: {
    fontSize: 54,
    color: '#FFFFFF',
    fontWeight: 'bold',
  },
  successTitle: {
    fontSize: 26,
    fontWeight: '900',
    color: '#FFFFFF',
    textAlign: 'center',
  },
  successSubtitle: {
    fontSize: 18,
    color: '#A7F3D0',
    textAlign: 'center',
    marginTop: 8,
    marginBottom: 24,
  },
  resultDetailsCard: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    padding: 18,
    borderRadius: 14,
    width: '100%',
    marginBottom: 32,
  },
  detailItem: {
    color: '#FFFFFF',
    fontSize: 16,
    marginVertical: 4,
    fontWeight: '600',
  },
  distanceText: {
    color: '#CBD5E1',
    fontSize: 13,
    marginTop: 8,
  },
  successButton: {
    backgroundColor: '#FFFFFF',
    paddingVertical: 18,
    borderRadius: 16,
    width: '100%',
    alignItems: 'center',
  },
  successButtonText: {
    color: '#064E3B',
    fontSize: 18,
    fontWeight: 'bold',
  },

  // TELA: FALHA
  failureContainer: {
    flex: 1,
    backgroundColor: '#450A0A',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  failureIconCircle: {
    width: 90,
    height: 90,
    borderRadius: 45,
    backgroundColor: '#EF4444',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  failureCheckIcon: {
    fontSize: 48,
    color: '#FFFFFF',
    fontWeight: 'bold',
  },
  failureTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#FFFFFF',
    textAlign: 'center',
  },
  failureSubtitle: {
    fontSize: 16,
    color: '#FECACA',
    textAlign: 'center',
    marginTop: 8,
    marginBottom: 30,
    lineHeight: 22,
  },
  retryButton: {
    backgroundColor: '#FFFFFF',
    paddingVertical: 16,
    borderRadius: 14,
    width: '100%',
    alignItems: 'center',
  },
  retryButtonText: {
    color: '#7F1D1D',
    fontSize: 18,
    fontWeight: 'bold',
  },
});

