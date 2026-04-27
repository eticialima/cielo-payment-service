from django.urls import path, include
from rest_framework.routers import DefaultRouter
from payment.views import (
    CheckoutLinkViewSet, 
    criar_link_pagamento,
    buscar_links_por_pedido,
    PaymentCieloLioViewSet
)
from payment.payment_views import (
    validar_checkout_link,
    PaymentProcessView,
    PaymentListView,
    PaymentTransactionViewSet,
    PaymentAttemptDetailView,
    PaymentWebhookDetailView,
    PaymentWebhookView,
    PaymentStatusView,
    Get3DSTokenView,
    Log3DSEventView,
    Test3DSCredentialsView
)
router = DefaultRouter()
router.register(r'links', CheckoutLinkViewSet, basename='checkoutlink')
router.register(r'cielo-lio', PaymentCieloLioViewSet, basename='cielolio')
router.register(r'transactions', PaymentTransactionViewSet, basename='payment-transactions')

urlpatterns = [
    path('', include(router.urls)),

    # cria link de checkout
    path('criar-link/', criar_link_pagamento, name='criar_link_pagamento'),

    # busca links de um pedido (aceita string ou int)
    path('links-pedido/<str:pedido_id>/', buscar_links_por_pedido, name='buscar_links_por_pedido'),

    # valida link de checkout
    path('validar-checkout-link/<str:chave>/', validar_checkout_link, name='validar_checkout_link'), 

    # processa pagamento
    path('process/', PaymentProcessView.as_view(), name='payment-process'),

    # lista pagamentos
    path('list/', PaymentListView.as_view(), name='payment-list'),

    # detalhes de uma tentativa de pagamento específica
    path('attempt/<int:attempt_id>/', PaymentAttemptDetailView.as_view(), name='attempt-detail'),

    # status pagamento
    path('status/<str:transaction_id>/', PaymentStatusView.as_view(), name='payment-status'),

    # Webhook de pagamento
    path('webhook/', PaymentWebhookView.as_view(), name='payment-webhook'),

    # detalhes de um webhook específico
    path('webhook/<int:webhook_id>/', PaymentWebhookDetailView.as_view(), name='webhook-detail'),

    # Gerar token 3DS para autenticação
    path('3ds/token/', Get3DSTokenView.as_view(), name='3ds-token'),

    # Registrar eventos 3DS (onReady, onSuccess, onFailure, etc)
    path('3ds/log/', Log3DSEventView.as_view(), name='3ds-log'),

    # Testar credenciais 3DS (útil para diagnóstico)
    path('3ds/test/', Test3DSCredentialsView.as_view(), name='3ds-test'),
]
