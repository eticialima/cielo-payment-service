import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatCardModule } from '@angular/material/card';
import { PaymentPixComponent } from './payment-pix/payment-pix';
import { PaymentCardComponent } from './payment-card/payment-card';
import { ApiService } from '../services/api';

@Component({
  selector: 'app-checkout',
  imports: [
    CommonModule,
    MatProgressSpinnerModule,
    MatCardModule,
    PaymentPixComponent,
    PaymentCardComponent
  ],
  templateUrl: './checkout.html',
  styleUrl: './checkout.scss',
})
export class Checkout implements OnInit {
  loading = true;
  message = '';
  checkoutKey = '';
  checkoutData: any = null;
  selectedMethod: 'pix' | 'credit_card' | null = null;

  constructor(
    private route: ActivatedRoute,
    private api: ApiService
  ) {}

  ngOnInit() {
    this.route.queryParams.subscribe(params => {
      this.checkoutKey = params['c'];

      if (!this.checkoutKey) {
        this.message = 'Link de pagamento inválido';
        this.loading = false;
        return;
      }

      this.validateCheckout();
    });
  }

  validateCheckout() {
    try {
      const decoded = atob(this.checkoutKey);
      console.log("Decoded checkout key:", this.checkoutKey,  decoded);

      this.api.getCheckoutLinks()
        .subscribe({
          next: (response: any) => {
            const checkout = response.find((c: any) => c.key === decoded);

            if (!checkout) {
              this.message = 'Checkout não encontrado';
              this.loading = false;
              return;
            }

            if (checkout.used) {
              this.message = 'Este link já foi utilizado';
              this.loading = false;
              return;
            }

            if (checkout.canceled) {
              this.message = 'Este link foi cancelado';
              this.loading = false;
              return;
            }

            if (new Date(checkout.expires_at) < new Date()) {
              this.message = 'Este link expirou';
              this.loading = false;
              return;
            }

            this.checkoutData = checkout;
            this.loading = false;
          },
          error: () => {
            this.message = 'Erro ao carregar checkout';
            this.loading = false;
          }
        });
    } catch {
      this.message = 'Link de pagamento inválido';
      this.loading = false;
    }
  }

  selectMethod(method: 'pix' | 'credit_card') {
    this.selectedMethod = method;
  }

  formatAmount(amount: number): string {
    return (amount / 100).toFixed(2);
  }

  onPaymentSuccess(response: any) {
    this.message = 'Pagamento aprovado com sucesso!';
    this.selectedMethod = null;
  }
}
