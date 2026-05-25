import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/Dashboard";
import { RunDetailPage } from "./pages/RunDetail";
import { SourcesPage } from "./pages/Sources";

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <nav className="border-b border-gray-800 px-6 py-3 flex gap-6 items-center">
        <span className="text-lg font-bold text-white">NewsVid</span>
        <NavLink
          to="/"
          className={({ isActive }) =>
            isActive ? "text-blue-400" : "text-gray-400 hover:text-gray-200"
          }
        >
          Dashboard
        </NavLink>
        <NavLink
          to="/sources"
          className={({ isActive }) =>
            isActive ? "text-blue-400" : "text-gray-400 hover:text-gray-200"
          }
        >
          Sources
        </NavLink>
      </nav>
      <main className="p-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
