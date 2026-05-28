import { createContext, useContext, useState, useCallback } from "react";

interface ToastMessage {
  id: number;
  text: string;
  type: "success" | "error" | "info";
}

interface ToastContextValue {
  showToast: (text: string, type?: ToastMessage["type"]) => void;
}

const ToastContext = createContext<ToastContextValue>({
  showToast: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

const TYPE_STYLES: Record<ToastMessage["type"], string> = {
  success: "bg-emerald-500/10 border-emerald-500/20 text-emerald-300",
  error: "bg-red-500/10 border-red-500/20 text-red-300",
  info: "bg-white/[0.06] border-white/[0.08] text-white/80",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback(
    (text: string, type: ToastMessage["type"] = "info") => {
      const id = Date.now();
      setToasts((prev) => [...prev, { id, text, type }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 3000);
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`px-4 py-3 rounded-xl border text-sm shadow-2xl backdrop-blur-lg animate-fade-up ${TYPE_STYLES[toast.type]}`}
          >
            {toast.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
