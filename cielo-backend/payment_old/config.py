"""
Configurações do módulo de pagamento
Centraliza configurações e flags de ambiente
"""
import os
from django.conf import settings

# ============================================
# CONFIGURAÇÕES DE GATEWAY
# ============================================

# Modo MOCK para PIX (sandbox da Cielo não funciona)
PIX_MOCK_MODE = settings.PIX_MOCK_MODE  # true se quiser ativar o modo MOCK para testes locais

# Gateway padrão
DEFAULT_GATEWAY = 'cielo'

# ============================================
# CONFIGURAÇÕES DE TIMEOUT
# ============================================

# Timeout para requisições ao gateway (segundos)
GATEWAY_TIMEOUT = int(os.getenv('GATEWAY_TIMEOUT', '30'))

# Tempo máximo de expiração do QR Code PIX (segundos)
# Nova integração Cielo2: Máximo 86400 segundos (24 horas)
PIX_MAX_EXPIRATION = int(os.getenv('PIX_MAX_EXPIRATION', '86400'))  # 24 horas

# Tempo padrão de expiração do QR Code PIX (segundos)
# Ajustado para 30 minutos (1800s) - valor recomendado para pagamentos rápidos
PIX_DEFAULT_EXPIRATION = int(os.getenv('PIX_DEFAULT_EXPIRATION', '1800'))  # 30 minutos

# ============================================
# CONFIGURAÇÕES DE POLLING
# ============================================

# Número máximo de tentativas de polling
POLLING_MAX_ATTEMPTS = int(os.getenv('POLLING_MAX_ATTEMPTS', '60'))

# Intervalo entre tentativas de polling (segundos)
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '5'))

# ============================================
# CONFIGURAÇÕES DE SEGURANÇA
# ============================================

# Score mínimo do reCAPTCHA
RECAPTCHA_MIN_SCORE = float(os.getenv('RECAPTCHA_MIN_SCORE', '0.6'))

# Habilitar logs de debug (apenas desenvolvimento)
DEBUG_LOGS = settings.DEBUG

# ============================================
# MENSAGENS DE ERRO
# ============================================

ERROR_MESSAGES = {
    'INVALID_CHECKOUT_LINK': 'Link de checkout inválido ou expirado',
    'PAYMENT_PROCESSING_ERROR': 'Erro ao processar pagamento',
    'GATEWAY_TIMEOUT': 'Tempo limite excedido ao comunicar com gateway',
    'INVALID_CARD_DATA': 'Dados do cartão inválidos',
    'INSUFFICIENT_FUNDS': 'Saldo insuficiente',
    'CARD_EXPIRED': 'Cartão expirado',
    'INVALID_CVV': 'CVV inválido',
}

# ============================================
# STATUS DE PAGAMENTO
# ============================================

PAYMENT_STATUS = {
    'PENDING': 'pending',
    'PROCESSING': 'processing',
    'APPROVED': 'approved',
    'DENIED': 'denied',
    'CANCELLED': 'cancelled',
    'WAITING': 'waiting',
    'ERROR': 'error',
}

# ============================================
# FUNÇÕES AUXILIARES
# ============================================

def is_mock_mode() -> bool:
    """
    Verifica se está em modo MOCK
    
    Returns:
        bool: True se modo MOCK ativo
    """
    return PIX_MOCK_MODE

def get_pix_expiration(custom_time: int = None) -> int:
    """
    Obtém tempo de expiração do PIX
    
    Args:
        custom_time: Tempo customizado em segundos
        
    Returns:
        int: Tempo de expiração em segundos (limitado ao máximo)
    """
    if custom_time:
        return min(custom_time, PIX_MAX_EXPIRATION)
    return PIX_DEFAULT_EXPIRATION

def should_log_debug() -> bool:
    """
    Verifica se deve logar informações de debug
    
    Returns:
        bool: True se debug ativo
    """
    return DEBUG_LOGS
