import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MethodSelector } from './method-selector';

describe('MethodSelector', () => {
  let component: MethodSelector;
  let fixture: ComponentFixture<MethodSelector>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MethodSelector]
    })
    .compileComponents();

    fixture = TestBed.createComponent(MethodSelector);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
