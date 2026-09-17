import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'

import SourcesPage from '@/pages/sources'
import { renderWithProviders, t } from '@/test/utils'

const api = vi.hoisted(() => ({
  intelligence: {
    listSources: vi.fn(),
    connectSource: vi.fn(),
    disconnectSource: vi.fn(),
    syncSource: vi.fn(),
  },
}))

vi.mock('@/lib/api', () => ({
  intelligence: api.intelligence,
}))

vi.mock('@/contexts/workspace-context', () => ({
  useWorkspace: () => ({ canWrite: true }),
}))

describe('SourcesPage', () => {
  it('does not offer connect when the OAuth client is missing', async () => {
    api.intelligence.listSources.mockResolvedValue([
      {
        id: '00000000-0000-0000-0000-000000000000',
        provider: 'gmail',
        display_name: 'Gmail',
        status: 'not_configured',
        granted_scopes: 'https://www.googleapis.com/auth/gmail.readonly',
        last_sync_at: null,
        last_sync_result: null,
        last_error: 'Client id is not set',
      },
    ])
    renderWithProviders(<SourcesPage />, { route: '/sources' })
    expect(await screen.findByText('Client id is not set')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('intelligence.sourceConnect') })).not.toBeInTheDocument()
  })

  it('offers connect once the operator has configured a client', async () => {
    api.intelligence.listSources.mockResolvedValue([
      {
        id: '00000000-0000-0000-0000-000000000000',
        provider: 'gmail',
        display_name: 'Gmail',
        status: 'awaiting_consent',
        granted_scopes: 'https://www.googleapis.com/auth/gmail.readonly',
        last_sync_at: null,
        last_sync_result: null,
        last_error: 'OAuth consent from the owner is required',
      },
    ])
    renderWithProviders(<SourcesPage />, { route: '/sources' })
    expect(await screen.findByRole('button', { name: t('intelligence.sourceConnect') })).toBeEnabled()
  })

  it('offers a read-only sync once connected', async () => {
    api.intelligence.listSources.mockResolvedValue([
      {
        id: '00000000-0000-0000-0000-000000000001',
        provider: 'gmail',
        display_name: 'Gmail',
        status: 'connected',
        granted_scopes: 'https://www.googleapis.com/auth/gmail.readonly',
        last_sync_at: null,
        last_sync_result: 'ok',
        last_error: null,
      },
    ])
    renderWithProviders(<SourcesPage />, { route: '/sources' })
    expect(await screen.findByRole('button', { name: t('intelligence.sourceSync') })).toBeEnabled()
    expect(screen.getByRole('button', { name: t('intelligence.sourceDisconnect') })).toBeEnabled()
  })
})
