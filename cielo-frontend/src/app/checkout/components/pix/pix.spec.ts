import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Pix } from './pix';

describe('Pix', () => {
  let component: Pix;
  let fixture: ComponentFixture<Pix>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Pix]
    })
    .compileComponents();

    fixture = TestBed.createComponent(Pix);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
