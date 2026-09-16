import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { accounts as accountsApi, intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { useWorkspace } from '@/contexts/workspace-context'
import { formatCurrency } from '@/lib/format'
import { useAuth } from '@/contexts/auth-context'

export default function ReviewPage() {
  const { t } = useTranslation()
  const { canWrite } = useWorkspace()
  const { user } = useAuth()
  const currency = user?.preferences?.currency_display ?? 'USD'
  const queryClient = useQueryClient()
  const [accountId, setAccountId] = useState('')
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  const { data: candidates, isLoading } = useQuery({
    queryKey: ['review-candidates'],
    queryFn: () => intelligence.listCandidates('pending'),
  })
  const { data: accounts } = useQuery({ queryKey: ['accounts'], queryFn: () => accountsApi.list() })

  const selectedIds = useMemo(
    () => Object.entries(checked).filter(([, on]) => on).map(([id]) => id),
    [checked],
  )

  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject' | 'defer') =>
      intelligence.decide(selectedIds, decision, accountId || undefined),
    onSuccess: (_, decision) => {
      toast.success(t(`intelligence.${decision}Ok`))
      setChecked({})
      queryClient.invalidateQueries({ queryKey: ['review-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
    },
    onError: () => toast.error(t('intelligence.decideErr')),
  })

  return (
    <div>
      <PageHeader section={t('intelligence.group')} title={t('nav.review')} />
      <p className="text-sm text-muted-foreground mb-4">{t('intelligence.reviewHint')}</p>
      <div className="flex flex-wrap gap-2 mb-4">
        <select
          className="border border-border rounded-lg px-3 py-2 text-sm bg-card"
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
        >
          <option value="">{t('intelligence.chooseAccount')}</option>
          {accounts?.map((account) => (
            <option key={account.id} value={account.id}>{account.display_name || account.name}</option>
          ))}
        </select>
        {canWrite && (
          <>
            <Button disabled={!selectedIds.length || decide.isPending} onClick={() => decide.mutate('approve')}>
              {t('intelligence.approve')}
            </Button>
            <Button variant="outline" disabled={!selectedIds.length} onClick={() => decide.mutate('reject')}>
              {t('intelligence.reject')}
            </Button>
            <Button variant="ghost" disabled={!selectedIds.length} onClick={() => decide.mutate('defer')}>
              {t('intelligence.defer')}
            </Button>
          </>
        )}
      </div>
      <div className="bg-card rounded-xl border border-border overflow-x-auto">
        {isLoading && <div className="p-6 text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
        {!isLoading && !candidates?.length && (
          <div className="p-8 text-sm text-muted-foreground">{t('intelligence.reviewEmpty')}</div>
        )}
        {candidates?.map((row) => (
          <label key={row.id} className="flex items-start gap-3 px-4 py-3 border-b border-border last:border-0">
            <input
              type="checkbox"
              className="mt-1"
              checked={Boolean(checked[row.id])}
              onChange={(e) => setChecked((cur) => ({ ...cur, [row.id]: e.target.checked }))}
            />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{row.description}</p>
              <p className="text-xs text-muted-foreground">
                {row.competence_date} · {formatCurrency(Number(row.amount), row.currency || currency)} · {row.txn_type}
                {row.locator ? ` · ${row.locator}` : ''}
              </p>
              {row.suggestion_rationale && (
                <p className="text-xs text-muted-foreground mt-1">
                  {t('intelligence.suggestion')}: {row.suggested_category || t('intelligence.none')} ({row.suggestion_rationale})
                </p>
              )}
              {row.duplicate_of_transaction_id && (
                <p className="text-xs text-warning mt-1">{t('intelligence.possibleDuplicate')}</p>
              )}
            </div>
          </label>
        ))}
      </div>
    </div>
  )
}
