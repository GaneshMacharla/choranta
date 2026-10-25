import React, { useEffect, useState } from 'react';
import { MessageCircle } from 'lucide-react';
import { WhatsAppMessage, portalWhatsApp } from '../../services/whatsapp';

const STATUS_LABEL: Record<string, string> = {
  QUEUED: 'Sending…',
  SENDING: 'Sending…',
  SENT: 'Sent ✓',
  DELIVERED: 'Delivered ✓✓',
  READ: 'Read ✓✓',
  FAILED: 'Not delivered',
  SKIPPED: 'Not sent',
};

/** The WhatsApp follow-up sent after a call, and the lead's replies (client portal only). */
export const WhatsAppThread: React.FC<{ callId: string }> = ({ callId }) => {
  const [messages, setMessages] = useState<WhatsAppMessage[]>([]);

  useEffect(() => {
    let live = true;
    portalWhatsApp
      .callThread(callId)
      .then((m) => live && setMessages(m))
      .catch(() => live && setMessages([]));
    return () => {
      live = false;
    };
  }, [callId]);

  if (messages.length === 0) return null;
  return (
    <div className="space-y-2 rounded border border-[#143c49] bg-[#06141a]/60 p-3 text-xs">
      <span className="flex items-center gap-1.5 font-semibold text-[#00df8f]">
        <MessageCircle className="h-4 w-4" /> WhatsApp follow-up
      </span>
      {messages.map((m) => (
        <div key={m.id} className={`flex ${m.direction === 'IN' ? 'justify-start' : 'justify-end'}`}>
          <div className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 ${m.direction === 'IN' ? 'bg-[#151824] text-slate-200' : 'bg-[#0b3b2e] text-emerald-50'}`}>
            {m.body}
            <div className="mt-1 text-right text-[10px] text-slate-400">
              {m.direction === 'IN' ? new Date(m.created_at).toLocaleString() : STATUS_LABEL[m.status] || m.status}
              {m.direction === 'OUT' && m.error && <span className="block text-rose-300">{m.error}</span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};
