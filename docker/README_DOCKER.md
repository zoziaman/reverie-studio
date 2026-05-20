# Reverie Studio Docker 가이드 (WSL2 + NVIDIA)

이 문서는 Windows 11 + WSL2 환경에서 Reverie Studio를 Docker로 실행하기 위한 최소 가이드입니다.

## 1) 요구사항
- Windows 11
- NVIDIA GPU (최소 RTX 4060Ti 8GB)
- 최신 NVIDIA 드라이버
- Docker Desktop (WSL2 backend)
- Ubuntu 등 WSL2 배포판 1개 이상

---

## 2) WSL2 + NVIDIA Toolkit 설정

WSL 터미널(Ubuntu)에서 실행:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo service docker restart
```

GPU 인식 확인:

```bash
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

---

## 3) 환경변수 준비

프로젝트 루트에 `.env` 파일 생성:

```env
GEMINI_API_KEY=your_gemini_api_key
SD_MODELS_PATH=C:/AI/sd-models
REVERIE_ROOT=C:/path/to/reverie-studio
```

> `GEMINI_API_KEY`는 반드시 사용자 본인 키를 입력해야 합니다.

---

## 4) 실행 방법

프로젝트 루트에서 실행:

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml --env-file .env up -d
```

상태 확인:

```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f reverie-studio
```

---

## 5) 서비스 구성
- `reverie-studio` : Reverie Studio GPU 런타임
- `stable-diffusion` : CUDA 기반 이미지 생성 서버
- `gpt-sovits` : CUDA 기반 음성 합성 서버

---

## 6) 자주 겪는 문제
- **GPU가 안 잡히는 경우**: Docker Desktop 재시작 + `wsl --shutdown` 후 재실행
- **7860/9880 포트 충돌**: 로컬에서 실행 중인 동일 포트 프로세스 종료
- **모델 로드 실패**: `SD_MODELS_PATH` 및 `REVERIE_ROOT` 경로 오타 확인
