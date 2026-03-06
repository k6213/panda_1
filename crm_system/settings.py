import os
import json
from pathlib import Path
import firebase_admin
from firebase_admin import credentials

# 1. 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. 보안 및 환경 설정
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-$*h1acx7s&s*=!9u&o+57rup_yxxubmb7nuyso9wn=l8of=3wd')
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [
    'localhost', 
    '127.0.0.1', 
    'panda-1-hd18.onrender.com', 
    '*' 
]

# 3. 애플리케이션 정의
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    'sales', 
]

# 4. 미들웨어 설정
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'crm_system.urls'
WSGI_APPLICATION = 'crm_system.wsgi.application'

# 템플릿 설정 (관리자 페이지용)
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# 5. 데이터베이스
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 7. 🌍 언어 및 시간 설정
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = False 

# 8. 정적 파일 및 미디어 파일 설정
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ⭐️ [신규] 미디어(이미지 업로드) 설정 추가
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

AUTH_USER_MODEL = 'sales.User'

# ==============================================================================
# ⭐️ CORS 및 CSRF 인증 설정
# ==============================================================================
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://panda-2-lupm.vercel.app",
    "https://panda-2-lupm-git-main-kanghos-projects-dd73d55a.vercel.app",
]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "https://panda-2-lupm.vercel.app",
    "https://panda-1-hd18.onrender.com",
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]
# ==============================================================================
# 🔥 Firebase Admin SDK 초기화
# ==============================================================================
if not firebase_admin._apps:
    try:
        fb_config_str = os.environ.get('FIREBASE_CONFIG')
        if fb_config_str:
            fb_config = json.loads(fb_config_str)
            cred = credentials.Certificate(fb_config)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase: 환경 변수를 통해 초기화 완료")
        else:
            local_key_path = os.path.join(BASE_DIR, "firebase-admin-sdk.json")
            if os.path.exists(local_key_path):
                cred = credentials.Certificate(local_key_path)
                firebase_admin.initialize_app(cred)
                print("✅ Firebase: 로컬 파일을 통해 초기화 완료")
            else:
                print("⚠️ Firebase: 인증 정보가 없습니다.")
    except Exception as e:
        print(f"❌ Firebase 초기화 에러: {e}")