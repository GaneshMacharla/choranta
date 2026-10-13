import React, { createContext, useContext, useState, useEffect } from 'react';
import { User } from '../types';
import { authService } from '../services/auth';
import { ApiError } from '../services/api';

const TOKEN_KEY = 'choranta_token';
const USER_KEY = 'choranta_user';
// Active sessions get a fresh token this often; each token lasts 7 days (backend ACCESS_TOKEN_EXPIRE_MINUTES)
const REFRESH_EVERY_MS = 6 * 60 * 60 * 1000;

const readCachedUser = (): User | null => {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw && localStorage.getItem(TOKEN_KEY) ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
};

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<User>;
  loginWithGoogle: (credential: string) => Promise<User>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Signed-in users are restored from the browser straight away, then checked with the server
  const [user, setUser] = useState<User | null>(readCachedUser);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [isLoading, setIsLoading] = useState<boolean>(() => !!localStorage.getItem(TOKEN_KEY) && !readCachedUser());

  const startSession = (response: { access_token: string; user: User }) => {
    localStorage.setItem(TOKEN_KEY, response.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(response.user));
    setToken(response.access_token);
    setUser(response.user);
    return response.user;
  };

  const clearSession = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  };

  useEffect(() => {
    if (!token) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    // Renew the token; only a rejected token (401) signs the user out. A server restart
    // or network error keeps the saved session and the next renewal tries again.
    const renew = async () => {
      try {
        const response = await authService.refresh();
        if (!cancelled) startSession(response);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) clearSession();
        else console.warn('Could not renew the session; keeping the saved login.', err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    renew();
    const timer = setInterval(renew, REFRESH_EVERY_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // Runs once per sign-in, not on every token renewal
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!token]);

  // Keep tabs in sync: signing in or out in one tab applies to the others
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== TOKEN_KEY && e.key !== USER_KEY) return;
      setToken(localStorage.getItem(TOKEN_KEY));
      setUser(readCachedUser());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const login = async (email: string, password: string) => startSession(await authService.login(email, password));

  const loginWithGoogle = async (credential: string) => startSession(await authService.loginWithGoogle(credential));

  const logout = clearSession;

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        loginWithGoogle,
        logout,
        isAuthenticated: !!token && !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
