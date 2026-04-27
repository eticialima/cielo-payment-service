/**
 * Cartões de Teste Cielo Sandbox
 *
 * Os status das transações são definidos pelo final do cartão
 */

export interface TestCard {
  name: string;
  number: string;
  holder: string;
  expiry: string;
  cvv: string;
  status: string;
  returnCode: string;
  message: string;
}

export const TEST_CARDS: TestCard[] = [
  {
    name: '✅ Autorizado (Final 0)',
    number: '4024007153763190',
    holder: 'TESTE APROVADO',
    expiry: '12/30',
    cvv: '123',
    status: 'Autorizado',
    returnCode: '4/6',
    message: 'Operação realizada com sucesso'
  },
  {
    name: '✅ Autorizado (Final 1)',
    number: '4024007153763191',
    holder: 'TESTE APROVADO',
    expiry: '12/30',
    cvv: '123',
    status: 'Autorizado',
    returnCode: '4/6',
    message: 'Operação realizada com sucesso'
  },
  {
    name: '✅ Autorizado (Final 4)',
    number: '4024007153763194',
    holder: 'TESTE APROVADO',
    expiry: '12/30',
    cvv: '123',
    status: 'Autorizado',
    returnCode: '4/6',
    message: 'Operação realizada com sucesso'
  },
  {
    name: '❌ Não Autorizado (Final 2)',
    number: '4024007153763192',
    holder: 'TESTE NEGADO',
    expiry: '12/30',
    cvv: '123',
    status: 'Não Autorizado',
    returnCode: '05',
    message: 'Não autorizada'
  },
  {
    name: '⏰ Cartão Expirado (Final 3)',
    number: '4024007153763193',
    holder: 'TESTE EXPIRADO',
    expiry: '12/30',
    cvv: '123',
    status: 'Não Autorizado',
    returnCode: '57',
    message: 'Cartão expirado'
  },
  {
    name: '🔒 Cartão Bloqueado (Final 5)',
    number: '4024007153763195',
    holder: 'TESTE BLOQUEADO',
    expiry: '12/30',
    cvv: '123',
    status: 'Não Autorizado',
    returnCode: '78',
    message: 'Cartão bloqueado'
  },
  {
    name: '⏱️ Timeout (Final 6)',
    number: '4024007153763196',
    holder: 'TESTE TIMEOUT',
    expiry: '12/30',
    cvv: '123',
    status: 'Não Autorizado',
    returnCode: '99',
    message: 'Timeout'
  },
  {
    name: '🚫 Cartão Cancelado (Final 7)',
    number: '4024007153763197',
    holder: 'TESTE CANCELADO',
    expiry: '12/30',
    cvv: '123',
    status: 'Não Autorizado',
    returnCode: '77',
    message: 'Cartão cancelado'
  },
  {
    name: '⚠️ Problemas com Cartão (Final 8)',
    number: '4024007153763198',
    holder: 'TESTE PROBLEMA',
    expiry: '12/30',
    cvv: '123',
    status: 'Não Autorizado',
    returnCode: '70',
    message: 'Problemas com o cartão de crédito'
  },
  {
    name: '🎲 Autorização Aleatória (Final 9)',
    number: '4024007153763199',
    holder: 'TESTE ALEATORIO',
    expiry: '12/30',
    cvv: '123',
    status: 'Autorização Aleatória',
    returnCode: '4 a 99',
    message: 'Operation Successful / Timeout'
  }
];

// Log dos cartões de teste no console
console.log('🃏 Cartões de Teste Cielo Sandbox:');
console.table(TEST_CARDS.map(card => ({
  'Nome': card.name,
  'Número': card.number,
  'Status': card.status,
  'Código': card.returnCode
})));

