"""
💳 Calculadora de Parcelamento com Juros (Tabela Price)

Este módulo implementa a lógica de cálculo de parcelamento para o sistema FeiraPay,
seguindo o modelo do Mercado Livre e utilizando o método ByMerchant da Cielo.

Funcionalidades:
- Cálculo de parcelas com/sem juros (Tabela Price)
- Validação de parcela mínima (R$ 150,00)
- Suporte a múltiplos produtos no carrinho
- Limites configuráveis por produto

Documentação de referência:
- Cielo ByMerchant: https://developercielo.github.io/manual/cielo-ecommerce#tipos-de-parcelamento
- Tabela Price: PMT = PV × [i × (1+i)^n] / [(1+i)^n - 1]
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional
from dataclasses import dataclass


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES GLOBAIS
# ══════════════════════════════════════════════════════════════════════════════

# Valor mínimo da parcela (em reais)
PARCELA_MINIMA = Decimal('150.00')

# Taxa de juros mensal padrão (2.7% ao mês)
TAXA_JUROS_PADRAO = Decimal('0.027')


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProdutoParcelamento:
    """
    Dados de um produto para cálculo de parcelamento
    """
    id: int
    nome: str
    valor: Decimal  # Valor em reais
    max_parcelas: int  # Máximo de parcelas permitidas
    parcelas_sem_juros: int  # Quantidade de parcelas sem juros
    taxa_juros: Decimal = TAXA_JUROS_PADRAO  # Taxa de juros mensal


@dataclass
class OpcaoParcelamento:
    """
    Uma opção de parcelamento disponível
    """
    parcelas: int
    valor_parcela: Decimal  # Valor de cada parcela
    valor_total: Decimal  # Valor total a pagar (com juros)
    tem_juros: bool
    taxa_juros: Decimal  # Taxa de juros aplicada
    juros_total: Decimal  # Valor total dos juros
    percentual_juros: str  # Percentual formatado (ex: "+10.5%")
    
    def to_dict(self) -> Dict:
        """Converte para dicionário (JSON-friendly)"""
        return {
            'parcelas': self.parcelas,
            'valor_parcela': float(self.valor_parcela),
            'valor_total': float(self.valor_total),
            'tem_juros': self.tem_juros,
            'taxa_juros': float(self.taxa_juros),
            'juros_total': float(self.juros_total),
            'percentual_juros': self.percentual_juros
        }


# ══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES DE CÁLCULO
# ══════════════════════════════════════════════════════════════════════════════

def calcular_parcela_price(
    valor_presente: Decimal,
    taxa_juros: Decimal,
    num_parcelas: int
) -> Decimal:
    """
    Calcula valor da parcela usando Tabela Price (juros compostos)
    
    Fórmula: PMT = PV × [i × (1+i)^n] / [(1+i)^n - 1]
    
    Args:
        valor_presente: Valor total do produto/pedido
        taxa_juros: Taxa de juros mensal (decimal, ex: 0.027 = 2.7%)
        num_parcelas: Número de parcelas
    
    Returns:
        Decimal: Valor de cada parcela (arredondado para 2 casas)
    
    Exemplos:
        >>> calcular_parcela_price(Decimal('1000.00'), Decimal('0.027'), 6)
        Decimal('183.43')
        
        >>> calcular_parcela_price(Decimal('1000.00'), Decimal('0'), 3)
        Decimal('333.33')
    """
    # Se não tem juros, divide igualmente
    if taxa_juros == 0:
        parcela = valor_presente / num_parcelas
        return parcela.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    # Fórmula Tabela Price
    fator = (1 + taxa_juros) ** num_parcelas
    numerador = taxa_juros * fator
    denominador = fator - 1
    
    parcela = valor_presente * (numerador / denominador)
    
    # Arredondar para 2 casas decimais
    return parcela.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calcular_max_parcelas_permitidas(
    valor_total: Decimal,
    parcela_minima: Decimal = PARCELA_MINIMA
) -> int:
    """
    Calcula o número máximo de parcelas baseado no valor mínimo da parcela
    
    Regra: Parcela mínima de R$ 150,00
    - R$ 300,00 → máx 2x (150 cada)
    - R$ 450,00 → máx 3x (150 cada)
    - R$ 1.800,00 → máx 12x (150 cada)
    - R$ 3.600,00 → máx 24x (150 cada)
    
    Args:
        valor_total: Valor total do pedido
        parcela_minima: Valor mínimo permitido por parcela
    
    Returns:
        int: Número máximo de parcelas permitidas
    
    Exemplos:
        >>> calcular_max_parcelas_permitidas(Decimal('300.00'))
        2
        
        >>> calcular_max_parcelas_permitidas(Decimal('3600.00'))
        24
    """
    max_parcelas = int(valor_total / parcela_minima)
    
    # Limitar entre 1 e 24 parcelas
    return max(1, min(max_parcelas, 24))


def calcular_opcoes_parcelamento(
    valor_total: Decimal,
    max_parcelas: int,
    parcelas_sem_juros: int,
    taxa_juros: Decimal = TAXA_JUROS_PADRAO,
    parcela_minima: Decimal = PARCELA_MINIMA
) -> List[OpcaoParcelamento]:
    """
    Calcula todas as opções de parcelamento disponíveis
    
    Args:
        valor_total: Valor total do pedido
        max_parcelas: Máximo de parcelas permitidas
        parcelas_sem_juros: Quantidade de parcelas sem juros
        taxa_juros: Taxa de juros mensal (padrão: 2.7%)
        parcela_minima: Valor mínimo por parcela (padrão: R$ 150)
    
    Returns:
        List[OpcaoParcelamento]: Lista de opções de parcelamento
    
    Exemplo:
        >>> opcoes = calcular_opcoes_parcelamento(
        ...     valor_total=Decimal('1000.00'),
        ...     max_parcelas=6,
        ...     parcelas_sem_juros=3,
        ...     taxa_juros=Decimal('0.027')
        ... )
        >>> len(opcoes)
        6
        >>> opcoes[0].tem_juros
        False
        >>> opcoes[5].tem_juros
        True
    """
    opcoes = []
    
    # Validar parcela mínima
    max_permitido = calcular_max_parcelas_permitidas(valor_total, parcela_minima)
    max_parcelas = min(max_parcelas, max_permitido)
    
    # Garantir que parcelas_sem_juros não exceda max_parcelas
    parcelas_sem_juros = min(parcelas_sem_juros, max_parcelas)
    
    print(f"\n{'='*80}")
    print(f"📊 CÁLCULO DE PARCELAMENTO")
    print(f"{'='*80}")
    print(f"💰 Valor Total: R$ {valor_total:.2f}")
    print(f"📦 Max Parcelas: {max_parcelas}")
    print(f"🎁 Parcelas Sem Juros: {parcelas_sem_juros}")
    print(f"📈 Taxa de Juros: {float(taxa_juros * 100):.2f}% ao mês")
    print(f"💵 Parcela Mínima: R$ {parcela_minima:.2f}")
    print(f"{'-'*80}")
    
    for num_parcelas in range(1, max_parcelas + 1):
        # Determinar se tem juros
        tem_juros = num_parcelas > parcelas_sem_juros
        taxa_aplicada = taxa_juros if tem_juros else Decimal('0')
        
        # Calcular valor da parcela
        valor_parcela = calcular_parcela_price(
            valor_presente=valor_total,
            taxa_juros=taxa_aplicada,
            num_parcelas=num_parcelas
        )
        
        # Calcular valor total
        valor_total_calculado = valor_parcela * num_parcelas
        
        # Calcular juros total
        juros_total = valor_total_calculado - valor_total
        
        # Calcular percentual de juros
        if juros_total > 0:
            percentual = (juros_total / valor_total) * 100
            percentual_juros = f"+{percentual:.2f}%"
        else:
            percentual_juros = "0%"
        
        opcao = OpcaoParcelamento(
            parcelas=num_parcelas,
            valor_parcela=valor_parcela,
            valor_total=valor_total_calculado,
            tem_juros=tem_juros,
            taxa_juros=taxa_aplicada,
            juros_total=juros_total,
            percentual_juros=percentual_juros
        )
        
        opcoes.append(opcao)
        
        # Log de debug
        juros_str = f"(R$ {valor_total_calculado:.2f}) {percentual_juros}" if tem_juros else "sem juros"
        print(f"{num_parcelas:2}x  R$ {valor_parcela:8.2f}  {juros_str}")
    
    print(f"{'='*80}\n")
    
    return opcoes


def calcular_opcoes_carrinho(
    produtos: List[ProdutoParcelamento],
    parcela_minima: Decimal = PARCELA_MINIMA
) -> Dict:
    """
    Calcula opções de parcelamento para um carrinho com múltiplos produtos
    
    REGRA: Usar as configurações do produto MAIS RESTRITIVO
    - Max parcelas = MIN(max_parcelas de todos os produtos)
    - Parcelas sem juros = MIN(parcelas_sem_juros de todos os produtos)
    - Taxa de juros = MAX(taxa_juros de todos os produtos)
    
    Args:
        produtos: Lista de produtos no carrinho
        parcela_minima: Valor mínimo por parcela
    
    Returns:
        Dict com opções de parcelamento e detalhes
    
    Exemplo:
        >>> produto_a = ProdutoParcelamento(
        ...     id=1, nome="Produto A", valor=Decimal('300.00'),
        ...     max_parcelas=3, parcelas_sem_juros=2
        ... )
        >>> produto_b = ProdutoParcelamento(
        ...     id=2, nome="Produto B", valor=Decimal('1400.00'),
        ...     max_parcelas=12, parcelas_sem_juros=3
        ... )
        >>> resultado = calcular_opcoes_carrinho([produto_a, produto_b])
        >>> resultado['max_parcelas']
        3
        >>> resultado['parcelas_sem_juros']
        2
    """
    if not produtos:
        raise ValueError("Lista de produtos vazia")
    
    # Calcular valor total
    valor_total = sum(p.valor for p in produtos)
    
    # Determinar configurações (produto mais restritivo)
    max_parcelas = min(p.max_parcelas for p in produtos)
    parcelas_sem_juros = min(p.parcelas_sem_juros for p in produtos)
    taxa_juros = max(p.taxa_juros for p in produtos)
    
    print(f"\n{'='*80}")
    print(f"🛒 CARRINHO COM MÚLTIPLOS PRODUTOS")
    print(f"{'='*80}")
    for produto in produtos:
        print(f"📦 {produto.nome}")
        print(f"   Valor: R$ {produto.valor:.2f}")
        print(f"   Max Parcelas: {produto.max_parcelas}x")
        print(f"   Sem Juros: até {produto.parcelas_sem_juros}x")
        print(f"   Taxa: {float(produto.taxa_juros * 100):.2f}%")
    print(f"{'-'*80}")
    print(f"💰 VALOR TOTAL: R$ {valor_total:.2f}")
    print(f"📊 CONFIGURAÇÃO RESULTANTE (mais restritivo):")
    print(f"   Max Parcelas: {max_parcelas}x")
    print(f"   Sem Juros: até {parcelas_sem_juros}x")
    print(f"   Taxa: {float(taxa_juros * 100):.2f}%")
    print(f"{'='*80}")
    
    # Calcular opções
    opcoes = calcular_opcoes_parcelamento(
        valor_total=valor_total,
        max_parcelas=max_parcelas,
        parcelas_sem_juros=parcelas_sem_juros,
        taxa_juros=taxa_juros,
        parcela_minima=parcela_minima
    )
    
    return {
        'valor_total': float(valor_total),
        'max_parcelas': max_parcelas,
        'parcelas_sem_juros': parcelas_sem_juros,
        'taxa_juros': float(taxa_juros),
        'parcela_minima': float(parcela_minima),
        'produtos': [
            {
                'id': p.id,
                'nome': p.nome,
                'valor': float(p.valor)
            }
            for p in produtos
        ],
        'opcoes_parcelamento': [opcao.to_dict() for opcao in opcoes]
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXEMPLOS DE USO
# ══════════════════════════════════════════════════════════════════════════════

def exemplo_produto_simples():
    """Exemplo 1: Produto único R$ 1.000,00"""
    print("\n" + "="*80)
    print("EXEMPLO 1: PRODUTO ÚNICO")
    print("="*80)
    
    opcoes = calcular_opcoes_parcelamento(
        valor_total=Decimal('1000.00'),
        max_parcelas=6,
        parcelas_sem_juros=3,
        taxa_juros=Decimal('0.027')
    )
    
    return opcoes


def exemplo_carrinho_multiplos_produtos():
    """Exemplo 2: Carrinho com 2 produtos"""
    print("\n" + "="*80)
    print("EXEMPLO 2: CARRINHO COM MÚLTIPLOS PRODUTOS")
    print("="*80)
    
    # Produto A: R$ 300,00 (máx 3x, 2x sem juros)
    produto_a = ProdutoParcelamento(
        id=1,
        nome="Equipamento A",
        valor=Decimal('300.00'),
        max_parcelas=3,
        parcelas_sem_juros=2,
        taxa_juros=Decimal('0.027')
    )
    
    # Produto B: R$ 1.400,00 (máx 12x, 3x sem juros)
    produto_b = ProdutoParcelamento(
        id=2,
        nome="Equipamento B",
        valor=Decimal('1400.00'),
        max_parcelas=12,
        parcelas_sem_juros=3,
        taxa_juros=Decimal('0.027')
    )
    
    resultado = calcular_opcoes_carrinho([produto_a, produto_b])
    
    return resultado


def exemplo_valor_alto():
    """Exemplo 3: Produto de alto valor R$ 10.000,00"""
    print("\n" + "="*80)
    print("EXEMPLO 3: PRODUTO DE ALTO VALOR")
    print("="*80)
    
    opcoes = calcular_opcoes_parcelamento(
        valor_total=Decimal('10000.00'),
        max_parcelas=24,
        parcelas_sem_juros=3,
        taxa_juros=Decimal('0.027')
    )
    
    return opcoes


def exemplo_validacao_parcela_minima():
    """Exemplo 4: Validação de parcela mínima"""
    print("\n" + "="*80)
    print("EXEMPLO 4: VALIDAÇÃO DE PARCELA MÍNIMA")
    print("="*80)
    
    # Produto de R$ 300,00 tentando parcelar em 24x
    # Sistema deve limitar a 2x (R$ 150 por parcela)
    
    opcoes = calcular_opcoes_parcelamento(
        valor_total=Decimal('300.00'),
        max_parcelas=24,  # Tenta 24x
        parcelas_sem_juros=3,
        taxa_juros=Decimal('0.027')
    )
    
    print(f"\n⚠️  LIMITAÇÃO APLICADA:")
    print(f"   Produto: R$ 300,00")
    print(f"   Parcelas solicitadas: 24x")
    print(f"   Parcelas permitidas: {len(opcoes)}x (R$ 150 mínimo)")
    
    return opcoes


# ══════════════════════════════════════════════════════════════════════════════
# SCRIPT DE TESTE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    """
    Execute este arquivo para ver exemplos práticos:
    
        cd /home/leticia/DMC/FeiraBackend/VendasFeiraServer
        python -m payment.payment_installments
    """
    
    print("\n" + "╔" + "="*78 + "╗")
    print("║" + " "*20 + "💳 CALCULADORA DE PARCELAMENTO" + " "*28 + "║")
    print("║" + " "*30 + "FeiraPay System" + " "*34 + "║")
    print("╚" + "="*78 + "╝\n")
    
    # Executar exemplos
    exemplo_produto_simples()
    exemplo_carrinho_multiplos_produtos()
    exemplo_valor_alto()
    exemplo_validacao_parcela_minima()
    
    print("\n" + "="*80)
    print("✅ TESTES CONCLUÍDOS")
    print("="*80)
    print("\nPróximos passos:")
    print("1. Criar migration para Produto.parcelas_sem_juros")
    print("2. Criar endpoint /payment/calcular-parcelamento/")
    print("3. Integrar no frontend do checkout")
    print("4. Testar com dados reais\n")
