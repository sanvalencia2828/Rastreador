// Token de sesión (sessionStorage: se borra al cerrar la pestaña) y fetch con Authorization.
const TOKEN_KEY = "rastreador_token";
const AUTH_EVENT = "auth-changed";

function notify() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EVENT));
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Devuelve false si el navegador no deja guardar (p. ej. almacenamiento bloqueado). */
export function setToken(token: string): boolean {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    return false;
  }
  notify();
  return true;
}

export function clearToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* sin almacenamiento: no hay nada que borrar */
  }
  notify();
}

export function onAuthChange(callback: () => void): () => void {
  window.addEventListener(AUTH_EVENT, callback);
  return () => window.removeEventListener(AUTH_EVENT, callback);
}

/** Solo rutas internas ("/x"), nunca "//host" ni URLs absolutas (evita open redirect). */
export function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/\\") ? raw : "/";
}

/** Mensaje claro para los errores de servidor que el usuario puede entender; null si no aplica. */
export function friendlyError(status: number): string | null {
  if (status === 401) return "Sua sessão expirou. Entre novamente.";
  if (status === 429) return "Muitas tentativas. Aguarde alguns minutos e tente de novo.";
  if (status === 503) return "Servidor sem acesso ao banco de dados. Tente mais tarde.";
  return null;
}
