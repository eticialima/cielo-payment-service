import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CheckoutLink } from './checkout-link';

describe('CheckoutLink', () => {
  let component: CheckoutLink;
  let fixture: ComponentFixture<CheckoutLink>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CheckoutLink]
    })
    .compileComponents();

    fixture = TestBed.createComponent(CheckoutLink);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
