import { useState } from "react";
import { api, setToken } from "../api/client";
import { PasswordInput } from "./PasswordInput";
import { btnConfirm, inputCls, errorTextCls } from "../styles";

export function Login({ onSuccess }: { onSuccess: (username: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password || loading) return;
    setLoading(true);
    setError("");
    try {
      const { token, username: name } = await api.auth.login(username, password);
      setToken(token);
      onSuccess(name);
    } catch {
      setError("用户名或密码错误");
      setToken(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-surface)] text-white/96 px-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-2xl bg-white/[0.03] border border-white/[0.06] p-8 shadow-2xl">
        <div className="text-center space-y-1">
          <h1 className="text-xl font-bold tracking-tight">新闻视频工作流</h1>
          <p className="text-xs text-white/60">请登录以继续</p>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-white/66 mb-1.5">用户名</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              placeholder="admin"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-white/66 mb-1.5">密码</label>
            <PasswordInput value={password} onChange={setPassword} placeholder="请输入密码" autoComplete="current-password" className={inputCls} />
          </div>
        </div>
        {error && <p className={errorTextCls}>{error}</p>}
        <button type="submit" disabled={loading} className={`${btnConfirm} w-full`}>
          {loading ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}
