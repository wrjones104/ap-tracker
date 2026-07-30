import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.getenv('SECRET_KEY', 'a-very-secret-key')
    DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
    DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
    DISCORD_API_BASE_URL = 'https://discord.com/api'
    DISCORD_AUTHORIZATION_BASE_URL = DISCORD_API_BASE_URL + '/oauth2/authorize'
    DISCORD_TOKEN_URL = DISCORD_API_BASE_URL + '/oauth2/token'

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False

class UatConfig(Config):
    """UAT configuration."""
    DEBUG = True

config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'uat': UatConfig
}

env = os.getenv('FLASK_ENV', 'development').lower().strip()
app_config = config_by_name.get(env, DevelopmentConfig)