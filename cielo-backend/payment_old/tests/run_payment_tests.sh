#!/bin/bash

# ============================================
# Script para Rodar Testes de Pagamento
# Sistema: DMC Vendas Server
# Gateway: Cielo
# ============================================

# Cores para output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Banner
echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                                                            ║"
echo "║        🧪 TESTES DE PAGAMENTO - GATEWAY CIELO 🧪          ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Função para rodar testes
run_test() {
    local test_name=$1
    local test_path=$2
    
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "--${BLUE}🧪 Executando: ${test_name}${NC}"
    echo -e "--${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    
    ./manage test ${test_path} --verbosity=2
    
    if [ $? -eq 0 ]; then
        echo -e "\n${GREEN}✅ ${test_name} - PASSOU!${NC}"
    else
        echo -e "\n${RED}❌ ${test_name} - FALHOU!${NC}"
    fi
}

# Menu de opções
echo -e "${YELLOW}Escolha qual teste executar:${NC}\n"
echo "1) 🧪 Testes Simples (Models e Lógica Básica)"
echo "2) 💳 Testes Cartão Cielo (Todos os Finais XXX0-XXX9)"
echo "3) 💰 Testes PIX Cielo"
echo "4) 🎯 Todos os Testes de Pagamento"
echo "5) 🚀 Todos os Testes (Simples + Cielo)"
echo "0) ❌ Sair"
echo ""
read -p "Digite sua opção: " option

case $option in
    1)
        run_test "Testes Simples" "payment.tests.test_payment_simple"
        ;;
    2)
        run_test "Testes Cartão Cielo" "payment.tests.test_payment_cielo_credit"
        ;;
    3)
        run_test "Testes PIX Cielo" "payment.tests.test_payment_cielo_pix"
        ;;
    4)
        run_test "Testes Cielo (Cartão + PIX)" "payment.tests.test_payment_cielo_credit payment.tests.test_payment_cielo_pix"
        ;;
    5)
        echo -e "\n${BLUE}🚀 Executando TODOS os testes...${NC}\n"
        
        run_test "Testes Simples" "payment.tests.test_payment_simple"
        run_test "Testes Cartão Cielo" "payment.tests.test_payment_cielo_credit"
        run_test "Testes PIX Cielo" "payment.tests.test_payment_cielo_pix"
        
        echo -e "\n${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
        echo -e "--${BLUE}║                    📊 RESUMO FINAL                         ║${NC}"
        echo -e "--${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
        
        ./manage test payment.tests.test_payment_simple payment.tests.test_payment_cielo_credit payment.tests.test_payment_cielo_pix --verbosity=1
        ;;
    0)
        echo -e "${YELLOW}👋 Saindo...${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}❌ Opção inválida!${NC}"
        exit 1
        ;;
esac

echo -e "\n${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "--${BLUE}║                    ✅ TESTES CONCLUÍDOS                    ║${NC}"
echo -e "--${BLUE}╚════════════════════════════════════════════════════════════╝${NC}\n"
