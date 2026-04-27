"""
Gerenciador centralizado de status de pagamentos e links
Alinhado com o PaymentStatusService do frontend
"""
from rest_framework.response import Response
from rest_framework import status


class PaymentStatusHandler:
    """
    Classe para gerenciar status de links e transações de pagamento
    Mantém consistência com o frontend
    """
    
    # Status válidos para LINKS (CheckoutLink)
    LINK_STATUS = {
        'valid': 'Válido',
        'used': 'Já Utilizado',
        'expired': 'Expirado',
        'canceled': 'Cancelado'
    }
    
    # Status válidos para TRANSAÇÕES (PaymentTransaction)
    TRANSACTION_STATUS = {
        'pending': 'Pendente',
        'processing': 'Processando',
        'approved': 'Aprovado',
        'denied': 'Negado',
        'canceled': 'Cancelado',
        'refunded': 'Reembolsado'
    }
    
    @staticmethod
    def get_link_status_response(link_status, pedido_id=None, transaction_id=None):
        """
        Retorna resposta para status de LINK de pagamento
        """
        link_responses = {
            'used': {
                "detail": "Este link de pagamento já foi utilizado.",
                "message": "Cada link é único e só pode ser usado uma vez. Em caso de dúvidas, entre em contato com o suporte.",
                "link_status": "used",
                "pedido_id": pedido_id,
                "transaction_id": transaction_id,
                "can_retry": False,
                "http_status": status.HTTP_400_BAD_REQUEST
            },
            
            'expired': {
                "detail": "Este link de pagamento expirou.",
                "message": "O link não foi utilizado e o prazo de validade expirou. Solicite um novo link ao suporte.",
                "link_status": "expired",
                "pedido_id": pedido_id,
                "can_retry": False,
                "http_status": status.HTTP_400_BAD_REQUEST
            },
            
            'canceled': {
                "detail": "Este link de pagamento foi cancelado.",
                "message": "O link foi cancelado pelo vendedor. Entre em contato com o suporte para gerar um novo link.",
                "link_status": "canceled",
                "pedido_id": pedido_id,
                "can_retry": False,
                "http_status": status.HTTP_400_BAD_REQUEST
            },
            
            'valid': {
                "detail": "Link de pagamento válido.",
                "message": "Você pode prosseguir com o pagamento.",
                "link_status": "valid",
                "pedido_id": pedido_id,
                "can_retry": False,
                "http_status": status.HTTP_200_OK
            }
        }
        
        # Pegar resposta ou usar padrão
        response_data = link_responses.get(link_status, {
            "detail": "Status de link desconhecido.",
            "message": "Entre em contato com o suporte.",
            "link_status": link_status,
            "pedido_id": pedido_id,
            "can_retry": False,
            "http_status": status.HTTP_400_BAD_REQUEST
        })
        
        http_status_code = response_data.pop('http_status')
        return Response(response_data, status=http_status_code)
    
    @staticmethod
    def get_transaction_status_response(payment_status, pedido_id=None, transaction_id=None, denial_reason=None):
        """
        Retorna resposta para status de TRANSAÇÃO de pagamento
        """
        transaction_responses = {
            'approved': {
                "detail": "Pagamento aprovado com sucesso!",
                "message": "Seu pagamento foi processado com sucesso. Obrigado pela sua compra!",
                "payment_status": "approved",
                "pedido_id": pedido_id,
                "transaction_id": transaction_id,
                "can_retry": False,
                "show_success": True,
                "http_status": status.HTTP_200_OK
            },
            
            'pending': {
                "detail": "Pagamento pendente.",
                "message": "Seu pagamento está pendente. Aguarde enquanto processamos sua solicitação.",
                "payment_status": "pending",
                "pedido_id": pedido_id,
                "transaction_id": transaction_id,
                "can_retry": False,
                "show_status_check": True,
                "http_status": status.HTTP_200_OK
            },
            
            'processing': {
                "detail": "Processando pagamento.",
                "message": "Estamos processando seu pagamento. Isso pode levar alguns instantes.",
                "payment_status": "processing",
                "pedido_id": pedido_id,
                "transaction_id": transaction_id,
                "can_retry": False,
                "show_status_check": True,
                "http_status": status.HTTP_200_OK
            },
            
            'denied': {
                "detail": "Pagamento negado.",
                "message": "Não foi possível processar seu pagamento. Verifique os dados e tente novamente.",
                "payment_status": "denied",
                "pedido_id": pedido_id,
                "transaction_id": transaction_id,
                "denial_reason": denial_reason,
                "can_retry": True,
                "show_retry": True,
                "http_status": status.HTTP_200_OK
            },
            
            'canceled': {
                "detail": "Pagamento cancelado.",
                "message": "A transação foi cancelada. Você pode tentar novamente.",
                "payment_status": "canceled",
                "pedido_id": pedido_id,
                "transaction_id": transaction_id,
                "can_retry": True,
                "show_retry": True,
                "http_status": status.HTTP_200_OK
            },
            
            'refunded': {
                "detail": "Pagamento reembolsado.",
                "message": "Este pagamento foi reembolsado. O valor foi devolvido para sua conta.",
                "payment_status": "refunded",
                "pedido_id": pedido_id,
                "transaction_id": transaction_id,
                "can_retry": False,
                "http_status": status.HTTP_200_OK
            }
        }
        
        # Pegar resposta ou usar padrão
        response_data = transaction_responses.get(payment_status, {
            "detail": "Status de pagamento desconhecido.",
            "message": "Entre em contato com o suporte.",
            "payment_status": payment_status,
            "pedido_id": pedido_id,
            "transaction_id": transaction_id,
            "can_retry": False,
            "http_status": status.HTTP_400_BAD_REQUEST
        })
        
        http_status_code = response_data.pop('http_status')
        return Response(response_data, status=http_status_code)
    
    @staticmethod
    def is_valid_link_transition(from_status, to_status):
        """
        Valida se uma transição de status de link é permitida
        Links cancelados, usados ou expirados NÃO podem mudar
        """
        # Estados finais não podem mudar
        if from_status in ['canceled', 'used', 'expired']:
            return False
        
        # Link válido pode ir para: usado, expirado ou cancelado
        if from_status == 'valid':
            return to_status in ['used', 'expired', 'canceled']
        
        return False
    
    @staticmethod
    def is_valid_transaction_transition(from_status, to_status):
        """
        Valida se uma transição de status de transação é permitida
        """
        # Aprovado só pode ir para reembolsado
        if from_status == 'approved':
            return to_status == 'refunded'
        
        # Reembolsado é final
        if from_status == 'refunded':
            return False
        
        # Negado ou cancelado pode ser retentado (volta para pending)
        if from_status in ['denied', 'canceled']:
            return to_status == 'pending'
        
        # Fluxo normal
        valid_transitions = {
            'pending': ['processing', 'canceled'],
            'processing': ['approved', 'denied', 'canceled']
        }
        
        return to_status in valid_transitions.get(from_status, [])
    
    @staticmethod
    def get_status_transition_log(from_status, to_status, context='transaction'):
        """
        Retorna mensagem de log para transição de status
        """
        context_label = "Link" if context == 'link' else "Transação"
        return f"{context_label}: {from_status.upper()} → {to_status.upper()}"


# Funções auxiliares para manter compatibilidade com código existente
def get_payment_status_response(payment_status, pedido_id=None, transaction_id=None, denial_reason=None):
    """
    Função de compatibilidade - usa o handler de transações
    """
    return PaymentStatusHandler.get_transaction_status_response(
        payment_status, 
        pedido_id, 
        transaction_id, 
        denial_reason
    )


def get_link_status_response(link_status, pedido_id=None, transaction_id=None):
    """
    Nova função para status de links
    """
    return PaymentStatusHandler.get_link_status_response(
        link_status, 
        pedido_id, 
        transaction_id
    )
