import { useState } from 'react'
import { SectionTabs } from '@/components/controls/SectionTabs'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { AppSection } from './AppSection'
import { ConnectionsSection } from './ConnectionsSection'
import { DataSection } from './DataSection'
import { NotificationsSection } from './NotificationsSection'
import { ProfileSection } from './ProfileSection'
import { SecuritySection } from './SecuritySection'
import { useSettingsView } from './useSettingsView'
import './settings.css'

/** One tab per question the owner comes with: who I am, what the app shows, where the data
 *  comes from, when the bot may speak, how to get the data out, who may sign in. */
const TABS = [
  { id: 'profile', key: 'settings.tab.profile' },
  { id: 'app', key: 'settings.tab.app' },
  { id: 'conn', key: 'settings.tab.conn' },
  { id: 'notify', key: 'settings.tab.notify' },
  { id: 'data', key: 'settings.tab.data' },
  { id: 'security', key: 'settings.tab.security' },
] as const

type TabId = (typeof TABS)[number]['id']

export default function SettingsScreen() {
  const { t } = useT()
  const settings = useSettingsView()
  const [activeTab, setActiveTab] = useState<TabId>('profile')

  return (
    <>
      <TopBar title={t('nav.settings')} />

      <header className="mast">
        <div className="kicker">
          <span className="crumb">{t('app.system')}</span>
        </div>
        <SectionTabs
          items={TABS.map((tab) => ({ id: tab.id, label: t(tab.key) }))}
          active={activeTab}
          onSelect={(id) => setActiveTab(id as TabId)}
        />
      </header>

      <Headline title={t('nav.settings')} />

      <div className="settings-content">
        {activeTab === 'profile' && <ProfileSection settings={settings} />}
        {activeTab === 'app' && <AppSection settings={settings} />}
        {activeTab === 'conn' && <ConnectionsSection settings={settings} />}
        {activeTab === 'notify' && <NotificationsSection settings={settings} />}
        {activeTab === 'data' && <DataSection />}
        {activeTab === 'security' && <SecuritySection settings={settings} />}
      </div>
    </>
  )
}
