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

type Theme = "dark" | "light";

// 系统当前偏好（无 matchMedia 时回退暗色）
const systemTheme = (): Theme =>
  window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";

// 主题：无存储记录 = 跟随系统（并随系统实时切换）；用户点过切换后固定到 localStorage。
// 亮色时给 <html> 加 .light（index.css 据此覆盖配色变量）。
function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("theme") as Theme) || systemTheme());

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
  }, [theme]);

  // 未显式选择时跟随系统变化
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem("theme")) setTheme(e.matches ? "light" : "dark");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = () =>
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      localStorage.setItem("theme", next); // 显式选择后固定，不再跟随系统
      return next;
    });

  return [theme, toggle];
}

function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const toLight = theme === "dark";
  return (
    <button
      onClick={onToggle}
      title={toLight ? "切换到亮色主题" : "切换到暗色主题"}
      aria-label="切换主题"
      className="text-white/60 hover:text-white/92 transition p-1.5 rounded-md hover:bg-white/[0.04]"
    >
      {toLight ? (
        // 暗色时显示太阳（点击切到亮色）
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" />
          <path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" />
        </svg>
      ) : (
        // 亮色时显示月亮（点击切回暗色）
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
        </svg>
      )}
    </button>
  );
}

function Layout({ username, onLogout, theme, onToggleTheme, children }: { username: string; onLogout: () => void; theme: Theme; onToggleTheme: () => void; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--color-surface)] text-white/96">
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
                      : "text-white/66 hover:text-white/92 hover:bg-white/[0.04]"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
            <span className="text-white/66">{username}</span>
            <button
              onClick={onLogout}
              title="退出登录"
              aria-label="退出登录"
              className="text-white/60 hover:text-white/92 transition p-1.5 rounded-md hover:bg-white/[0.04]"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" x2="9" y1="12" y2="12" />
              </svg>
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
  const [theme, toggleTheme] = useTheme();

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
        <Layout username={username} onLogout={handleLogout} theme={theme} onToggleTheme={toggleTheme}>
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
