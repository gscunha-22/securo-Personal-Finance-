import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { useWorkspace } from '@/contexts/workspace-context'
import axios from 'axios'

export default function SourcesPage() {
  const { t } = useTranslation()
  const { canWrite } = useWorkspace()
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['sources'],
    queryFn: intelligence.listSources,
    refetchInterval: (query) =>
      query.state.data?.some((source) => source.status === 'connected') ? 4000 : false,
  })

  const connect = useMutation({
    mutationFn: intelligence.connectSource,
    onSuccess: (row) => {
      window.location.assign(row.authorization_url)
    },
    onError: (err) => {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null
      toast.error(typeof detail === 'string' ? detail : t('intelligence.sourceConnectErr'))
    },
  })

  const disconnect = useMutation({
    mutationFn: intelligence.disconnectSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      toast.success(t('intelligence.sourceDisconnected'))
    },
    onError: () => toast.error(t('intelligence.sourceConnectErr')),
  })

  const sync = useMutation({
    mutationFn: intelligence.syncSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['review-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      toast.success(t('intelligence.sourceSyncOk'))
    },
    onError: (err) => {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null
      toast.error(typeof detail === 'string' ? detail : t('intelligence.sourceSyncErr'))
    },
  })

  return (
    <div>
      <PageHeader section={t('intelligence.group')} title={t('nav.sources')} />
      <p className="text-sm text-muted-foreground mb-4">{t('intelligence.sourcesHint')}</p>
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        {isLoading && <div className="p-6 text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
        {data?.map((source) => {
          const canConnect = source.status === 'awaiting_consent' || source.status === 'disconnected'
          const connected = source.status === 'connected'
          return (
            <div
              key={`${source.provider}-${source.id}`}
              className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 border-b border-border last:border-0"
            >
              <div>
                <p className="text-sm font-medium capitalize">{source.display_name}</p>
                <p className="text-xs text-muted-foreground">
                  {t(`intelligence.sourceStatus_${source.status}`, { defaultValue: source.status })}
                  {source.last_sync_at ? ` · ${source.last_sync_at}` : ''}
                </p>
                {source.granted_scopes ? (
                  <p className="text-xs text-muted-foreground mt-1">
                    {t('intelligence.sourceScopes', { scopes: source.granted_scopes })}
                  </p>
                ) : null}
                {source.last_error && <p className="text-xs text-destructive mt-1">{source.last_error}</p>}
              </div>
              {canWrite && canConnect && (
                <Button
                  size="sm"
                  onClick={() => connect.mutate(source.provider)}
                  disabled={connect.isPending}
                >
                  {t('intelligence.sourceConnect')}
                </Button>
              )}
              {canWrite && connected && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => sync.mutate(source.provider)}
                    disabled={sync.isPending}
                  >
                    {t('intelligence.sourceSync')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => disconnect.mutate(source.provider)}
                    disabled={disconnect.isPending}
                  >
                    {t('intelligence.sourceDisconnect')}
                  </Button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
