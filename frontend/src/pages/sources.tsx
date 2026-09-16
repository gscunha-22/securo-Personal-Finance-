import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'

export default function SourcesPage() {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({ queryKey: ['sources'], queryFn: intelligence.listSources })

  return (
    <div>
      <PageHeader section={t('intelligence.group')} title={t('nav.sources')} />
      <p className="text-sm text-muted-foreground mb-4">{t('intelligence.sourcesHint')}</p>
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        {isLoading && <div className="p-6 text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
        {data?.map((source) => (
          <div key={`${source.provider}-${source.id}`} className="px-4 py-3 border-b border-border last:border-0">
            <p className="text-sm font-medium capitalize">{source.display_name}</p>
            <p className="text-xs text-muted-foreground">
              {source.status}
              {source.last_sync_at ? ` · ${source.last_sync_at}` : ''}
            </p>
            {source.last_error && <p className="text-xs text-destructive mt-1">{source.last_error}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}
