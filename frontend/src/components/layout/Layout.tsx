import { Outlet, NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { group: "Monitor", items: [
    { path: "/", label: "Overview", icon: "📊" },
    { path: "/cpu", label: "CPU", icon: "⚡" },
    { path: "/memory", label: "Memory", icon: "💾" },
    { path: "/storage", label: "Storage", icon: "💿" },
    { path: "/network", label: "Network", icon: "🌐" },
    { path: "/processes", label: "Processes", icon: "⚙️" },
    { path: "/services", label: "Services", icon: "🔧" },
  ]},
  { group: "Activity", items: [
    { path: "/events", label: "Events", icon: "📋" },
    { path: "/alerts", label: "Alerts", icon: "🚨" },
  ]},
  { group: "System", items: [
    { path: "/server", label: "Server", icon: "🖥️" },
    { path: "/settings", label: "Settings", icon: "⚙️" },
  ]},
];

export function Layout() {
  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.logo}>ServerWatch</span>
          <span style={styles.hostname}>serverwatch.local</span>
          <span style={styles.liveBadge}>● LIVE</span>
        </div>
        <div style={styles.headerRight}>
          <span style={styles.currentTime}>{new Date().toLocaleTimeString()}</span>
        </div>
      </header>

      <div style={styles.main}>
        <aside style={styles.sidebar}>
          <nav style={styles.nav}>
            {NAV_ITEMS.map((section) => (
              <div key={section.group} style={styles.navSection}>
                <div style={styles.navSectionTitle}>{section.group}</div>
                <ul style={styles.navList}>
                  {section.items.map((item) => (
                    <li key={item.path} style={styles.navItem}>
                      <NavLink
                        to={item.path}
                        style={({ isActive }) => ({
                          ...styles.navLink,
                          ...(isActive ? styles.navLinkActive : {}),
                        })}
                      >
                        <span style={styles.navIcon}>{item.icon}</span>
                        <span>{item.label}</span>
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        <main style={styles.content}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: "flex", flexDirection: "column", minHeight: "100vh", background: "var(--color-bg-primary)" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", height: "var(--header-height)", padding: "0 var(--space-md)", background: "var(--color-bg-secondary)", borderBottom: "1px solid var(--color-border)" },
  headerLeft: { display: "flex", alignItems: "center", gap: "var(--space-md)" },
  logo: { fontSize: "var(--text-xl)", fontWeight: 600, color: "var(--color-cyan)" },
  hostname: { fontSize: "var(--text-sm)", color: "var(--color-text-secondary)" },
  liveBadge: { fontSize: "var(--text-xs)", color: "var(--color-live)" },
  headerRight: { display: "flex", alignItems: "center", gap: "var(--space-md)" },
  currentTime: { fontSize: "var(--text-sm)", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" },
  main: { display: "flex", flex: 1, overflow: "hidden" },
  sidebar: { width: "var(--sidebar-width)", flexShrink: 0, background: "var(--color-bg-secondary)", borderRight: "1px solid var(--color-border)", overflowY: "auto" },
  nav: { padding: "var(--space-md)" },
  navSection: { marginBottom: "var(--space-lg)" },
  navSectionTitle: { fontSize: "var(--text-xs)", textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)", marginBottom: "var(--space-xs)", paddingLeft: "var(--space-sm)" },
  navList: { listStyle: "none", display: "flex", flexDirection: "column", gap: "var(--space-xs)" },
  navItem: { margin: 0 },
  navLink: { display: "flex", alignItems: "center", gap: "var(--space-sm)", padding: "var(--space-sm) var(--space-md)", borderRadius: "var(--border-radius)", color: "var(--color-text-secondary)", textDecoration: "none", fontSize: "var(--text-sm)", transition: "background var(--transition-fast), color var(--transition-fast)" },
  navLinkActive: { background: "var(--color-bg-tertiary)", color: "var(--color-cyan)" },
  navIcon: { fontSize: "var(--text-base)" },
  content: { flex: 1, overflowY: "auto", padding: "var(--space-lg)" },
};