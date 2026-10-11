import React, { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { ShieldCheck, Lock, Mail, ArrowRight } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';

export const LoginPage: React.FC = () => {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please provide both internal email and password.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await login(email, password);
      navigate('/', { replace: true });
    } catch (err: any) {
      setError(err.message || 'Authentication failed. Please verify credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#040d12] px-4 py-12 select-none">
      <div className="w-full max-w-sm space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg bg-[#00df8f] shadow-lg shadow-[#00df8f]/20 text-[#022016] font-bold text-sm">
            CH
          </div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">
            CHORANTA
          </h1>
          <p className="text-xs text-slate-400">
            Internal Agent Studio &bull; Operating System
          </p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-[#143c49] bg-[#091b22] p-6 shadow-2xl">
          <div className="mb-4 flex items-center gap-2 rounded border border-[#00df8f]/30 bg-[#00df8f]/10 px-3 py-2 text-xs text-[#00df8f]">
            <ShieldCheck className="h-4 w-4 shrink-0 text-[#00df8f]" />
            <span>Restricted internal portal. Authorized personnel only.</span>
          </div>

          {error && (
            <div className="mb-4 rounded-md border border-rose-900/50 bg-rose-950/30 p-3 text-xs text-rose-300">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="Internal Email"
              type="email"
              required
              autoComplete="email"
              placeholder="operator@choranta.internal"
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

            <Button
              type="submit"
              className="w-full mt-2"
              size="md"
              isLoading={isLoading}
              rightIcon={<ArrowRight className="h-4 w-4" />}
            >
              Authenticate & Enter
            </Button>
          </form>

          <div className="mt-5 border-t border-[#102d38] pt-4 text-center">
            <div className="text-[11px] text-slate-500 font-mono">
              Restricted to authorized Choranta internal operators
            </div>
          </div>
        </div>

        <div className="text-center text-[11px] text-slate-600">
          Choranta Autonomous Agent Architecture &copy; 2026
        </div>
      </div>
    </div>
  );
};
