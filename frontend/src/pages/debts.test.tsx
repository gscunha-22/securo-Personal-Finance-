import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'

import DebtsPage from '@/pages/debts'
import { renderWithProviders, t } from '@/test/utils'
import type { RenegotiationPlan } from '@/types'

const emptyPlan: RenegotiationPlan = {
  disclaimer: 'educational',
  totals: { payoff: '0.00', count: 0, priority_one: 0 },
  debts: [],
  offers: [],
  cash: {
    income: '0.00',
    variable_income: '0.00',
    essential: '0.00',
    discretionary: '0.00',
    reserve: '0.00',
    shock: '0.00',
  },
  scenarios: {
    service: '0.00',
    reneg: null,
    cap_cons: '0.00',
    cons_free: '0.00',
    rec_free: '0.00',
    base_free: '0.00',
    base_free_r: null,
    cons_free_r: null,
    commit: '0.0000',
    commit_r: null,
    ceiling30: '0.00',
    filter30_ok: true,
  },
  cashflow: Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    income: '0.00',
    fixed: '0.00',
    service: '0.00',
    reneg: null,
    balance: '0.00',
    balance_reneg: null,
  })),
  paths: [
    { id: 'keep', applicable: true },
    { id: 'arrears', applicable: false, arrears_count: 0 },
    { id: 'swap', applicable: false },
  ],
  gates: {
    items: [
      { id: 'material', ok: true },
      { id: 'conservative', ok: true },
      { id: 'documented', ok: true },
      { id: 'no_new_guarantee', ok: true },
      { id: 'no_revolve', ok: false },
    ],
    filter30: { ok: true, commit: '0.0000', auxiliary: true },
    ready: false,
  },
  steps: { s1: false, s2: false, s3: false, s4: false, s5: false, s6: false, s7: false },
  alerts: ['entryEatsReserve', 'noCet', 'essentialCollateral', 'newCreditForBills', 'unofficialBroker', 'higherPmtBreaksConservative'],
  bank_script_facts: [],
  avalanche: null,
}

const api = vi.hoisted(() => ({
  intelligence: {
    getPlan: vi.fn().mockResolvedValue(emptyPlan),
    seedExample: vi.fn(),
    createDebt: vi.fn(),
    deleteDebt: vi.fn(),
    updateCash: vi.fn(),
    createOffer: vi.fn(),
    deleteOffer: vi.fn(),
    updateSteps: vi.fn(),
    amortize: vi.fn(),
    pmtHint: vi.fn(),
  },
}))

vi.mock('@/lib/api', () => ({
  intelligence: api.intelligence,
}))

vi.mock('@/contexts/auth-context', () => ({
  useAuth: () => ({ user: { preferences: { currency_display: 'BRL' } } }),
}))

vi.mock('@/contexts/workspace-context', () => ({
  useWorkspace: () => ({ canWrite: true }),
}))

describe('DebtsPage', () => {
  it('shows the renegotiation workspace with inventory empty and the five-gate model', async () => {
    const { user } = renderWithProviders(<DebtsPage />, { route: '/debts' })
    expect(await screen.findByText(t('intelligence.planTitle'))).toBeInTheDocument()
    expect(screen.getByText(t('intelligence.todayLead'))).toBeInTheDocument()
    expect(screen.getByText(t('intelligence.disclaimer'))).toBeInTheDocument()
    expect(screen.getByText(t('intelligence.inventoryEmpty'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('intelligence.loadExample') })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: t('intelligence.tabDecision') }))
    expect(screen.getByText(t('intelligence.gateMaterial'))).toBeInTheDocument()
    expect(screen.getByText(t('intelligence.readyNo'))).toBeInTheDocument()
    expect(screen.getByText(t('intelligence.filterHint', { pct: '0%' }))).toBeInTheDocument()
  })
})
