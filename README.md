# 🛡️ BeyondTime - Sistema de Prova de Vida por Flash de Cores & Reconhecimento Facial 1:1

Solução 100% **open-source**, **gratuita** e **autocontida** para autenticação biométrica e prevenção contra estelionato amoroso/perfis falsos em aplicativos de relacionamento, especialmente desenhada para a **terceira idade** (sem exigir movimentos complexos de cabeça ou expressões forçadas).

---

## 📌 Índice
1. [Como Funciona a Tecnologia](#-como-funciona-a-tecnologia)
   - [1.1. Prova de Vida Ativa por Reflexo de Luz (Flash Challenge-Response)](#11-prova-de-vida-ativa-por-reflexo-de-luz-flash-challenge-response)
   - [1.2. Reconhecimento de Pontos e Linhas Faciais (ArcFace)](#12-reconhecimento-de-pontos-e-linhas-faciais-arcface)
2. [Arquitetura e Fluxo do Sistema](#-arquitetura-e-fluxo-do-sistema)
3. [Estrutura de Arquivos](#-estrutura-de-arquivos)
4. [Pré-requisitos de Instalação](#-pré-requisitos-de-instalação)
5. [Guia Passo a Passo de Execução](#-guia-passo-a-passo-de-execução)
   - [Passo 1: Subir o Servidor Backend (Docker)](#passo-1-subir-o-servidor-backend-docker)
   - [Passo 2: Rodar o Aplicativo Mobile (React Native / Expo)](#passo-2-rodar-o-aplicativo-mobile-react-native--expo)
6. [O que Já Está Implementado vs. Calibragens Futuras](#-o-que-já-está-implementado-vs-calibragens-futuras)
7. [Licença](#-licença)

---

## 🔬 Como Funciona a Tecnologia

### 1.1. Prova de Vida Ativa por Reflexo de Luz (Flash Challenge-Response)
Similar à tecnologia utilizada por grandes bancos e fintechs (ex: Mercado Pago, FaceTec):
1. O backend sorteia uma sequência aleatória de 3 cores (exemplo: `VERMELHO, AZUL, VERDE`) e envia para o aplicativo com um token de sessão.
2. O aplicativo abre a câmera frontal com uma moldura oval amigável para o idoso, eleva o brilho da tela para 100% e projeta as cores em tela cheia por 750ms cada, gravando o reflexo no rosto em vídeo.
3. O backend analisa o ganho relativo ($\Delta$) de cada canal espectral (R, G, B) em relação ao frame inicial escuro (baseline):
   $$\Delta R = \frac{R_t - R_0}{R_0}, \quad \Delta G = \frac{G_t - G_0}{G_0}, \quad \Delta B = \frac{B_t - B_0}{B_0}$$
4. **Por que impede golpistas?**
   - **Vídeos da internet e fotos impressas:** Não possuem como adivinhar a ordem das cores sorteadas em tempo real.
   - **Telas de celulares/tablets:** Apresentam distorção moiré, vidro reflexivo plano e reflexos especulares anômalos.
   - **Pele humana real:** A pele possui relevo tridimensional (curvatura do nariz, maçãs do rosto e testa) que absorve e dispersa a luz difusamente.

### 1.2. Reconhecimento de Pontos e Linhas Faciais (ArcFace)
O sistema utiliza a rede neural **ArcFace** (Additive Angular Margin Loss), uma das mais precisas do estado da arte em visão computacional open-source:
1. **Detecção de Marcos Anatômicos (Landmarks):** Localiza os pontos-chave da face (cantos dos olhos, ponta do nariz e extremidades dos lábios).
2. **Alinhamento Afim Digital:** Corrige inclinações de cabeça, centralizando a face matematicamente.
3. **Extração de Vetor de Características (Embeddings):** Transforma as linhas, relevos e proporções do rosto em um vetor numérico de **512 dimensões**.
4. **Comparação por Distância de Cosseno:** Compara o vetor do vídeo vivo com o vetor da foto de cadastro. Se a distância for menor que o limiar (`threshold = 0.68`), a identidade é confirmada com altíssima precisão.

---

## 📐 Arquitetura e Fluxo do Sistema

```text
[ Aplicativo Mobile (Expo) ]                      [ Servidor Backend (FastAPI + Docker) ]
            |                                                        |
            |------------ 1. GET /challenge ------------------------>|
            |                                                        | Sorteia sequência de cores
            |<----------- 2. Cores: ['VERMELHO', 'AZUL', 'VERDE'] ---| (Token temporário)
            |                                                        |
  [Ajusta Brilho: 100%]                                              |
  [Filma rosto com Flash das Cores]                                  |
  [Restaura Brilho original]                                         |
            |                                                        |
            |------------ 3. POST /verify (Vídeo + Foto Perfil) ---->|
            |                                                        | 4. OpenCV: Valida picos de luz espectral
            |                                                        | 5. ArcFace: Extrai 512 embeddings e compara
            |<----------- 6. Retorna { verified: true/false } -------|
```

---

## 🗂️ Estrutura de Arquivos

```text
Reconchecimento_facil/
├── README.md                   # Documentação completa e guia de execução
├── backend/
│   ├── Dockerfile              # Imagem Docker com dependências C++, OpenCV e download do ArcFace
│   ├── docker-compose.yml      # Orquestração do container do serviço
│   ├── requirements.txt        # Dependências Python com versões travadas (FastAPI, OpenCV, DeepFace)
│   ├── main.py                 # API REST com rotas /challenge, /verify e algoritmo Delta RGB
│   └── test_liveness.py        # Teste unitário com geração sintética de vídeo
└── mobile/
    ├── package.json            # Dependências React Native / Expo
    ├── app.json                # Permissões de Câmera, Áudio e Brilho
    ├── tsconfig.json           # Configurações TypeScript
    ├── index.ts                # Ponto de entrada do Expo
    └── App.tsx                 # Interface sênior acessível (START, LIVENESS, SUCESSO/FALHA)
```

---

## 📋 Pré-requisitos de Instalação

Antes de começar, verifique se você tem instalado no seu computador:

1. **Docker & Docker Compose:**
   - Instalação no Linux: `sudo apt-get install docker.io docker-compose-v2`
   - Certifique-se de que o daemon do Docker está rodando: `docker ps`
2. **Node.js (versão 18 ou superior) & npm:**
   - Verifique com: `node -v` e `npm -v`
3. **Expo Go no Smartphone:**
   - Instale o app **Expo Go** no seu smartphone (disponível na Google Play Store e Apple App Store).
   - O computador e o smartphone devem estar conectados na **mesma rede Wi-Fi**.

---

## 🚀 Guia Passo a Passo de Execução

### Passo 1: Subir o Servidor Backend (Docker)

1. Abra o terminal e entre na pasta `backend`:
   ```bash
   cd backend
   ```

2. Construa a imagem Docker e inicialize o serviço:
   ```bash
   docker compose up --build -d
   ```
   > **Nota:** No primeiro build, o Docker baixará automaticamente os pesos neurais do ArcFace para dentro da imagem. Isso garante que o backend funcionará para sempre, mesmo que links externos da internet fiquem fora do ar.

3. Verifique se o container está rodando e acompanhe os logs:
   ```bash
   docker logs -f liveness_verification_api
   ```

4. Teste no navegador do computador:
   - Documentação Swagger Interativa: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Teste de Saúde da API: [http://localhost:8000/health](http://localhost:8000/health)

---

### Passo 2: Rodar o Aplicativo Mobile (React Native / Expo)

1. **Descubra o IP local do seu computador na rede Wi-Fi:**
   - No Linux/Mac: execute `hostname -I` ou `ifconfig` (exemplo: `192.168.1.15`).
   - No Windows: execute `ipconfig` (procure por Endereço IPv4).

2. **Configure o IP no aplicativo:**
   - **Opção A (Direto no Celular):** Abra o app no smartphone e clique em **⚙️ Configurar** logo abaixo do card de foto. Digite o IP do seu computador ou toque em um dos atalhos rápidos (*Wi-Fi*, *Emulador*, *Localhost*). Você pode inclusive tocar em **⚡ Testar Conectividade** para validar a conexão antes de iniciar o teste!
   - **Opção B (Variável de Ambiente):** Defina `EXPO_PUBLIC_API_URL` ao iniciar o Expo:
     ```bash
     EXPO_PUBLIC_API_URL="http://192.168.1.15:8000" npx expo start
     ```
   - **Opção C (Arquivo):** Se preferir, altere o valor padrão no topo de `mobile/App.tsx`.

3. **Instale as dependências e inicie o Expo:**
   - No terminal, acesse a pasta `mobile`:
     ```bash
     cd ../mobile
     npm install
     npx expo start
     ```

4. **Abra o app no celular:**
   - Abra o app **Expo Go** no seu celular físico.
   - Aponte a câmera para o QR Code exibido no terminal.
   - Selecione a foto de perfil/cadastro desejada e toque em **INICIAR TESTE**.
   - Segure o celular na frente do rosto e aguarde o flash de cores confirmar sua autenticidade!

---

## 🧪 Executando Testes Sintéticos sem Celular

O backend inclui uma suíte completa de testes unitários automatizados que simulam vídeos com e sem reflexo espectral, avaliam a detecção de ausência de rosto e testam a seleção do frame mais nítido via Laplaciano:

```bash
cd backend
python3 test_liveness.py
```
Resultado:
```text
🧪 [1/3] Testando rejeição imediata quando nenhum rosto é detectado...
  -> Resultado: sucesso=False, mensagem='Nenhum rosto identificado no vídeo'
  -> Rejeição sem rosto: PASSOU ✅

🧪 [2/3] Testando seleção inteligente do melhor frame com filtro Laplaciano...
  -> Score frame selecionado: 1452.33 vs borrado: 12.45
  -> Seleção Laplaciana: PASSOU ✅

🧪 [3/3] Testando algoritmo Delta RGB com ROI dinâmica...
  -> Teste com reflexo real: PASSOU ✅ (Reflexo espectral correspondente à pele real.)
  -> Teste com spoofing (sem reflexo): PASSOU ✅ (Reflexo não compatível)
  -> Validação espectral Delta RGB: PASSOU ✅

🎉 Todos os testes unitários foram concluídos com 100% de sucesso!
```

### Testes de Estresse, Criptografia e Resiliência

Execute a suíte de estresse que valida assinatura de tokens JWT, proteção contra força bruta, decodificação de múltiplos formatos e imagens corrompidas:

```bash
cd backend
python3 test_stress.py
```
Resultado:
```text
🧪 [Estresse 1/6] Testando geração e validação de Token JWT... PASSOU ✅
🧪 [Estresse 2/6] Testando rejeição de Token JWT adulterado/forjado... PASSOU ✅
🧪 [Estresse 3/6] Testando proteção contra força bruta (Rate Limiting)... PASSOU ✅
🧪 [Estresse 4/6] Testando formatos de imagem (PNG, WEBP, JPG)... PASSOU ✅
🧪 [Estresse 5/6] Testando resiliência contra arquivos corrompidos... PASSOU ✅
🧪 [Estresse 6/6] Testando registro e retenção de logs de auditoria... PASSOU ✅

🎉 Todos os 6 testes de estresse e resiliência foram concluídos com 100% de sucesso!
```

---

## 🔍 O que Já Está Implementado vs. Calibragens Futuras

| Componente | Estado Atual | Detalhes Técnicos |
| :--- | :---: | :--- |
| **Prova de Vida por Cores** | ✅ Implementado | Algoritmo Delta RGB ($\Delta R, \Delta G, \Delta B$) que não quebra em salas iluminadas. |
| **Reconhecimento Facial 1:1** | ✅ Implementado | ArcFace com extração de vetor 512D e distância por cosseno. |
| **Isolamento de Ambiente** | ✅ Implementado | Dockerfile hermético com pré-download dos pesos neurais. |
| **UX Sênior & Acessibilidade** | ✅ Implementado | 3 telas simples, botões grandes, síntese de voz (`expo-speech`), vibração tátil (`expo-haptics`) e switch de controle. |
| **Detecção Facial Dinâmica (ROI)** | ✅ Implementado | Detector Haar Cascade localiza o rosto nos frames iniciais e ancora a medição na testa/bochechas. Rejeita sem rosto com mensagem padronizada. |
| **Configuração de IP em Tela** | ✅ Implementado | Configuração em tempo real no app, atalhos rápidos (*Wi-Fi*, *Emulador*, *Localhost*), teste de conectividade e suporte a `EXPO_PUBLIC_API_URL`. |
| **Seleção Inteligente de Frame** | ✅ Implementado | Varredura temporal com variância do filtro Laplaciano (`cv2.Laplacian`), eliminando motion blur e piscadas antes do ArcFace. |
| **Tratamento Acolhedor de Erros** | ✅ Implementado | Captura de exceções técnicas do DeepFace e mensagens humanizadas em português orientando o idoso com clareza e empatia. |
| **Token JWT & Selo de Perfil** | ✅ Implementado | Assinatura HMAC-SHA256 gerando token de atestação e `SELO_VERIFICADO_OURO` para integração direta com o Spring Boot do BeyondTime. |
| **Rate Limiting & Auditoria** | ✅ Implementado | Proteção contra força bruta (máximo 5 req/min por IP) e buffer de auditoria com endpoint `/audit/logs`. |
| **Resiliência de Rede** | ✅ Implementado | Mecanismo de retry automático com backoff exponencial no app mobile contra oscilações de Wi-Fi. |

---

## 📄 Licença
Este projeto é distribuído sob licença livre e open-source para fins educacionais, proteção contra fraudes e desenvolvimento comunitário.

