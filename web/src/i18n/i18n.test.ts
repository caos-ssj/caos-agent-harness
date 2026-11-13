import { describe, expect, it } from 'vitest'
import { translate } from './index'

describe('English text for a Spanish interface', () => {
  it('translates exact strings and keeps the spacing around them', () => {
    expect(translate('Abiertas')).toBe('Open')
    expect(translate(' Esperando por ti ')).toBe(' Waiting on you ')
  })
  it('translates strings that carry a number or a name', () => {
    expect(translate('hace 18 h · plan · 0 msg')).toBe('18 h ago · plan · 0 msg')
    expect(translate('45 cambio(s) sin confirmar')).toBe('45 uncommitted change(s)')
    expect(translate('3 skill(s) de Código & Infra')).toBe('3 skill(s) from Code & Infra')
    expect(translate('Plan: solo lectura')).toBe('Plan: read-only')
  })
  it('leaves what is already English, and what the person wrote, alone', () => {
    expect(translate('Add a task')).toBe('Add a task')
    expect(translate('Quiero definir la politica de failover')).toBe('Quiero definir la politica de failover')
  })
})
