import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'

export default function AuditPage() {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({ queryKey: ['audit'], queryFn: intelligence.listAudit })

  return (
    <div>
      <PageHeader section={t('intelligence.group')} title={t('nav.audit')} />
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        {isLoading && <div className="p-6 text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
        {!isLoading && !data?.length && (
          <div className="p-8 text-sm text-muted-foreground">{t('intelligence.auditEmpty')}</div>
        )}
        {data?.map((event) => (
          <div key={event.id} className="px-4 py-3 border-b border-border last:border-0">
            <p className="text-sm font-medium">{event.summary}</p>
            <p className="text-xs text-muted-foreground">
              {event.action} · {event.created_at}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
