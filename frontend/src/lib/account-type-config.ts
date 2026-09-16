import type { ElementType } from 'react'
import { Building2, PiggyBank, CreditCard, Landmark, TrendingUp, Wallet } from 'lucide-react'

// Account-type → icon/color, the fallback shown when an account has no bank
// logo (manual accounts, and connected accounts whose provider exposes none).
export const ACCOUNT_TYPE_CONFIG: Record<
  string,
  { icon: ElementType; color: string; bg: string; label: string }
> = {
  checking:    { icon: Building2,   color: 'text-primary',     bg: 'bg-primary/10',      label: 'accounts.typeChecking' },
  savings:     { icon: PiggyBank,   color: 'text-primary',     bg: 'bg-primary/10',      label: 'accounts.typeSavings' },
  credit_card: { icon: CreditCard,  color: 'text-destructive', bg: 'bg-destructive/10',  label: 'accounts.typeCreditCard' },
  loan:        { icon: Landmark,    color: 'text-destructive', bg: 'bg-destructive/10',  label: 'accounts.typeLoan' },
  investment:  { icon: TrendingUp,  color: 'text-warning',     bg: 'bg-warning/10',      label: 'accounts.typeInvestment' },
  wallet:      { icon: Wallet,      color: 'text-primary',     bg: 'bg-primary/10',      label: 'accounts.typeWallet' },
}

export function getAccountTypeConfig(type: string) {
  return ACCOUNT_TYPE_CONFIG[type] ?? ACCOUNT_TYPE_CONFIG['checking']
}
