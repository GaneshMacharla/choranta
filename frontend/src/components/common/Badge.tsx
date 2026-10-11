import React from 'react';

type BadgeVariant = 'green' | 'yellow' | 'red' | 'gray' | 'blue' | 'purple';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  dot?: boolean;
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'gray',
  size = 'md',
  dot = false,
}) => {
  const variantStyles = {
    green: 'bg-[#052b20]/90 text-[#00df8f] border-[#0a4d39]',
    yellow: 'bg-amber-950/60 text-amber-400 border-amber-800/40',
    red: 'bg-rose-950/60 text-rose-400 border-rose-800/40',
    gray: 'bg-[#0a2028] text-slate-300 border-[#143c49]',
    blue: 'bg-[#052b20]/90 text-[#00df8f] border-[#0a4d39]',
    purple: 'bg-purple-950/60 text-purple-400 border-purple-800/40',
  };

  const dotColors = {
    green: 'bg-[#00df8f]',
    yellow: 'bg-amber-400',
    red: 'bg-rose-400',
    gray: 'bg-slate-400',
    blue: 'bg-[#00df8f]',
    purple: 'bg-purple-400',
  };

  const sizeStyles = {
    sm: 'text-[10px] px-1.5 py-0.5 font-medium tracking-wide',
    md: 'text-xs px-2 py-0.5 font-medium',
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border ${variantStyles[variant]} ${sizeStyles[size]} select-none`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${dotColors[variant]}`} />}
      <span>{children}</span>
    </span>
  );
};

export const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  switch (status.toUpperCase()) {
    case 'ACTIVE':
    case 'READY':
    case 'DEPLOYED':
      return <Badge variant="green" dot>{status}</Badge>;
    case 'TESTING':
      return <Badge variant="yellow" dot>{status}</Badge>;
    case 'PAUSED':
      return <Badge variant="red" dot>{status}</Badge>;
    case 'DRAFT':
    case 'INACTIVE':
    case 'ARCHIVED':
    default:
      return <Badge variant="gray" dot>{status}</Badge>;
  }
};
