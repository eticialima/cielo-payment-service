import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private baseUrl = 'http://127.0.0.1:8000/django_cielo';

  constructor(private http: HttpClient) {}

  // ==========================================
  // CHECKOUT LINKS
  // ==========================================

  /**
   * Lista todos os checkouts
   * GET /django_cielo/checkoutlink/
   */
  getCheckoutLinks(): Observable<any> {
    return this.http.get(`${this.baseUrl}/checkoutlink/`);
  }

  /**
   * Busca checkout por key (encodada ou não)
   * GET /django_cielo/checkoutlink/?key=xxx
   */
  getCheckoutByKey(key: string): Observable<any> {
    return this.http.get(`${this.baseUrl}/checkoutlink/`, { params: { key } });
  }

  /**
   * Cria novo link de pagamento
   * POST /django_cielo/checkoutlink/create_payment_link/
   */
  createPaymentLink(amount: number, expirationHours: number = 24): Observable<any> {
    return this.http.post(`${this.baseUrl}/checkoutlink/create_payment_link/`, {
      amount,
      expiration_hours: expirationHours
    });
  }

  /**
   * Marca checkout como cancelado
   * POST /django_cielo/checkoutlink/{id}/mark_as_canceled/
   */
  cancelCheckout(checkoutId: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/checkoutlink/${checkoutId}/mark_as_canceled/`, {});
  }

  /**
   * Retorna link completo do checkout
   * GET /django_cielo/checkoutlink/{id}/get_full_link/
   */
  getCheckoutFullLink(checkoutId: number): Observable<any> {
    return this.http.get(`${this.baseUrl}/checkoutlink/${checkoutId}/get_full_link/`);
  }

  /**
   * Status do checkout
   * GET /django_cielo/checkoutlink/{id}/status/
   */
  getCheckoutStatus(checkoutId: number): Observable<any> {
    return this.http.get(`${this.baseUrl}/checkoutlink/${checkoutId}/status/`);
  }

  // ==========================================
  // PAYMENT PROCESSING (não implementado ainda no backend)
  // ==========================================

  /**
   * Processa pagamento
   * POST /django_cielo/payment/process/
   *
   * Formato oficial da lib django-cielo
   */
  processPayment(data: {
    checkout_key: string;
    payment_method: 'pix' | 'credit_card';
    card_data?: {
      card_number: string;
      cardholder_name: string;
      expiration_month: string;
      expiration_year: string;
      security_code: string;
      installments?: number;
    };
    customer: {
      name: string;
      email?: string;
      cpf?: string;
    };
    billing_address?: {
      street: string;
      number: string;
      district: string;
      city: string;
      state: string;
      zip_code: string;
      complement?: string;
    };
  }): Observable<any> {
    // Modo antigo: chave vai no body como 'chave' (não 'checkout_key')
    const paymentData = {
      chave: data.checkout_key,  // backend espera 'chave'
      payment_method: data.payment_method,
      card_data: data.card_data,
      customer: data.customer,
      billing_address: data.billing_address
    };

    console.log("Processing payment data:", paymentData);

    return this.http.post(`${this.baseUrl}/payment/process/`, paymentData);
  }

  // ==========================================
  // TRANSACTIONS
  // ==========================================

  /**
   * Lista transações
   * GET /django_cielo/transactions/
   */
  getTransactions(): Observable<any> {
    return this.http.get(`${this.baseUrl}/transactions/`);
  }

  /**
   * Detalhe da transação
   * GET /django_cielo/transactions/{id}/
   */
  getTransaction(transactionId: number): Observable<any> {
    return this.http.get(`${this.baseUrl}/transactions/${transactionId}/`);
  }

  /**
   * Status da transação (consulta Cielo)
   * GET /django_cielo/payment/{transaction_id}/status/
   */
  getPaymentStatus(transactionId: number): Observable<any> {
    return this.http.get(`${this.baseUrl}/payment/${transactionId}/status/`);
  }

  /**
   * Tentativas de pagamento da transação
   * GET /django_cielo/transactions/{id}/attempts/
   */
  getTransactionAttempts(transactionId: number): Observable<any> {
    return this.http.get(`${this.baseUrl}/transactions/${transactionId}/attempts/`);
  }

  /**
   * Webhooks da transação
   * GET /django_cielo/transactions/{id}/webhooks/
   */
  getTransactionWebhooks(transactionId: number): Observable<any> {
    return this.http.get(`${this.baseUrl}/transactions/${transactionId}/webhooks/`);
  }

  // ==========================================
  // PAYMENT ACTIONS
  // ==========================================

  /**
   * Captura pagamento pré-autorizado
   * POST /django_cielo/payment/{transaction_id}/capture/
   */
  capturePayment(transactionId: number, amount?: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/payment/${transactionId}/capture/`, { amount });
  }

  /**
   * Cancela transação
   * POST /django_cielo/payment/{transaction_id}/cancel/
   */
  cancelPayment(transactionId: number, amount?: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/payment/${transactionId}/cancel/`, { amount });
  }

  // ==========================================
  // WEBHOOK (uso interno)
  // ==========================================

  /**
   * Endpoint para Cielo enviar notificações
   * POST /django_cielo/payment/webhook/
   *
   * Nota: Este endpoint é chamado pela Cielo, não pelo frontend
   */
  webhookUrl(): string {
    return `${this.baseUrl}/payment/webhook/`;
  }
}
