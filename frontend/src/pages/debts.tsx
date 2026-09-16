import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toast } from 'sonner'
import { useWorkspace } from '@/contexts/workspace-context'
import { useAuth } from '@/contexts/auth-context'
import { formatCurrency } from '@/lib/format'
import type { RenegotiationPlan } from '@/types'

const PRODUCTS = ['rotativo', 'parcelamento', 'cheque', 'emprestimo', 'consignado', 'financiamento', 'outro'] as const
const STATUSES = ['em_dia', 'atraso', 'negativado', 'cobranca'] as const
const GUARANTEES = ['nenhuma', 'consignacao', 'veiculo', 'imovel', 'aval'] as const
const STEPS = ['s1', 's2', 's3', 's4', 's5', 's6', 's7'] as const
const GATE_LABEL: Record<string, string> = {
  material: 'gateMaterial',
  conservative: 'gateConservative',
  documented: 'gateDocumented',
  no_new_guarantee: 'gateGuarantee',
  no_revolve: 'gateNoRevolve',
}

function n(value: string | number | null | undefined): number {
  if (value == null || value === '') return 0
  return Number(value)
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function NativeSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="border-input h-9 w-full rounded-md border bg-card px-3 text-sm"
    />
  )
}

function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: string
  hint?: string
  tone?: 'ok' | 'bad' | 'warn'
}) {
  const color =
    tone === 'ok' ? 'text-primary' : tone === 'bad' ? 'text-destructive' : tone === 'warn' ? 'text-warning' : 'text-foreground'
  return (
    <Card>
      <CardHeader className="pb-2">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-xl font-semibold ${color}`}>{value}</p>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </CardHeader>
    </Card>
  )
}

export default function DebtsPage() {
  const { t } = useTranslation()
  const { canWrite } = useWorkspace()
  const { user } = useAuth()
  const currency = user?.preferences?.currency_display ?? 'BRL'
  const queryClient = useQueryClient()
  const { data: plan, isLoading } = useQuery({ queryKey: ['renegotiation'], queryFn: intelligence.getPlan })
  const [amortDebtId, setAmortDebtId] = useState('')
  const [lump, setLump] = useState('0')
  const [extra, setExtra] = useState('0')
  const [source, setSource] = useState('recuperacao')
  const [amort, setAmort] = useState<Record<string, unknown> | null>(null)
  const [pmtHint, setPmtHint] = useState('')

  const money = (value: string | number | null | undefined) => formatCurrency(n(value), currency)
  const pct = (value: string | number | null | undefined) =>
    `${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`

  const setPlan = (next: RenegotiationPlan) => {
    queryClient.setQueryData(['renegotiation'], next)
  }

  const seed = useMutation({
    mutationFn: (replace: boolean) => intelligence.seedExample(replace, currency),
    onSuccess: (next) => {
      setPlan(next)
      toast.success(t('intelligence.exampleLoaded'))
    },
    onError: () => toast.error(t('intelligence.decideErr')),
  })

  const createDebt = useMutation({
    mutationFn: intelligence.createDebt,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['renegotiation'] })
      toast.success(t('intelligence.debtCreated'))
    },
    onError: () => toast.error(t('intelligence.decideErr')),
  })

  const removeDebt = useMutation({
    mutationFn: intelligence.deleteDebt,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['renegotiation'] }),
  })

  const saveCash = useMutation({
    mutationFn: intelligence.updateCash,
    onSuccess: (next) => {
      setPlan(next)
      toast.success(t('intelligence.cashUpdated'))
    },
  })

  const saveOffer = useMutation({
    mutationFn: intelligence.createOffer,
    onSuccess: (next) => {
      setPlan(next)
      toast.success(t('intelligence.offerRecorded'))
    },
    onError: () => toast.error(t('intelligence.decideErr')),
  })

  const removeOffer = useMutation({
    mutationFn: intelligence.deleteOffer,
    onSuccess: setPlan,
  })

  const saveSteps = useMutation({
    mutationFn: intelligence.updateSteps,
    onSuccess: setPlan,
  })

  const runAmort = useMutation({
    mutationFn: intelligence.amortize,
    onSuccess: (row) => setAmort(row),
  })

  const script = useMemo(() => {
    if (!plan?.bank_script_facts.length) return t('intelligence.bankScriptEmpty')
    const lines = plan.bank_script_facts.map((row) =>
      t('intelligence.bankScriptLine', {
        creditor: row.creditor,
        product: t(`intelligence.product_${row.product}`),
        payoff: money(row.payoff),
        rate: row.rate ? `${row.rate}% a.m.` : t('intelligence.bankScriptRateUnknown'),
        installment: money(row.installment),
        dpd: row.dpd,
        penalty: n(row.penalty) ? t('intelligence.bankScriptPenalty', { amount: money(row.penalty) }) : '',
      }),
    )
    return `${t('intelligence.bankScriptIntro')}\n${lines.join('\n')}${t('intelligence.bankScriptOutro')}`
  }, [plan, t, currency])

  const onExample = () => {
    const replace = Boolean(plan?.debts.length)
    if (replace && !window.confirm(t('intelligence.exampleReplace'))) return
    seed.mutate(replace)
  }

  return (
    <div>
      <PageHeader
        section={t('intelligence.group')}
        title={t('intelligence.planTitle')}
        action={
          canWrite ? (
            <Button variant="outline" onClick={onExample}>
              {t('intelligence.loadExample')}
            </Button>
          ) : null
        }
      />
      <p className="text-sm text-muted-foreground mb-4">{t('intelligence.todayLead')}</p>
      {isLoading && <div className="text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
      {plan && (
        <Tabs defaultValue="today" className="gap-4">
          <TabsList variant="line" className="flex h-auto w-full flex-wrap justify-start">
            {(['tabToday', 'tabInventory', 'tabCash', 'tabPaths', 'tabAmort', 'tabOffers', 'tabDecision', 'tabExecute'] as const).map(
              (key, i) => (
                <TabsTrigger key={key} value={['today', 'inventory', 'cash', 'paths', 'amort', 'offers', 'decision', 'execute'][i]}>
                  {t(`intelligence.${key}`)}
                </TabsTrigger>
              ),
            )}
          </TabsList>

          <TabsContent value="today" className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi label={t('intelligence.payoffTotal')} value={money(plan.totals.payoff)} hint={t('intelligence.obligations', { count: plan.totals.count })} />
              <Kpi
                label={t('intelligence.currentService')}
                value={money(plan.scenarios.service)}
                hint={t('intelligence.ofIncome', { pct: pct(plan.scenarios.commit) })}
              />
              <Kpi
                label={t('intelligence.conservativeFree')}
                value={money(plan.scenarios.cons_free)}
                hint={t('intelligence.authorizesInstallment')}
                tone={n(plan.scenarios.cons_free) >= 0 ? 'ok' : 'bad'}
              />
              <Kpi
                label={t('intelligence.filter30')}
                value={money(plan.scenarios.ceiling30)}
                hint={plan.scenarios.filter30_ok ? t('intelligence.withinFilter') : t('intelligence.aboveFilter')}
                tone={plan.scenarios.filter30_ok ? 'ok' : 'warn'}
              />
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{t('intelligence.attackOrder')}</CardTitle>
                </CardHeader>
                <CardContent>
                  {!plan.debts.length && <p className="text-sm text-muted-foreground">{t('intelligence.inventoryEmpty')}</p>}
                  {plan.debts.length > 0 && (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t('intelligence.priority')}</TableHead>
                          <TableHead>{t('intelligence.creditor')}</TableHead>
                          <TableHead>{t('intelligence.rateCet')}</TableHead>
                          <TableHead>{t('intelligence.outstanding')}</TableHead>
                          <TableHead>{t('intelligence.installment')}</TableHead>
                          <TableHead>{t('intelligence.dpd')}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {plan.debts.map((debt) => (
                          <TableRow key={debt.id}>
                            <TableCell>
                              <Badge variant={debt.priority === 1 ? 'destructive' : 'secondary'}>
                                {t(`intelligence.prio_${debt.priority}`)}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              <p className="font-medium">{debt.creditor}</p>
                              <p className="text-xs text-muted-foreground">{t(`intelligence.product_${debt.product}`)}</p>
                            </TableCell>
                            <TableCell>
                              {debt.rate ? `${debt.rate}% a.m.` : t('intelligence.rateUnknown')}
                              <p className="text-xs text-muted-foreground">
                                {debt.cet_annual
                                  ? t(debt.cet_is_estimate ? 'intelligence.cetEstimate' : 'intelligence.cetStated', { pct: pct(debt.cet_annual) })
                                  : t('intelligence.cetUnknown')}
                              </p>
                            </TableCell>
                            <TableCell>{money(debt.payoff)}</TableCell>
                            <TableCell>{money(debt.installment)}</TableCell>
                            <TableCell>{debt.dpd}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{t('intelligence.capacityVsService')}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <p>
                    {t('intelligence.conservativeCapacity')}: <b>{money(plan.scenarios.cap_cons)}</b>
                  </p>
                  <p>
                    {t('intelligence.currentService')}: <b>{money(plan.scenarios.service)}</b> · {t('intelligence.filter30')}:{' '}
                    <b>{money(plan.scenarios.ceiling30)}</b>
                  </p>
                  <p className={plan.scenarios.filter30_ok ? 'text-primary' : 'text-warning'}>
                    {plan.scenarios.filter30_ok ? t('intelligence.withinFilter') : t('intelligence.aboveFilter')}
                  </p>
                  <p className={n(plan.scenarios.cons_free) >= 0 ? 'text-primary' : 'text-destructive'}>
                    {n(plan.scenarios.cons_free) >= 0 ? t('intelligence.currentFits') : t('intelligence.currentBreaks')}
                  </p>
                  {plan.scenarios.reneg != null && (
                    <p>
                      {t('intelligence.renegService', { amount: money(plan.scenarios.reneg) })} ·{' '}
                      {n(plan.scenarios.cons_free_r) >= 0 ? t('intelligence.consSurvives') : t('intelligence.consBreaks')} (
                      {money(plan.scenarios.cons_free_r)})
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">{t('intelligence.higherPmtNote')}</p>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="inventory" className="space-y-4">
            <p className="text-sm text-muted-foreground">{t('intelligence.inventoryLead')}</p>
            {canWrite && (
              <Card>
                <CardContent className="pt-4">
                  <form
                    className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
                    onSubmit={(e) => {
                      e.preventDefault()
                      const form = new FormData(e.currentTarget)
                      const payoff = String(form.get('payoff') || '0')
                      createDebt.mutate({
                        name: String(form.get('creditor')),
                        creditor: String(form.get('creditor')),
                        currency,
                        principal: payoff,
                        outstanding_balance: payoff,
                        interest_rate: form.get('rate') || null,
                        product: String(form.get('product')),
                        installment_amount: form.get('installment') || null,
                        remaining_term_months: form.get('term') ? Number(form.get('term')) : null,
                        delinquency_status: String(form.get('status')),
                        days_past_due: Number(form.get('dpd') || 0),
                        penalty_amount: form.get('penalty') || '0',
                        guarantee: String(form.get('guarantee')),
                        cet_annual_informed: form.get('cet') || null,
                        due_date: form.get('due') || null,
                        notes: String(form.get('notes') || ''),
                        strategy_assumptions: t('intelligence.debtAssumptionDefault'),
                      })
                      e.currentTarget.reset()
                    }}
                  >
                    <Field label={t('intelligence.creditor')}>
                      <Input name="creditor" required />
                    </Field>
                    <Field label={t('intelligence.product')}>
                      <NativeSelect name="product" defaultValue="rotativo">
                        {PRODUCTS.map((p) => (
                          <option key={p} value={p}>{t(`intelligence.product_${p}`)}</option>
                        ))}
                      </NativeSelect>
                    </Field>
                    <Field label={t('intelligence.outstanding')}>
                      <Input name="payoff" type="number" step="0.01" min="0" required />
                    </Field>
                    <Field label={t('intelligence.monthlyRate')}>
                      <Input name="rate" type="number" step="0.01" />
                    </Field>
                    <Field label={t('intelligence.cetAnnualInformed')}>
                      <Input name="cet" type="number" step="0.01" />
                    </Field>
                    <Field label={t('intelligence.installment')}>
                      <Input name="installment" type="number" step="0.01" min="0" />
                    </Field>
                    <Field label={t('intelligence.remainingTerm')}>
                      <Input name="term" type="number" min="0" />
                    </Field>
                    <Field label={t('intelligence.delinquency')}>
                      <NativeSelect name="status" defaultValue="em_dia">
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>{t(`intelligence.status_${s}`)}</option>
                        ))}
                      </NativeSelect>
                    </Field>
                    <Field label={t('intelligence.dpd')}>
                      <Input name="dpd" type="number" min="0" defaultValue="0" />
                    </Field>
                    <Field label={t('intelligence.penalty')}>
                      <Input name="penalty" type="number" step="0.01" defaultValue="0" />
                    </Field>
                    <Field label={t('intelligence.guarantee')}>
                      <NativeSelect name="guarantee" defaultValue="nenhuma">
                        {GUARANTEES.map((g) => (
                          <option key={g} value={g}>{t(`intelligence.guarantee_${g}`)}</option>
                        ))}
                      </NativeSelect>
                    </Field>
                    <Field label={t('intelligence.dueDate')}>
                      <Input name="due" type="date" />
                    </Field>
                    <Field label={t('intelligence.notes')}>
                      <Input name="notes" />
                    </Field>
                    <div className="flex items-end">
                      <Button type="submit" disabled={createDebt.isPending}>{t('intelligence.addDebt')}</Button>
                    </div>
                  </form>
                </CardContent>
              </Card>
            )}
            <Card>
              <CardContent className="pt-4">
                {!plan.debts.length && <p className="text-sm text-muted-foreground">{t('intelligence.debtsEmpty')}</p>}
                {plan.debts.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t('intelligence.priority')}</TableHead>
                        <TableHead>{t('intelligence.creditor')}</TableHead>
                        <TableHead>{t('intelligence.product')}</TableHead>
                        <TableHead>{t('intelligence.outstanding')}</TableHead>
                        <TableHead>{t('intelligence.rateCet')}</TableHead>
                        <TableHead>{t('intelligence.installment')}</TableHead>
                        {canWrite && <TableHead />}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {plan.debts.map((debt) => (
                        <TableRow key={debt.id}>
                          <TableCell><Badge variant={debt.priority === 1 ? 'destructive' : 'outline'}>P{debt.priority}</Badge></TableCell>
                          <TableCell>
                            <p className="font-medium">{debt.creditor}</p>
                            <p className="text-xs text-muted-foreground">{debt.notes}</p>
                          </TableCell>
                          <TableCell>
                            {t(`intelligence.product_${debt.product}`)}
                            <p className="text-xs text-muted-foreground">{t(`intelligence.status_${debt.delinquency_status}`)}</p>
                          </TableCell>
                          <TableCell>
                            {money(debt.payoff)}
                            {n(debt.penalty) > 0 && <p className="text-xs text-warning">{money(debt.penalty)}</p>}
                          </TableCell>
                          <TableCell>
                            {debt.rate ? `${debt.rate}% a.m.` : '—'}
                            <p className="text-xs text-muted-foreground">
                              {debt.cet_annual ? t('intelligence.cetEstimate', { pct: pct(debt.cet_annual) }) : t('intelligence.cetUnknown')}
                            </p>
                          </TableCell>
                          <TableCell>{money(debt.installment)}</TableCell>
                          {canWrite && (
                            <TableCell>
                              <Button variant="ghost" size="sm" onClick={() => removeDebt.mutate(debt.id)}>
                                {t('intelligence.delete')}
                              </Button>
                            </TableCell>
                          )}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="cash" className="space-y-4">
            <p className="text-sm text-muted-foreground">{t('intelligence.cashLead')}</p>
            {canWrite && (
              <Card>
                <CardContent className="pt-4">
                  <form
                    className="grid gap-3 sm:grid-cols-3"
                    onSubmit={(e) => {
                      e.preventDefault()
                      const form = new FormData(e.currentTarget)
                      saveCash.mutate({
                        income: form.get('income') || '0',
                        variable_income: form.get('variable_income') || '0',
                        essential: form.get('essential') || '0',
                        discretionary: form.get('discretionary') || '0',
                        reserve: form.get('reserve') || '0',
                        shock: form.get('shock') || '0',
                      })
                    }}
                  >
                    {(['income', 'varIncome', 'essential', 'discretionary', 'reserve', 'shock'] as const).map((key) => {
                      const name = key === 'varIncome' ? 'variable_income' : key
                      return (
                        <Field key={key} label={t(`intelligence.${key}`)}>
                          <Input name={name} type="number" step="0.01" defaultValue={plan.cash[name as keyof typeof plan.cash]} />
                        </Field>
                      )
                    })}
                    <div className="flex items-end">
                      <Button type="submit">{t('intelligence.updateCash')}</Button>
                    </div>
                  </form>
                </CardContent>
              </Card>
            )}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi label={t('intelligence.baseCurrent')} value={money(plan.scenarios.base_free)} tone={n(plan.scenarios.base_free) >= 0 ? 'ok' : 'bad'} />
              <Kpi label={t('intelligence.consCurrent')} value={money(plan.scenarios.cons_free)} tone={n(plan.scenarios.cons_free) >= 0 ? 'ok' : 'bad'} />
              <Kpi label={t('intelligence.baseReneg')} value={plan.scenarios.base_free_r == null ? '—' : money(plan.scenarios.base_free_r)} tone={plan.scenarios.base_free_r == null ? undefined : n(plan.scenarios.base_free_r) >= 0 ? 'ok' : 'bad'} />
              <Kpi label={t('intelligence.consReneg')} value={plan.scenarios.cons_free_r == null ? '—' : money(plan.scenarios.cons_free_r)} tone={plan.scenarios.cons_free_r == null ? undefined : n(plan.scenarios.cons_free_r) >= 0 ? 'ok' : 'bad'} />
            </div>
            <Card>
              <CardContent className="pt-4">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('intelligence.month')}</TableHead>
                      <TableHead>{t('intelligence.income')}</TableHead>
                      <TableHead>{t('intelligence.fixedOut')}</TableHead>
                      <TableHead>{t('intelligence.installmentsNow')}</TableHead>
                      <TableHead>{t('intelligence.installmentsReneg')}</TableHead>
                      <TableHead>{t('intelligence.balanceNow')}</TableHead>
                      <TableHead>{t('intelligence.balanceReneg')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {plan.cashflow.map((row) => (
                      <TableRow key={row.month}>
                        <TableCell>{row.month}</TableCell>
                        <TableCell>{money(row.income)}</TableCell>
                        <TableCell>{money(row.fixed)}</TableCell>
                        <TableCell>{money(row.service)}</TableCell>
                        <TableCell>{row.reneg == null ? '—' : money(row.reneg)}</TableCell>
                        <TableCell className={n(row.balance) >= 0 ? 'text-primary' : 'text-destructive'}>{money(row.balance)}</TableCell>
                        <TableCell className={row.balance_reneg == null ? '' : n(row.balance_reneg) >= 0 ? 'text-primary' : 'text-destructive'}>
                          {row.balance_reneg == null ? '—' : money(row.balance_reneg)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="paths">
            <p className="text-sm text-muted-foreground mb-4">{t('intelligence.pathsLead')}</p>
            <div className="grid gap-3 lg:grid-cols-3">
              {plan.paths.map((path) => (
                <Card key={path.id}>
                  <CardHeader>
                    <CardTitle className="text-base">
                      {t(`intelligence.path${path.id === 'keep' ? 'Keep' : path.id === 'arrears' ? 'Arrears' : 'Swap'}Title`)}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <p className="text-muted-foreground">
                      {t(`intelligence.path${path.id === 'keep' ? 'Keep' : path.id === 'arrears' ? 'Arrears' : 'Swap'}Body`)}
                    </p>
                    <p className={path.applicable ? 'text-primary' : 'text-warning'}>
                      {path.applicable ? t('intelligence.applicable') : t('intelligence.notFirst')}
                    </p>
                    {path.id === 'arrears' && (
                      <p className="text-xs text-muted-foreground">{t('intelligence.arrearsCount', { count: path.arrears_count ?? 0 })}</p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="amort" className="space-y-4">
            <p className="text-sm text-muted-foreground">{t('intelligence.amortLead')}</p>
            <div className="rounded-lg border border-border bg-warning/10 p-3 text-sm text-warning">{t('intelligence.amortBanner')}</div>
            <Card>
              <CardContent className="pt-4">
                <form
                  className="grid gap-3 sm:grid-cols-4"
                  onSubmit={(e) => {
                    e.preventDefault()
                    const id = amortDebtId || plan.debts[0]?.id
                    if (!id) return
                    runAmort.mutate({ debt_id: id, lump, extra, source })
                  }}
                >
                  <Field label={t('nav.debts')}>
                    <NativeSelect value={amortDebtId || plan.debts[0]?.id || ''} onChange={(e) => setAmortDebtId(e.target.value)}>
                      {plan.debts.map((d) => (
                        <option key={d.id} value={d.id}>{d.creditor}</option>
                      ))}
                    </NativeSelect>
                  </Field>
                  <Field label={t('intelligence.lump')}>
                    <Input type="number" step="0.01" value={lump} onChange={(e) => setLump(e.target.value)} />
                  </Field>
                  <Field label={t('intelligence.extraMonthly')}>
                    <Input type="number" step="0.01" value={extra} onChange={(e) => setExtra(e.target.value)} />
                  </Field>
                  <Field label={t('intelligence.extraSource')}>
                    <NativeSelect value={source} onChange={(e) => setSource(e.target.value)}>
                      <option value="recuperacao">{t('intelligence.source_recuperacao')}</option>
                      <option value="reserva">{t('intelligence.source_reserva')}</option>
                      <option value="base">{t('intelligence.source_base')}</option>
                    </NativeSelect>
                  </Field>
                  <div className="flex gap-2">
                    <Button type="submit">{t('intelligence.simulate')}</Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setExtra(String(Math.max(0, Math.floor(n(plan.scenarios.rec_free)))))
                        setSource('recuperacao')
                      }}
                    >
                      {t('intelligence.useRecovery')}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
            {amort && amort.ok === false && (
              <p className="text-sm text-muted-foreground">{t('intelligence.addInventory')}</p>
            )}
            {amort && amort.ok === true && (
              <>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <Kpi label={t('intelligence.outstanding')} value={money(String((amort.terms as { pv: string }).pv))} />
                  <Kpi
                    label={t('intelligence.remainingInterest')}
                    value={(amort.baseline as { never?: boolean }).never ? t('intelligence.doesNotAmortize') : money(String((amort.baseline as { interest: string }).interest))}
                    hint={(amort.baseline as { never?: boolean }).never ? t('intelligence.pmtAtOrBelowInterest') : undefined}
                  />
                  <Kpi label={t('intelligence.saveKeepTerm')} value={amort.save_keep ? money(String(amort.save_keep)) : '—'} tone={n(String(amort.save_keep || 0)) > 0 ? 'ok' : undefined} />
                  <Kpi label={t('intelligence.saveCutPmt')} value={amort.save_cut ? money(String(amort.save_cut)) : '—'} />
                </div>
                <Card>
                  <CardContent className="pt-4">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t('intelligence.scenario')}</TableHead>
                          <TableHead>{t('intelligence.months')}</TableHead>
                          <TableHead>{t('intelligence.effectivePmt')}</TableHead>
                          <TableHead>{t('intelligence.totalInterest')}</TableHead>
                          <TableHead>{t('intelligence.totalPaid')}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {(['baseline', 'quit', 'keep_term', 'cut_pmt'] as const).map((key, i) => {
                          const row = amort[key] as { months: number | null; new_pmt: string; interest: string | null; paid: string; never: boolean }
                          const labels = ['scenarioBaseline', 'scenarioQuit', 'scenarioKeep', 'scenarioCut']
                          return (
                            <TableRow key={key}>
                              <TableCell>{t(`intelligence.${labels[i]}`)}</TableCell>
                              <TableCell>{row.never ? '∞' : row.months}</TableCell>
                              <TableCell>{row.never ? '—' : money(row.new_pmt)}</TableCell>
                              <TableCell>{row.never || row.interest == null ? '—' : money(row.interest)}</TableCell>
                              <TableCell>{money(row.paid)}</TableCell>
                            </TableRow>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </>
            )}
            <div className="grid gap-3 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle className="text-base">{t('intelligence.avalancheTitle')}</CardTitle></CardHeader>
                <CardContent className="text-sm space-y-2">
                  {plan.avalanche?.creditor && (
                    <p>{t('intelligence.avalancheTarget', { creditor: plan.avalanche.creditor, rate: plan.avalanche.rate || '—' })}</p>
                  )}
                  <p className="text-xs text-muted-foreground">{t('intelligence.avalancheHint')}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-base">{t('intelligence.amortCashTitle')}</CardTitle></CardHeader>
                <CardContent className="text-sm space-y-2">
                  <p>{t('intelligence.recoverySurplus')}: <b>{money(plan.scenarios.rec_free)}</b></p>
                  <p className={source === 'base' ? 'text-destructive' : source === 'reserva' ? 'text-warning' : 'text-primary'}>
                    {source === 'base' ? t('intelligence.sourceBaseWarn') : source === 'reserva' ? t('intelligence.sourceReserveWarn') : t('intelligence.sourceRecoveryOk')}
                  </p>
                  <p className={n(extra) <= n(plan.scenarios.rec_free) || n(extra) === 0 ? 'text-primary' : 'text-warning'}>
                    {n(extra) <= n(plan.scenarios.rec_free) || n(extra) === 0 ? t('intelligence.extraFits') : t('intelligence.extraBreaks')}
                  </p>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="offers" className="space-y-4">
            <p className="text-sm text-muted-foreground">{t('intelligence.offersLead')}</p>
            {canWrite && (
              <Card>
                <CardContent className="pt-4">
                  <form
                    className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
                    onSubmit={async (e) => {
                      e.preventDefault()
                      if (!plan.debts.length) {
                        toast.error(t('intelligence.offerNeedDebt'))
                        return
                      }
                      const form = new FormData(e.currentTarget)
                      saveOffer.mutate({
                        debt_id: String(form.get('debt_id')),
                        path: String(form.get('path')),
                        name: String(form.get('name')),
                        payoff: form.get('payoff') || '0',
                        cet_monthly: form.get('cet') || null,
                        installment: form.get('pmt') || '0',
                        term_months: form.get('n') ? Number(form.get('n')) : null,
                        down_payment: form.get('down') || '0',
                        waiver: form.get('waiver') || '0',
                        grace: String(form.get('grace')),
                        new_guarantee: form.get('newG') === 'sim',
                        operational_notes: String(form.get('ops') || ''),
                      })
                      e.currentTarget.reset()
                      setPmtHint('')
                    }}
                  >
                    <Field label={t('nav.debts')}>
                      <NativeSelect name="debt_id">
                        {plan.debts.map((d) => (
                          <option key={d.id} value={d.id}>{d.creditor}</option>
                        ))}
                      </NativeSelect>
                    </Field>
                    <Field label={t('intelligence.offerPath')}>
                      <NativeSelect name="path" defaultValue="atraso">
                        <option value="atraso">{t('intelligence.pathArrearsTitle')}</option>
                        <option value="troca">{t('intelligence.pathSwapTitle')}</option>
                        <option value="parcela">{t('intelligence.product_parcelamento')}</option>
                        <option value="outro">{t('intelligence.product_outro')}</option>
                      </NativeSelect>
                    </Field>
                    <Field label={t('intelligence.offerName')}>
                      <Input name="name" required />
                    </Field>
                    <Field label={t('intelligence.outstanding')}>
                      <Input name="payoff" type="number" step="0.01" />
                    </Field>
                    <Field label={t('intelligence.cetMonthly')}>
                      <Input name="cet" type="number" step="0.0001" />
                    </Field>
                    <Field label={t('intelligence.installment')}>
                      <Input name="pmt" type="number" step="0.01" />
                    </Field>
                    <Field label={t('intelligence.remainingTerm')}>
                      <Input name="n" type="number" min="1" />
                    </Field>
                    <Field label={t('intelligence.downPayment')}>
                      <Input name="down" type="number" step="0.01" defaultValue="0" />
                    </Field>
                    <Field label={t('intelligence.waiver')}>
                      <Input name="waiver" type="number" step="0.01" defaultValue="0" />
                    </Field>
                    <Field label={t('intelligence.grace')}>
                      <NativeSelect name="grace" defaultValue="nao">
                        <option value="nao">{t('intelligence.grace_nao')}</option>
                        <option value="sim">{t('intelligence.grace_sim')}</option>
                        <option value="juros">{t('intelligence.grace_juros')}</option>
                      </NativeSelect>
                    </Field>
                    <Field label={t('intelligence.newGuarantee')}>
                      <NativeSelect name="newG" defaultValue="nao">
                        <option value="nao">{t('intelligence.no')}</option>
                        <option value="sim">{t('intelligence.yes')}</option>
                      </NativeSelect>
                    </Field>
                    <Field label={t('intelligence.ops')}>
                      <Input name="ops" />
                    </Field>
                    <div className="flex items-end gap-2">
                      <Button type="submit">{t('intelligence.recordOffer')}</Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={async (ev) => {
                          const form = (ev.currentTarget.form as HTMLFormElement | null)
                          if (!form) return
                          const fd = new FormData(form)
                          const payoff = n(String(fd.get('payoff') || 0))
                          const cet = n(String(fd.get('cet') || 0))
                          const term = Number(fd.get('n') || 0)
                          if (!payoff || !term) {
                            setPmtHint(t('intelligence.pmtHintNeed'))
                            return
                          }
                          const hint = await intelligence.pmtHint({
                            payoff,
                            down_payment: n(String(fd.get('down') || 0)),
                            waiver: n(String(fd.get('waiver') || 0)),
                            cet_monthly: cet,
                            term_months: term,
                          })
                          setPmtHint(t('intelligence.pmtHintResult', { pmt: money(hint.pmt), cet: pct(hint.cet_annual) }))
                          if (!fd.get('pmt')) {
                            const pmtInput = form.elements.namedItem('pmt') as HTMLInputElement | null
                            if (pmtInput) pmtInput.value = hint.pmt
                          }
                        }}
                      >
                        {t('intelligence.pmtHintBtn')}
                      </Button>
                    </div>
                  </form>
                  {pmtHint && <p className="text-xs text-muted-foreground mt-2">{pmtHint}</p>}
                </CardContent>
              </Card>
            )}
            <Card>
              <CardContent className="pt-4">
                {!plan.offers.length && <p className="text-sm text-muted-foreground">{t('intelligence.offersEmpty')}</p>}
                {plan.offers.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t('intelligence.offerName')}</TableHead>
                        <TableHead>{t('intelligence.outstanding')}</TableHead>
                        <TableHead>CET</TableHead>
                        <TableHead>{t('intelligence.installment')}</TableHead>
                        <TableHead>{t('intelligence.totalCost')}</TableHead>
                        <TableHead>{t('intelligence.tabCash')}</TableHead>
                        {canWrite && <TableHead />}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {plan.offers.map((offer) => (
                        <TableRow key={offer.id}>
                          <TableCell>
                            <p className="font-medium">{offer.name}</p>
                            <p className="text-xs text-muted-foreground">{offer.creditor}</p>
                          </TableCell>
                          <TableCell>{money(offer.payoff)}</TableCell>
                          <TableCell>{offer.cet ? `${offer.cet}% a.m.` : '—'}</TableCell>
                          <TableCell>{money(offer.pmt)} × {offer.n || '—'}</TableCell>
                          <TableCell>
                            {money(offer.total)}
                            <p className="text-xs text-muted-foreground">{t('intelligence.extraCost', { amount: money(offer.extra) })}</p>
                          </TableCell>
                          <TableCell className={offer.fits_conservative ? 'text-primary' : 'text-destructive'}>
                            {offer.fits_conservative ? t('intelligence.fitsConservative') : t('intelligence.doesNotFit')}
                          </TableCell>
                          {canWrite && (
                            <TableCell>
                              <Button variant="ghost" size="sm" onClick={() => removeOffer.mutate(offer.id)}>{t('intelligence.delete')}</Button>
                            </TableCell>
                          )}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="decision">
            <p className="text-sm text-muted-foreground mb-4">{t('intelligence.decisionLead')}</p>
            <Card>
              <CardContent className="pt-4 space-y-3">
                {plan.gates.items.map((item) => (
                  <div key={item.id} className="flex gap-3 text-sm">
                    <span className={item.ok ? 'text-primary font-semibold' : 'text-destructive font-semibold'}>
                      {item.ok ? t('intelligence.meets') : t('intelligence.missing')}
                    </span>
                    <span>{t(`intelligence.${GATE_LABEL[item.id]}`)}</span>
                  </div>
                ))}
                <div className="flex gap-3 text-sm">
                  <span className={plan.gates.filter30.ok ? 'text-primary font-semibold' : 'text-warning font-semibold'}>
                    {plan.gates.filter30.ok ? t('intelligence.filterOk') : t('intelligence.filterWarn')}
                  </span>
                  <span>{t('intelligence.filterHint', { pct: pct(plan.gates.filter30.commit) })}</span>
                </div>
                <p className={`pt-2 font-semibold ${plan.gates.ready ? 'text-primary' : 'text-destructive'}`}>
                  {plan.gates.ready ? t('intelligence.readyYes') : t('intelligence.readyNo')}
                </p>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="execute" className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm">{t('intelligence.executeBanner')}</div>
            <div className="grid gap-3 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle className="text-base">{t('intelligence.playbook')}</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {STEPS.map((id) => (
                    <label key={id} className="flex gap-2 text-sm items-start">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={Boolean(plan.steps[id])}
                        disabled={!canWrite}
                        onChange={(e) => saveSteps.mutate({ ...plan.steps, [id]: e.target.checked })}
                      />
                      <span>{t(`intelligence.step_${id}`)}</span>
                    </label>
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <CardTitle className="text-base">{t('intelligence.bankScriptTitle')}</CardTitle>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={async () => {
                      await navigator.clipboard.writeText(script)
                      toast.success(t('intelligence.copied'))
                    }}
                  >
                    {t('intelligence.copyScript')}
                  </Button>
                </CardHeader>
                <CardContent>
                  <pre className="whitespace-pre-wrap text-sm bg-muted/40 rounded-lg p-3 border border-border">{script}</pre>
                </CardContent>
              </Card>
            </div>
            <Card>
              <CardHeader><CardTitle className="text-base">{t('intelligence.alertsTitle')}</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {plan.alerts.map((key) => (
                  <p key={key} className="text-sm text-warning">▸ {t(`intelligence.alert_${key}`)}</p>
                ))}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
      <p className="text-xs text-muted-foreground mt-8 max-w-3xl">{t('intelligence.disclaimer')}</p>
    </div>
  )
}
