import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Menu, X, ArrowRight, ShieldCheck, Sparkles, User } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface NavbarProps {
  onOpenDemo: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenDemo }) => {
  const { isAuthenticated, user } = useAuth();
  const [isScrolled, setIsScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const navLinks = [
    { label: 'Capabilities', href: '#capabilities' },
    { label: 'Benchmark', href: '#benchmark' },
    { label: 'Audio Demos', href: '#demo' },
    { label: 'ROI Calculator', href: '#roi' },
    { label: 'Pricing', href: '#pricing' },
    { label: 'Integrations', href: '#integrations' },
    { label: 'FAQ', href: '#faq' },
  ];

  return (
    <header
      className={`fixed top-0 left-0 right-0 z-40 transition-all duration-300 ${
        isScrolled
          ? 'bg-[#040d12]/90 backdrop-blur-md border-b border-[#143c49]/80 py-3 shadow-lg'
          : 'bg-transparent py-5'
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between">
          {/* Logo & Brand */}
          <Link to="/" className="flex items-center gap-2.5 group">
            <img
              src="/logo.png"
              alt="Choranta"
              className="h-9 w-9 object-contain group-hover:scale-105 transition-transform"
            />
            <div className="flex flex-col">
              <div className="font-extrabold text-base tracking-wider text-white flex items-center gap-1.5">
                <span>CHORANTA</span>
                <span className="flex h-2 w-2 relative">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00df8f] opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00df8f]" />
                </span>
              </div>
              <span className="text-[10px] text-slate-400 font-mono tracking-wider uppercase -mt-0.5">
                AI Voice Workforce
              </span>
            </div>
          </Link>

          {/* Desktop Navigation Links */}
          <nav className="hidden lg:flex items-center gap-7">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="text-sm font-medium text-slate-300 hover:text-[#00df8f] transition-colors"
              >
                {link.label}
              </a>
            ))}
          </nav>

          {/* Right Action Buttons */}
          <div className="hidden sm:flex items-center gap-3">
            {isAuthenticated ? (
              <Link
                to={user?.role === 'CLIENT' ? '/portal' : '/overview'}
                className="flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold bg-[#091f28] hover:bg-[#0e2c39] border border-[#143c49] text-white transition-colors"
              >
                <User className="w-3.5 h-3.5 text-[#00df8f]" />
                <span>{user?.role === 'CLIENT' ? 'Client Portal' : 'Studio Console'}</span>
              </Link>
            ) : (
              <Link
                to="/login"
                className="px-4 py-2 rounded-full text-xs font-semibold text-slate-300 hover:text-white transition-colors"
              >
                Sign In
              </Link>
            )}

            <button
              onClick={onOpenDemo}
              className="flex items-center gap-2 px-5 py-2.5 rounded-full text-xs font-bold text-[#022016] bg-[#00df8f] hover:bg-[#00f59b] transition-all shadow-[0_0_20px_-3px_rgba(0,223,143,0.4)] hover:shadow-[0_0_25px_-1px_rgba(0,223,143,0.6)] cursor-pointer"
            >
              <span>Deploy Voice Agent</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Mobile Menu Button */}
          <div className="lg:hidden flex items-center gap-2">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 rounded-xl text-slate-300 hover:text-white hover:bg-[#091f28] transition-colors"
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="lg:hidden bg-[#051117] border-b border-[#143c49] px-4 pt-3 pb-6 space-y-4 animate-in slide-in-from-top-2">
          <div className="flex flex-col space-y-3">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={() => setMobileMenuOpen(false)}
                className="text-sm font-medium text-slate-200 hover:text-[#00df8f] py-1 transition-colors"
              >
                {link.label}
              </a>
            ))}
          </div>

          <div className="pt-4 border-t border-[#143c49]/60 flex flex-col gap-3">
            {isAuthenticated ? (
              <Link
                to={user?.role === 'CLIENT' ? '/portal' : '/overview'}
                className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl text-xs font-semibold bg-[#091f28] border border-[#143c49] text-white"
              >
                <span>{user?.role === 'CLIENT' ? 'Go to Client Portal' : 'Go to Studio Console'}</span>
              </Link>
            ) : (
              <Link
                to="/login"
                className="w-full text-center py-2.5 rounded-xl text-xs font-semibold bg-[#091f28] border border-[#143c49] text-white"
              >
                Sign In
              </Link>
            )}

            <button
              onClick={() => {
                setMobileMenuOpen(false);
                onOpenDemo();
              }}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-xs font-bold text-[#022016] bg-[#00df8f]"
            >
              <span>Deploy Voice Agent</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </header>
  );
};
