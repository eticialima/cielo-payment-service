"""
Testa o cálculo do valor_total do CheckoutLink

Uso:
    python manage.py testar_calculo_link <pedido_id>
"""

from django.core.management.base import BaseCommand
from payment.models import CheckoutLink
from Pedidos.models import Pedido


class Command(BaseCommand):
    help = 'Testa o cálculo do valor_total do CheckoutLink'

    def add_arguments(self, parser):
        parser.add_argument(
            'pedido_id',
            type=str,
            help='ID do pedido para testar'
        )

    def handle(self, *args, **options):
        pedido_id = options['pedido_id']
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write(self.style.WARNING("🧪 TESTE DE CÁLCULO DE CHECKOUT LINK"))
        self.stdout.write("="*80)
        
        try:
            pedido = Pedido.objects.get(id=pedido_id)
            
            self.stdout.write(f"\n📦 Pedido: {pedido.id}")
            
            # Calcular valores
            preco_produtos = float(pedido.precoDosProdutos())
            descontos = float(pedido.descontosTotais() or 0)
            pagamentos_feitos = float(pedido.valor_pago() or 0)
            
            self.stdout.write(f"\n💰 VALORES:")
            self.stdout.write(f"   Preço dos Produtos: R$ {preco_produtos:.2f}")
            self.stdout.write(f"   Descontos: R$ {descontos:.2f}")
            self.stdout.write(f"   Total Bruto: R$ {preco_produtos - descontos:.2f}")
            self.stdout.write(f"   Já Pago: R$ {pagamentos_feitos:.2f}")
            self.stdout.write(self.style.SUCCESS(f"   ✅ RESTANTE: R$ {(preco_produtos - descontos - pagamentos_feitos):.2f}"))
            
            # Criar checkout link temporário para testar cálculo
            self.stdout.write(f"\n🔧 Criando CheckoutLink temporário...")
            checkout = CheckoutLink(pedido=pedido)
            valor_calculado = checkout.calcular_valor_total()
            
            self.stdout.write(f"\n📊 RESULTADO DO CÁLCULO:")
            self.stdout.write(f"   valor_total (centavos): {valor_calculado}")
            self.stdout.write(self.style.SUCCESS(f"   valor_total (reais): R$ {valor_calculado / 100:.2f}"))
            
            # Verificar se já existe link para este pedido
            links_existentes = CheckoutLink.objects.filter(pedido=pedido).order_by('-criado_em')
            
            if links_existentes.exists():
                self.stdout.write(f"\n🔗 LINKS EXISTENTES PARA ESTE PEDIDO:")
                for link in links_existentes[:5]:  # Mostrar últimos 5
                    status_str = "❌ USADO" if link.usado else ("🚫 CANCELADO" if link.cancelado else "✅ ATIVO")
                    self.stdout.write(f"   {status_str} - ID: {link.id} - Valor: R$ {link.valor_total / 100:.2f} - Criado: {link.criado_em.strftime('%d/%m/%Y %H:%M')}")
            else:
                self.stdout.write(f"\n⚠️  Nenhum link existente para este pedido")
            
            self.stdout.write("="*80 + "\n")
            
        except Pedido.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"\n❌ Pedido não encontrado: {pedido_id}"))
            self.stdout.write("="*80 + "\n")
