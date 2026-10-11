import React, { useEffect, useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { ShieldCheck, Lock, Mail, ArrowRight } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { authService } from '../services/auth';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { User } from '../types';

declare global {
  interface Window {
    google?: any;
  }
}

const GSI_SRC = 'https://accounts.google.com/gsi/client';

const loadGoogleScript = () =>
  new Promise<void>((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve();
    const existing = document.querySelector(`script[src="${GSI_SRC}"]`) as HTMLScriptElement | null;
    const script = existing || document.createElement('script');
    script.addEventListener('load', () => resolve());
    script.addEventListener('error', () => reject(new Error('Could not load Google Sign-In.')));
    if (!existing) {
      script.src = GSI_SRC;
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }
  });

const homeFor = (user: User) => (user.role === 'CLIENT' ? '/portal' : '/');

export const LoginPage: React.FC = () => {
  const { login, loginWithGoogle, isAuthenticated, user } = useAuth();
  const navigate = useNavigate();
  const googleButtonRef = useRef<HTMLDivElement | null>(null);

  const [googleReady, setGoogleReady] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isAuthenticated) return;
    let cancelled = false;
    (async () => {
      try {
        const { google_client_id } = await authService.getConfig();
        if (!google_client_id) {
          if (!cancelled) setGoogleReady('unavailable');
          return;
        }
        await loadGoogleScript();
        if (cancelled || !googleButtonRef.current) return;
        window.google.accounts.id.initialize({
          client_id: google_client_id,
          callback: async (response: { credential: string }) => {
            setIsLoading(true);
            setError(null);
            try {
              const signedIn = await loginWithGoogle(response.credential);
              navigate(homeFor(signedIn), { replace: true });
            } catch (err: any) {
              setError(err.message || 'Google sign-in failed.');
            } finally {
              setIsLoading(false);
            }
          },
        });
        window.google.accounts.id.renderButton(googleButtonRef.current, {
          theme: 'filled_black',
          size: 'large',
          shape: 'pill',
          text: 'signin_with',
          width: 300,
        });
        setGoogleReady('ready');
      } catch {
        if (!cancelled) setGoogleReady('unavailable');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  if (isAuthenticated && user) {
    return <Navigate to={homeFor(user)} replace />;
  }

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please provide both email and password.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const signedIn = await login(email, password);
      navigate(homeFor(signedIn), { replace: true });
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Please verify credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#040d12] px-4 py-12 select-none">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-2">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg bg-[#00df8f] shadow-lg shadow-[#00df8f]/20 text-[#022016] font-bold text-sm">
            CH
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">CHORANTA</h1>
          <p className="text-xs text-slate-400">AI Voice Employees &bull; Studio &amp; Client Portal</p>
        </div>

        <div className="rounded-xl border border-[#143c49] bg-[#091b22] p-6 shadow-2xl space-y-4">
          <div className="flex items-center gap-2 rounded border border-[#00df8f]/30 bg-[#00df8f]/10 px-3 py-2 text-xs text-[#00df8f]">
            <ShieldCheck className="h-4 w-4 shrink-0 text-[#00df8f]" />
            <span>Invite-only. Sign in with the Google account your administrator added.</span>
          </div>

          {error && (
            <div className="rounded-md border border-rose-900/50 bg-rose-950/30 p-3 text-xs text-rose-300">{error}</div>
          )}

          <div className="flex min-h-[44px] flex-col items-center justify-center gap-2">
            <div ref={googleButtonRef} className={googleReady === 'ready' ? '' : 'hidden'} />
            {googleReady === 'loading' && <p className="text-xs text-slate-500">Loading Google Sign-In...</p>}
            {googleReady === 'unavailable' && (
              <p className="text-center text-xs text-amber-300">
                Google Sign-In isn't configured yet (GOOGLE_CLIENT_ID on the server).
              </p>
            )}
            {isLoading && <p className="text-xs text-slate-400">Signing you in...</p>}
          </div>

          <div className="border-t border-[#102d38] pt-3 text-center">
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="text-[11px] text-slate-500 hover:text-slate-300"
            >
              {showPassword ? 'Hide admin password login' : 'Admin password login'}
            </button>
          </div>

          {showPassword && (
            <form onSubmit={handlePasswordSubmit} className="space-y-4">
              <Input
                label="Admin Email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                leftIcon={<Mail className="h-4 w-4" />}
              />
              <Input
                label="Password"
                type="password"
                required
                autoComplete="current-password"
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                leftIcon={<Lock className="h-4 w-4" />}
              />
              <Button type="submit" className="w-full" size="md" isLoading={isLoading} rightIcon={<ArrowRight className="h-4 w-4" />}>
                Sign in
              </Button>
            </form>
          )}
        </div>

        <div className="text-center text-[11px] text-slate-600">Choranta &copy; 2026</div>
      </div>
    </div>
  );
};
