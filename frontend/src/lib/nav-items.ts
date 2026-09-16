import {
  ArrowLeftRight,
  BarChart3,
  Building2,
  FileSearch,
  FileText,
  Landmark,
  ListChecks,
  PiggyBank,
  Receipt,
  Repeat,
  ScrollText,
  SlidersHorizontal,
  Split,
  Tag,
  Target,
  Upload,
  Users,
  Wallet,
  Workflow,
} from 'lucide-react'
// Relative, not aliased: this file is pulled into the test project,
// which compiles without the `@/*` path mapping (see tsconfig.node.json).
import type { ModuleId } from './modules'

/**
 * Sidebar destinations. Lives outside `app-layout.tsx` so the filtering
 * below can be tested without mounting the whole layout.
 *
 * Every link carries the module it belongs to. That is what makes the
 * "a personal workspace shows exactly what it always showed" guarantee
 * checkable rather than aspirational.
 */
export type NavItem =
  | { type: 'link'; key: string; path: string; icon: React.ElementType; module: ModuleId }
  | { type: 'separator'; labelKey: string }

export const navItems: NavItem[] = [
  // The dashboard ("Painel") is now reachable by clicking the Securo
  // logo + name in the sidebar header — no dedicated menu item to keep
  // the sidebar focused on the main destinations. Transactions sits
  // inside the ACCOUNTS section since it's account-scoped data.
  { type: 'separator', labelKey: 'nav.groupAccounts' },
  { type: 'link', key: 'transactions', path: '/transactions', icon: ArrowLeftRight, module: 'transactions' },
  { type: 'link', key: 'invoices', path: '/invoices', icon: Receipt, module: 'invoices' },
  { type: 'link', key: 'accounts', path: '/accounts', icon: Building2, module: 'accounts' },
  { type: 'link', key: 'import', path: '/import', icon: Upload, module: 'import' },
  { type: 'link', key: 'documents', path: '/documents', icon: FileText, module: 'documents' },
  { type: 'link', key: 'review', path: '/review', icon: ListChecks, module: 'review' },
  { type: 'separator', labelKey: 'nav.groupAnalysis' },
  { type: 'link', key: 'reports', path: '/reports', icon: BarChart3, module: 'reports' },
  { type: 'link', key: 'assets', path: '/assets', icon: Landmark, module: 'assets' },
  { type: 'link', key: 'debts', path: '/debts', icon: Wallet, module: 'debts' },
  { type: 'separator', labelKey: 'nav.groupSetup' },
  { type: 'link', key: 'budgets', path: '/budgets', icon: PiggyBank, module: 'budgets' },
  { type: 'link', key: 'goals', path: '/goals', icon: Target, module: 'goals' },
  { type: 'link', key: 'recurring', path: '/recurring', icon: Repeat, module: 'recurring' },
  { type: 'link', key: 'categories', path: '/categories', icon: Tag, module: 'categories' },
  { type: 'link', key: 'payees', path: '/payees', icon: Users, module: 'payees' },
  { type: 'link', key: 'splitGroups', path: '/groups', icon: Split, module: 'split_groups' },
  { type: 'link', key: 'rules', path: '/rules', icon: SlidersHorizontal, module: 'rules' },
  { type: 'separator', labelKey: 'nav.groupOperations' },
  { type: 'link', key: 'sources', path: '/sources', icon: FileSearch, module: 'sources' },
  { type: 'link', key: 'processing', path: '/processing', icon: Workflow, module: 'processing' },
  { type: 'link', key: 'audit', path: '/audit', icon: ScrollText, module: 'audit' },
]

/**
 * Drop links whose module is off, then drop any section header left
 * with nothing under it. Without the second pass, hiding a section's
 * only link leaves a floating heading.
 */
export function visibleNavItems(
  items: NavItem[],
  hasModule: (id: ModuleId) => boolean,
): NavItem[] {
  const kept = items.filter((item) => item.type !== 'link' || hasModule(item.module))
  return kept.filter((item, index) => {
    if (item.type !== 'separator') return true
    // Links always follow their own header, so the item right after a
    // header is either one of its links or the next header.
    const next = kept[index + 1]
    return next !== undefined && next.type === 'link'
  })
}
