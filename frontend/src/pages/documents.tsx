import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { accounts as accountsApi, intelligence } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { Link } from 'react-router-dom'
import { useWorkspace } from '@/contexts/workspace-context'

export default function DocumentsPage() {
  const { t } = useTranslation()
  const { canWrite } = useWorkspace()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [accountId, setAccountId] = useState('')

  const { data: documents, isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: intelligence.listDocuments,
  })
  const { data: accounts } = useQuery({ queryKey: ['accounts'], queryFn: () => accountsApi.list() })

  const upload = useMutation({
    mutationFn: (file: File) => intelligence.uploadDocument(file, accountId || undefined),
    onSuccess: () => {
      toast.success(t('intelligence.uploadOk'))
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['review-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
    onError: () => toast.error(t('intelligence.uploadErr')),
  })

  return (
    <div>
      <PageHeader
        section={t('intelligence.group')}
        title={t('nav.documents')}
        action={
          canWrite ? (
            <Button onClick={() => inputRef.current?.click()} disabled={upload.isPending}>
              {t('intelligence.upload')}
            </Button>
          ) : null
        }
      />
      <p className="text-sm text-muted-foreground mb-4">{t('intelligence.documentsHint')}</p>
      <div className="mb-4 max-w-xs">
        <select
          className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card"
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
        >
          <option value="">{t('intelligence.optionalAccount')}</option>
          {accounts?.map((account) => (
            <option key={account.id} value={account.id}>{account.display_name || account.name}</option>
          ))}
        </select>
      </div>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept=".csv,.pdf,.ofx,.qif,.xlsx,.png,.jpg,.jpeg"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) upload.mutate(file)
          e.target.value = ''
        }}
      />
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        {isLoading && <div className="p-6 text-sm text-muted-foreground">{t('intelligence.loading')}</div>}
        {!isLoading && !documents?.length && (
          <div className="p-8 text-sm text-muted-foreground">{t('intelligence.documentsEmpty')}</div>
        )}
        {documents?.map((doc) => (
          <div key={doc.id} className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border last:border-0">
            <div>
              <p className="text-sm font-medium">{doc.filename}</p>
              <p className="text-xs text-muted-foreground">
                {doc.document_type} · {doc.status} · {doc.mime}
                {doc.interpretation_version ? ` · v${doc.interpretation_version}` : ''}
              </p>
            </div>
            <Link to="/review" className="text-sm text-primary">{t('intelligence.review')}</Link>
          </div>
        ))}
      </div>
    </div>
  )
}
