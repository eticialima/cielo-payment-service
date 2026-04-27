import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CheckoutLinkCreate } from './checkout-link-create';

describe('CheckoutLinkCreate', () => {
  let component: CheckoutLinkCreate;
  let fixture: ComponentFixture<CheckoutLinkCreate>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CheckoutLinkCreate]
    })
    .compileComponents();

    fixture = TestBed.createComponent(CheckoutLinkCreate);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
