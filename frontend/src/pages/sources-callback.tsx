import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import axios from 'axios'
import { intelligence } from '@/lib/api'

export default function SourcesCallbackPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const code = params.get('code')
  const state = params.get('state')
  const errorParam = params.get('error')
  const errorDescription = params.get('error_description')

  useEffect(() => {
    if (errorParam) {
      toast.error(errorDescription || errorParam)
      navigate('/sources', { replace: true })
      return
    }
    if (!code || !state) {
      toast.error(t('intelligence.sourceCallbackMissing'))
      navigate('/sources', { replace: true })
      return
    }
    const submitKey = `source-oauth:${code}:${state}`
    if (sessionStorage.getItem(submitKey)) return
    sessionStorage.setItem(submitKey, '1')

    ;(async () => {
      try {
        await intelligence.completeSourceOAuth(code, state)
        await queryClient.invalidateQueries({ queryKey: ['sources'] })
        toast.success(t('intelligence.sourceCallbackOk'))
        navigate('/sources', { replace: true })
      } catch (err) {
        sessionStorage.removeItem(submitKey)
        const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null
        toast.error(typeof detail === 'string' ? detail : t('intelligence.sourceConnectErr'))
        navigate('/sources', { replace: true })
      }
    })()
  }, [code, errorDescription, errorParam, navigate, queryClient, state, t])

  return (
    <div className="p-8 text-sm text-muted-foreground">{t('intelligence.loading')}</div>
  )
}
