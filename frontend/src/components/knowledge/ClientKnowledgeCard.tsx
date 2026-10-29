import React, { useMemo } from 'react';
import { BookOpen } from 'lucide-react';
import { KnowledgeBase } from './KnowledgeBase';
import { clientKnowledge } from '../../services/knowledge';

/** Admin: reviews the knowledge the client added in their portal. Its AI employees answer from the entries ticked for them. */
export const ClientKnowledgeCard: React.FC<{ clientId: string }> = ({ clientId }) => {
  const api = useMemo(() => clientKnowledge(clientId), [clientId]);
  return (
    <section className="space-y-3">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <BookOpen className="h-4 w-4 text-[#00df8f]" /> Knowledge base
        </h2>
        <p className="text-xs text-slate-400">
          Documents the client uploaded in their portal (Knowledge). AI employees never read them: download and read them,
          then write what each employee needs to know into its own knowledge in its Build tab.
        </p>
      </div>
      <KnowledgeBase api={api} mode="team" />
    </section>
  );
};
