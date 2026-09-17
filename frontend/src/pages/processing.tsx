import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { useWorkspace } from '@/contexts/workspace-context'

export default function ProcessingPage() {
  const { t } = useTranslation()
  const { canWrite } = useWorkspace()
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => intelligence.listJobs(),
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === 'queued' || job.status === 'running')
        ? 2000
        : false,
  })
  const retry = useMutation({
    mutationFn: intelligence.retryJob,
    onSuccess: () => {
      toast.success(t('intelligence.retryOk'))
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['review-candidates'] })
    },
  })

  return (
    <div>
      <PageHeader section={t('intelligence.group')} title={t('nav.processing')} />
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        {isLoading && <div className="p-6 text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
        {!isLoading && !data?.length && (
          <div className="p-8 text-sm text-muted-foreground">{t('intelligence.jobsEmpty')}</div>
        )}
        {data?.map((job) => (
          <div key={job.id} className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border last:border-0">
            <div>
              <p className="text-sm font-medium">{job.job_type}</p>
              <p className="text-xs text-muted-foreground">
                {job.status} · {job.attempts} {t('intelligence.attempts')}
              </p>
              {job.error && <p className="text-xs text-destructive mt-1">{job.error}</p>}
            </div>
            {canWrite && job.status !== 'running' && (
              <Button variant="outline" size="sm" onClick={() => retry.mutate(job.id)}>
                {t('intelligence.retry')}
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
