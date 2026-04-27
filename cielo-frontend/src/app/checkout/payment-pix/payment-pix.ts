import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBarModule, MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../services/api';

@Component({
  selector: 'app-payment-pix',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatSnackBarModule
  ],
  template: `
    <div class="pix-container">
      <div *ngIf="!pixGenerated && !loading">
        <button mat-raised-button color="primary" (click)="generatePix()" class="btn-generate">
          🔷 Gerar PIX
        </button>
      </div>

      <div *ngIf="loading" class="loading">
        <mat-spinner diameter="50"></mat-spinner>
        <p>Gerando PIX...</p>
      </div>

      <div *ngIf="pixGenerated && !loading" class="pix-content">
        <h3>✅ PIX Gerado!</h3>

        <div class="qr-code">
          <img [src]="getQrCodeUrl()" alt="QR Code PIX" />
        </div>

        <div class="pix-code">
          <p><strong>Código PIX (Copia e Cola):</strong></p>
          <div class="code-box">
            {{ pixQrCode }}
          </div>
          <button mat-raised-button color="accent" (click)="copyPixCode()">
            📋 Copiar Código
          </button>
        </div>

        <div class="timer">
          ⏱️ Expira em: <strong>{{ formatTime(expirationTime) }}</strong>
        </div>

        <div class="instructions">
          <p><strong>Como pagar:</strong></p>
          <ol>
            <li>Abra o app do seu banco</li>
            <li>Escolha pagar com PIX</li>
            <li>Escaneie o QR Code ou cole o código</li>
          </ol>
        </div>
      </div>

      <div *ngIf="error" class="error">
        {{ error }}
      </div>
    </div>
  `,
  styles: [`
    .pix-container {
      text-align: center;
      padding: 20px;
    }
    .btn-generate {
      width: 100%;
      padding: 16px;
      font-size: 18px;
    }
    .loading {
      padding: 40px;
    }
    .loading p {
      margin-top: 16px;
    }
    .pix-content h3 {
      color: #4CAF50;
      margin-bottom: 20px;
    }
    .qr-code {
      margin: 20px 0;
      padding: 20px;
      background: white;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .qr-code img {
      max-width: 200px;
      height: auto;
    }
    .pix-code {
      margin: 20px 0;
    }
    .code-box {
      background: #f5f5f5;
      padding: 12px;
      border-radius: 4px;
      word-break: break-all;
      margin: 12px 0;
      font-family: monospace;
      font-size: 12px;
      max-height: 100px;
      overflow-y: auto;
    }
    .timer {
      margin: 20px 0;
      font-size: 18px;
      color: #FF9800;
    }
    .instructions {
      text-align: left;
      background: #E3F2FD;
      padding: 16px;
      border-radius: 8px;
      margin-top: 20px;
    }
    .instructions ol {
      margin: 8px 0 0 20px;
    }
    .error {
      color: #f44336;
      padding: 16px;
      background: #FFEBEE;
      border-radius: 4px;
      margin-top: 16px;
    }
  `]
})
export class PaymentPixComponent {
  @Input() checkoutKey = '';
  @Input() amount = 0;
  @Output() paymentSuccess = new EventEmitter<any>();

  loading = false;
  pixGenerated = false;
  pixQrCode = '';
  pixQrCodeBase64 = '';
  paymentId = '';
  expirationTime = 0;
  error = '';
  private interval: any;

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar
  ) {}

  generatePix() {
    this.loading = true;
    this.error = '';

    // Enviar chave encodada (backend decodifica)
    this.api.processPayment({
      checkout_key: this.checkoutKey,
      payment_method: 'pix',
      customer: {
        name: 'Cliente Teste',
        email: 'teste@exemplo.com',
        cpf: '12345678900'
      }
    }).subscribe({
      next: (response: any) => {
        if (response.success) {
          this.pixQrCode = response.qr_code;
          this.pixQrCodeBase64 = response.qr_code_base64;
          this.paymentId = response.payment_id;
          this.expirationTime = response.expiration_seconds || 1800; // Usa valor do backend ou 30min default
          this.pixGenerated = true;
          this.startCountdown();
        } else {
          this.error = response.message || 'Erro ao gerar PIX';
        }
        this.loading = false;
      },
      error: (err) => {
        this.error = 'Erro ao gerar PIX';
        this.loading = false;
        console.error(err);
      }
    });
  }

  getQrCodeUrl(): string {
    if (!this.pixQrCode) return '';
    const size = '200x200';
    const encodedData = encodeURIComponent(this.pixQrCode);
    return `https://api.qrserver.com/v1/create-qr-code/?size=${size}&data=${encodedData}`;
  }

  copyPixCode() {
    navigator.clipboard.writeText(this.pixQrCode).then(() => {
      this.snackBar.open('✅ Código PIX copiado!', 'Fechar', {
        duration: 3000,
        horizontalPosition: 'center',
        verticalPosition: 'top'
      });
    }).catch(() => {
      this.snackBar.open('Erro ao copiar', 'Fechar', { duration: 3000 });
    });
  }

  startCountdown() {
    this.interval = setInterval(() => {
      this.expirationTime--;
      if (this.expirationTime <= 0) {
        clearInterval(this.interval);
        this.error = 'PIX expirado. Gere um novo código.';
        this.pixGenerated = false;
      }
    }, 1000);
  }

  formatTime(seconds: number): string {
    const min = Math.floor(seconds / 60);
    const sec = seconds % 60;
    return `${min}:${sec.toString().padStart(2, '0')}`;
  }

  ngOnDestroy() {
    if (this.interval) {
      clearInterval(this.interval);
    }
  }
}
