// The one red banner every API/LLM failure goes through, so errors look the same everywhere (M12).
export function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="rounded border border-red-800 bg-red-950 p-2 text-sm text-red-200">
      {children}
    </p>
  )
}
