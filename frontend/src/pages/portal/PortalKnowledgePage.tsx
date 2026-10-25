import React from 'react';
import { KnowledgeBase } from '../../components/knowledge/KnowledgeBase';
import { portalKnowledge } from '../../services/knowledge';

/** Clients teach their AI employees about the business: details, documents and extra notes. */
export const PortalKnowledgePage: React.FC = () => (
  <div className="mx-auto max-w-5xl space-y-4">
    <div>
      <h1 className="text-xl font-bold">Knowledge</h1>
      <p className="text-xs text-slate-400">
        Your AI employees answer callers only from what you give here. Fill in the key details, upload any documents you already have,
        and our team will check everything and ask if anything's missing.
      </p>
    </div>
    <KnowledgeBase api={portalKnowledge} mode="client" />
  </div>
);
