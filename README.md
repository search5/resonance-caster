# GCP App Engine 배포 매뉴얼

## 프로젝트 개요
- **프레임워크**: Python Pyramid
- **배포 환경**: Google App Engine
- **사용 서비스**: Google Cloud Storage, Firestore
- **실행 서버**: Gunicorn

## 준비사항

### Poetry 설치
프로젝트는 Poetry를 사용하여 의존성을 관리합니다. Poetry를 먼저 설치해야 합니다:

**pipx 사용 (권장):**
```bash
pipx install poetry
```

**uv 사용:**
```bash
uv tool install poetry
```

### Google Cloud Platform 설정
1. **GCP 프로젝트 생성**
   - Google Cloud Console에서 새 프로젝트 생성
   - 프로젝트 ID 기록 (PROJECT_ID에 사용)

2. **필요한 API 활성화**
   - Cloud Storage API
   - Firestore API
   - App Engine API

3. **서비스 계정 설정 (필요시만)**
   - Google App Engine은 기본 서비스 계정을 제공합니다
   - 추가적인 권한이 필요한 경우에만 별도 서비스 계정 생성
   - 로컬 개발시에만 JSON 키 파일 필요

4. **Cloud Storage 버킷 생성**
   - Cloud Storage에서 새 버킷 생성
   - 버킷 이름 기록 (GCS_BUCKET_NAME에 사용)

5. **Firestore 데이터베이스 설정**
   - Firestore에서 데이터베이스 생성
   - 데이터베이스 ID 기록 (APP_FIRESTORE_DB에 사용)

### 로컬 개발용 환경변수 설정 (.env 파일)
**로컬 개발시에만** 프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 다음 내용을 입력:

```env
GCS_BUCKET_NAME=<생성한 GCS 버킷 이름>
JWT_SECRET=<임의의 긴 랜덤 문자열>
PROJECT_ID=<GCP 프로젝트 ID>
APP_FIRESTORE_DB=<Firestore 데이터베이스 ID>
GOOGLE_APPLICATION_CREDENTIALS=<서비스 계정 JSON 키 파일명>
```

**주의사항:**
- JWT_SECRET은 충분히 긴 랜덤 문자열을 사용하세요
- GOOGLE_APPLICATION_CREDENTIALS는 로컬 개발시에만 필요합니다
- 서비스 계정 JSON 키 파일은 로컬 개발시에만 프로젝트 루트에 위치시키세요
- `.env` 파일은 버전 관리에 포함하지 마세요 (`.gitignore`에 추가)

## 로컬 개발 및 테스트

### Poetry 환경 초기화
먼저 프로젝트 의존성을 설치합니다:
```bash
poetry install
```

### 로컬 서버 실행
```bash
poetry run pserve development.ini
```

이 명령으로 로컬 개발 서버를 시작할 수 있습니다.

## 배포 설정

### app.yaml 파일 수정
Google App Engine 배포를 위해 `app.yaml` 파일에 다음과 같이 gunicorn 실행 명령을 설정:

```yaml
runtime: python39

entrypoint: gunicorn --bind :$PORT main:application

env_variables:
  GCS_BUCKET_NAME: <GCS 버킷 이름>
  JWT_SECRET: <JWT 시크릿>
  PROJECT_ID: <GCP 프로젝트 ID>
  APP_FIRESTORE_DB: <Firestore DB ID>

automatic_scaling:
  min_instances: 1
  max_instances: 10
```

### 배포 명령
```bash
gcloud app deploy
```

## 주의사항
- App Engine은 기본 서비스 계정을 사용하므로 GOOGLE_APPLICATION_CREDENTIALS는 배포시 불필요합니다
- 서비스 계정 JSON 키 파일은 로컬 개발시에만 사용하며, 보안상 중요하므로 안전하게 관리하세요
- JWT_SECRET은 충분히 복잡하고 예측하기 어려운 값을 사용하세요
