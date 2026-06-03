import { useEffect, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/Dashboard";
import { SourcesPage } from "./pages/Sources";
import { PublishersPage } from "./pages/Publishers";
import { SettingsPage } from "./pages/Settings";
import { ToastProvider } from "./components/Toast";
import { Login } from "./components/Login";
import { api, getToken, setToken, onUnauthorized } from "./api/client";

const navItems = [
  { to: "/", label: "工作台", end: true },
  { to: "/sources", label: "信息源" },
  { to: "/publish", label: "发布管理" },
  { to: "/settings", label: "设置" },
];

function Layout({ username, onLogout, children }: { username: string; onLogout: () => void; children: React.ReactNode }) {
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
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-white/40">{username}</span>
            <button
              onClick={onLogout}
              className="text-white/30 hover:text-white/70 transition px-2 py-1 rounded-md hover:bg-white/[0.04]"
            >
              退出
            </button>
          </div>
        </div>
      </nav>
      <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
    </div>
  );
}

export default function App() {
  // null = 校验中；"" = 未登录；非空 = 已登录用户名
  const [username, setUsername] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      setUsername("");
      return;
    }
    api.auth
      .me()
      .then((r) => setUsername(r.username))
      .catch(() => setUsername(""));
  }, []);

  useEffect(() => onUnauthorized(() => setUsername("")), []);

  const handleLogout = () => {
    setToken(null);
    setUsername("");
  };

  if (username === null) {
    return <div className="min-h-screen bg-[var(--color-surface)]" />;
  }

  if (username === "") {
    return (
      <ToastProvider>
        <Login onSuccess={setUsername} />
      </ToastProvider>
    );
  }

  return (
    <BrowserRouter>
      <ToastProvider>
        <Layout username={username} onLogout={handleLogout}>
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
