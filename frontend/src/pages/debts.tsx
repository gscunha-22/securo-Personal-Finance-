import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toast } from 'sonner'
import { useWorkspace } from '@/contexts/workspace-context'
import { formatCurrency } from '@/lib/format'

export default function DebtsPage() {
  const { t } = useTranslation()
  const { canWrite } = useWorkspace()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useQuery({ queryKey: ['debts'], queryFn: intelligence.listDebts })

  const create = useMutation({
    mutationFn: intelligence.createDebt,
    onSuccess: () => {
      toast.success(t('intelligence.debtCreated'))
      queryClient.invalidateQueries({ queryKey: ['debts'] })
      setOpen(false)
    },
    onError: () => toast.error(t('intelligence.decideErr')),
  })

  return (
    <div>
      <PageHeader
        section={t('intelligence.group')}
        title={t('nav.debts')}
        action={canWrite ? <Button onClick={() => setOpen(true)}>{t('intelligence.newDebt')}</Button> : null}
      />
      <p className="text-sm text-muted-foreground mb-4">{t('intelligence.debtsHint')}</p>
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        {isLoading && <div className="p-6 text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
        {!isLoading && !data?.length && (
          <div className="p-8 text-sm text-muted-foreground">{t('intelligence.debtsEmpty')}</div>
        )}
        {data?.map((debt) => (
          <div key={debt.id} className="px-4 py-3 border-b border-border last:border-0">
            <p className="text-sm font-medium">{debt.name}</p>
            <p className="text-xs text-muted-foreground">
              {debt.creditor} · {formatCurrency(Number(debt.outstanding_balance), debt.currency)}
              {debt.maturity_date ? ` · ${debt.maturity_date}` : ''}
            </p>
            {debt.strategy_assumptions && (
              <p className="text-xs text-muted-foreground mt-1">{debt.strategy_assumptions}</p>
            )}
          </div>
        ))}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('intelligence.newDebt')}</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              const form = new FormData(e.currentTarget)
              create.mutate({
                name: String(form.get('name')),
                creditor: String(form.get('creditor')),
                currency: String(form.get('currency') || 'USD'),
                principal: String(form.get('principal')),
                outstanding_balance: String(form.get('outstanding')),
                strategy_assumptions: String(form.get('assumptions') || t('intelligence.debtAssumptionDefault')),
              })
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="name">{t('intelligence.debtName')}</Label>
              <Input id="name" name="name" required />
            </div>
            <div className="space-y-1">
              <Label htmlFor="creditor">{t('intelligence.creditor')}</Label>
              <Input id="creditor" name="creditor" required />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="principal">{t('intelligence.principal')}</Label>
                <Input id="principal" name="principal" required />
              </div>
              <div className="space-y-1">
                <Label htmlFor="outstanding">{t('intelligence.outstanding')}</Label>
                <Input id="outstanding" name="outstanding" required />
              </div>
            </div>
            <Input name="currency" defaultValue="USD" />
            <Input name="assumptions" placeholder={t('intelligence.debtAssumptionDefault')} />
            <DialogFooter>
              <Button type="submit" disabled={create.isPending}>{t('intelligence.save')}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
