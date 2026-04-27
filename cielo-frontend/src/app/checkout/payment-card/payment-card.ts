import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBarModule, MatSnackBar } from '@angular/material/snack-bar';
import { MatSelectModule } from '@angular/material/select';
import { ApiService } from '../../services/api';
import { TEST_CARDS, TestCard } from './card-test-logs';

@Component({
  selector: 'app-payment-card',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatInputModule,
    MatFormFieldModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatSelectModule
  ],
  template: `
    <div class="card-container">
      <form (ngSubmit)="processPayment()">
        <h3>Dados do Cartão</h3>

        <!-- Botão Cartões de Teste -->
        <div class="test-cards-section">
          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Cartões de Teste (Sandbox)</mat-label>
            <mat-select (selectionChange)="fillTestCard($event.value)">
              <mat-option *ngFor="let card of testCards" [value]="card">
                {{ card.name }}
              </mat-option>
            </mat-select>
          </mat-form-field>
        </div>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Número do Cartão</mat-label>
          <input matInput [(ngModel)]="cardData.card_number" name="card_number"
                 placeholder="0000 0000 0000 0000" maxlength="19" required>
        </mat-form-field>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Nome no Cartão</mat-label>
          <input matInput [(ngModel)]="cardData.cardholder_name" name="cardholder_name"
                 placeholder="NOME COMO NO CARTÃO" required>
        </mat-form-field>

        <div class="row">
          <mat-form-field appearance="outline" class="half-width">
            <mat-label>Validade (MM/AA)</mat-label>
            <input matInput [(ngModel)]="expiry" name="expiry"
                   placeholder="12/30" maxlength="5" required>
          </mat-form-field>

          <mat-form-field appearance="outline" class="half-width">
            <mat-label>CVV</mat-label>
            <input matInput [(ngModel)]="cardData.security_code" name="cvv"
                   placeholder="123" maxlength="4" required>
          </mat-form-field>
        </div>

        <h3>👤 Dados do Cliente</h3>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Nome Completo</mat-label>
          <input matInput [(ngModel)]="customer.name" name="name" required>
        </mat-form-field>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Email</mat-label>
          <input matInput [(ngModel)]="customer.email" name="email"
                 type="email" required>
        </mat-form-field>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>CPF</mat-label>
          <input matInput [(ngModel)]="customer.cpf" name="cpf"
                 placeholder="000.000.000-00" maxlength="14" required>
        </mat-form-field>

        <div *ngIf="error" class="error">
          {{ error }}
        </div>

        <div *ngIf="success" class="success">
          Pagamento aprovado com sucesso!
        </div>

        <button mat-raised-button color="primary" type="submit" [disabled]="loading" class="btn-submit">
          <span *ngIf="!loading">💳 Pagar</span>
          <mat-spinner *ngIf="loading" diameter="24"></mat-spinner>
        </button>
      </form>
    </div>
  `,
  styles: [`
    .card-container {
      padding: 20px;
    }
    form h3 {
      margin: 20px 0 16px 0;
      font-size: 18px;
    }
    .test-cards-section {
      margin-bottom: 20px;
      padding: 12px;
      background: #FFF3E0;
      border-radius: 8px;
      border: 2px dashed #FF9800;
    }
    .full-width {
      width: 100%;
    }
    .row {
      display: flex;
      gap: 16px;
    }
    .half-width {
      flex: 1;
    }
    .btn-submit {
      width: 100%;
      padding: 16px;
      font-size: 18px;
      margin-top: 20px;
    }
    .error {
      color: #f44336;
      padding: 12px;
      background: #FFEBEE;
      border-radius: 4px;
      margin: 16px 0;
    }
    .success {
      color: #4CAF50;
      padding: 12px;
      background: #E8F5E9;
      border-radius: 4px;
      margin: 16px 0;
      font-weight: bold;
    }
  `]
})
export class PaymentCardComponent {
  @Input() checkoutKey = '';
  @Input() amount = 0;
  @Output() paymentSuccess = new EventEmitter<any>();

  loading = false;
  success = false;
  error = '';
  expiry = '';
  testCards = TEST_CARDS; // Cartões de teste

  cardData = {
    card_number: '',
    cardholder_name: '',
    expiration_month: '',
    expiration_year: '',
    security_code: '',
    installments: 1
  };

  customer = {
    name: '',
    email: '',
    cpf: ''
  };

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar
  ) {}

  fillTestCard(card: TestCard) {
    this.cardData.card_number = card.number;
    this.cardData.cardholder_name = card.holder;
    this.expiry = card.expiry;
    this.cardData.security_code = card.cvv;

    // Preencher dados do cliente também
    this.customer.name = 'Cliente Teste';
    this.customer.email = 'teste@exemplo.com';
    this.customer.cpf = '12345678900';

    this.snackBar.open(`🧪 ${card.name} - ${card.message}`, 'Fechar', {
      duration: 5000,
      horizontalPosition: 'center',
      verticalPosition: 'top'
    });
  }

  processPayment() {
    this.loading = true;
    this.error = '';
    this.success = false;

    // Parse expiry MM/YY
    if (this.expiry) {
      const [month, year] = this.expiry.split('/');
      this.cardData.expiration_month = month;
      this.cardData.expiration_year = year;
    }

    // atob é usado para decodificar o checkoutKey
    const decoded = atob(this.checkoutKey);

    console.log(
      decoded,
      "\n",
      this.cardData,
      "\n",
      this.customer
    )

    this.api.processPayment({
      checkout_key: decoded,
      payment_method: 'credit_card',
      card_data: this.cardData,
      customer: this.customer
    }).subscribe({
      next: (response: any) => {
        if (response.success && response.status === 'APPROVED') {
          this.success = true;
          this.paymentSuccess.emit(response); // Notificar componente pai
          this.snackBar.open('✅ Pagamento aprovado!', 'Fechar', {
            duration: 5000,
            horizontalPosition: 'center',
            verticalPosition: 'top'
          });
        } else {
          this.error = response.return_message || response.message || 'Pagamento negado';
        }
        this.loading = false;
      },
      error: (err) => {
        this.error = err.error?.error || 'Erro ao processar pagamento';
        this.loading = false;
        console.error(err);
      }
    });
  }
}
