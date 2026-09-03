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
  TextInput,
  ScrollView,
  Switch,
} from 'react-native';
import { CameraView, useCameraPermissions, useMicrophonePermissions } from 'expo-camera';
import * as Brightness from 'expo-brightness';
import * as ImagePicker from 'expo-image-picker';
import * as Speech from 'expo-speech';
import * as Haptics from 'expo-haptics';
import axios from 'axios';
import { StatusBar } from 'expo-status-bar';

// Endereço IP padrão: configurado com o IP real da sua máquina (192.168.1.44)
const DEFAULT_API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://192.168.1.44:8000';

type ScreenState = 'START' | 'LIVENESS' | 'PROCESSING' | 'SUCCESS' | 'FAILURE';

const COLOR_MAP: Record<string, string> = {
  VERMELHO: '#FF0000',
  AZUL: '#0000FF',
  VERDE: '#00FF00',
};

// Funções utilitárias seguras para Acessibilidade Sênior (Voz e Vibração)
const speakInstruction = (text: string, enabled: boolean = true) => {
  if (!enabled) return;
  try {
    Speech.stop();
    Speech.speak(text, {
      language: 'pt-BR',
      rate: 0.88, // Fala ligeiramente mais calma para idosos
      pitch: 1.0,
    });
  } catch (err) {
    console.warn('Falha na síntese de voz:', err);
  }
};

const triggerHapticFeedback = async (type: 'impact' | 'success' | 'error') => {
  try {
    if (type === 'impact') {
      await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } else if (type === 'success') {
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } else if (type === 'error') {
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    }
  } catch (err) {
    console.warn('Falha no haptic:', err);
  }
};

