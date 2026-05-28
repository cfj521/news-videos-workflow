import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/Dashboard";
import { SourcesPage } from "./pages/Sources";
import { PublishersPage } from "./pages/Publishers";
import { SettingsPage } from "./pages/Settings";
import { ToastProvider } from "./components/Toast";

const navItems = [
  { to: "/", label: "工作台", end: true },
  { to: "/sources", label: "信息源" },
  { to: "/publish", label: "发布管理" },
  { to: "/settings", label: "设置" },
];

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--color-surface)] text-white/90">
      <nav className="sticky top-0 z-40 border-b border-white/[0.06] bg-[var(--color-surface)]/80 backdrop-blur-xl">
        <div className="max-w-6xl mx-auto px-6 flex items-center h-14 gap-8">
          <div className="flex items-center gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg text-sm transition ${
                    isActive
                      ? "bg-white/[0.08] text-white font-medium"
                      : "text-white/40 hover:text-white/70 hover:bg-white/[0.04]"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>
      <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/publish" element={<PublishersPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </Layout>
      </ToastProvider>
    </BrowserRouter>
  );
}
