#!/bin/bash

# ============================================
# Script Rápido - Testes de Pagamento
# ============================================

echo "🧪 Rodando Testes Simples..."
./manage test payment.tests.test_payment_simple --verbosity=1

echo ""
echo "💳 Rodando Testes Cartão Cielo..."
./manage test payment.tests.test_payment_cielo_credit --verbosity=1

echo ""
echo "💰 Rodando Testes PIX Cielo..."
./manage test payment.tests.test_payment_cielo_pix --verbosity=1

echo ""
echo "✅ Testes concluídos!"