// Função de resiliência de rede com Retry e Backoff Exponencial
async function executeWithRetry<T>(
  action: () => Promise<T>,
  maxRetries: number = 3,
  baseDelayMs: number = 1000,
  onRetry?: (tentativa: number, total: number) => void
): Promise<T> {
  let attempt = 0;
  while (attempt < maxRetries) {
    try {
      return await action();
    } catch (error: any) {
      attempt++;
      if (attempt >= maxRetries) {
        throw error;
      }
      if (onRetry) {
        onRetry(attempt, maxRetries);
      }
      const delay = baseDelayMs * Math.pow(2, attempt - 1);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw new Error('Falha na comunicação após múltiplas tentativas.');
}

export default function App() {
  const [screenState, setScreenState] = useState<ScreenState>('START');
  const [permission, requestPermission] = useCameraPermissions();
  const [micPermission, requestMicPermission] = useMicrophonePermissions();
  const [profileImageUri, setProfileImageUri] = useState<string | null>(null);
  const [backgroundColor, setBackgroundColor] = useState('#000000');
  const [statusMessage, setStatusMessage] = useState('');
  const [verificationData, setVerificationData] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState('');

  // Acessibilidade por Voz (Ativada por padrão para a terceira idade)
  const [voiceAssistance, setVoiceAssistance] = useState<boolean>(true);

  // Configuração dinâmica de IP da API
  const [apiUrl, setApiUrl] = useState<string>(DEFAULT_API_URL);
  const [showServerConfig, setShowServerConfig] = useState<boolean>(false);
  const [isTestingServer, setIsTestingServer] = useState<boolean>(false);

  const cameraRef = useRef<CameraView>(null);

  // Solicita permissões de câmera e áudio ao carregar se não tiver
  useEffect(() => {
    if (!permission?.granted) {
      requestPermission();
    }
    if (!micPermission?.granted) {
      requestMicPermission();
    }
  }, [permission, micPermission]);

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

  // Testa conectividade com o backend diretamente pelo app
  const handleTestConnection = async () => {
    setIsTestingServer(true);
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    try {
      const res = await axios.get(`${cleanUrl}/health`, { timeout: 4000 });
      if (res.data?.status === 'ok') {
        Alert.alert(
          'Servidor Online! ✅',
          `Conexão bem-sucedida com o backend.\nModelo: ${res.data.model || 'YuNet-SFace'}\nServiço: ${res.data.service || 'Reconhecimento Fácil'}`
        );
      } else {
        Alert.alert('Aviso ⚠️', 'O servidor respondeu com formato inesperado.');
      }
    } catch (err: any) {
      Alert.alert(
        'Falha na Conexão ❌',
        `Não foi possível conectar a:\n${cleanUrl}\n\nVerifique se o backend está rodando no Docker e se o celular está no mesmo Wi-Fi.`
      );
    } finally {
      setIsTestingServer(false);
    }
  };

  // Botão "INICIAR TESTE" da Tela 1
  const handleStartPress = async () => {
    let photoUri = profileImageUri;
    if (!photoUri) {
      speakInstruction('Por favor, selecione primeiro uma foto de cadastro nítida.', voiceAssistance);
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

    triggerHapticFeedback('impact');
    setScreenState('LIVENESS');
  };

  // Executa o desafio do flash de cores na Tela 2
  const runLivenessSequence = async () => {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    try {
      setStatusMessage('Buscando sequência com o servidor...');
      speakInstruction('Aproxime o celular do rosto e olhe para a tela.', voiceAssistance);

      // 1. Obtém desafio dinâmico da API com retry automático contra instabilidade
      const res = await executeWithRetry(
        () => axios.get(`${cleanUrl}/challenge`, { timeout: 5000 }),
        3,
        1000,
        (att, tot) => setStatusMessage(`Reconectando ao servidor (${att}/${tot})...`)
      );
      const { colors, flash_duration_ms } = res.data;

      // 2. Eleva brilho da tela ao máximo
      const { status } = await Brightness.requestPermissionsAsync();
      let originalBrightness = 0.5;
      if (status === 'granted') {
        originalBrightness = await Brightness.getBrightnessAsync();
        await Brightness.setBrightnessAsync(1.0);
      }

      setStatusMessage('Fique olhando para a tela...');
      triggerHapticFeedback('impact');

      // 3. Garante permissão de gravação e inicia vídeo mudo (sem necessidade de áudio)
      if (!micPermission?.granted) {
        await requestMicPermission();
      }
      const recordPromise = cameraRef.current?.recordAsync({ maxDuration: 5, mute: true });

      // Frame inicial neutro escuro (300ms)
      setBackgroundColor('#000000');
      await new Promise((r) => setTimeout(r, 300));

      // 4. Alterna as cores do desafio com micro-vibrações táteis
      for (const color of colors) {
        setBackgroundColor(COLOR_MAP[color] || '#FFFFFF');
        triggerHapticFeedback('impact');
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
      speakInstruction('Analisando seus traços faciais. Só um momento.', voiceAssistance);

      if (videoData?.uri && profileImageUri) {
        await sendVerification(videoData.uri, profileImageUri, colors);
      } else {
        throw new Error('Vídeo ou foto de perfil não disponível.');
      }
    } catch (error: any) {
      console.error(error);
      setBackgroundColor('#000000');
      const errTxt = error.message || 'Falha ao conectar com o servidor.';
      setErrorMessage(errTxt);
      setScreenState('FAILURE');
      triggerHapticFeedback('error');
      speakInstruction('Não foi possível concluir o teste. Verifique a conexão e tente novamente.', voiceAssistance);
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

  // Envia vídeo e foto para o Backend com resiliência de rede
  const sendVerification = async (videoUri: string, profileUri: string, colors: string[]) => {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
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

      const response = await executeWithRetry(
        () =>
          axios.post(`${cleanUrl}/verify`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 45000,
          }),
        2,
        1500,
        (att, tot) => setStatusMessage(`Enviando dados biométricos (${att}/${tot})...`)
      );

      setVerificationData(response.data);

      if (response.data.verified) {
        setScreenState('SUCCESS');
        triggerHapticFeedback('success');
        speakInstruction('Identidade confirmada com sucesso! Teste biométrico aprovado.', voiceAssistance);
      } else {
        const failReason =
          response.data.reason ||
          response.data.status ||
          'A verificação não atingiu o nível de confiança necessário.';
        setErrorMessage(failReason);
        setScreenState('FAILURE');
        triggerHapticFeedback('error');
        speakInstruction(failReason, voiceAssistance);
      }
    } catch (err: any) {
      console.error(err);
      const errDetail = err.response?.data?.detail || err.message || 'Erro de comunicação com o servidor.';
      setErrorMessage(errDetail);
      setScreenState('FAILURE');
      triggerHapticFeedback('error');
      speakInstruction('Ocorreu uma falha de conexão com o servidor. Tente novamente.', voiceAssistance);
    }
  };

  // Reinicia o fluxo para a Tela 1
  const resetToStart = () => {
    Speech.stop();
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
        <ScrollView
          contentContainerStyle={styles.startScrollContent}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.header}>
            <Text style={styles.appTitle}>RECONHECIMENTO FÁCIL</Text>
            <Text style={styles.appSubtitle}>Biometria & Prova de Vida Inteligente</Text>
          </View>

          <View style={styles.startCard}>
            <Text style={styles.cardEmoji}>🛡️</Text>
            <Text style={styles.startInstruction}>
              Teste de prova de vida e reconhecimento facial com flash de cores.
            </Text>

            {profileImageUri ? (
              <View style={styles.profileBadge}>
                <Image source={{ uri: profileImageUri }} style={styles.thumbImage} />
                <View style={{ marginLeft: 12, flex: 1 }}>
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

          {/* CARD DE CONFIGURAÇÃO DE IP / SERVIDOR */}
          <View style={styles.serverConfigCard}>
            <TouchableOpacity
              style={styles.serverConfigHeader}
              onPress={() => setShowServerConfig(!showServerConfig)}
              activeOpacity={0.7}
            >
              <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
                <Text style={styles.serverConfigIcon}>🌐</Text>
                <View style={{ marginLeft: 8, flex: 1 }}>
                  <Text style={styles.serverConfigLabel}>Servidor Backend (API)</Text>
                  <Text style={styles.serverConfigValue} numberOfLines={1}>
                    {apiUrl}
                  </Text>
                </View>
              </View>
              <Text style={styles.serverToggleText}>{showServerConfig ? '▲ Fechar' : '⚙️ Configurar'}</Text>
            </TouchableOpacity>

            {showServerConfig && (
              <View style={styles.serverConfigBody}>
                <Text style={styles.inputFieldLabel}>Endereço do Servidor:</Text>
                <TextInput
                  style={styles.serverInput}
                  value={apiUrl}
                  onChangeText={setApiUrl}
                  placeholder="http://192.168.1.15:8000"
                  placeholderTextColor="#64748B"
                  autoCapitalize="none"
                  autoCorrect={false}
                />

                <Text style={styles.presetsLabel}>Atalhos Rápidos:</Text>
                <View style={styles.presetsContainer}>
                  <TouchableOpacity
                    style={styles.presetButton}
                    onPress={() => setApiUrl('http://192.168.1.44:8000')}
                  >
                    <Text style={styles.presetButtonText}>Wi-Fi (192.168.1.44)</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.presetButton}
                    onPress={() => setApiUrl('http://10.0.2.2:8000')}
                  >
                    <Text style={styles.presetButtonText}>Emulador Android (10.0.2.2)</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.presetButton}
                    onPress={() => setApiUrl('http://localhost:8000')}
                  >
                    <Text style={styles.presetButtonText}>Localhost (8000)</Text>
                  </TouchableOpacity>
                </View>

                <TouchableOpacity
                  style={styles.testConnectionBtn}
                  onPress={handleTestConnection}
                  disabled={isTestingServer}
                >
                  {isTestingServer ? (
                    <ActivityIndicator size="small" color="#FFFFFF" />
                  ) : (
                    <Text style={styles.testConnectionBtnText}>⚡ Testar Conectividade</Text>
                  )}
                </TouchableOpacity>
              </View>
            )}
          </View>

          {/* ACESSIBILIDADE SÊNIOR: VOZ */}
          <View style={styles.voiceConfigRow}>
            <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
              <Text style={styles.voiceIcon}>🔊</Text>
              <View style={{ marginLeft: 10 }}>
                <Text style={styles.voiceTitle}>Instruções por Voz</Text>
                <Text style={styles.voiceSubtitle}>Auxílio falado passo a passo</Text>
              </View>
            </View>
            <Switch
              value={voiceAssistance}
              onValueChange={(val) => {
                setVoiceAssistance(val);
                if (val) speakInstruction('Instruções por voz ativadas.', true);
              }}
              trackColor={{ false: '#334155', true: '#2563EB' }}
              thumbColor={voiceAssistance ? '#38BDF8' : '#94A3B8'}
            />
          </View>

          {/* BOTÃO ÚNICO DE INICIAR */}
          <View style={styles.bottomArea}>
            <TouchableOpacity style={styles.startMainButton} onPress={handleStartPress}>
              <Text style={styles.startMainButtonText}>INICIAR TESTE</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
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
          {backgroundColor !== '#000000' && (
            <View
              style={[
                StyleSheet.absoluteFillObject,
                { backgroundColor, opacity: 0.38 },
              ]}
              pointerEvents="none"
            />
          )}
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
            {verificationData?.jwt_token && (
              <Text style={styles.jwtPreviewText} numberOfLines={1}>
                Token de Segurança: {verificationData.jwt_token.substring(0, 28)}...
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
  },
  startScrollContent: {
    flexGrow: 1,
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 30,
    paddingHorizontal: 24,
  },
  header: {
    alignItems: 'center',
    marginTop: 10,
    marginBottom: 16,
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
  serverConfigCard: {
    backgroundColor: '#1E293B',
    width: '100%',
    borderRadius: 16,
    padding: 16,
    marginTop: 16,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: '#334155',
  },
  serverConfigHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  serverConfigIcon: {
    fontSize: 24,
  },
  serverConfigLabel: {
    color: '#94A3B8',
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  serverConfigValue: {
    color: '#38BDF8',
    fontSize: 14,
    fontWeight: 'bold',
    marginTop: 2,
  },
  serverToggleText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
  },
  serverConfigBody: {
    marginTop: 14,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: '#334155',
  },
  inputFieldLabel: {
    color: '#E2E8F0',
    fontSize: 13,
    fontWeight: '600',
    marginBottom: 6,
  },
  serverInput: {
    backgroundColor: '#0F172A',
    color: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#475569',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
  },
  presetsLabel: {
    color: '#94A3B8',
    fontSize: 12,
    marginTop: 12,
    marginBottom: 6,
  },
  presetsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 14,
  },
  presetButton: {
    backgroundColor: '#334155',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
  },
  presetButtonText: {
    color: '#E2E8F0',
    fontSize: 11,
    fontWeight: '500',
  },
  testConnectionBtn: {
    backgroundColor: '#0284C7',
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  testConnectionBtnText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: 'bold',
  },
  voiceConfigRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#1E293B',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 14,
    width: '100%',
    marginBottom: 20,
    borderWidth: 1,
    borderColor: '#334155',
  },
  voiceIcon: {
    fontSize: 22,
  },
  voiceTitle: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: 'bold',
  },
  voiceSubtitle: {
    color: '#94A3B8',
    fontSize: 12,
    marginTop: 2,
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
  jwtPreviewText: {
    color: '#38BDF8',
    fontSize: 12,
    fontFamily: 'monospace',
    marginTop: 6,
    backgroundColor: 'rgba(0, 0, 0, 0.2)',
    padding: 6,
    borderRadius: 6,
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

