import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, Bell, CheckCheck, CheckCircle, Info } from 'lucide-react';
import { NotificationList, PortalNotification, portalService } from '../../services/portal';

const POLL_MS = 60_000;

const LEVEL_STYLE: Record<PortalNotification['level'], { icon: React.ReactNode; dot: string }> = {
  success: { icon: <CheckCircle className="h-4 w-4 text-[#00df8f]" />, dot: 'bg-[#00df8f]' },
  warning: { icon: <AlertTriangle className="h-4 w-4 text-amber-400" />, dot: 'bg-amber-400' },
  info: { icon: <Info className="h-4 w-4 text-sky-400" />, dot: 'bg-sky-400' },
};

const timeAgo = (iso: string) => {
  const then = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).getTime();
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
};

/** Bell with unread count and a dropdown of the client's notifications. */
export const NotificationBell: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<NotificationList>({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    portalService.notifications().then(setData).catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
  }, [load, location.pathname]);

  useEffect(() => {
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Close when clicking outside
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  const openItem = async (n: PortalNotification) => {
    setOpen(false);
    if (!n.read) portalService.readNotification(n.id).then(setData).catch(() => undefined);
    if (n.link) navigate(n.link);
  };

  return (
    <div className="relative" ref={panel}>
      <button
        type="button"
        aria-label={data.unread ? `Notifications, ${data.unread} unread` : 'Notifications'}
        onClick={() => setOpen(!open)}
        className="relative rounded-md p-2 text-slate-400 hover:bg-[#0c2129] hover:text-slate-100"
      >
        <Bell className="h-5 w-5" />
        {data.unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
            {data.unread > 9 ? '9+' : data.unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 top-11 z-50 w-80 overflow-hidden rounded-lg border border-[#143c49] bg-[#071419] shadow-2xl md:left-auto md:right-auto">
          <div className="flex items-center justify-between border-b border-[#102d38] px-4 py-3">
            <span className="text-sm font-semibold text-slate-100">Notifications</span>
            {data.unread > 0 && (
              <button
                type="button"
                onClick={() => portalService.readAllNotifications().then(setData).catch(() => undefined)}
                className="flex items-center gap-1 text-xs text-[#00df8f] hover:underline"
              >
                <CheckCheck className="h-3.5 w-3.5" /> Mark all read
              </button>
            )}
          </div>
          {data.items.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-slate-500">No notifications yet. We'll let you know when something happens.</p>
          ) : (
            <ul className="max-h-96 divide-y divide-[#102d38] overflow-y-auto">
              {data.items.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => openItem(n)}
                    className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-[#0c2129] ${n.read ? 'opacity-70' : ''}`}
                  >
                    <span className="mt-0.5 shrink-0">{LEVEL_STYLE[n.level]?.icon || LEVEL_STYLE.info.icon}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start justify-between gap-2">
                        <span className={`text-sm ${n.read ? 'text-slate-300' : 'font-semibold text-slate-100'}`}>{n.title}</span>
                        {!n.read && <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${LEVEL_STYLE[n.level]?.dot || 'bg-sky-400'}`} />}
                      </span>
                      {n.body && <span className="mt-0.5 block text-xs text-slate-400">{n.body}</span>}
                      <span className="mt-1 block text-[11px] text-slate-500">{timeAgo(n.created_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
