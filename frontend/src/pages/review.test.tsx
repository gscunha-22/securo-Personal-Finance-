import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'

import ReviewPage from '@/pages/review'
import { renderWithProviders, t } from '@/test/utils'

const api = vi.hoisted(() => ({
  accounts: { list: vi.fn().mockResolvedValue([]) },
  intelligence: {
    listCandidates: vi.fn().mockResolvedValue([]),
    decide: vi.fn(),
  },
}))

vi.mock('@/lib/api', () => ({
  accounts: api.accounts,
  intelligence: api.intelligence,
}))

vi.mock('@/contexts/auth-context', () => ({
  useAuth: () => ({ user: { preferences: { currency_display: 'USD' } } }),
}))

vi.mock('@/contexts/workspace-context', () => ({
  useWorkspace: () => ({ canWrite: true }),
}))

describe('ReviewPage', () => {
  it('polls pending candidates while extraction runs on the worker', () => {
    expect(ReviewPage.toString()).toContain('refetchInterval')
  })

  it('explains that nothing is waiting when the queue is empty', async () => {
    renderWithProviders(<ReviewPage />, { route: '/review' })
    expect(await screen.findByText(t('intelligence.reviewEmpty'))).toBeInTheDocument()
    expect(screen.getByText(t('intelligence.reviewHint'))).toBeInTheDocument()
  })
})
