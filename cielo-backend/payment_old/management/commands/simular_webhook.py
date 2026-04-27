"""
Comando para simular webhook da Cielo aprovando pagamento (PIX, Cartão, Débito)

Uso:
    python manage.py simular_webhook_pix <id_ou_transaction_id>
    
Exemplos:
    python manage.py simular_webhook 123
    python manage.py simular_webhook MOCK-PIX-f86898827df0445f
    python manage.py simular_webhook 6463896e-04e7-407b-ba38-1bc6b8c4f4b7 --status 2
"""

from django.core.management.base import BaseCommand
from payment.models import PaymentTransaction
import json


class Command(BaseCommand):
    help = 'Simula webhook da Cielo aprovando pagamento (PIX, Cartão ou Débito)'

    def add_arguments(self, parser):
        parser.add_argument(
            'transaction_identifier',
            type=str,
            help='ID numérico ou transaction_id (PaymentId) da transação'
        )
        parser.add_argument(
            '--status',
            type=int,
            default=2,
            help='Status Cielo (2=Approved, 3=Denied, 10=Canceled). Default: 2'
        )

    def handle(self, *args, **options):
        transaction_identifier = options['transaction_identifier']
        cielo_status = options['status']
        
        status_map = {
            2: 'APPROVED (PaymentConfirmed)',
            3: 'DENIED',
            10: 'CANCELED (Voided)',
            12: 'PENDING'
        }
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write(self.style.WARNING("🧪 SIMULANDO WEBHOOK CIELO"))
        self.stdout.write("="*80)
        
        try:
            # Tentar encontrar por ID numérico ou por transaction_id (PaymentId)
            transaction = None
            
            # Primeiro tenta como ID numérico
            if transaction_identifier.isdigit():
                try:
                    transaction = PaymentTransaction.objects.get(id=int(transaction_identifier))
                    self.stdout.write(f"\n Encontrado por ID: {transaction_identifier}")
                except PaymentTransaction.DoesNotExist:
                    pass
            
            # Se não encontrou, tenta como transaction_id (string)
            if not transaction:
                try:
                    transaction = PaymentTransaction.objects.get(transaction_id=transaction_identifier)
                    self.stdout.write(f"\n Encontrado por transaction_id: {transaction_identifier}")
                except PaymentTransaction.DoesNotExist:
                    pass
            
            if not transaction:
                raise PaymentTransaction.DoesNotExist()
            
            self.stdout.write(f"\n Transação encontrada:")
            self.stdout.write(f"   ID: {transaction.id}")
            self.stdout.write(f"   Transaction ID Cielo: {transaction.transaction_id}")
            self.stdout.write(f"   Pedido: {transaction.checkout_link.pedido.id}")
            self.stdout.write(f"   Status Atual: {transaction.status}")
            self.stdout.write(f"   Método: {transaction.metodo_pagamento}")
            
            # Mostrar valores detalhados
            if transaction.metodo_pagamento == 'credit_card' and transaction.installments and transaction.installments > 1:
                valor_principal = transaction.valor / 100  # transaction.valor está em CENTAVOS
                # transaction.valor_com_juros está em REAIS (do frontend), NÃO dividir por 100
                valor_com_juros = float(transaction.valor_com_juros) if transaction.valor_com_juros else valor_principal
                valor_parcela = valor_com_juros / transaction.installments if transaction.installments else valor_com_juros
                
                self.stdout.write(f"   Valor Principal: R$ {valor_principal:,.2f}")
                self.stdout.write(f"   Valor com Juros: R$ {valor_com_juros:,.2f} ({transaction.installments}x de R$ {valor_parcela:,.2f})")
            else:
                self.stdout.write(f"   Valor: R$ {transaction.valor / 100:,.2f}")
            
            if not transaction.transaction_id:
                self.stdout.write(self.style.ERROR("\n Transação sem transaction_id da Cielo!"))
                self.stdout.write(self.style.ERROR("   Não é possível simular webhook sem PaymentId"))
                return
            
            # Montar payload do webhook como a Cielo envia
            webhook_payload = {
                "PaymentId": transaction.transaction_id,
                "ChangeType": 1,  # Mudança de status da transação
                "Payment": {
                    "PaymentId": transaction.transaction_id,
                    "Status": cielo_status,
                    "ReturnCode": "00" if cielo_status == 2 else "57",
                    "ReturnMessage": "Transacao autorizada" if cielo_status == 2 else "Transacao negada",
                    "AuthorizationCode": f"SIM{transaction.id:06d}" if cielo_status == 2 else ""
                }
            }
            
            self.stdout.write(f"\n Enviando webhook simulado:")
            self.stdout.write(f"   Status Cielo: {cielo_status} - {status_map.get(cielo_status, 'DESCONHECIDO')}")
            self.stdout.write(f"   PaymentId: {transaction.transaction_id}")
            
            # Importar e processar webhook
            from payment.payment_views import PaymentWebhookView
            
            view = PaymentWebhookView()
            response = view._process_cielo_webhook(webhook_payload)
            
            # Recarregar transação para ver mudanças
            transaction.refresh_from_db()
            pedido = transaction.checkout_link.pedido
            pedido.refresh_from_db()
            checkout_link = transaction.checkout_link
            checkout_link.refresh_from_db()
            
            self.stdout.write(f"\n RESULTADO:")
            self.stdout.write(f"   HTTP Status: {response.status_code}")
            self.stdout.write(f"   Transaction Status: {transaction.status}")
            self.stdout.write(f"   Pedido Phase: {pedido.phase}")
            self.stdout.write(f"   Link Usado: {checkout_link.usado}")
            
            # Verificar se Payment foi criado
            from Pedidos.models import Payment
            payment_records = Payment.objects.filter(
                pedido=pedido,
                identif=transaction.transaction_id
            )
            
            if payment_records.exists():
                payment = payment_records.first()
                self.stdout.write(self.style.SUCCESS(f"\n Payment criado com sucesso!"))
                self.stdout.write(f"   ID: {payment.id}")
                self.stdout.write(f"   Tipo: {payment.payment_type}")
                self.stdout.write(f"   Valor: R$ {payment.valor}")
                self.stdout.write(f"   Parcelas: {payment.installments}x")
            else:
                self.stdout.write(self.style.WARNING(f"\n Nenhum Payment foi criado"))
            
            self.stdout.write("="*80 + "\n")
            
            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS(" Webhook processado com sucesso!"))
            else:
                self.stdout.write(self.style.ERROR(f" Erro ao processar webhook (HTTP {response.status_code})"))
            
        except PaymentTransaction.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"\n Transação não encontrada: {transaction_identifier}"))
            self.stdout.write("\n💡 Dica: Liste transações PIX recentes com:")
            self.stdout.write("   ./manage shell")
            self.stdout.write("   >>> from payment.models import PaymentTransaction")
            self.stdout.write("   >>> for t in PaymentTransaction.objects.filter(metodo_pagamento='pix').order_by('-id')[:5]:")
            self.stdout.write("   ...     print(f'ID: {t.id}, transaction_id: {t.transaction_id}, status: {t.status}')")
            self.stdout.write("   >>> exit()")
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n ERRO: {str(e)}"))
            import traceback
            traceback.print_exc()
