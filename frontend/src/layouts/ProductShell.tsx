import { Bell, Building2, ChevronDown, HelpCircle, Menu, PanelLeftClose, Search, X } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

import { modeMeta, navigationByMode, type ShellMode } from '../app/navigation';
import type { CurrentUser } from '../types';

interface ProductShellProps {
  mode: ShellMode;
  currentUser: CurrentUser | null;
}

function initials(value: string): string {
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, 1).toUpperCase() : 'U';
}

export function ProductShell({ mode, currentUser }: ProductShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const navItems = navigationByMode[mode];
  const meta = modeMeta[mode];
  const tenantLabel = currentUser?.tenant_id ?? '正在加载租户';
  const username = currentUser?.username ?? '当前用户';

  return (
    <div className={`ru-shell ru-shell-${mode}`}>
      <aside className={`ru-sidebar ${mobileNavOpen ? 'is-open' : ''}`} aria-label={`${meta.label}导航`}>
        <div className="ru-brand-block">
          <div className="ru-brand">RAG UPPER</div>
          <div className="ru-brand-mode">{meta.label}</div>
          <button className="ru-mobile-close" type="button" onClick={() => setMobileNavOpen(false)} aria-label="关闭导航">
            <X size={20} />
          </button>
        </div>

        <div className="ru-tenant-switcher">
          <span>当前租户</span>
          <button type="button">
            <Building2 size={15} />
            <strong>{tenantLabel}</strong>
            <ChevronDown size={14} />
          </button>
        </div>

        <nav className="ru-nav">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `ru-nav-link ${isActive ? 'is-active' : ''}`}
                onClick={() => setMobileNavOpen(false)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="ru-sidebar-footer">
          <NavLink to={meta.switchTo} className="ru-mode-switch">
            <meta.switchIcon size={17} />
            <span>{meta.switchLabel}</span>
          </NavLink>
          <button className="ru-collapse-button" type="button" title="收起侧栏">
            <PanelLeftClose size={17} />
          </button>
        </div>
      </aside>

      {mobileNavOpen ? <button className="ru-nav-scrim" type="button" aria-label="关闭导航" onClick={() => setMobileNavOpen(false)} /> : null}

      <div className="ru-shell-main">
        <header className="ru-topbar">
          <div className="ru-topbar-start">
            <button className="ru-mobile-menu" type="button" onClick={() => setMobileNavOpen(true)} aria-label="打开导航">
              <Menu size={21} />
            </button>
            <button className="ru-workspace-button" type="button">
              <Building2 size={16} />
              <span>{tenantLabel}</span>
              <ChevronDown size={14} />
            </button>
          </div>

          <div className="ru-topbar-actions">
            <button className="ru-icon-button" type="button" title="全局搜索" aria-label="全局搜索"><Search size={19} /></button>
            <button className="ru-icon-button ru-notification" type="button" title="通知" aria-label="通知">
              <Bell size={19} />
              <span>12</span>
            </button>
            <button className="ru-icon-button" type="button" title="帮助" aria-label="帮助"><HelpCircle size={19} /></button>
            <button className="ru-user-menu" type="button">
              <span className="ru-avatar">{initials(username)}</span>
              <span className="ru-user-copy"><strong>{username}</strong><small>{currentUser?.role ?? '成员'}</small></span>
              <ChevronDown size={14} />
            </button>
          </div>
        </header>

        <main className="ru-page-area">
          <Outlet />
        </main>

        {mode === 'user' ? (
          <nav className="ru-mobile-bottom-nav" aria-label="用户端快捷导航">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => isActive ? 'is-active' : ''}>
                  <Icon size={21} />
                  <span>{item.label.replace('AI ', '')}</span>
                </NavLink>
              );
            })}
          </nav>
        ) : null}
      </div>
    </div>
  );
}
