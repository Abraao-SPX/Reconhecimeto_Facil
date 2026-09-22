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
import * as Speech from 'expo-speech';
import * as Haptics from 'expo-haptics';
import axios from 'axios';
import { StatusBar } from 'expo-status-bar';

// Endereço IP padrão: Let's Encrypt HTTPS direto na VPS Oracle
const DEFAULT_API_URL = process.env.EXPO_PUBLIC_API_URL || 'https://132.226.242.158.sslip.io';

type ScreenState = 'START' | 'LIVENESS' | 'PROCESSING' | 'SUCCESS' | 'REGISTER_SUCCESS' | 'FAILURE';
type ActionMode = 'VERIFY' | 'REGISTER';

interface RegisteredUser {
  id: string;
  name: string;
  photo_url: string;
  latest_photo_url?: string;
  samples_count?: number;
  created_at: string;
  updated_at?: string;
}

const COLOR_MAP: Record<string, string> = {
  VERMELHO: '#FF0000',
  AZUL: '#0000FF',
  VERDE: '#00FF00',
};

// Funções utilitárias de Acessibilidade Sênior (Voz e Vibração)
const speakInstruction = (text: string, enabled: boolean = true) => {
  if (!enabled) return;
  try {
    Speech.stop();
    Speech.speak(text, {
      language: 'pt-BR',
      rate: 0.88,
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

// Resiliência de rede com Retry e Backoff Exponencial
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
  const [actionMode, setActionMode] = useState<ActionMode>('VERIFY');
  const [permission, requestPermission] = useCameraPermissions();
  const [micPermission, requestMicPermission] = useMicrophonePermissions();

  const [registerName, setRegisterName] = useState('');
  const [backgroundColor, setBackgroundColor] = useState('#000000');
  const [statusMessage, setStatusMessage] = useState('');
  const [verificationData, setVerificationData] = useState<any>(null);
  const [registrationData, setRegistrationData] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState('');

  // Lista de usuários cadastrados na nuvem
  const [registeredUsers, setRegisteredUsers] = useState<RegisteredUser[]>([]);
  const [loadingUsers, setLoadingUsers] = useState<boolean>(false);
  const [showUsersModal, setShowUsersModal] = useState<boolean>(false);

  // Acessibilidade por Voz
  const [voiceAssistance, setVoiceAssistance] = useState<boolean>(true);

  // Configuração dinâmica de IP da API
  const [apiUrl, setApiUrl] = useState<string>(DEFAULT_API_URL);
  const [showServerConfig, setShowServerConfig] = useState<boolean>(false);
  const [isTestingServer, setIsTestingServer] = useState<boolean>(false);

  const cameraRef = useRef<CameraView>(null);

  // Solicita permissões ao inicializar
  useEffect(() => {
    if (!permission?.granted) {
      requestPermission();
    }
    if (!micPermission?.granted) {
      requestMicPermission();
    }
  }, [permission, micPermission]);

  // Carrega lista de usuários da VPS ao iniciar
  useEffect(() => {
    fetchRegisteredUsers();
  }, [apiUrl]);

  const fetchRegisteredUsers = async () => {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    setLoadingUsers(true);
    try {
      const res = await axios.get(`${cleanUrl}/users`, { timeout: 6000 });
      if (res.data?.users) {
        setRegisteredUsers(res.data.users);
      }
    } catch {
      // Falha silenciosa de sincronização inicial
    } finally {
      setLoadingUsers(false);
    }
  };

  const deleteUser = async (userId: string, userName: string) => {
    Alert.alert(
      'Excluir Biometria',
      `Tem certeza que deseja apagar a biometria de ${userName}?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Excluir',
          style: 'destructive',
          onPress: async () => {
            const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
            try {
              await axios.delete(`${cleanUrl}/users/${userId}`);
              triggerHapticFeedback('impact');
              fetchRegisteredUsers();
            } catch (err: any) {
              Alert.alert('Erro', 'Não foi possível excluir o usuário.');
            }
          },
        },
      ]
    );
  };

  // Testa conectividade com o backend
  const handleTestConnection = async () => {
    setIsTestingServer(true);
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    try {
      const res = await axios.get(`${cleanUrl}/health`, {
        timeout: 8000,
        headers: { 'Bypass-Tunnel-Reminder': 'true' },
      });
      if (res.data?.status === 'ok') {
        Alert.alert(
          'Servidor Conectado! ✅',
          `Servidor biométrico ativo na nuvem.\nModelo: ${res.data.model || 'YuNet-SFace'}\nVersão: ${res.data.version || '1.2.0'}`
        );
        fetchRegisteredUsers();
      } else {
        Alert.alert('Aviso ⚠️', 'O servidor respondeu com formato inesperado.');
      }
    } catch (err: any) {
      Alert.alert(
        'Falha na Conexão ❌',
        `Não foi possível conectar a:\n${cleanUrl}\n\nDetalhes: ${err.message || 'Sem resposta do servidor'}`
      );
    } finally {
      setIsTestingServer(false);
    }
  };

  // Iniciar Reconhecimento Facial ao Vivo
  const handleStartVerify = () => {
    setActionMode('VERIFY');
    triggerHapticFeedback('impact');
    setScreenState('LIVENESS');
  };

  // Iniciar Cadastro Facial ao Vivo
  const handleStartRegister = () => {
    if (!registerName.trim()) {
      speakInstruction('Por favor, digite seu nome antes de cadastrar.', voiceAssistance);
      Alert.alert('Nome Obrigatório', 'Digite o seu nome no campo acima para salvar sua biometria.');
      return;
    }
    setActionMode('REGISTER');
    triggerHapticFeedback('impact');
    setScreenState('LIVENESS');
  };

  // Sequência de Prova de Vida e Gravação da Câmera
  const runLivenessSequence = async () => {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    try {
      setStatusMessage('Sincronizando com o servidor...');
      speakInstruction('Aproxime o celular do rosto e olhe para a tela.', voiceAssistance);

      // 1. Obtém desafio dinâmico da API com retry automático
      const res = await executeWithRetry(
        () => axios.get(`${cleanUrl}/challenge`, { timeout: 5000 }),
        3,
        1000,
        (att, tot) => setStatusMessage(`Reconectando ao servidor (${att}/${tot})...`)
      );
      const { colors, flash_duration_ms } = res.data;

      // 2. Eleva brilho da tela ao máximo para reflexo na pele
      const { status } = await Brightness.requestPermissionsAsync();
      let originalBrightness = 0.5;
      if (status === 'granted') {
        originalBrightness = await Brightness.getBrightnessAsync();
        await Brightness.setBrightnessAsync(1.0);
      }

      setStatusMessage('Fique olhando para a tela...');
      triggerHapticFeedback('impact');

      // 3. Inicia gravação de vídeo pela câmera frontal
      if (!micPermission?.granted) {
        await requestMicPermission();
      }
      const recordPromise = cameraRef.current?.recordAsync({ maxDuration: 3 });

      // Frame inicial neutro escuro (300ms)
      setBackgroundColor('#000000');
      await new Promise((r) => setTimeout(r, 300));

      // 4. Alterna as cores do desafio espectral
      for (const color of colors) {
        setBackgroundColor(COLOR_MAP[color] || '#FFFFFF');
        triggerHapticFeedback('impact');
        await new Promise((r) => setTimeout(r, flash_duration_ms ? Math.min(flash_duration_ms, 500) : 500));
      }

      // 5. Finaliza gravação e restaura brilho
      setBackgroundColor('#000000');
      cameraRef.current?.stopRecording();
      const videoData = await recordPromise;

      if (status === 'granted') {
        await Brightness.setBrightnessAsync(originalBrightness);
      }

      // 6. Processa o vídeo de acordo com a ação (Verificar ou Cadastrar)
      setScreenState('PROCESSING');

      if (!videoData?.uri) {
        throw new Error('Não foi possível capturar o vídeo da câmera.');
      }

      if (actionMode === 'REGISTER') {
        setStatusMessage('Cadastrando biometria facial na nuvem (YuNet + SFace)...');
        speakInstruction('Salvando seus traços biométricos no servidor. Aguarde um instante.', voiceAssistance);
        await sendRegistration(videoData.uri, registerName, colors);
      } else {
        setStatusMessage('Reconhecendo traços faciais na nuvem (YuNet + SFace)...');
        speakInstruction('Analisando sua biometria facial. Só um momento.', voiceAssistance);
        await sendVerification(videoData.uri, colors);
      }
    } catch (error: any) {
      console.error(error);
      setBackgroundColor('#000000');
      const errTxt = error.message || 'Falha ao conectar com o servidor.';
      setErrorMessage(errTxt);
      setScreenState('FAILURE');
      triggerHapticFeedback('error');
      speakInstruction('Não foi possível concluir o teste. Tente novamente.', voiceAssistance);
    }
  };

  // Dispara automaticamente ao entrar na tela de Liveness
  useEffect(() => {
    if (screenState === 'LIVENESS') {
      setStatusMessage('Posicione o rosto no círculo...');
      const timer = setTimeout(() => {
        runLivenessSequence();
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [screenState]);

  // Envia vídeo para /register (Cadastro ao vivo)
  const sendRegistration = async (videoUri: string, userName: string, colors: string[]) => {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    try {
      const formData = new FormData();
      formData.append('name', userName.trim());
      formData.append('expected_colors', colors.join(','));
      formData.append('video', {
        uri: videoUri,
        name: 'register_video.mp4',
        type: 'video/mp4',
      } as any);

      setStatusMessage('Enviando vídeo para o servidor...');

      const response = await executeWithRetry(
        () =>
          axios.post(`${cleanUrl}/register`, formData, {
            headers: {
              'Content-Type': 'multipart/form-data',
            },
            timeout: 90000,
          }),
        2,
        2000,
        (att, tot) => setStatusMessage(`Reenviando vídeo para o servidor (${att}/${tot})...`)
      );

      if (response.data.success) {
        setRegistrationData(response.data);
        setScreenState('REGISTER_SUCCESS');
        triggerHapticFeedback('success');
        speakInstruction(`Biometria de ${userName} cadastrada com sucesso!`, voiceAssistance);
        fetchRegisteredUsers();
      } else {
        const failReason = response.data.reason || response.data.error || 'Falha ao cadastrar a biometria facial.';
        setErrorMessage(failReason);
        setScreenState('FAILURE');
        triggerHapticFeedback('error');
        speakInstruction(failReason, voiceAssistance);
      }
    } catch (err: any) {
      console.error('Erro no registro:', err);
      let errDetail = 'Erro de comunicação com o servidor.';
      if (err.code === 'ERR_NETWORK' || err.message?.includes('Network Error')) {
        errDetail = 'Falha na conexão de internet durante o envio do vídeo. Verifique se seu Wi-Fi ou 4G está estável e tente novamente.';
      } else if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
        errDetail = 'O envio do vídeo demorou demais. Verifique sua conexão e tente novamente.';
      } else if (err.response?.data?.detail) {
        errDetail = err.response.data.detail;
      } else if (err.message) {
        errDetail = err.message;
      }
      setErrorMessage(errDetail);
      setScreenState('FAILURE');
      triggerHapticFeedback('error');
      speakInstruction('Falha na comunicação com o servidor. Tente novamente.', voiceAssistance);
    }
  };

  // Envia vídeo para /verify (Reconhecimento ao vivo)
  const sendVerification = async (videoUri: string, colors: string[]) => {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    try {
      const formData = new FormData();
      formData.append('expected_colors', colors.join(','));
      formData.append('video', {
        uri: videoUri,
        name: 'challenge_video.mp4',
        type: 'video/mp4',
      } as any);

      setStatusMessage('Enviando vídeo para reconhecimento...');

      const response = await executeWithRetry(
        () =>
          axios.post(`${cleanUrl}/verify`, formData, {
            headers: {
              'Content-Type': 'multipart/form-data',
            },
            timeout: 90000,
          }),
        2,
        2000,
        (att, tot) => setStatusMessage(`Reenviando vídeo para o servidor (${att}/${tot})...`)
      );

      setVerificationData(response.data);

      if (response.data.verified) {
        setScreenState('SUCCESS');
        triggerHapticFeedback('success');
        const nome = response.data.matched_user?.name || 'Usuário';
        speakInstruction(`Identidade confirmada com sucesso! Olá, ${nome}.`, voiceAssistance);
      } else {
        const failReason =
          response.data.reason ||
          response.data.status ||
          'Rosto não reconhecido ou não cadastrado no sistema.';
        setErrorMessage(failReason);
        setScreenState('FAILURE');
        triggerHapticFeedback('error');
        speakInstruction(failReason, voiceAssistance);
      }
    } catch (err: any) {
      console.error('Erro na verificação:', err);
      let errDetail = 'Erro de comunicação com o servidor.';
      if (err.code === 'ERR_NETWORK' || err.message?.includes('Network Error')) {
        errDetail = 'Falha na conexão de internet durante o envio do vídeo. Verifique se seu Wi-Fi ou 4G está estável e tente novamente.';
      } else if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
        errDetail = 'O envio do vídeo demorou demais. Verifique sua conexão e tente novamente.';
      } else if (err.response?.data?.detail) {
        errDetail = err.response.data.detail;
      } else if (err.message) {
        errDetail = err.message;
      }
      setErrorMessage(errDetail);
      setScreenState('FAILURE');
      triggerHapticFeedback('error');
      speakInstruction('Falha na conexão com o servidor. Tente novamente.', voiceAssistance);
    }
  };

  // Reinicia para a tela inicial
  const resetToStart = () => {
    Speech.stop();
    setVerificationData(null);
    setRegistrationData(null);
    setErrorMessage('');
    setBackgroundColor('#000000');
    setScreenState('START');
  };

  // ==========================================
  // RENDERIZAÇÃO: TELA 1 - INICIAL
  // ==========================================
  if (screenState === 'START') {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');

    return (
      <SafeAreaView style={styles.startContainer}>
        <StatusBar style="light" />
        <ScrollView
          contentContainerStyle={styles.startScrollContent}
          keyboardShouldPersistTaps="handled"
        >
          {/* CABEÇALHO */}
          <View style={styles.header}>
            <Text style={styles.appTitle}>RECONHECIMENTO FÁCIL</Text>
            <Text style={styles.appSubtitle}>Biometria Facial 100% ao Vivo na Nuvem</Text>
          </View>

          {/* MODO 1: RECONHECIMENTO FACIAL AO VIVO */}
          <View style={styles.mainCard}>
            <View style={styles.cardHeaderRow}>
              <Text style={styles.cardBadgeEmoji}>⚡</Text>
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={styles.cardMainTitle}>Reconhecimento Facial</Text>
                <Text style={styles.cardMainSubtitle}>
                  Identifica seu rosto ao vivo na câmera sem precisar de fotos da galeria.
                </Text>
              </View>
            </View>

            <TouchableOpacity
              style={styles.verifyMainButton}
              onPress={handleStartVerify}
              activeOpacity={0.8}
            >
              <Text style={styles.verifyMainButtonText}>👤 RECONHECER MEU ROSTO</Text>
            </TouchableOpacity>
          </View>

          {/* MODO 2: CADASTRAR NOVA BIOMETRIA */}
          <View style={[styles.mainCard, { borderColor: '#0284C7' }]}>
            <View style={styles.cardHeaderRow}>
              <Text style={styles.cardBadgeEmoji}>📝</Text>
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={styles.cardMainTitle}>Cadastrar Nova Pessoa</Text>
                <Text style={styles.cardMainSubtitle}>
                  Grave seu rosto agora mesmo para salvar sua biometria no servidor.
                </Text>
              </View>
            </View>

            <Text style={styles.inputFieldLabel}>Seu Nome Completo:</Text>
            <TextInput
              style={styles.nameInput}
              value={registerName}
              onChangeText={setRegisterName}
              placeholder="Ex: Abraão da Silva"
              placeholderTextColor="#64748B"
              autoCapitalize="words"
            />

            <TouchableOpacity
              style={styles.registerMainButton}
              onPress={handleStartRegister}
              activeOpacity={0.8}
            >
              <Text style={styles.registerMainButtonText}>📸 CADASTRAR BIOMETRIA AO VIVO</Text>
            </TouchableOpacity>
          </View>

          {/* GERENCIAMENTO DE PESSOAS CADASTRADAS */}
          <View style={styles.usersCard}>
            <TouchableOpacity
              style={styles.usersHeaderToggle}
              onPress={() => {
                setShowUsersModal(!showUsersModal);
                if (!showUsersModal) fetchRegisteredUsers();
              }}
              activeOpacity={0.7}
            >
              <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
                <Text style={{ fontSize: 20 }}>👥</Text>
                <Text style={styles.usersCardTitle}>
                  Biometrias Cadastradas ({registeredUsers.length})
                </Text>
              </View>
              <Text style={styles.usersToggleText}>{showUsersModal ? '▲ Ocultar' : '▼ Ver Lista'}</Text>
            </TouchableOpacity>

            {showUsersModal && (
              <View style={styles.usersListContainer}>
                {loadingUsers ? (
                  <ActivityIndicator size="small" color="#38BDF8" style={{ marginVertical: 12 }} />
                ) : registeredUsers.length === 0 ? (
                  <Text style={styles.emptyUsersText}>
                    Nenhuma pessoa cadastrada ainda. Use o campo acima para se cadastrar!
                  </Text>
                ) : (
                  registeredUsers.map((u) => (
                    <View key={u.id} style={styles.userItemRow}>
                      <Image
                        source={{ uri: `${cleanUrl}${u.photo_url}` }}
                        style={styles.userItemPhoto}
                      />
                      <View style={{ flex: 1, marginLeft: 12 }}>
                        <Text style={styles.userItemName}>{u.name}</Text>
                        <Text style={styles.userItemId}>
                          🧠 {u.samples_count || 1} amostra{(u.samples_count || 1) > 1 ? 's' : ''} aprendida{(u.samples_count || 1) > 1 ? 's' : ''} • ID: {u.id.substring(0, 10)}...
                        </Text>
                      </View>
                      <TouchableOpacity
                        style={styles.deleteUserBtn}
                        onPress={() => deleteUser(u.id, u.name)}
                      >
                        <Text style={styles.deleteUserBtnText}>🗑️</Text>
                      </TouchableOpacity>
                    </View>
                  ))
                )}
              </View>
            )}
          </View>

          {/* CONFIGURAÇÃO DO SERVIDOR (VPS / IP) */}
          <View style={styles.serverConfigCard}>
            <TouchableOpacity
              style={styles.serverConfigHeader}
              onPress={() => setShowServerConfig(!showServerConfig)}
              activeOpacity={0.7}
            >
              <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
                <Text style={styles.serverConfigIcon}>🌐</Text>
                <View style={{ marginLeft: 8, flex: 1 }}>
                  <Text style={styles.serverConfigLabel}>Servidor Backend (VPS Oracle)</Text>
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
                  placeholder="https://132.226.242.158.sslip.io"
                  placeholderTextColor="#64748B"
                  autoCapitalize="none"
                  autoCorrect={false}
                />

                <Text style={styles.presetsLabel}>Atalhos Rápidos de Conexão:</Text>
                <View style={styles.presetsContainer}>
                  <TouchableOpacity
                    style={[styles.presetButton, apiUrl.includes('sslip.io') && styles.presetButtonActive]}
                    onPress={() => setApiUrl('https://132.226.242.158.sslip.io')}
                  >
                    <Text style={styles.presetButtonText}>🔒 VPS HTTPS Oficial (sslip.io)</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.presetButton}
                    onPress={() => setApiUrl('http://132.226.242.158')}
                  >
                    <Text style={styles.presetButtonText}>🌐 VPS Porta 80</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.presetButton}
                    onPress={() => setApiUrl('http://132.226.242.158:8000')}
                  >
                    <Text style={styles.presetButtonText}>🔌 VPS Porta 8000</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.presetButton}
                    onPress={() => setApiUrl('http://192.168.1.44:8000')}
                  >
                    <Text style={styles.presetButtonText}>💻 Wi-Fi Local (192.168.1.44)</Text>
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
                    <Text style={styles.testConnectionBtnText}>⚡ Testar Conexão com Servidor</Text>
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
                <Text style={styles.voiceSubtitle}>Orientação falada para terceira idade</Text>
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
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ==========================================
  // RENDERIZAÇÃO: TELA 2 - CÂMERA & PROVA DE VIDA
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

        <Text style={styles.livenessTip}>
          {actionMode === 'REGISTER'
            ? 'Olhe para a moldura para cadastrar seu rosto'
            : 'Mantenha o rosto parado na moldura'}
        </Text>
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
        <ActivityIndicator size="large" color="#38BDF8" />
        <Text style={styles.processingTitle}>
          {actionMode === 'REGISTER' ? 'Cadastrando Biometria' : 'Processando Autenticação'}
        </Text>
        <Text style={styles.processingSubtitle}>{statusMessage}</Text>
      </SafeAreaView>
    );
  }

  // ==========================================
  // RENDERIZAÇÃO: TELA 3 - SUCESSO DE CADASTRO
  // ==========================================
  if (screenState === 'REGISTER_SUCCESS') {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    const photoUrl = registrationData?.photo_url
      ? `${cleanUrl}${registrationData.photo_url}`
      : null;

    return (
      <SafeAreaView style={styles.successContainer}>
        <StatusBar style="light" />
        <View style={styles.successContent}>
          <View style={styles.successIconCircle}>
            <Text style={styles.successCheckIcon}>✓</Text>
          </View>

          <Text style={styles.successTitle}>BIOMETRIA CADASTRADA!</Text>
          <Text style={styles.successSubtitle}>
            Seu rosto foi registrado e salvo com sucesso na nuvem.
          </Text>

          {photoUrl && (
            <Image
              source={{ uri: photoUrl }}
              style={styles.registeredFaceCrop}
            />
          )}

          <View style={styles.resultDetailsCard}>
            <Text style={styles.detailItem}>👤 Nome: {registrationData?.name}</Text>
            <Text style={styles.detailItem}>🆔 ID: {registrationData?.user_id}</Text>
            <Text style={styles.detailItem}>🔒 Modelo: YuNet + SFace (128D)</Text>
            <Text style={styles.detailItem}>☁️ Armazenamento: Banco SQLite VPS</Text>
          </View>

          <TouchableOpacity
            style={styles.successButton}
            onPress={() => {
              setActionMode('VERIFY');
              handleStartVerify();
            }}
          >
            <Text style={styles.successButtonText}>TESTAR RECONHECIMENTO AGORA</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.successButton, { backgroundColor: 'transparent', borderWidth: 1, borderColor: '#FFFFFF', marginTop: 12 }]}
            onPress={resetToStart}
          >
            <Text style={[styles.successButtonText, { color: '#FFFFFF' }]}>VOLTAR AO INÍCIO</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // ==========================================
  // RENDERIZAÇÃO: TELA 4 - SUCESSO DE RECONHECIMENTO
  // ==========================================
  if (screenState === 'SUCCESS') {
    const cleanUrl = apiUrl.trim().replace(/\/+$/, '');
    const matched = verificationData?.matched_user;
    const photoUrl = matched?.photo_url ? `${cleanUrl}${matched.photo_url}` : null;

    return (
      <SafeAreaView style={styles.successContainer}>
        <StatusBar style="light" />
        <View style={styles.successContent}>
          <View style={styles.successIconCircle}>
            <Text style={styles.successCheckIcon}>✓</Text>
          </View>

          <Text style={styles.successTitle}>
            {matched?.name ? `OLÁ, ${matched.name.toUpperCase()}!` : 'IDENTIDADE CONFIRMADA!'}
          </Text>
          <Text style={styles.successSubtitle}>
            Reconhecimento facial e prova de vida aprovados.
          </Text>

          {photoUrl && (
            <Image
              source={{ uri: photoUrl }}
              style={styles.registeredFaceCrop}
            />
          )}

          <View style={styles.resultDetailsCard}>
            <Text style={styles.detailItem}>✅ Prova de Vida por Luz: Aprovada</Text>
            <Text style={styles.detailItem}>
              {matched ? `✅ Pessoa Reconhecida: ${matched.name}` : '✅ Rosto Compatível'}
            </Text>
            {verificationData?.samples_count !== undefined && (
              <Text style={styles.detailItem}>
                🧠 Perfil Adaptativo: {verificationData.samples_count} amostra{verificationData.samples_count > 1 ? 's' : ''} aprendida{verificationData.samples_count > 1 ? 's' : ''}
              </Text>
            )}
            {verificationData?.distance !== undefined && (
              <Text style={styles.distanceText}>
                Distância Biométrica: {verificationData.distance} (Limite: {verificationData.threshold})
              </Text>
            )}
            {verificationData?.jwt_token && (
              <Text style={styles.jwtPreviewText} numberOfLines={1}>
                Token JWT: {verificationData.jwt_token.substring(0, 32)}...
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
  // RENDERIZAÇÃO: TELA 5 - FALHA
  // ==========================================
  return (
    <SafeAreaView style={styles.failureContainer}>
      <StatusBar style="light" />
      <View style={styles.successContent}>
        <View style={styles.failureIconCircle}>
          <Text style={styles.failureCheckIcon}>✕</Text>
        </View>

        <Text style={styles.failureTitle}>Não Aprovado</Text>
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
    paddingVertical: 24,
    paddingHorizontal: 20,
  },
  header: {
    alignItems: 'center',
    marginTop: 10,
    marginBottom: 20,
  },
  appTitle: {
    fontSize: 26,
    fontWeight: '900',
    color: '#38BDF8',
    letterSpacing: 2,
    textAlign: 'center',
  },
  appSubtitle: {
    fontSize: 15,
    color: '#94A3B8',
    marginTop: 4,
    textAlign: 'center',
  },

  // CARDS PRINCIPAIS
  mainCard: {
    backgroundColor: '#1E293B',
    width: '100%',
    padding: 20,
    borderRadius: 20,
    marginBottom: 18,
    borderWidth: 1.5,
    borderColor: '#334155',
  },
  cardHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  cardBadgeEmoji: {
    fontSize: 32,
  },
  cardMainTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#F8FAFC',
  },
  cardMainSubtitle: {
    fontSize: 13,
    color: '#94A3B8',
    marginTop: 2,
    lineHeight: 18,
  },
  verifyMainButton: {
    backgroundColor: '#2563EB',
    paddingVertical: 18,
    borderRadius: 14,
    alignItems: 'center',
    elevation: 4,
    shadowColor: '#2563EB',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  verifyMainButtonText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: '900',
    letterSpacing: 0.5,
  },

  // CADASTRO
  nameInput: {
    backgroundColor: '#0F172A',
    color: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#475569',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    marginBottom: 16,
  },
  registerMainButton: {
    backgroundColor: '#0284C7',
    paddingVertical: 16,
    borderRadius: 14,
    alignItems: 'center',
  },
  registerMainButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: 'bold',
    letterSpacing: 0.5,
  },

  // LISTA DE USUÁRIOS
  usersCard: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 16,
    marginBottom: 18,
    borderWidth: 1,
    borderColor: '#334155',
  },
  usersHeaderToggle: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  usersCardTitle: {
    color: '#E2E8F0',
    fontSize: 15,
    fontWeight: 'bold',
    marginLeft: 8,
  },
  usersToggleText: {
    color: '#38BDF8',
    fontSize: 13,
    fontWeight: '600',
  },
  usersListContainer: {
    marginTop: 14,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#334155',
  },
  emptyUsersText: {
    color: '#94A3B8',
    fontSize: 13,
    textAlign: 'center',
    paddingVertical: 8,
  },
  userItemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    padding: 10,
    borderRadius: 12,
    marginBottom: 8,
  },
  userItemPhoto: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#334155',
  },
  userItemName: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: 'bold',
  },
  userItemId: {
    color: '#64748B',
    fontSize: 11,
    marginTop: 2,
  },
  deleteUserBtn: {
    padding: 8,
  },
  deleteUserBtnText: {
    fontSize: 18,
  },

  // CONFIGURAÇÃO DO SERVIDOR
  serverConfigCard: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 16,
    marginBottom: 18,
    borderWidth: 1,
    borderColor: '#334155',
  },
  serverConfigHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  serverConfigIcon: {
    fontSize: 22,
  },
  serverConfigLabel: {
    color: '#94A3B8',
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  serverConfigValue: {
    color: '#38BDF8',
    fontSize: 13,
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
    color: '#CBD5E1',
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
  presetButtonActive: {
    backgroundColor: '#0284C7',
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

  // VOZ
  voiceConfigRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#1E293B',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#334155',
    marginBottom: 20,
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
    textAlign: 'center',
    paddingHorizontal: 16,
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

  // TELA: SUCESSO
  successContainer: {
    flex: 1,
    backgroundColor: '#064E3B',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  successContent: {
    width: '100%',
    alignItems: 'center',
  },
  successIconCircle: {
    width: 90,
    height: 90,
    borderRadius: 45,
    backgroundColor: '#10B981',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  successCheckIcon: {
    fontSize: 50,
    color: '#FFFFFF',
    fontWeight: 'bold',
  },
  successTitle: {
    fontSize: 24,
    fontWeight: '900',
    color: '#FFFFFF',
    textAlign: 'center',
  },
  successSubtitle: {
    fontSize: 16,
    color: '#A7F3D0',
    textAlign: 'center',
    marginTop: 6,
    marginBottom: 20,
  },
  registeredFaceCrop: {
    width: 90,
    height: 90,
    borderRadius: 45,
    borderWidth: 3,
    borderColor: '#10B981',
    marginBottom: 18,
    backgroundColor: '#0F172A',
  },
  resultDetailsCard: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    padding: 16,
    borderRadius: 14,
    width: '100%',
    marginBottom: 24,
  },
  detailItem: {
    color: '#FFFFFF',
    fontSize: 15,
    marginVertical: 3,
    fontWeight: '600',
  },
  distanceText: {
    color: '#CBD5E1',
    fontSize: 13,
    marginTop: 6,
  },
  jwtPreviewText: {
    color: '#38BDF8',
    fontSize: 11,
    fontFamily: 'monospace',
    marginTop: 6,
    backgroundColor: 'rgba(0, 0, 0, 0.25)',
    padding: 6,
    borderRadius: 6,
  },
  successButton: {
    backgroundColor: '#FFFFFF',
    paddingVertical: 16,
    borderRadius: 14,
    width: '100%',
    alignItems: 'center',
  },
  successButtonText: {
    color: '#064E3B',
    fontSize: 16,
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
