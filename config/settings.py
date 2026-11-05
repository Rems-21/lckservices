"""
Paramètres Django 5.x pour la plateforme LCK Services SARL.
Architecture 3 couches : Présentation (Bootstrap 5.3 / JS ES6), Applicative (Django), Données (MySQL InnoDB).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Enregistrement automatique des DLL GTK3/MSYS2 sous Windows pour WeasyPrint si présentes
if os.name == "nt":
    _gtk_candidates = [
        r"C:\Program Files\GTK3-Runtime Win64\bin",
        r"C:\Program Files (x86)\GTK3-Runtime Win64\bin",
        r"C:\msys64\mingw64\bin",
        r"C:\msys64\ucrt64\bin",
    ]
    for _gtk_dir in _gtk_candidates:
        if os.path.isdir(_gtk_dir):
            os.environ["PATH"] = _gtk_dir + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(_gtk_dir)
                except OSError:
                    pass

SECRET_KEY = os.getenv("SECRET_KEY", "lck-services-sarl-dev-secret-key-2026")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost,*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Modules métiers indépendants LCK Services SARL
    "core",
    "accounts",
    "clients",
    "shipments",
    "cargo",
    "logistics",
    "finance",
    "billing",
    "documents",
    "communications",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.AuditContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.global_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Base de données relationnelle MySQL 8+ (Moteur InnoDB)
DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "core.db_backends.mysql"),
        "NAME": os.getenv("DB_NAME", "lck_services_db"),
        "USER": os.getenv("DB_USER", "root"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES', default_storage_engine=INNODB",
        },
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "reports:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# Paramètres société par défaut
COMPANY_DEFAULTS = {
    "name": os.getenv("COMPANY_NAME", "LCK Services SARL"),
    "slogan": os.getenv("COMPANY_SLOGAN", "Transit, Transport International & Groupage Maritime et Aérien"),
    "phone": os.getenv("COMPANY_PHONE", "+237 600 00 00 00"),
    "email": os.getenv("COMPANY_EMAIL", "contact@lckservices.com"),
    "address": os.getenv("COMPANY_ADDRESS", "Douala, Cameroun"),
    "default_currency": os.getenv("DEFAULT_CURRENCY", "FCFA"),
}
